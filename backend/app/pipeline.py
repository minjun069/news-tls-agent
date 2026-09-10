"""S5 검색·검증 루프 기반 타임라인 생성 오케스트레이션."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel

from core.config import TimelineConfig
from core.errors import LLMGenerationError, PipelineInvariantError
from core.models import (
    AdditionalHypotheses,
    Article,
    ArticleSearchRequest,
    ArticleSelection,
    EventArticleInput,
    GenerationStatus,
    HypotheticalEvent,
    HypotheticalTimeline,
    IntentInterpretation,
    IssueCreate,
    IssueEventInput,
    KeywordOperator,
    MergedTimeline,
    PipelineProgress,
    PipelineStage,
    RejectedArticle,
    RelatedEvent,
    RelatedEvents,
    SearchMethod,
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
RunIdFactory = Callable[[], str]
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _new_run_id() -> str:
    return str(uuid4())


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
        run_id_factory: RunIdFactory = _new_run_id,
    ) -> None:
        self._repository = repository
        self._searcher = searcher
        self._generator = generator
        self._model_name = getattr(generator, "model_name", type(generator).__name__)
        self._config = config
        self._progress_sink = progress_sink
        self._clock = clock
        self._sleeper = sleeper
        self._run_id_factory = run_id_factory

    def generate(
        self,
        topic: str,
        *,
        clarification_answer: str | None = None,
        clarification_count: int = 0,
    ) -> TimelineGenerationResult:
        run_id = self._run_id_factory()
        normalized_topic = " ".join(topic.split())
        if not normalized_topic:
            raise ValueError("토픽은 빈 문자열일 수 없습니다")
        if clarification_count < 0:
            raise ValueError("clarification_count는 0 이상이어야 합니다")

        logger.info(
            "pipeline started: run_id=%s model=%s",
            run_id,
            self._model_name,
            extra={
                "event_name": "pipeline.started",
                "run_id": run_id,
                "model_name": self._model_name,
            },
        )

        existing = self._repository.find_issue_by_topic(normalized_topic)
        if existing is not None:
            self._emit(
                round_number=0,
                stage=PipelineStage.CACHED,
                selected_count=sum(len(event.articles) for event in existing.events),
                termination=TerminationReason.CACHED,
                run_id=run_id,
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

        self._emit(0, PipelineStage.INTERPRET_INTENT, 0, run_id=run_id)
        interpretation = self._call_llm(
            _intent_prompt(normalized_topic, clarification_answer),
            IntentInterpretation,
            run_id=run_id,
        )
        logger.info(
            "pipeline intent: run_id=%s needs_clarification=%s user_specified_date=%s intent=%s",
            run_id,
            interpretation.needs_clarification,
            interpretation.user_specified_date,
            interpretation.intent,
            extra={
                "event_name": "pipeline.intent",
                "run_id": run_id,
                "needs_clarification": interpretation.needs_clarification,
                "user_specified_date": interpretation.user_specified_date,
                "interpreted_intent": interpretation.intent,
            },
        )
        if (
            interpretation.needs_clarification
            and clarification_count < self._config.max_clarifications
        ):
            self._emit(0, PipelineStage.CLARIFY, 0, run_id=run_id)
            return TimelineGenerationResult(
                status=GenerationStatus.NEEDS_CLARIFICATION,
                clarification_question=interpretation.clarification_question,
            )

        self._emit(0, PipelineStage.BUILD_HYPOTHETICAL_TIMELINE, 0, run_id=run_id)
        hypothetical = self._call_llm(
            _hypothetical_timeline_prompt(interpretation.intent),
            HypotheticalTimeline,
            run_id=run_id,
        )
        logger.info(
            "pipeline hypothetical: run_id=%s date_from=%s date_to=%s",
            run_id,
            hypothetical.date_from,
            hypothetical.date_to,
            extra={
                "event_name": "pipeline.hypothetical",
                "run_id": run_id,
                "date_from": hypothetical.date_from.isoformat(),
                "date_to": hypothetical.date_to.isoformat(),
            },
        )
        return self._collect_and_save(
            normalized_topic,
            interpretation.intent,
            hypothetical,
            user_specified_date=interpretation.user_specified_date,
            clarification_count=clarification_count,
            run_id=run_id,
        )

    def _collect_and_save(
        self,
        topic: str,
        intent: str,
        hypothetical: HypotheticalTimeline,
        *,
        user_specified_date: bool,
        clarification_count: int,
        run_id: str,
    ) -> TimelineGenerationResult:
        selected_by_id: dict[int, SelectedArticle] = {}
        articles_by_id: dict[int, Article] = {}
        rejected_history: list[RejectedArticle] = []
        pending_seeds = list(hypothetical.events)
        date_from = hypothetical.date_from
        date_to = hypothetical.date_to
        previous_selected_ids: set[int] = set()
        chain_depth = 0
        termination: TerminationReason | None = None
        rounds = 0

        for round_number in range(1, self._config.max_rounds + 1):
            rounds = round_number
            self._emit(
                round_number,
                PipelineStage.GENERATE_SEARCH_QUERY,
                len(selected_by_id),
                run_id=run_id,
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
                run_id=run_id,
            )
            search_request = draft.to_search_request(top_k=self._config.search_top_k)
            bounded_date_from = max(date_from, draft.date_from)
            bounded_date_to = min(date_to, draft.date_to)
            if bounded_date_from > bounded_date_to:
                bounded_date_from = date_from
                bounded_date_to = date_to
            apply_date_filter = user_specified_date or round_number > 1
            applied_date_from = bounded_date_from if apply_date_filter else None
            applied_date_to = bounded_date_to if apply_date_filter else None
            search_request = search_request.model_copy(
                update={
                    "options": SearchOptions(
                        top_k=self._config.search_top_k,
                        date_from=applied_date_from,
                        date_to=applied_date_to,
                    )
                }
            )
            logger.info(
                "pipeline search request: run_id=%s round=%s attempt=primary method=%s "
                "keywords=%s semantic=%s requested_period=%s..%s applied_period=%s..%s reason=%s",
                run_id,
                round_number,
                draft.method,
                draft.keyword_terms,
                draft.semantic_text,
                draft.date_from,
                draft.date_to,
                applied_date_from,
                applied_date_to,
                draft.reason,
                extra={
                    "event_name": "pipeline.search.request",
                    "run_id": run_id,
                    "round_number": round_number,
                    "search_attempt": "primary",
                    "search_method": draft.method.value,
                    "keyword_terms": draft.keyword_terms,
                    "semantic_text": draft.semantic_text,
                    "requested_date_from": draft.date_from.isoformat(),
                    "requested_date_to": draft.date_to.isoformat(),
                    "applied_date_from": (
                        applied_date_from.isoformat() if applied_date_from else None
                    ),
                    "applied_date_to": applied_date_to.isoformat() if applied_date_to else None,
                    "search_reason": draft.reason,
                },
            )
            search_result = self._searcher.search_request(search_request)
            rejected_ids = {rejected.article_id for rejected in rejected_history}
            candidate_articles = self._repository.get_articles(
                [hit.article_id for hit in search_result.hits if hit.article_id not in rejected_ids]
            )
            logger.info(
                "pipeline search result: run_id=%s round=%s attempt=primary "
                "qdrant_hits=%s mssql_articles=%s",
                run_id,
                round_number,
                len(search_result.hits),
                len(candidate_articles),
                extra={
                    "event_name": "pipeline.search.result",
                    "run_id": run_id,
                    "round_number": round_number,
                    "search_attempt": "primary",
                    "qdrant_result_count": len(search_result.hits),
                    "mssql_restored_count": len(candidate_articles),
                },
            )
            if round_number == 1 and not candidate_articles:
                fallback_request = ArticleSearchRequest(
                    method=SearchMethod.HYBRID,
                    options=SearchOptions(top_k=self._config.search_top_k),
                    keyword_terms=(topic,),
                    keyword_operator=KeywordOperator.OR,
                    semantic_text=topic,
                )
                logger.info(
                    "pipeline search request: run_id=%s round=1 attempt=fallback method=hybrid "
                    "keywords=%s semantic=%s applied_period=None..None reason=first_search_empty",
                    run_id,
                    fallback_request.keyword_terms,
                    fallback_request.semantic_text,
                    extra={
                        "event_name": "pipeline.search.request",
                        "run_id": run_id,
                        "round_number": 1,
                        "search_attempt": "fallback",
                        "search_method": SearchMethod.HYBRID.value,
                        "keyword_terms": fallback_request.keyword_terms,
                        "semantic_text": fallback_request.semantic_text,
                        "requested_date_from": None,
                        "requested_date_to": None,
                        "applied_date_from": None,
                        "applied_date_to": None,
                        "search_reason": "first_search_empty",
                    },
                )
                search_result = self._searcher.search_request(fallback_request)
                candidate_articles = self._repository.get_articles(
                    [hit.article_id for hit in search_result.hits]
                )
                logger.info(
                    "pipeline search result: run_id=%s round=1 attempt=fallback "
                    "qdrant_hits=%s mssql_articles=%s",
                    run_id,
                    len(search_result.hits),
                    len(candidate_articles),
                    extra={
                        "event_name": "pipeline.search.result",
                        "run_id": run_id,
                        "round_number": 1,
                        "search_attempt": "fallback",
                        "qdrant_result_count": len(search_result.hits),
                        "mssql_restored_count": len(candidate_articles),
                    },
                )
                if not candidate_articles:
                    logger.info(
                        "pipeline terminated: run_id=%s round=1 reason=no_articles selected=0",
                        run_id,
                        extra={
                            "event_name": "pipeline.terminated",
                            "run_id": run_id,
                            "round_number": 1,
                            "termination_reason": GenerationStatus.NO_ARTICLES.value,
                            "selected_article_count": 0,
                        },
                    )
                    return TimelineGenerationResult(
                        status=GenerationStatus.NO_ARTICLES,
                        rounds=1,
                    )

            candidate_years = sorted({article.service_date.year for article in candidate_articles})
            if (
                round_number == 1
                and not user_specified_date
                and len(candidate_years) > 1
                and clarification_count < self._config.max_clarifications
            ):
                question = (
                    f"{', '.join(str(year) for year in candidate_years)}년 중 어느 시기의 사건을 "
                    "말씀하시나요?"
                )
                logger.info(
                    "pipeline period clarification: run_id=%s candidate_years=%s",
                    run_id,
                    tuple(candidate_years),
                    extra={
                        "event_name": "pipeline.period_clarification",
                        "run_id": run_id,
                        "candidate_years": tuple(candidate_years),
                    },
                )
                self._emit(0, PipelineStage.CLARIFY, 0, run_id=run_id)
                return TimelineGenerationResult(
                    status=GenerationStatus.NEEDS_CLARIFICATION,
                    clarification_question=question,
                )

            if not candidate_articles:
                if round_number >= 2:
                    termination = TerminationReason.CONVERGED
                    self._emit(
                        round_number,
                        PipelineStage.GENERATE_SEARCH_QUERY,
                        len(selected_by_id),
                        termination=termination,
                        run_id=run_id,
                    )
                    break
                continue

            articles_by_id.update({article.article_id: article for article in candidate_articles})
            candidate_ids = {article.article_id for article in candidate_articles}

            self._emit(
                round_number,
                PipelineStage.SELECT_ARTICLES,
                len(selected_by_id),
                run_id=run_id,
            )
            selection = self._call_llm(
                _selection_prompt(intent, candidate_articles),
                ArticleSelection,
                run_id=run_id,
            )
            (
                round_selected,
                round_rejected,
                unclassified_ids,
                unexpected_ids,
                classification_complete,
            ) = _selection_details(selection, candidate_ids)
            selection_attempt = 1
            if not classification_complete or not round_selected:
                logger.info(
                    "pipeline selection retry: run_id=%s round=%s selected_ids=%s "
                    "rejected=%s unclassified_ids=%s unexpected_ids=%s",
                    run_id,
                    round_number,
                    tuple(item.article_id for item in round_selected),
                    tuple((item.article_id, item.reason) for item in round_rejected),
                    unclassified_ids,
                    unexpected_ids,
                    extra={
                        "event_name": "pipeline.selection.retry",
                        "run_id": run_id,
                        "round_number": round_number,
                        "selection_attempt": selection_attempt,
                        "selected_article_ids": tuple(item.article_id for item in round_selected),
                        "rejected_articles": tuple(
                            (item.article_id, item.reason) for item in round_rejected
                        ),
                        "unclassified_article_ids": unclassified_ids,
                        "unexpected_article_ids": unexpected_ids,
                    },
                )
                selection = self._call_llm(
                    _selection_retry_prompt(
                        intent,
                        candidate_articles,
                        selection,
                        unclassified_ids,
                        unexpected_ids,
                    ),
                    ArticleSelection,
                    run_id=run_id,
                )
                (
                    round_selected,
                    round_rejected,
                    unclassified_ids,
                    unexpected_ids,
                    classification_complete,
                ) = _selection_details(selection, candidate_ids)
                selection_attempt = 2

            if unclassified_ids:
                round_rejected = (
                    *round_rejected,
                    *(
                        RejectedArticle(
                            article_id=article_id,
                            reason="P4 응답에서 선정 또는 탈락으로 분류하지 않음",
                        )
                        for article_id in unclassified_ids
                    ),
                )

            for selected in round_selected:
                previous = selected_by_id.get(selected.article_id)
                if previous is None or selected.relevance_score > previous.relevance_score:
                    selected_by_id[selected.article_id] = selected
            rejected_history.extend(round_rejected)
            new_selected_ids = set(selected_by_id) - previous_selected_ids
            logger.info(
                "pipeline selection: run_id=%s round=%s attempt=%s complete=%s "
                "selected_ids=%s rejected=%s unclassified_ids=%s unexpected_ids=%s",
                run_id,
                round_number,
                selection_attempt,
                classification_complete,
                tuple(item.article_id for item in round_selected),
                tuple((item.article_id, item.reason) for item in round_rejected),
                unclassified_ids,
                unexpected_ids,
                extra={
                    "event_name": "pipeline.selection",
                    "run_id": run_id,
                    "round_number": round_number,
                    "selection_attempt": selection_attempt,
                    "classification_complete": classification_complete,
                    "selected_article_ids": tuple(item.article_id for item in round_selected),
                    "rejected_articles": tuple(
                        (item.article_id, item.reason) for item in round_rejected
                    ),
                    "unclassified_article_ids": unclassified_ids,
                    "unexpected_article_ids": unexpected_ids,
                },
            )

            if not round_selected:
                if round_number >= 2:
                    termination = TerminationReason.CONVERGED
                    self._emit(
                        round_number,
                        PipelineStage.SELECT_ARTICLES,
                        len(selected_by_id),
                        termination=termination,
                        run_id=run_id,
                    )
                    break
                continue

            related_events: tuple[RelatedEvent, ...] = ()
            if round_selected:
                self._emit(
                    round_number,
                    PipelineStage.EXTRACT_RELATED_EVENTS,
                    len(selected_by_id),
                    run_id=run_id,
                )
                related = self._call_llm(
                    _related_events_prompt(
                        round_selected,
                        articles_by_id,
                        date_from,
                        date_to,
                    ),
                    RelatedEvents,
                    run_id=run_id,
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
                run_id=run_id,
            )
            review = self._call_llm(
                _sufficiency_prompt(intent, hypothetical, tuple(selected_by_id.values())),
                SufficiencyReview,
                run_id=run_id,
            )
            if review.updated_date_from is not None and review.updated_date_to is not None:
                date_from = review.updated_date_from
                date_to = review.updated_date_to

            selected_count = len(selected_by_id)
            if review.is_sufficient:
                termination = TerminationReason.SUFFICIENCY_PASSED
            elif round_number >= 2 and not new_selected_ids:
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
                run_id=run_id,
            )
            if termination is not None:
                break

            self._emit(
                round_number,
                PipelineStage.GENERATE_HYPOTHESES,
                selected_count,
                run_id=run_id,
            )
            additional = self._call_llm(
                _additional_hypotheses_prompt(review.gaps, tuple(selected_by_id.values())),
                AdditionalHypotheses,
                run_id=run_id,
            )
            pending_seeds = [
                HypotheticalEvent(
                    expected_date=event.event_date,
                    description=event.description,
                )
                for event in related_events
            ]
            pending_seeds.extend(additional.events)
            previous_selected_ids = set(selected_by_id)

        if not selected_by_id:
            logger.info(
                "pipeline terminated: run_id=%s round=%s reason=no_articles selected=0",
                run_id,
                rounds,
                extra={
                    "event_name": "pipeline.terminated",
                    "run_id": run_id,
                    "round_number": rounds,
                    "termination_reason": GenerationStatus.NO_ARTICLES.value,
                    "selected_article_count": 0,
                },
            )
            return TimelineGenerationResult(
                status=GenerationStatus.NO_ARTICLES,
                termination=termination,
                rounds=rounds,
            )
        if termination is None:
            raise PipelineInvariantError("수집 루프가 종료 사유 없이 끝났습니다")

        self._emit(
            rounds,
            PipelineStage.MERGE_TIMELINE,
            len(selected_by_id),
            run_id=run_id,
        )
        merged = self._call_llm(
            _merge_prompt(tuple(selected_by_id.values()), articles_by_id),
            MergedTimeline,
            run_id=run_id,
        )
        issue = self._validated_issue(topic, merged, selected_by_id)
        self._emit(
            rounds,
            PipelineStage.SAVE_ISSUE,
            len(selected_by_id),
            run_id=run_id,
        )
        issue_id = self._repository.save_issue(issue)
        logger.info(
            "pipeline completed: run_id=%s rounds=%s selected=%s termination=%s issue_id=%s",
            run_id,
            rounds,
            len(selected_by_id),
            termination,
            issue_id,
            extra={
                "event_name": "pipeline.completed",
                "run_id": run_id,
                "round_number": rounds,
                "selected_article_count": len(selected_by_id),
                "termination_reason": termination.value,
                "issue_id": issue_id,
            },
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
        *,
        run_id: str,
    ) -> ResponseModel:
        for attempt in range(2):
            logger.info(
                "pipeline LLM call: run_id=%s model=%s response_type=%s attempt=%s",
                run_id,
                self._model_name,
                response_type.__name__,
                attempt + 1,
                extra={
                    "event_name": "pipeline.llm.call",
                    "run_id": run_id,
                    "model_name": self._model_name,
                    "response_type": response_type.__name__,
                    "attempt": attempt + 1,
                },
            )
            try:
                return self._generator.generate(prompt, response_type)
            except LLMGenerationError:
                if attempt == 1:
                    raise
                delay = 2**attempt
                logger.warning(
                    "pipeline LLM retry: run_id=%s model=%s response_type=%s delay_seconds=%s",
                    run_id,
                    self._model_name,
                    response_type.__name__,
                    delay,
                    extra={
                        "event_name": "pipeline.llm.retry",
                        "run_id": run_id,
                        "model_name": self._model_name,
                        "response_type": response_type.__name__,
                        "delay_seconds": delay,
                    },
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
        run_id: str,
    ) -> None:
        progress = PipelineProgress(
            round_number=round_number,
            stage=stage,
            selected_article_count=selected_count,
            termination=termination,
        )
        logger.info(
            "pipeline progress: run_id=%s round=%s stage=%s selected=%s termination=%s",
            run_id,
            round_number,
            stage,
            selected_count,
            termination,
            extra={
                "event_name": "pipeline.progress",
                "run_id": run_id,
                "round_number": round_number,
                "pipeline_stage": stage.value,
                "selected_article_count": selected_count,
                "termination_reason": termination.value if termination else None,
            },
        )
        if self._progress_sink is not None:
            self._progress_sink(progress)


def _intent_prompt(topic: str, clarification_answer: str | None) -> str:
    answer = clarification_answer.strip() if clarification_answer else "없음"
    return f"""P1 질의 의도 해석
토픽: {topic}
사용자의 보충 답변: {answer}

사건 범위와 관점을 한 문장의 intent로 정리하세요. 사건을 특정할 수 없으면 임의로 좁히지
말고 needs_clarification=true와 질문 하나만 반환하세요. 토픽 또는 보충 답변에 연도·월·일·
기간 표현이 있으면 user_specified_date=true, 없으면 false로 반환하세요. 날짜가 없다는 이유만으로
되묻지 말고 보충 답변이 있으면 함께 반영하세요.
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


def _selection_details(
    selection: ArticleSelection,
    candidate_ids: set[int],
) -> tuple[
    tuple[SelectedArticle, ...],
    tuple[RejectedArticle, ...],
    tuple[int, ...],
    tuple[int, ...],
    bool,
]:
    selected_by_id: dict[int, SelectedArticle] = {}
    for item in selection.selected:
        if item.article_id not in candidate_ids:
            continue
        previous = selected_by_id.get(item.article_id)
        if previous is None or item.relevance_score > previous.relevance_score:
            selected_by_id[item.article_id] = item

    rejected_by_id: dict[int, RejectedArticle] = {}
    for item in selection.rejected:
        if item.article_id in candidate_ids and item.article_id not in selected_by_id:
            rejected_by_id.setdefault(item.article_id, item)

    raw_ids = [item.article_id for item in (*selection.selected, *selection.rejected)]
    classified_ids = set(raw_ids)
    unclassified_ids = tuple(sorted(candidate_ids - classified_ids))
    unexpected_ids = tuple(sorted(classified_ids - candidate_ids))
    classification_complete = len(raw_ids) == len(candidate_ids) and classified_ids == candidate_ids
    return (
        tuple(selected_by_id.values()),
        tuple(rejected_by_id.values()),
        unclassified_ids,
        unexpected_ids,
        classification_complete,
    )


def _selection_prompt(intent: str, articles: Sequence[Article]) -> str:
    return f"""P4 핵심 이벤트 선정
의도: {intent}
검색 결과 기사:
{_format_articles(articles)}

입력 ARTICLE_ID만 사용하세요. 이 사건에 실제로 속하는 기사는 모두 selected에 넣고,
event_date·event_summary·0~1 relevance_score를 반환하세요. 탈락 기사는 rejected에 이유를
남기세요. 같은 사건을 다룬 여러 기사도 이 단계에서는 모두 선택하세요.
"""


def _selection_retry_prompt(
    intent: str,
    articles: Sequence[Article],
    previous: ArticleSelection,
    unclassified_ids: Sequence[int],
    unexpected_ids: Sequence[int],
) -> str:
    return f"""P4 핵심 이벤트 선정 수정
의도: {intent}
검색 결과 기사:
{_format_articles(articles)}

이전 판정:
{previous.model_dump_json()}
미분류 ARTICLE_ID: {tuple(unclassified_ids)}
입력에 없던 ARTICLE_ID: {tuple(unexpected_ids)}

검색 결과의 모든 ARTICLE_ID를 정확히 한 번만 판정하세요. 실제 사건에 속하면 selected에
event_date·event_summary·0~1 relevance_score와 함께 넣고, 속하지 않으면 rejected에 구체적인
탈락 사유와 함께 넣으세요. 입력에 없는 ARTICLE_ID는 반환하지 마세요.
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
