from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.graph import KnowledgeGraphService
from core.errors import InsufficientEventsError, LLMOutputValidationError
from core.models import (
    Article,
    ArticleGraph,
    ArticleGraphExtraction,
    EventArticle,
    ExtractedEntity,
    ExtractedRelation,
    GraphEdge,
    GraphNode,
    IssueDetail,
    IssueEvent,
)


def article(article_id: int, *, extracted: bool) -> Article:
    return Article(
        article_id=article_id,
        title=f"기사 {article_id}",
        service_date=date(2026, 9, article_id),
        content=f"기관 {article_id}가 사건 {article_id}를 발표했다.",
        entities_extracted_at=datetime.now(UTC) if extracted else None,
    )


def event(order: int, item: Article) -> IssueEvent:
    link = EventArticle(article=item, relevance_score=0.9)
    return IssueEvent(
        event_id=order,
        event_order=order,
        event_date=item.service_date,
        title=f"사건 {order}",
        summary=None,
        articles=(link,),
        representative_article=item,
    )


class FakeRepository:
    def __init__(self, issue: IssueDetail) -> None:
        self.issue = issue
        self.saved: dict[int, ArticleGraph] = {}
        for item in issue.events:
            article_item = item.representative_article
            if article_item.entities_extracted_at is not None:
                self.saved[article_item.article_id] = ArticleGraph(
                    article_id=article_item.article_id,
                    article_title=article_item.title,
                    article_service_date=article_item.service_date,
                )

    def get_issue(self, issue_id: int):
        return self.issue if issue_id == self.issue.issue_id else None

    def replace_article_graph(self, article_id: int, extraction: ArticleGraphExtraction):
        ids = {entity.name: index for index, entity in enumerate(extraction.entities, start=1)}
        source = next(
            item.representative_article
            for item in self.issue.events
            if item.representative_article.article_id == article_id
        )
        self.saved[article_id] = ArticleGraph(
            article_id=article_id,
            article_title=source.title,
            article_service_date=source.service_date,
            nodes=tuple(
                GraphNode(id=ids[entity.name], name=entity.name, type=entity.entity_type)
                for entity in extraction.entities
            ),
            edges=tuple(
                GraphEdge(
                    id=index,
                    source=ids[relation.source],
                    target=ids[relation.target],
                    type=relation.relation_type,
                )
                for index, relation in enumerate(extraction.relations, start=1)
            ),
        )

    def get_article_graph(self, article_id: int):
        return self.saved.get(article_id)


class FakeGenerator:
    model_name = "test-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str, response_type):
        self.prompts.append(prompt)
        assert response_type is ArticleGraphExtraction
        return ArticleGraphExtraction(
            entities=(
                ExtractedEntity(name="기관", entity_type="기관"),
                ExtractedEntity(name="사건", entity_type="사건"),
            ),
            relations=(ExtractedRelation(source="기관", target="사건", relation_type="발표"),),
        )


def make_issue(*, one_event: bool = False) -> IssueDetail:
    cached = article(1, extracted=True)
    pending = article(2, extracted=False)
    events = (event(1, cached),) if one_event else (event(1, cached), event(2, pending))
    return IssueDetail(
        issue_id=7,
        topic="그래프 테스트",
        title="그래프 테스트",
        summary=None,
        generated_at=datetime.now(UTC),
        events=events,
    )


def test_graph_extracts_only_pending_representatives_and_reports_remaining() -> None:
    repository = FakeRepository(make_issue())
    generator = FakeGenerator()
    progress: list[int] = []
    service = KnowledgeGraphService(
        repository,
        generator,
        progress_sink=lambda item: progress.append(item.remaining),
    )

    graphs = service.build(7)

    assert [graph.article_id for graph in graphs] == [1, 2]
    assert len(generator.prompts) == 1
    assert "ARTICLE_ID: 2" in generator.prompts[0]
    assert progress == [1]
    assert graphs[1].edges[0].type == "발표"


def test_graph_requires_two_events() -> None:
    service = KnowledgeGraphService(FakeRepository(make_issue(one_event=True)), FakeGenerator())

    with pytest.raises(InsufficientEventsError):
        service.build(7)


def test_extraction_rejects_relations_without_article_entities() -> None:
    with pytest.raises(ValidationError, match="'기관'->'사건'"):
        ArticleGraphExtraction(
            entities=(ExtractedEntity(name="기관", entity_type="기관"),),
            relations=(ExtractedRelation(source="기관", target="사건", relation_type="발표"),),
        )


def invalid_output_error(
    raw_output: object,
    *,
    endpoints: tuple[tuple[str, str], ...] = (),
) -> LLMOutputValidationError:
    return LLMOutputValidationError(
        "구조화 출력 검증 실패",
        response_type="ArticleGraphExtraction",
        validation_error="관계의 주체와 대상은 entities에 있어야 합니다",
        raw_output=raw_output,
        invalid_endpoints=endpoints,
    )


class CorrectedGraphGenerator:
    model_name = "test-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str, response_type):
        self.prompts.append(prompt)
        assert response_type is ArticleGraphExtraction
        if len(self.prompts) == 1:
            raise invalid_output_error(
                {
                    "entities": [{"name": "기관", "entity_type": "기관"}],
                    "relations": [
                        {"source": "기관", "target": "없는 사건", "relation_type": "발표"}
                    ],
                },
                endpoints=(("기관", "없는 사건"),),
            )
        return ArticleGraphExtraction(
            entities=(ExtractedEntity(name="기관", entity_type="기관"),),
        )


def test_graph_requests_one_correction_with_invalid_endpoints() -> None:
    repository = FakeRepository(make_issue())
    generator = CorrectedGraphGenerator()
    service = KnowledgeGraphService(
        repository,
        generator,
        run_id_factory=lambda: "graph-rh01",
    )

    graphs = service.build(7)

    assert len(generator.prompts) == 2
    assert "잘못된 관계 끝점: '기관'->'없는 사건'" in generator.prompts[1]
    assert [node.name for node in graphs[1].nodes] == ["기관"]


class TwiceInvalidGraphGenerator:
    model_name = "test-model"

    def __init__(self, raw_output: object) -> None:
        self.raw_output = raw_output
        self.calls = 0

    def generate(self, prompt: str, response_type):
        self.calls += 1
        raise invalid_output_error(
            self.raw_output,
            endpoints=(("기관", "없는 사건"),),
        )


def test_graph_discards_only_invalid_relations_after_correction_fails(caplog) -> None:
    raw_output = {
        "entities": [
            {"name": "기관", "entity_type": "기관"},
            {"name": "사건", "entity_type": "사건"},
        ],
        "relations": [
            {"source": "기관", "target": "사건", "relation_type": "발표"},
            {"source": "기관", "target": "없는 사건", "relation_type": "참조"},
        ],
    }
    generator = TwiceInvalidGraphGenerator(raw_output)
    service = KnowledgeGraphService(
        FakeRepository(make_issue()),
        generator,
        run_id_factory=lambda: "graph-rh05",
    )

    with caplog.at_level("INFO", logger="news_tls_agent.graph"):
        graphs = service.build(7)

    assert generator.calls == 2
    assert [edge.type for edge in graphs[1].edges] == ["발표"]
    audit = next(
        record
        for record in caplog.records
        if getattr(record, "event_name", None) == "graph.extraction.invalid_relations_discarded"
    )
    assert audit.run_id == "graph-rh05"
    assert audit.article_id == 2
    assert audit.invalid_endpoints == (("기관", "없는 사건"),)
    assert "기관 2가 사건 2" not in caplog.text


def test_graph_logs_failed_article_when_output_cannot_be_recovered(caplog) -> None:
    service = KnowledgeGraphService(
        FakeRepository(make_issue()),
        TwiceInvalidGraphGenerator({"entities": [{"bad": "shape"}], "relations": []}),
        run_id_factory=lambda: "graph-rh05-failed",
    )

    with caplog.at_level("INFO", logger="news_tls_agent.graph"):
        with pytest.raises(LLMOutputValidationError):
            service.build(7)

    failure = next(
        record
        for record in caplog.records
        if getattr(record, "event_name", None) == "graph.extraction.failed"
    )
    assert failure.run_id == "graph-rh05-failed"
    assert failure.article_id == 2
    assert failure.response_type == "ArticleGraphExtraction"
    assert failure.error_type == "LLMOutputValidationError"
    assert "entities에 있어야" in failure.validation_error
    assert "기관 2가 사건 2" not in caplog.text
