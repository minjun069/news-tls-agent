"""외부 계정 없이 핵심 사용자 흐름을 HTTP 경계에서 끝까지 검증한다."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

import httpx

from api import providers
from api.main import create_app
from app.exporting import BriefingExportService
from app.graph import KnowledgeGraphService
from app.pipeline import TimelinePipeline
from core.config import TimelineConfig
from core.models import (
    Article,
    ArticleGraph,
    ArticleGraphExtraction,
    ArticleSelection,
    ChatDone,
    ChatSource,
    ChatToken,
    ChatToolProgress,
    EventArticle,
    ExtractedEntity,
    ExtractedRelation,
    GraphEdge,
    GraphNode,
    HypotheticalEvent,
    HypotheticalTimeline,
    IntentInterpretation,
    IssueCitation,
    IssueCreate,
    IssueDetail,
    IssueEvent,
    IssueSummary,
    MergedTimeline,
    MergedTimelineEvent,
    RelatedEvents,
    SearchHit,
    SearchMethod,
    SearchQueryDraft,
    SearchResult,
    SelectedArticle,
    SufficiencyReview,
)
from core.ranking import choose_representative
from mcp_server.tools.payloads import (
    export_briefing_payload,
    get_issue_payload,
    list_issues_payload,
    read_article_payload,
)


class MemoryRepository:
    def __init__(self, articles: Sequence[Article]) -> None:
        self.articles = {article.article_id: article for article in articles}
        self.issues: dict[int, IssueDetail] = {}
        self.graphs: dict[int, ArticleGraph] = {}

    def upsert_articles(self, articles: Sequence[Article]) -> int:
        self.articles.update({article.article_id: article for article in articles})
        return len(articles)

    def get_article(self, article_id: int) -> Article | None:
        return self.articles.get(article_id)

    def get_articles(self, article_ids: Sequence[int]) -> list[Article]:
        unique_ids = dict.fromkeys(article_ids)
        return [
            self.articles[article_id] for article_id in unique_ids if article_id in self.articles
        ]

    def save_issue(self, issue: IssueCreate) -> int:
        issue_id = len(self.issues) + 1
        events: list[IssueEvent] = []
        for event_input in issue.events:
            links = tuple(
                EventArticle(
                    article=self.articles[link.article_id],
                    relevance_score=link.relevance_score,
                )
                for link in event_input.articles
            )
            events.append(
                IssueEvent(
                    event_id=len(events) + 1,
                    event_order=event_input.event_order,
                    event_date=event_input.event_date,
                    title=event_input.title,
                    summary=event_input.summary,
                    articles=links,
                    representative_article=choose_representative(links, event_input.event_date),
                )
            )
        self.issues[issue_id] = IssueDetail(
            issue_id=issue_id,
            topic=issue.topic,
            title=issue.title,
            summary=issue.summary,
            generated_at=issue.generated_at,
            events=tuple(events),
        )
        return issue_id

    def get_issue(self, issue_id: int) -> IssueDetail | None:
        return self.issues.get(issue_id)

    def list_issues(self) -> list[IssueSummary]:
        return [
            IssueSummary(
                issue_id=issue.issue_id,
                topic=issue.topic,
                title=issue.title,
                generated_at=issue.generated_at,
                event_count=len(issue.events),
            )
            for issue in sorted(
                self.issues.values(),
                key=lambda item: (-item.generated_at.timestamp(), item.issue_id),
            )
        ]

    def find_issue_by_topic(self, topic: str) -> IssueDetail | None:
        return next((issue for issue in self.issues.values() if issue.topic == topic), None)

    def find_issues_by_article(self, article_id: int) -> list[IssueCitation]:
        return [
            IssueCitation(
                issue_id=issue.issue_id,
                topic=issue.topic,
                event_id=event.event_id,
                event_date=event.event_date,
                event_title=event.title,
            )
            for issue in self.issues.values()
            for event in issue.events
            if any(link.article.article_id == article_id for link in event.articles)
        ]

    def replace_article_graph(
        self,
        article_id: int,
        extraction: ArticleGraphExtraction,
    ) -> None:
        article = self.articles[article_id]
        node_ids = {entity.name: index for index, entity in enumerate(extraction.entities, start=1)}
        self.graphs[article_id] = ArticleGraph(
            article_id=article_id,
            article_title=article.title,
            article_service_date=article.service_date,
            nodes=tuple(
                GraphNode(id=node_ids[entity.name], name=entity.name, type=entity.entity_type)
                for entity in extraction.entities
            ),
            edges=tuple(
                GraphEdge(
                    id=index,
                    source=node_ids[relation.source],
                    target=node_ids[relation.target],
                    type=relation.relation_type,
                )
                for index, relation in enumerate(extraction.relations, start=1)
            ),
        )
        self.articles[article_id] = article.model_copy(
            update={"entities_extracted_at": datetime(2026, 9, 4, 12, 0)}
        )

    def get_article_graph(self, article_id: int) -> ArticleGraph | None:
        return self.graphs.get(article_id)


class DeterministicSearcher:
    def search_request(self, request) -> SearchResult:
        assert request.method is SearchMethod.KEYWORD
        return SearchResult(
            method=request.method,
            hits=(
                SearchHit(article_id=1001, score=0.95),
                SearchHit(article_id=1002, score=0.91),
            ),
        )


class DeterministicGenerator:
    def generate(self, prompt, response_type):
        if response_type is IntentInterpretation:
            return IntentInterpretation(intent="영남 산불 전개", needs_clarification=False)
        if response_type is HypotheticalTimeline:
            return HypotheticalTimeline(
                date_from=date(2025, 3, 20),
                date_to=date(2025, 4, 5),
                events=(HypotheticalEvent(expected_date=date(2025, 3, 22), description="발화"),),
            )
        if response_type is SearchQueryDraft:
            return SearchQueryDraft(
                method=SearchMethod.KEYWORD,
                reason="사건명 정확 검색",
                keyword_terms=("영남", "산불"),
                date_from=date(2025, 3, 20),
                date_to=date(2025, 4, 5),
            )
        if response_type is ArticleSelection:
            return ArticleSelection(
                selected=(
                    SelectedArticle(
                        article_id=1001,
                        event_date=date(2025, 3, 22),
                        event_summary="산불이 발생해 주민 대피가 시작됐다.",
                        relevance_score=0.95,
                    ),
                    SelectedArticle(
                        article_id=1002,
                        event_date=date(2025, 4, 2),
                        event_summary="진화 뒤 복구가 시작됐다.",
                        relevance_score=0.91,
                    ),
                )
            )
        if response_type is RelatedEvents:
            return RelatedEvents()
        if response_type is SufficiencyReview:
            return SufficiencyReview(is_sufficient=True)
        if response_type is MergedTimeline:
            return MergedTimeline(
                title="2025년 영남권 대형 산불",
                summary="발화와 대피부터 진화·복구까지의 전개",
                events=(
                    MergedTimelineEvent(
                        event_date=date(2025, 3, 22),
                        title="산불 발생과 대피",
                        summary="주민 대피가 시작됐다.",
                        article_ids=(1001,),
                    ),
                    MergedTimelineEvent(
                        event_date=date(2025, 4, 2),
                        title="진화와 복구",
                        summary="주불 진화 뒤 복구가 시작됐다.",
                        article_ids=(1002,),
                    ),
                ),
            )
        if response_type is ArticleGraphExtraction:
            label = "복구본부" if "1002" in prompt else "산림청"
            return ArticleGraphExtraction(
                entities=(
                    ExtractedEntity(name=label, entity_type="기관"),
                    ExtractedEntity(name="영남 산불", entity_type="사건"),
                ),
                relations=(
                    ExtractedRelation(
                        source=label,
                        target="영남 산불",
                        relation_type="대응",
                    ),
                ),
            )
        raise AssertionError(response_type)


class StubPdfRenderer:
    def render(self, markdown: str, output_path: str) -> None:
        assert "## 사건 타임라인" in markdown
        Path(output_path).write_bytes(b"%PDF-1.4\nnews-tls-agent e2e\n%%EOF")


class StatefulToolClient:
    def __init__(self, repository: MemoryRepository, exporter: BriefingExportService) -> None:
        self._repository = repository
        self._exporter = exporter

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        arguments = arguments or {}
        if name == "list_issues":
            return list_issues_payload(self._repository)
        if name == "get_issue":
            return get_issue_payload(self._repository, int(arguments["issue_id"]))
        if name == "read_article":
            return read_article_payload(self._repository, int(arguments["article_id"]))
        if name == "export_briefing":
            return export_briefing_payload(
                self._exporter,
                issue_id=int(arguments["issue_id"]),
                output_format=str(arguments["format"]),
                parent_page_id=(
                    str(arguments["parent_page_id"])
                    if arguments.get("parent_page_id") is not None
                    else None
                ),
            )
        raise AssertionError(name)


class EvidenceAgent:
    def __init__(self, tools: StatefulToolClient) -> None:
        self._tools = tools

    async def stream(self, issue, message, history):
        if "PDF" in message.upper():
            yield ChatToolProgress(name="export_briefing", label="브리핑 내보내기")
            exported = await self._tools.call_tool(
                "export_briefing",
                {"issue_id": issue["issue_id"], "format": "pdf", "parent_page_id": None},
            )
            yield ChatDone(exports=(dict(exported),))
            return

        article_id = issue["events"][0]["primary_article"]["article_id"]
        yield ChatToolProgress(name="read_article", label="기사 조회")
        article = await self._tools.call_tool("read_article", {"article_id": article_id})
        assert article["ok"] is True
        yield ChatToken(text="기사에서 주민 대피를 확인했습니다.", source=ChatSource.ARTICLE)
        yield ChatToken(
            text="산불 대응 단계는 일반적인 배경 설명입니다.", source=ChatSource.GENERAL
        )
        yield ChatDone(article_ids=(article_id,))


class HealthyDependencies:
    async def check(self):
        return {"mssql": "ok", "qdrant": "ok", "mcp_server": "ok"}


class AsyncServiceAdapter:
    """빠른 결정론적 서비스를 이벤트 루프에서 실행해 E2E 종료를 안정화한다."""

    def __init__(self, service) -> None:
        self._service = service

    async def generate(self, topic, **kwargs):
        return self._service.generate(topic, **kwargs)

    async def build(self, issue_id):
        return self._service.build(issue_id)


def _articles() -> tuple[Article, Article]:
    return (
        Article(
            article_id=1001,
            title="영남 산불 주민 대피",
            service_date=date(2025, 3, 22),
            summary="산불 확산으로 주민이 대피했다.",
            content="산림청은 영남 산불 확산에 따라 주민 대피를 지원했다.",
            url="https://example.com/articles/1001",
        ),
        Article(
            article_id=1002,
            title="영남 산불 진화 뒤 복구 착수",
            service_date=date(2025, 4, 2),
            summary="주불 진화 뒤 복구가 시작됐다.",
            content="복구본부는 영남 산불 피해 지역의 복구에 착수했다.",
            url="https://example.com/articles/1002",
        ),
    )


def _sse_events(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append((event, json.loads(data)))
    return events


async def _run_user_flow(download_dir: Path) -> None:
    repository = MemoryRepository(_articles())
    generator = DeterministicGenerator()
    exporter = BriefingExportService(repository, StubPdfRenderer(), download_dir)
    tools = StatefulToolClient(repository, exporter)
    app = create_app()

    async def health_dependency():
        return HealthyDependencies()

    async def tool_dependency():
        return tools

    async def pipeline_dependency():
        return lambda sink: AsyncServiceAdapter(
            TimelinePipeline(
                repository,
                DeterministicSearcher(),
                generator,
                TimelineConfig(
                    max_rounds=1,
                    max_chain_depth=2,
                    max_clarifications=2,
                    search_top_k=10,
                ),
                progress_sink=sink,
                clock=lambda: datetime(2026, 9, 4, 12, 0),
            )
        )

    async def agent_dependency():
        return EvidenceAgent(tools)

    async def graph_dependency():
        return lambda sink: AsyncServiceAdapter(
            KnowledgeGraphService(
                repository,
                generator,
                progress_sink=sink,
            )
        )

    app.dependency_overrides[providers.get_health_checker] = health_dependency
    app.dependency_overrides[providers.get_tool_client] = tool_dependency
    app.dependency_overrides[providers.get_pipeline_factory] = pipeline_dependency
    app.dependency_overrides[providers.get_chat_agent] = agent_dependency
    app.dependency_overrides[providers.get_graph_factory] = graph_dependency

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        assert health.json()["status"] == "ok"

        generation = await client.post("/issues", json={"topic": "2025년 영남권 대형 산불"})
        generation_events = _sse_events(generation.text)
        assert generation_events[-1] == (
            "done",
            {"issue_id": 1, "termination": "sufficiency_passed"},
        )
        assert {payload["stage"] for event, payload in generation_events if event == "stage"} >= {
            "intent",
            "search",
            "select",
            "save",
        }

        issues = await client.get("/issues")
        detail = await client.get("/issues/1")
        assert issues.json()["issues"][0]["event_count"] == 2
        assert [event["event_date"] for event in detail.json()["events"]] == [
            "2025-03-22",
            "2025-04-02",
        ]
        assert detail.json()["events"][0]["primary_article"]["article_id"] == 1001

        article = await client.get("/articles/1001")
        assert article.json()["content"].startswith("산림청은")
        assert article.json()["url"] == "https://example.com/articles/1001"

        chat = await client.post("/issues/1/chat", json={"message": "대피 근거와 배경을 설명해줘"})
        chat_events = _sse_events(chat.text)
        assert [payload["source"] for event, payload in chat_events if event == "token"] == [
            "article",
            "general",
        ]
        assert chat_events[-1][1]["article_ids"] == [1001]

        graph = await client.get("/issues/1/graph")
        graph_events = _sse_events(graph.text)
        graphs = graph_events[-1][1]["graphs"]
        assert {item["article_id"] for item in graphs} == {1001, 1002}
        assert all(item["nodes"] and item["edges"] for item in graphs)

        menu_export = await client.post("/issues/1/export", json={"format": "pdf"})
        assert menu_export.status_code == 200
        download_url = menu_export.json()["download_url"]
        downloaded = download_dir / menu_export.json()["file_name"]
        assert downloaded.read_bytes().startswith(b"%PDF-1.4")

        chat_export = await client.post("/issues/1/chat", json={"message": "PDF로 저장해줘"})
        export_events = _sse_events(chat_export.text)
        assert export_events[0][1]["name"] == "export_briefing"
        assert export_events[-1][1]["exports"][0]["download_url"] == download_url


def test_generation_to_export_and_graph_user_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EXPORT_DOWNLOAD_DIR", str(tmp_path))
    asyncio.run(_run_user_flow(tmp_path))
