from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import date, datetime

import pytest

from app.pipeline import TimelinePipeline
from core.config import TimelineConfig
from core.errors import LLMGenerationError, LLMServiceUnavailableError
from core.models import (
    AdditionalHypotheses,
    Article,
    ArticleSelection,
    GenerationStatus,
    HypotheticalEvent,
    HypotheticalTimeline,
    IntentInterpretation,
    IssueDetail,
    MergedTimeline,
    MergedTimelineEvent,
    RelatedEvent,
    RelatedEvents,
    SearchHit,
    SearchMethod,
    SearchQueryDraft,
    SearchResult,
    SelectedArticle,
    SufficiencyReview,
    TerminationReason,
)


class FakeRepository:
    def __init__(self, articles: list[Article]) -> None:
        self.articles = {article.article_id: article for article in articles}
        self.saved = []
        self.existing = None

    def find_issue_by_topic(self, topic):
        return self.existing

    def get_articles(self, article_ids):
        return [
            self.articles[article_id]
            for article_id in dict.fromkeys(article_ids)
            if article_id in self.articles
        ]

    def save_issue(self, issue):
        self.saved.append(issue)
        return 91


class FakeSearcher:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = deque(results)
        self.requests = []

    def search_request(self, request):
        self.requests.append(request)
        return self.results.popleft()


class ScriptedGenerator:
    model_name = "test-model"

    def __init__(self, responses: dict[type, list[object]]) -> None:
        self.responses = {key: deque(values) for key, values in responses.items()}
        self.prompts = defaultdict(list)

    def generate(self, prompt, response_type):
        self.prompts[response_type].append(prompt)
        response = self.responses[response_type].popleft()
        if isinstance(response, Exception):
            raise response
        return response


def article(article_id: int = 1, *, published_on: date | None = None) -> Article:
    return Article(
        article_id=article_id,
        title=f"실제 기사 {article_id}",
        service_date=published_on or date(2025, 1, article_id),
        content=f"실제 본문 {article_id}",
    )


def intent(
    *,
    needs_clarification: bool = False,
    user_specified_date: bool = True,
) -> IntentInterpretation:
    return IntentInterpretation(
        intent="대통령 탄핵 사건의 진행",
        user_specified_date=user_specified_date,
        needs_clarification=needs_clarification,
        clarification_question="어느 나라 사건인가요?" if needs_clarification else None,
    )


def hypothetical() -> HypotheticalTimeline:
    return HypotheticalTimeline(
        date_from=date(2025, 1, 1),
        date_to=date(2025, 1, 31),
        events=(
            HypotheticalEvent(
                expected_date=date(2025, 1, 2),
                description="절대 최종 결과에 나오면 안 되는 가상 사건",
            ),
        ),
    )


def draft() -> SearchQueryDraft:
    return SearchQueryDraft(
        method=SearchMethod.KEYWORD,
        reason="고유명사 중심",
        keyword_terms=("탄핵", "대통령"),
        date_from=date(2025, 1, 1),
        date_to=date(2025, 1, 31),
    )


def selected(article_id: int = 1) -> SelectedArticle:
    return SelectedArticle(
        article_id=article_id,
        event_date=date(2025, 1, 2),
        event_summary="실제 사건",
        relevance_score=0.9,
    )


def merged(*article_ids: int) -> MergedTimeline:
    return MergedTimeline(
        title="검증된 타임라인",
        summary="실제 기사 기반",
        events=(
            MergedTimelineEvent(
                event_date=date(2025, 1, 2),
                title="실제 이벤트",
                summary="근거 있음",
                article_ids=article_ids,
            ),
        ),
    )


def config(*, max_rounds: int = 4, max_chain_depth: int = 2) -> TimelineConfig:
    return TimelineConfig(
        max_rounds=max_rounds,
        max_chain_depth=max_chain_depth,
        max_clarifications=2,
        search_top_k=20,
    )


def test_pipeline_filters_hallucinated_ids_and_never_passes_hypotheses_to_p8() -> None:
    repository = FakeRepository([article()])
    searcher = FakeSearcher(
        [SearchResult(method=SearchMethod.KEYWORD, hits=(SearchHit(article_id=1, score=4),))]
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent()],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft()],
            ArticleSelection: [
                ArticleSelection(selected=(selected(), selected(999))),
                ArticleSelection(selected=(selected(),)),
            ],
            RelatedEvents: [
                RelatedEvents(
                    events=(
                        RelatedEvent(
                            event_date=date(2025, 1, 3),
                            description="본문의 후속 사건",
                            source_article_id=1,
                        ),
                        RelatedEvent(
                            event_date=date(2025, 1, 4),
                            description="허구 ID 사건",
                            source_article_id=999,
                        ),
                    )
                )
            ],
            SufficiencyReview: [SufficiencyReview(is_sufficient=True)],
            MergedTimeline: [
                MergedTimeline(
                    title="검증된 타임라인",
                    events=(
                        MergedTimelineEvent(
                            event_date=date(2025, 1, 2),
                            title="실제 이벤트",
                            article_ids=(1, 999),
                        ),
                        MergedTimelineEvent(
                            event_date=date(2025, 1, 5),
                            title="허구 이벤트",
                            article_ids=(999,),
                        ),
                    ),
                )
            ],
        }
    )
    progress = []
    pipeline = TimelinePipeline(
        repository,
        searcher,
        generator,
        config(),
        progress_sink=progress.append,
        clock=lambda: datetime(2025, 2, 1),
        sleeper=lambda _: None,
    )

    result = pipeline.generate(" 대통령   탄핵 ")

    assert result.status is GenerationStatus.COMPLETED
    assert result.issue_id == 91
    assert result.termination is TerminationReason.SUFFICIENCY_PASSED
    assert result.selected_article_count == 1
    saved = repository.saved[0]
    assert saved.topic == "대통령 탄핵"
    assert len(saved.events) == 1
    assert [link.article_id for link in saved.events[0].articles] == [1]
    merge_prompt = generator.prompts[MergedTimeline][0]
    assert "절대 최종 결과에 나오면 안 되는 가상 사건" not in merge_prompt
    assert "실제 기사 1" in merge_prompt
    assert progress[-1].stage.value == "save"


def test_pipeline_returns_no_articles_only_after_the_fallback_search_is_empty(caplog) -> None:
    repository = FakeRepository([])
    searcher = FakeSearcher(
        [
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(SearchHit(article_id=404, score=1),),
            ),
            SearchResult(method=SearchMethod.HYBRID, hits=()),
        ]
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent()],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft()],
        }
    )
    pipeline = TimelinePipeline(repository, searcher, generator, config(), sleeper=lambda _: None)

    with caplog.at_level(logging.INFO, logger="news_tls_agent.pipeline"):
        result = pipeline.generate("없는 기사")

    assert result.status is GenerationStatus.NO_ARTICLES
    assert result.rounds == 1
    assert repository.saved == []
    assert generator.prompts[ArticleSelection] == []
    assert len(searcher.requests) == 2
    fallback = searcher.requests[1]
    assert fallback.method is SearchMethod.HYBRID
    assert fallback.keyword_terms == ("없는 기사",)
    assert fallback.semantic_text == "없는 기사"
    assert fallback.options.date_from is None
    assert fallback.options.date_to is None
    result_attempts = [
        record.search_attempt
        for record in caplog.records
        if getattr(record, "event_name", None) == "pipeline.search.result"
    ]
    assert result_attempts == ["primary", "fallback"]


def test_pipeline_recovers_with_original_topic_hybrid_fallback() -> None:
    repository = FakeRepository([article(1, published_on=date(2025, 3, 22))])
    searcher = FakeSearcher(
        [
            SearchResult(method=SearchMethod.KEYWORD, hits=()),
            SearchResult(
                method=SearchMethod.HYBRID,
                hits=(SearchHit(article_id=1, score=4),),
            ),
        ]
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent(user_specified_date=False)],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft()],
            ArticleSelection: [ArticleSelection(selected=(selected(),))],
            RelatedEvents: [RelatedEvents()],
            SufficiencyReview: [SufficiencyReview(is_sufficient=True)],
            MergedTimeline: [merged(1)],
        }
    )
    pipeline = TimelinePipeline(repository, searcher, generator, config(), sleeper=lambda _: None)

    result = pipeline.generate("영남권 산불")

    assert result.status is GenerationStatus.COMPLETED
    assert len(searcher.requests) == 2
    fallback = searcher.requests[1]
    assert fallback.method is SearchMethod.HYBRID
    assert fallback.keyword_terms == ("영남권 산불",)
    assert fallback.semantic_text == "영남권 산불"
    assert fallback.options.date_from is None
    assert fallback.options.date_to is None


def test_pipeline_retries_incomplete_selection_with_missing_candidate_ids() -> None:
    repository = FakeRepository([article(1), article(2)])
    searcher = FakeSearcher(
        [
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(SearchHit(article_id=1, score=4), SearchHit(article_id=2, score=3)),
            )
        ]
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent()],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft()],
            ArticleSelection: [
                ArticleSelection(selected=(selected(1),)),
                ArticleSelection(
                    selected=(selected(1),),
                    rejected=({"article_id": 2, "reason": "다른 사건"},),
                ),
            ],
            RelatedEvents: [RelatedEvents()],
            SufficiencyReview: [SufficiencyReview(is_sufficient=True)],
            MergedTimeline: [merged(1)],
        }
    )
    pipeline = TimelinePipeline(repository, searcher, generator, config(), sleeper=lambda _: None)

    result = pipeline.generate("선정 완전성")

    assert result.status is GenerationStatus.COMPLETED
    assert len(generator.prompts[ArticleSelection]) == 2
    assert "미분류 ARTICLE_ID: (2,)" in generator.prompts[ArticleSelection][1]
    assert '"article_id":1' in generator.prompts[ArticleSelection][1]


def test_pipeline_moves_to_next_search_after_selection_retry_rejects_all() -> None:
    repository = FakeRepository([article(1), article(2)])
    searcher = FakeSearcher(
        [
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(SearchHit(article_id=1, score=4),),
            ),
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(SearchHit(article_id=2, score=4),),
            ),
        ]
    )
    rejected_one = ArticleSelection(rejected=({"article_id": 1, "reason": "다른 지역 사건"},))
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent()],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft(), draft()],
            ArticleSelection: [
                rejected_one,
                rejected_one,
                ArticleSelection(selected=(selected(2),)),
            ],
            RelatedEvents: [RelatedEvents()],
            SufficiencyReview: [SufficiencyReview(is_sufficient=True)],
            MergedTimeline: [merged(2)],
        }
    )
    pipeline = TimelinePipeline(repository, searcher, generator, config(), sleeper=lambda _: None)

    result = pipeline.generate("P4 전건 탈락")

    assert result.status is GenerationStatus.COMPLETED
    assert result.rounds == 2
    assert len(searcher.requests) == 2
    assert len(generator.prompts[ArticleSelection]) == 3
    assert "다른 지역 사건" in generator.prompts[ArticleSelection][1]
    assert len(generator.prompts[SufficiencyReview]) == 1


def test_pipeline_does_not_converge_when_each_round_selects_a_different_id() -> None:
    repository = FakeRepository([article(1), article(2)])
    searcher = FakeSearcher(
        [
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(SearchHit(article_id=1, score=4),),
            ),
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(SearchHit(article_id=2, score=4),),
            ),
        ]
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent()],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft(), draft()],
            ArticleSelection: [
                ArticleSelection(selected=(selected(1),)),
                ArticleSelection(selected=(selected(2),)),
            ],
            RelatedEvents: [RelatedEvents(), RelatedEvents()],
            SufficiencyReview: [
                SufficiencyReview(is_sufficient=False, gaps=("추가 검색",)),
                SufficiencyReview(is_sufficient=False, gaps=("추가 검색",)),
            ],
            AdditionalHypotheses: [AdditionalHypotheses()],
            MergedTimeline: [merged(1, 2)],
        }
    )
    pipeline = TimelinePipeline(
        repository,
        searcher,
        generator,
        config(max_rounds=2),
        sleeper=lambda _: None,
    )

    result = pipeline.generate("라운드별 다른 기사")

    assert result.status is GenerationStatus.COMPLETED
    assert result.termination is TerminationReason.ROUND_LIMIT
    assert result.selected_article_count == 2


@pytest.mark.parametrize(
    ("expected", "pipeline_config", "related_round_one", "rounds"),
    [
        (TerminationReason.CONVERGED, config(), RelatedEvents(), 2),
        (
            TerminationReason.DEPTH_LIMIT,
            config(max_chain_depth=1),
            RelatedEvents(
                events=(
                    RelatedEvent(
                        event_date=date(2025, 1, 3),
                        description="후속 사건",
                        source_article_id=1,
                    ),
                )
            ),
            1,
        ),
        (TerminationReason.ROUND_LIMIT, config(max_rounds=1), RelatedEvents(), 1),
    ],
)
def test_pipeline_enforces_each_non_sufficiency_termination(
    expected: TerminationReason,
    pipeline_config: TimelineConfig,
    related_round_one: RelatedEvents,
    rounds: int,
) -> None:
    repository = FakeRepository([article()])
    searcher = FakeSearcher(
        [
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(SearchHit(article_id=1, score=4),),
            )
            for _ in range(rounds)
        ]
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent()],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft() for _ in range(rounds)],
            ArticleSelection: [ArticleSelection(selected=(selected(),)) for _ in range(rounds)],
            RelatedEvents: [related_round_one] + [RelatedEvents() for _ in range(rounds - 1)],
            SufficiencyReview: [
                SufficiencyReview(is_sufficient=False, gaps=("중간 공백",)) for _ in range(rounds)
            ],
            AdditionalHypotheses: [AdditionalHypotheses(events=()) for _ in range(rounds - 1)],
            MergedTimeline: [merged(1)],
        }
    )
    pipeline = TimelinePipeline(
        repository,
        searcher,
        generator,
        pipeline_config,
        sleeper=lambda _: None,
    )

    result = pipeline.generate("종료 조건")

    assert result.status is GenerationStatus.COMPLETED
    assert result.termination is expected
    assert result.rounds == rounds


def test_pipeline_returns_one_clarification_and_respects_the_cap() -> None:
    repository = FakeRepository([])
    first = ScriptedGenerator({IntentInterpretation: [intent(needs_clarification=True)]})
    pipeline = TimelinePipeline(
        repository,
        FakeSearcher([]),
        first,
        config(),
        sleeper=lambda _: None,
    )

    result = pipeline.generate("탄핵")

    assert result.status is GenerationStatus.NEEDS_CLARIFICATION
    assert result.clarification_question == "어느 나라 사건인가요?"

    capped = ScriptedGenerator(
        {
            IntentInterpretation: [intent(needs_clarification=True)],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft()],
        }
    )
    capped_pipeline = TimelinePipeline(
        repository,
        FakeSearcher(
            [
                SearchResult(method=SearchMethod.KEYWORD, hits=()),
                SearchResult(method=SearchMethod.HYBRID, hits=()),
            ]
        ),
        capped,
        config(),
        sleeper=lambda _: None,
    )

    capped_result = capped_pipeline.generate("탄핵", clarification_count=2)

    assert capped_result.status is GenerationStatus.NO_ARTICLES
    assert len(capped.prompts[HypotheticalTimeline]) == 1


def test_pipeline_reuses_existing_topic_without_llm_or_search() -> None:
    repository = FakeRepository([])
    repository.existing = IssueDetail(
        issue_id=12,
        topic="기존 이슈",
        title="기존 제목",
        summary=None,
        generated_at=datetime(2025, 1, 1),
        events=(),
    )
    searcher = FakeSearcher([])
    generator = ScriptedGenerator({})
    pipeline = TimelinePipeline(
        repository,
        searcher,
        generator,
        config(),
        sleeper=lambda _: None,
    )

    result = pipeline.generate("기존 이슈")

    assert result.status is GenerationStatus.REUSED
    assert result.issue_id == 12
    assert result.termination is TerminationReason.CACHED
    assert searcher.requests == []
    assert generator.prompts == {}


def test_pipeline_retries_an_llm_failure_once() -> None:
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [LLMGenerationError("temporary"), intent()],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft()],
        }
    )
    delays = []
    pipeline = TimelinePipeline(
        FakeRepository([]),
        FakeSearcher(
            [
                SearchResult(method=SearchMethod.KEYWORD, hits=()),
                SearchResult(method=SearchMethod.HYBRID, hits=()),
            ]
        ),
        generator,
        config(),
        sleeper=delays.append,
    )

    result = pipeline.generate("재시도")

    assert result.status is GenerationStatus.NO_ARTICLES
    assert len(generator.prompts[IntentInterpretation]) == 2
    assert delays == [1]


def test_pipeline_does_not_repeat_adapter_managed_service_retries() -> None:
    generator = ScriptedGenerator(
        {IntentInterpretation: [LLMServiceUnavailableError("service unavailable")]}
    )
    delays: list[float] = []
    pipeline = TimelinePipeline(
        FakeRepository([]),
        FakeSearcher([]),
        generator,
        config(),
        sleeper=delays.append,
    )

    with pytest.raises(LLMServiceUnavailableError):
        pipeline.generate("재시도 중복 방지")

    assert len(generator.prompts[IntentInterpretation]) == 1
    assert delays == []


def test_pipeline_excludes_rejected_articles_and_bounds_search_period() -> None:
    repository = FakeRepository([article(1), article(2)])
    searcher = FakeSearcher(
        [
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(SearchHit(article_id=1, score=4), SearchHit(article_id=2, score=3)),
            ),
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(SearchHit(article_id=2, score=5),),
            ),
        ]
    )
    outside_draft = SearchQueryDraft(
        method=SearchMethod.KEYWORD,
        reason="기간 이탈 테스트",
        keyword_terms=("탄핵",),
        date_from=date(2024, 1, 1),
        date_to=date(2024, 1, 31),
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent()],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft(), outside_draft],
            ArticleSelection: [
                ArticleSelection(
                    selected=(selected(2),),
                    rejected=({"article_id": 1, "reason": "다른 사건"},),
                ),
                ArticleSelection(selected=(selected(2),)),
            ],
            RelatedEvents: [RelatedEvents(), RelatedEvents()],
            SufficiencyReview: [
                SufficiencyReview(is_sufficient=False, gaps=("공백",)),
                SufficiencyReview(is_sufficient=False, gaps=("공백",)),
            ],
            AdditionalHypotheses: [AdditionalHypotheses()],
            MergedTimeline: [merged(2)],
        }
    )
    pipeline = TimelinePipeline(
        repository,
        searcher,
        generator,
        config(),
        sleeper=lambda _: None,
    )

    result = pipeline.generate("탈락 제외")

    assert result.termination is TerminationReason.CONVERGED
    assert "ARTICLE_ID: 1" not in generator.prompts[ArticleSelection][1]
    assert searcher.requests[1].options.date_from == date(2025, 1, 1)
    assert searcher.requests[1].options.date_to == date(2025, 1, 31)


def test_pipeline_logs_one_run_search_restore_and_selection_details(caplog) -> None:
    repository = FakeRepository([article(1), article(2)])
    searcher = FakeSearcher(
        [
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(
                    SearchHit(article_id=1, score=4),
                    SearchHit(article_id=2, score=3),
                    SearchHit(article_id=999, score=2),
                ),
            )
        ]
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent()],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft()],
            ArticleSelection: [
                ArticleSelection(
                    selected=(selected(1),),
                    rejected=({"article_id": 2, "reason": "다른 사건"},),
                )
            ],
            RelatedEvents: [RelatedEvents()],
            SufficiencyReview: [SufficiencyReview(is_sufficient=True)],
            MergedTimeline: [merged(1)],
        }
    )
    pipeline = TimelinePipeline(
        repository,
        searcher,
        generator,
        config(),
        sleeper=lambda _: None,
        run_id_factory=lambda: "run-rh01",
    )

    with caplog.at_level(logging.INFO, logger="news_tls_agent.pipeline"):
        pipeline.generate("관측 테스트")

    by_event = {
        record.event_name: record for record in caplog.records if hasattr(record, "event_name")
    }
    assert by_event["pipeline.started"].run_id == "run-rh01"
    assert by_event["pipeline.started"].model_name == "test-model"
    assert by_event["pipeline.intent"].needs_clarification is False
    assert by_event["pipeline.hypothetical"].date_from == "2025-01-01"
    assert by_event["pipeline.search.request"].keyword_terms == ("탄핵", "대통령")
    assert by_event["pipeline.search.request"].applied_date_to == "2025-01-31"
    assert by_event["pipeline.search.result"].qdrant_result_count == 3
    assert by_event["pipeline.search.result"].mssql_restored_count == 2
    assert by_event["pipeline.selection"].selected_article_ids == (1,)
    assert by_event["pipeline.selection"].rejected_articles == ((2, "다른 사건"),)
    assert {record.run_id for record in by_event.values()} == {"run-rh01"}
    assert "실제 본문" not in caplog.text
    assert "test-key" not in caplog.text


def test_pipeline_searches_full_archive_when_user_did_not_specify_a_date() -> None:
    repository = FakeRepository([article(1, published_on=date(2025, 3, 22))])
    searcher = FakeSearcher(
        [SearchResult(method=SearchMethod.KEYWORD, hits=(SearchHit(article_id=1, score=4),))]
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent(user_specified_date=False)],
            HypotheticalTimeline: [
                HypotheticalTimeline(
                    date_from=date(2024, 3, 1),
                    date_to=date(2024, 3, 31),
                    events=(
                        HypotheticalEvent(
                            expected_date=date(2024, 3, 15),
                            description="잘못 추정한 산불 시기",
                        ),
                    ),
                )
            ],
            SearchQueryDraft: [
                SearchQueryDraft(
                    method=SearchMethod.KEYWORD,
                    reason="산불 지역명",
                    keyword_terms=("영남권", "산불"),
                    date_from=date(2024, 3, 1),
                    date_to=date(2024, 3, 31),
                )
            ],
            ArticleSelection: [ArticleSelection(selected=(selected(),))],
            RelatedEvents: [RelatedEvents()],
            SufficiencyReview: [SufficiencyReview(is_sufficient=True)],
            MergedTimeline: [merged(1)],
        }
    )
    pipeline = TimelinePipeline(repository, searcher, generator, config(), sleeper=lambda _: None)

    result = pipeline.generate("영남권 산불")

    assert result.status is GenerationStatus.COMPLETED
    assert searcher.requests[0].options.date_from is None
    assert searcher.requests[0].options.date_to is None


def test_pipeline_keeps_first_search_period_when_user_specified_a_date() -> None:
    searcher = FakeSearcher(
        [
            SearchResult(method=SearchMethod.KEYWORD, hits=()),
            SearchResult(method=SearchMethod.HYBRID, hits=()),
        ]
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent(user_specified_date=True)],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft()],
        }
    )
    pipeline = TimelinePipeline(
        FakeRepository([]),
        searcher,
        generator,
        config(),
        sleeper=lambda _: None,
    )

    result = pipeline.generate("2025년 대통령 탄핵")

    assert result.status is GenerationStatus.NO_ARTICLES
    assert searcher.requests[0].options.date_from == date(2025, 1, 1)
    assert searcher.requests[0].options.date_to == date(2025, 1, 31)


def test_pipeline_asks_for_period_only_after_multiple_years_are_found() -> None:
    repository = FakeRepository(
        [
            article(1, published_on=date(2024, 3, 10)),
            article(2, published_on=date(2025, 3, 22)),
        ]
    )
    searcher = FakeSearcher(
        [
            SearchResult(
                method=SearchMethod.KEYWORD,
                hits=(SearchHit(article_id=1, score=4), SearchHit(article_id=2, score=3)),
            )
        ]
    )
    generator = ScriptedGenerator(
        {
            IntentInterpretation: [intent(user_specified_date=False)],
            HypotheticalTimeline: [hypothetical()],
            SearchQueryDraft: [draft()],
        }
    )
    pipeline = TimelinePipeline(repository, searcher, generator, config(), sleeper=lambda _: None)

    result = pipeline.generate("영남권 산불")

    assert result.status is GenerationStatus.NEEDS_CLARIFICATION
    assert result.clarification_question == "2024, 2025년 중 어느 시기의 사건을 말씀하시나요?"
    assert len(searcher.requests) == 1
    assert generator.prompts[ArticleSelection] == []
