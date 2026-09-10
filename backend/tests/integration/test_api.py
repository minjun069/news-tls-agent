from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import date

import httpx
import pytest

from api import providers
from api.main import create_app
from core.errors import (
    DataAccessError,
    LLMModelConfigurationError,
    LLMOutputValidationError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
)
from core.models import (
    ArticleGraph,
    ChatDone,
    ChatSource,
    ChatToken,
    ChatToolProgress,
    GenerationStatus,
    GraphProgress,
    PipelineProgress,
    PipelineStage,
    TerminationReason,
    TimelineGenerationResult,
)


class FakeHealthChecker:
    async def check(self):
        return {"mssql": "ok", "qdrant": "error", "mcp_server": "ok"}


class FakeMCPClient:
    async def call_tool(self, name: str, arguments: Mapping[str, object] | None = None):
        if name == "list_issues":
            return {
                "ok": True,
                "issues": [
                    {
                        "issue_id": 7,
                        "topic": "테스트",
                        "title": "테스트 이슈",
                        "generated_at": "2026-09-04T10:00:00",
                        "event_count": 1,
                    }
                ],
            }
        if name == "get_issue":
            if arguments == {"issue_id": 404}:
                return {"ok": False, "error": {"code": "ISSUE_NOT_FOUND", "message": "없음"}}
            return {
                "ok": True,
                "issue": {
                    "issue_id": 7,
                    "topic": "테스트",
                    "title": "테스트 이슈",
                    "summary": "요약",
                    "generated_at": "2026-09-04T10:00:00",
                    "events": [],
                },
            }
        if name == "read_article":
            if arguments == {"article_id": 404}:
                return {
                    "ok": False,
                    "error": {"code": "ARTICLE_NOT_FOUND", "message": "없음"},
                }
            return {
                "ok": True,
                "article": {
                    "article_id": 10,
                    "title": "기사",
                    "sub_title": "",
                    "service_date": "2026-09-04",
                    "summary": "요약",
                    "content": "본문",
                    "url": "https://example.com/10",
                    "truncated": False,
                },
            }
        if name == "export_briefing":
            assert arguments == {"issue_id": 7, "format": "pdf", "parent_page_id": None}
            return {
                "ok": True,
                "format": "pdf",
                "file_name": "briefing.pdf",
                "download_url": "/downloads/briefing.pdf",
                "message": "PDF를 생성했습니다.",
            }
        raise AssertionError(name)


class OfflineMCPClient:
    async def call_tool(self, name: str, arguments: Mapping[str, object] | None = None):
        raise DataAccessError(f"offline: {name}")


class FakePipeline:
    def __init__(self, progress_sink, status=GenerationStatus.COMPLETED, error=None):
        self._progress_sink = progress_sink
        self._status = status
        self._error = error

    async def generate(self, topic, *, clarification_answer=None, clarification_count=0):
        assert topic
        self._progress_sink(
            PipelineProgress(
                round_number=1,
                stage=PipelineStage.SELECT_ARTICLES,
                selected_article_count=2,
            )
        )
        if self._error is not None:
            raise self._error
        if self._status is GenerationStatus.NEEDS_CLARIFICATION:
            return TimelineGenerationResult(
                status=self._status,
                clarification_question="어느 사건인가요?",
            )
        return TimelineGenerationResult(
            status=self._status,
            issue_id=7,
            termination=TerminationReason.SUFFICIENCY_PASSED,
        )


class FakeAgent:
    async def stream(self, issue, message, history):
        assert issue["issue_id"] == 7
        assert message
        yield ChatToolProgress(name="search_articles", label="기사 검색")
        yield ChatToken(text="근거 답변", source=ChatSource.ARTICLE)
        yield ChatDone(article_ids=(10,), exports=())


class FakeGraphService:
    def __init__(self, progress_sink, error=None) -> None:
        self._progress_sink = progress_sink
        self._error = error

    async def build(self, issue_id: int):
        assert issue_id == 7
        self._progress_sink(GraphProgress(remaining=1))
        if self._error is not None:
            raise self._error
        return (
            ArticleGraph(
                article_id=10,
                article_title="기사",
                article_service_date=date(2026, 9, 4),
            ),
        )


def make_app(
    *,
    clarification: bool = False,
    offline: bool = False,
    pipeline_error=None,
    graph_error=None,
):
    app = create_app()
    client = OfflineMCPClient() if offline else FakeMCPClient()

    async def health_dependency():
        return FakeHealthChecker()

    async def tool_dependency():
        return client

    async def pipeline_dependency():
        return lambda sink: FakePipeline(sink, status, pipeline_error)

    async def agent_dependency():
        return FakeAgent()

    async def graph_dependency():
        return lambda sink: FakeGraphService(sink, graph_error)

    app.dependency_overrides[providers.get_health_checker] = health_dependency
    app.dependency_overrides[providers.get_tool_client] = tool_dependency
    status = GenerationStatus.NEEDS_CLARIFICATION if clarification else GenerationStatus.COMPLETED
    app.dependency_overrides[providers.get_pipeline_factory] = pipeline_dependency
    app.dependency_overrides[providers.get_chat_agent] = agent_dependency
    app.dependency_overrides[providers.get_graph_factory] = graph_dependency
    return app


async def request(app, method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_health_and_mcp_backed_read_endpoints() -> None:
    app = make_app()

    health = asyncio.run(request(app, "GET", "/health"))
    issues = asyncio.run(request(app, "GET", "/issues"))
    detail = asyncio.run(request(app, "GET", "/issues/7"))
    article = asyncio.run(request(app, "GET", "/articles/10"))
    missing = asyncio.run(request(app, "GET", "/articles/404"))

    assert health.json()["status"] == "degraded"
    assert issues.json()["issues"][0]["issue_id"] == 7
    assert detail.json()["title"] == "테스트 이슈"
    assert article.json()["summary"] == "요약"
    assert missing.status_code == 404


def test_generation_stream_reports_stage_and_done() -> None:
    response = asyncio.run(request(make_app(), "POST", "/issues", json={"topic": "테스트"}))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: stage" in response.text
    assert '"round":1' in response.text
    assert "event: done" in response.text
    assert '"termination":"sufficiency_passed"' in response.text


def test_generation_stream_ends_with_clarification() -> None:
    response = asyncio.run(
        request(
            make_app(clarification=True),
            "POST",
            "/issues",
            json={"topic": "탄핵", "clarification_count": 1},
        )
    )

    assert "event: clarify" in response.text
    assert '"attempt":2' in response.text
    assert "event: done" not in response.text


def output_validation_error() -> LLMOutputValidationError:
    return LLMOutputValidationError(
        "invalid output",
        response_type="Probe",
        validation_error="invalid",
        raw_output={},
    )


@pytest.mark.parametrize(
    ("error", "reason", "retryable"),
    [
        (LLMModelConfigurationError("missing model"), "model_unavailable", False),
        (LLMServiceUnavailableError("service unavailable"), "model_unavailable", True),
        (output_validation_error(), "output_validation_failed", True),
        (LLMRateLimitError("rate limit", retry_after_seconds=9), "rate_limited", True),
    ],
)
def test_generation_stream_distinguishes_model_failures(error, reason, retryable) -> None:
    response = asyncio.run(
        request(make_app(pipeline_error=error), "POST", "/issues", json={"topic": "테스트"})
    )

    assert f'"reason":"{reason}"' in response.text
    assert f'"retryable":{str(retryable).lower()}' in response.text
    if isinstance(error, LLMRateLimitError):
        assert '"retry_after_seconds":9' in response.text


def test_chat_stream_distinguishes_source_and_citations() -> None:
    response = asyncio.run(
        request(make_app(), "POST", "/issues/7/chat", json={"message": "무슨 일이야?"})
    )

    assert "event: tool" in response.text
    assert '"source":"article"' in response.text
    assert '"article_ids":[10]' in response.text


def test_chat_returns_data_unavailable_without_repository_fallback() -> None:
    response = asyncio.run(
        request(make_app(offline=True), "POST", "/issues/7/chat", json={"message": "질문"})
    )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert '"reason":"data_unavailable"' in response.text


def test_graph_stream_reports_extraction_and_article_attribution() -> None:
    response = asyncio.run(request(make_app(), "GET", "/issues/7/graph"))

    assert response.status_code == 200
    assert "event: stage" in response.text
    assert '"remaining":1' in response.text
    assert "event: done" in response.text
    assert '"article_id":10' in response.text
    assert '"article_service_date":"2026-09-04"' in response.text


@pytest.mark.parametrize(
    ("error", "reason", "retryable"),
    [
        (LLMModelConfigurationError("missing model"), "model_unavailable", False),
        (LLMServiceUnavailableError("service unavailable"), "model_unavailable", True),
        (output_validation_error(), "output_validation_failed", True),
        (LLMRateLimitError("rate limit"), "rate_limited", True),
    ],
)
def test_graph_stream_distinguishes_model_failures(error, reason, retryable) -> None:
    response = asyncio.run(request(make_app(graph_error=error), "GET", "/issues/7/graph"))

    assert f'"reason":"{reason}"' in response.text
    assert f'"retryable":{str(retryable).lower()}' in response.text


def test_export_endpoint_uses_shared_exporter() -> None:
    response = asyncio.run(request(make_app(), "POST", "/issues/7/export", json={"format": "pdf"}))

    assert response.status_code == 200
    assert response.json()["download_url"] == "/downloads/briefing.pdf"
