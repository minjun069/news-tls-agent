"""대표 기사별 지식 그래프 추출·조회 SSE API."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.providers import GraphFactory, get_graph_factory
from api.routes import encode_sse
from core.errors import (
    GraphExtractionError,
    InsufficientEventsError,
    IssueNotFoundError,
    LLMRateLimitError,
)
from core.models import ArticleGraph, GraphProgress

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/issues", tags=["graph"])


@router.get("/{issue_id}/graph")
async def get_issue_graph(
    issue_id: int,
    graph_factory: GraphFactory = Depends(get_graph_factory),
) -> StreamingResponse:
    return StreamingResponse(
        _graph_stream(issue_id, graph_factory),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _graph_stream(issue_id: int, graph_factory: GraphFactory) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    progress_queue: asyncio.Queue[GraphProgress] = asyncio.Queue()

    def receive_progress(progress: GraphProgress) -> None:
        loop.call_soon_threadsafe(progress_queue.put_nowait, progress)

    service = graph_factory(receive_progress)
    if inspect.iscoroutinefunction(service.build):
        task = asyncio.create_task(service.build(issue_id))
    else:
        task = asyncio.create_task(asyncio.to_thread(service.build, issue_id))
    while not task.done() or not progress_queue.empty():
        try:
            progress = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
        except TimeoutError:
            continue
        yield encode_sse("stage", {"stage": "extracting", "remaining": progress.remaining})

    try:
        graphs = await task
    except IssueNotFoundError:
        yield _graph_error("issue_not_found", "해당 이슈를 찾을 수 없습니다.", False)
        return
    except InsufficientEventsError:
        yield _graph_error(
            "insufficient_events",
            "그래프를 표시할 만큼 이벤트가 충분하지 않습니다.",
            False,
        )
        return
    except LLMRateLimitError:
        yield _graph_error("rate_limited", "요청이 많아 잠시 후 다시 시도해 주세요.", True)
        return
    except GraphExtractionError:
        logger.exception("지식 그래프 추출·저장 실패")
        yield _graph_error("extraction_failed", "관계 분석에 실패했습니다.", True)
        return
    except Exception:
        logger.exception("지식 그래프 처리 중 예기치 않은 실패")
        yield _graph_error("extraction_failed", "관계 분석에 실패했습니다.", True)
        return

    yield encode_sse("done", {"graphs": [_graph_payload(graph) for graph in graphs]})


def _graph_payload(graph: ArticleGraph) -> dict[str, object]:
    return {
        "article_id": graph.article_id,
        "article_title": graph.article_title,
        "article_service_date": graph.article_service_date.isoformat(),
        "nodes": [node.model_dump() for node in graph.nodes],
        "edges": [edge.model_dump() for edge in graph.edges],
    }


def _graph_error(reason: str, message: str, retryable: bool) -> str:
    return encode_sse(
        "error",
        {"reason": reason, "message": message, "retryable": retryable},
    )
