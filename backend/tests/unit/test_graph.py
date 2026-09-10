from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.graph import KnowledgeGraphService
from core.errors import InsufficientEventsError
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
    with pytest.raises(ValidationError, match="entities에 있어야"):
        ArticleGraphExtraction(
            entities=(ExtractedEntity(name="기관", entity_type="기관"),),
            relations=(ExtractedRelation(source="기관", target="사건", relation_type="발표"),),
        )


class InvalidGraphGenerator:
    model_name = "test-model"

    def generate(self, prompt: str, response_type):
        assert response_type is ArticleGraphExtraction
        return ArticleGraphExtraction(
            entities=(ExtractedEntity(name="기관", entity_type="기관"),),
            relations=(ExtractedRelation(source="기관", target="없는 사건", relation_type="발표"),),
        )


def test_graph_logs_failed_article_and_validation_error(caplog) -> None:
    service = KnowledgeGraphService(
        FakeRepository(make_issue()),
        InvalidGraphGenerator(),
        run_id_factory=lambda: "graph-rh01",
    )

    with caplog.at_level("INFO", logger="news_tls_agent.graph"):
        with pytest.raises(ValidationError, match="entities에 있어야"):
            service.build(7)

    failure = next(
        record
        for record in caplog.records
        if getattr(record, "event_name", None) == "graph.extraction.failed"
    )
    assert failure.run_id == "graph-rh01"
    assert failure.article_id == 2
    assert failure.response_type == "ArticleGraphExtraction"
    assert failure.error_type == "ValidationError"
    assert "entities에 있어야" in failure.validation_error
    assert "기관 2가 사건 2" not in caplog.text
