"""S5 검색·검증 루프 기반 타임라인 생성 오케스트레이션."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from typing import TypeVar

from pydantic import BaseModel

from core.config import TimelineConfig
from core.errors import LLMGenerationError, PipelineInvariantError
from core.models import (
    AdditionalHypotheses,
    Article,
    ArticleSelection,
    EventArticleInput,
    GenerationStatus,
    HypotheticalEvent,
    HypotheticalTimeline,
    IntentInterpretation,
    IssueCreate,
    IssueEventInput,
    MergedTimeline,
    PipelineProgress,
    PipelineStage,
    RejectedArticle,
    RelatedEvent,
    RelatedEvents,
    SearchOptions,
    SearchQueryDraft,
    SelectedArticle,
    SufficiencyReview,
    TerminationReason,
    TimelineGenerationResult,
)
from core.ports import PlannedArticleSearcher, Repository, StructuredGenerator

logger = logging.getLogger("news_tls_agent.pipeline")

ProgressSink = Callable[[PipelineProgress], None]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TimelinePipeline:
    """P1~P8을 실행하고 검증된 실제 기사 인용만 원자적으로 저장한다."""

    def __init__(
        self,
        repository: Repository,
        searcher: PlannedArticleSearcher,
        generator: StructuredGenerator,
        config: TimelineConfig,
        *,
        progress_sink: ProgressSink | None = None,
        clock: Clock = _utc_now,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self._repository = repository
        self._searcher = searcher
        self._generator = generator
        self._config = config
        self._progress_sink = progress_sink
        self._clock = clock
        self._sleeper = sleeper

    def generate(
        self,
        topic: str,
        *,
        clarification_answer: str | None = None,
        clarification_count: int = 0,
    ) -> TimelineGenerationResult:
        normalized_topic = " ".join(topic.split())
        if not normalized_topic:
            raise ValueError("토픽은 빈 문자열일 수 없습니다")
        if clarification_count < 0:
            raise ValueError("clarification_count는 0 이상이어야 합니다")

        existing = self._repository.find_issue_by_topic(normalized_topic)
        if existing is not None:
            self._emit(
                round_number=0,
                stage=PipelineStage.CACHED,
                selected_count=sum(len(event.articles) for event in existing.events),
                termination=TerminationReason.CACHED,
            )
            return TimelineGenerationResult(
                status=GenerationStatus.REUSED,
                issue_id=existing.issue_id,
                termination=TerminationReason.CACHED,
                selected_article_count=len(
                    {
                        link.article.article_id
                        for event in existing.events
                        for link in event.articles
                    }
                ),
            )

        self._emit(0, PipelineStage.INTERPRET_INTENT, 0)
        interpretation = self._call_llm(
            _intent_prompt(normalized_topic, clarification_answer),
            IntentInterpretation,
        )
        if (
            interpretation.needs_clarification
            and clarification_count < self._config.max_clarifications
        ):
            self._emit(0, PipelineStage.CLARIFY, 0)
            return TimelineGenerationResult(
                status=GenerationStatus.NEEDS_CLARIFICATION,
                clarification_question=interpretation.clarification_question,
            )

        self._emit(0, PipelineStage.BUILD_HYPOTHETICAL_TIMELINE, 0)
        hypothetical = self._call_llm(
            _hypothetical_timeline_prompt(interpretation.intent),
            HypotheticalTimeline,
        )
        return self._collect_and_save(normalized_topic, interpretation.intent, hypothetical)

    def _collect_and_save(
        self,
        topic: str,
        intent: str,
        hypothetical: HypotheticalTimeline,
    ) -> TimelineGenerationResult:
        selected_by_id: dict[int, SelectedArticle] = {}
        articles_by_id: dict[int, Article] = {}
        rejected_history: list[RejectedArticle] = []
        pending_seeds = list(hypothetical.events)
        date_from = hypothetical.date_from
        date_to = hypothetical.date_to
        previous_selected_count = 0
        chain_depth = 0
        termination: TerminationReason | None = None
        rounds = 0

        for round_number in range(1, self._config.max_rounds + 1):
            rounds = round_number
            self._emit(
                round_number,
                PipelineStage.GENERATE_SEARCH_QUERY,
                len(selected_by_id),
            )
            draft = self._call_llm(
                _search_query_prompt(
                    intent,
                    date_from,
                    date_to,
                    pending_seeds,
                    rejected_history,
                ),
                SearchQueryDraft,
            )
            logger.info(
                "pipeline search: round=%s method=%s reason=%s",
                round_number,
                draft.method,
                draft.reason,
            )
            search_request = draft.to_search_request(top_k=self._config.search_top_k)
            bounded_date_from = max(date_from, draft.date_from)
            bounded_date_to = min(date_to, draft.date_to)
            if bounded_date_from > bounded_date_to:
                bounded_date_from = date_from
                bounded_date_to = date_to
            search_request = search_request.model_copy(
                update={
                    "options": SearchOptions(
                        top_k=self._config.search_top_k,
                        date_from=bounded_date_from,
                        date_to=bounded_date_to,
                    )
                }
            )
            search_result = self._searcher.search_request(search_request)
            rejected_ids = {rejected.article_id for rejected in rejected_history}
            candidate_articles = self._repository.get_articles(
                [hit.article_id for hit in search_result.hits if hit.article_id not in rejected_ids]
            )
            if round_number == 1 and not candidate_articles:
                logger.info("pipeline terminated: round=1 reason=no_articles selected=0")
                return TimelineGenerationResult(
                    status=GenerationStatus.NO_ARTICLES,
                    rounds=1,
                )

            articles_by_id.update({article.article_id: article for article in candidate_articles})
            candidate_ids = {article.article_id for article in candidate_articles}

            self._emit(round_number, PipelineStage.SELECT_ARTICLES, len(selected_by_id))
            selection = self._call_llm(
                _selection_prompt(intent, candidate_articles),
                ArticleSelection,
            )
            round_selected: list[SelectedArticle] = []
            for selected in selection.selected:
                if selected.article_id not in candidate_ids:
                    continue
                round_selected.append(selected)
                previous = selected_by_id.get(selected.article_id)
                if previous is None or selected.relevance_score > previous.relevance_score:
                    selected_by_id[selected.article_id] = selected
            rejected_history.extend(
                rejected for rejected in selection.rejected if rejected.article_id in candidate_ids
            )

            related_events: tuple[RelatedEvent, ...] = ()
            if round_selected:
                self._emit(
                    round_number,
                    PipelineStage.EXTRACT_RELATED_EVENTS,
                    len(selected_by_id),
                )
                related = self._call_llm(
                    _related_events_prompt(
                        round_selected,
                        articles_by_id,
                        date_from,
                        date_to,
                    ),
                    RelatedEvents,
                )
                round_selected_ids = {selected.article_id for selected in round_selected}
                related_events = tuple(
                    event
                    for event in related.events
                    if event.source_article_id in round_selected_ids
                    and date_from <= event.event_date <= date_to
                )
                if related_events:
                    chain_depth += 1

            self._emit(
                round_number,
                PipelineStage.REVIEW_SUFFICIENCY,
                len(selected_by_id),
            )
            review = self._call_llm(
                _sufficiency_prompt(intent, hypothetical, tuple(selected_by_id.values())),
                SufficiencyReview,
            )
            if review.updated_date_from is not None and review.updated_date_to is not None:
                date_from = review.updated_date_from
                date_to = review.updated_date_to

            selected_count = len(selected_by_id)
            if review.is_sufficient:
                termination = TerminationReason.SUFFICIENCY_PASSED
            elif selected_count == previous_selected_count:
                termination = TerminationReason.CONVERGED
            elif chain_depth >= self._config.max_chain_depth:
                termination = TerminationReason.DEPTH_LIMIT
            elif round_number >= self._config.max_rounds:
                termination = TerminationReason.ROUND_LIMIT

            self._emit(
                round_number,
                PipelineStage.REVIEW_SUFFICIENCY,
                selected_count,
                termination=termination,
            )
            if termination is not None:
                break

            self._emit(
                round_number,
                PipelineStage.GENERATE_HYPOTHESES,
                selected_count,
            )
            additional = self._call_llm(
                _additional_hypotheses_prompt(review.gaps, tuple(selected_by_id.values())),
                AdditionalHypotheses,
            )
            pending_seeds = [
                HypotheticalEvent(
                    expected_date=event.event_date,
                    description=event.description,
                )
                for event in related_events
            ]
            pending_seeds.extend(additional.events)
            previous_selected_count = selected_count

        if not selected_by_id:
            logger.info(
                "pipeline terminated: round=%s reason=no_articles selected=0",
                rounds,
            )
            return TimelineGenerationResult(
                status=GenerationStatus.NO_ARTICLES,
                termination=termination,
                rounds=rounds,
            )
        if termination is None:
            raise PipelineInvariantError("수집 루프가 종료 사유 없이 끝났습니다")

        self._emit(rounds, PipelineStage.MERGE_TIMELINE, len(selected_by_id))
        merged = self._call_llm(
            _merge_prompt(tuple(selected_by_id.values()), articles_by_id),
            MergedTimeline,
        )
        issue = self._validated_issue(topic, merged, selected_by_id)
        self._emit(rounds, PipelineStage.SAVE_ISSUE, len(selected_by_id))
        issue_id = self._repository.save_issue(issue)
        logger.info(
            "pipeline completed: rounds=%s selected=%s termination=%s issue_id=%s",
            rounds,
            len(selected_by_id),
            termination,
            issue_id,
        )
        return TimelineGenerationResult(
            status=GenerationStatus.COMPLETED,
            issue_id=issue_id,
            termination=termination,
            rounds=rounds,
            selected_article_count=len(selected_by_id),
        )

    def _validated_issue(
        self,
        topic: str,
        merged: MergedTimeline,
        selected_by_id: dict[int, SelectedArticle],
    ) -> IssueCreate:
        cited_ids = [article_id for event in merged.events for article_id in event.article_ids]
        existing_ids = {article.article_id for article in self._repository.get_articles(cited_ids)}
        valid_ids = existing_ids & selected_by_id.keys()
        event_inputs: list[IssueEventInput] = []
        seen_events: set[tuple[date, tuple[int, ...]]] = set()
        for event in sorted(merged.events, key=lambda item: (item.event_date, item.title)):
            article_ids = tuple(
                dict.fromkeys(
                    article_id for article_id in event.article_ids if article_id in valid_ids
                )
            )
            if not article_ids:
                continue
            identity = (event.event_date, tuple(sorted(article_ids)))
            if identity in seen_events:
                continue
            seen_events.add(identity)
            event_inputs.append(
                IssueEventInput(
                    event_order=len(event_inputs),
                    event_date=event.event_date,
                    title=event.title,
                    summary=event.summary,
                    articles=tuple(
                        EventArticleInput(
                            article_id=article_id,
                            relevance_score=selected_by_id[article_id].relevance_score,
                        )
                        for article_id in article_ids
                    ),
                )
            )
        if not event_inputs:
            raise PipelineInvariantError("인용 검증 뒤 근거가 있는 이벤트가 남지 않았습니다")
        return IssueCreate(
            topic=topic,
            title=merged.title,
            summary=merged.summary,
            generated_at=self._clock(),
            events=tuple(event_inputs),
        )

    def _call_llm(
        self,
        prompt: str,
        response_type: type[ResponseModel],
    ) -> ResponseModel:
        for attempt in range(2):
            try:
                return self._generator.generate(prompt, response_type)
            except LLMGenerationError:
                if attempt == 1:
                    raise
                delay = 2**attempt
                logger.warning(
                    "pipeline LLM retry: response_type=%s delay_seconds=%s",
                    response_type.__name__,
                    delay,
                )
                self._sleeper(delay)
        raise PipelineInvariantError("LLM 재시도 루프가 비정상 종료됐습니다")

    def _emit(
        self,
        round_number: int,
        stage: PipelineStage,
        selected_count: int,
        *,
        termination: TerminationReason | None = None,
    ) -> None:
        progress = PipelineProgress(
            round_number=round_number,
            stage=stage,
            selected_article_count=selected_count,
            termination=termination,
        )
        logger.info(
            "pipeline progress: round=%s stage=%s selected=%s termination=%s",
            round_number,
            stage,
            selected_count,
            termination,
        )
        if self._progress_sink is not None:
            self._progress_sink(progress)


def _intent_prompt(topic: str, clarification_answer: str | None) -> str:
    answer = clarification_answer.strip() if clarification_answer else "없음"
    return f"""P1 질의 의도 해석
토픽: {topic}
사용자의 보충 답변: {answer}

사건 범위와 관점을 한 문장의 intent로 정리하세요. 사건을 특정할 수 없으면 임의로 좁히지
말고 needs_clarification=true와 질문 하나만 반환하세요. 보충 답변이 있으면 함께 반영하세요.
"""


def _hypothetical_timeline_prompt(intent: str) -> str:
    return f"""P2 가상 타임라인 생성
해석된 의도: {intent}

검색을 이끌 기간과 가상 이벤트를 만드세요. 가상 이벤트는 검색 가설일 뿐 사실로 단정하지
마세요. 사건 성격에 맞는 범위를 잡고 근거 없이 기간을 넓히지 마세요.
"""


def _search_query_prompt(
    intent: str,
    date_from: date,
    date_to: date,
    seeds: Sequence[HypotheticalEvent],
    rejected: Sequence[RejectedArticle],
) -> str:
    seed_json = "\n".join(event.model_dump_json() for event in seeds) or "없음"
    rejected_json = "\n".join(item.model_dump_json() for item in rejected[-20:]) or "없음"
    return f"""P3 검색 쿼리 생성
의도: {intent}
허용 기간: {date_from.isoformat()} ~ {date_to.isoformat()}
검색 씨앗:
{seed_json}
이전 탈락 기사와 이유:
{rejected_json}

고유명사·날짜·수치가 핵심이면 keyword, 개념·상황이면 semantic, 둘 다 필요하거나 판단이
서지 않으면 hybrid를 고르세요. keyword/hybrid에는 keyword_terms와 연산자를,
semantic/hybrid에는 semantic_text를 채우세요. 선택 이유와 허용 기간 안의 날짜를 반환하세요.
"""


def _format_articles(articles: Sequence[Article]) -> str:
    blocks = []
    for article in articles:
        blocks.append(
            "\n".join(
                (
                    f"ARTICLE_ID: {article.article_id}",
                    f"SERVICE_DATE: {article.service_date.isoformat()}",
                    f"TITLE: {article.title}",
                    f"CONTENT: {article.content or ''}",
                )
            )
        )
    return "\n\n".join(blocks) or "없음"


def _selection_prompt(intent: str, articles: Sequence[Article]) -> str:
    return f"""P4 핵심 이벤트 선정
의도: {intent}
검색 결과 기사:
{_format_articles(articles)}

입력 ARTICLE_ID만 사용하세요. 이 사건에 실제로 속하는 기사는 모두 selected에 넣고,
event_date·event_summary·0~1 relevance_score를 반환하세요. 탈락 기사는 rejected에 이유를
남기세요. 같은 사건을 다룬 여러 기사도 이 단계에서는 모두 선택하세요.
"""


def _related_events_prompt(
    selected: Sequence[SelectedArticle],
    articles_by_id: dict[int, Article],
    date_from: date,
    date_to: date,
) -> str:
    articles = [articles_by_id[item.article_id] for item in selected]
    return f"""P5 선후 이벤트 추출
허용 기간: {date_from.isoformat()} ~ {date_to.isoformat()}
선정 기사:
{_format_articles(articles)}

본문에 실제로 서술된 선행·후속 사건만 반환하세요. 추론하지 말고 허용 기간 밖 사건과 이미
선정된 사건은 제외하세요. source_article_id는 입력 ARTICLE_ID만 사용하세요.
"""


def _sufficiency_prompt(
    intent: str,
    hypothetical: HypotheticalTimeline,
    selected: Sequence[SelectedArticle],
) -> str:
    selected_json = "\n".join(item.model_dump_json() for item in selected) or "없음"
    return f"""P6 충분성 검토
의도: {intent}
최초 가상 타임라인:
{hypothetical.model_dump_json()}
현재까지 실제 기사에서 선정한 사건 대응:
{selected_json}

사건의 시작과 끝, 날짜 사이 공백, 기사에서 언급됐지만 빠진 사건, 기간 조정 필요성을 모두
점검하세요. 충분하면 is_sufficient=true로 반환하세요. 부족하면 gaps에 구체적으로 쓰고 기간을
바꿀 때만 updated_date_from과 updated_date_to를 함께 반환하세요.
"""


def _additional_hypotheses_prompt(
    gaps: Sequence[str],
    selected: Sequence[SelectedArticle],
) -> str:
    gaps_text = "\n".join(f"- {gap}" for gap in gaps) or "- 명시된 공백 없음"
    selected_json = "\n".join(item.model_dump_json() for item in selected) or "없음"
    return f"""P7 추가 가상 이벤트 생성
부족한 지점:
{gaps_text}
이미 확보한 실제 사건 대응:
{selected_json}

부족한 지점을 겨냥하는 검색 가설만 만드세요. 사실로 단정하지 말고 이미 확보한 사건과
겹치지 않게 하세요.
"""


def _merge_prompt(
    selected: Sequence[SelectedArticle],
    articles_by_id: dict[int, Article],
) -> str:
    evidence_blocks = []
    for item in selected:
        article = articles_by_id[item.article_id]
        evidence_blocks.append(f"{item.model_dump_json()}\n{_format_articles((article,))}")
    evidence = "\n\n".join(evidence_blocks)
    return f"""P8 타임라인 병합
실제 선정 기사와 기사-사건 대응:
{evidence}

위 실제 기사만 근거로 제목·요약·시간순 이벤트를 만드세요. 입력 ARTICLE_ID만 인용하고 근거
기사가 없는 이벤트를 만들지 마세요. 날짜와 근거 기사 집합이 같은 이벤트는 하나로 합치세요.
"""
