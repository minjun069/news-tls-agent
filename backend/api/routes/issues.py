"""이슈 목록·상세·타임라인 생성 API."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Mapping

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.providers import PipelineFactory, get_pipeline_factory, get_tool_client
from api.routes import encode_sse
from core.errors import DataAccessError, LLMRateLimitError, TimelineGenerationError
from core.models import GenerationStatus, PipelineProgress, PipelineStage
from core.ports import ToolClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/issues", tags=["issues"])


class IssueCreateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    clarification: str | None = None
    clarification_count: int = Field(default=0, ge=0)


@router.get("")
async def list_issues(
    client: ToolClient[object] = Depends(get_tool_client),
) -> dict[str, object]:
    try:
        payload = await client.call_tool("list_issues")
    except DataAccessError as exc:
        raise HTTPException(status_code=503, detail="자료를 불러오지 못했습니다.") from exc
    _raise_mcp_http_error(payload)
    return {"issues": payload.get("issues", [])}


@router.get("/{issue_id}")
async def get_issue(
    issue_id: int,
    client: ToolClient[object] = Depends(get_tool_client),
) -> dict[str, object]:
    try:
        payload = await client.call_tool("get_issue", {"issue_id": issue_id})
    except DataAccessError as exc:
        raise HTTPException(status_code=503, detail="자료를 불러오지 못했습니다.") from exc
    _raise_mcp_http_error(payload)
    issue = payload.get("issue")
    if not isinstance(issue, Mapping):
        raise HTTPException(status_code=502, detail="MCP 이슈 응답 형식이 올바르지 않습니다.")
    return dict(issue)


@router.post("")
async def create_issue(
    request: IssueCreateRequest,
    pipeline_factory: PipelineFactory = Depends(get_pipeline_factory),
) -> StreamingResponse:
    return StreamingResponse(
        _generation_stream(request, pipeline_factory),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _generation_stream(
    request: IssueCreateRequest,
    pipeline_factory: PipelineFactory,
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    progress_queue: asyncio.Queue[PipelineProgress] = asyncio.Queue()

    def receive_progress(progress: PipelineProgress) -> None:
        loop.call_soon_threadsafe(progress_queue.put_nowait, progress)

    pipeline = pipeline_factory(receive_progress)
    generation_arguments = {
        "clarification_answer": request.clarification,
        "clarification_count": request.clarification_count,
    }
    if inspect.iscoroutinefunction(pipeline.generate):
        task = asyncio.create_task(pipeline.generate(request.topic, **generation_arguments))
    else:
        task = asyncio.create_task(
            asyncio.to_thread(pipeline.generate, request.topic, **generation_arguments)
        )

    while not task.done() or not progress_queue.empty():
        try:
            progress = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
        except TimeoutError:
            continue
        yield encode_sse("stage", _stage_payload(progress))

    try:
        result = await task
    except LLMRateLimitError:
        yield encode_sse(
            "error",
            {
                "reason": "rate_limited",
                "message": "외부 API 호출 한도를 초과했습니다.",
                "retryable": True,
            },
        )
        return
    except TimelineGenerationError:
        logger.exception("타임라인 생성 실패")
        yield encode_sse(
            "error",
            {
                "reason": "generation_failed",
                "message": "타임라인 생성에 실패했습니다.",
                "retryable": True,
            },
        )
        return
    except Exception:
        logger.exception("타임라인 생성 중 예기치 않은 실패")
        yield encode_sse(
            "error",
            {
                "reason": "generation_failed",
                "message": "타임라인 생성에 실패했습니다.",
                "retryable": True,
            },
        )
        return

    if result.status is GenerationStatus.NEEDS_CLARIFICATION:
        yield encode_sse(
            "clarify",
            {
                "question": result.clarification_question or "조금 더 구체적으로 알려주세요.",
                "attempt": request.clarification_count + 1,
            },
        )
        return
    if result.status is GenerationStatus.NO_ARTICLES:
        yield encode_sse(
            "error",
            {
                "reason": "no_articles",
                "message": "관련 기사를 찾지 못했습니다.",
                "retryable": False,
            },
        )
        return
    yield encode_sse(
        "done",
        {
            "issue_id": result.issue_id,
            "termination": result.termination.value if result.termination else None,
        },
    )


def _stage_payload(progress: PipelineProgress) -> dict[str, object]:
    messages = {
        PipelineStage.INTERPRET_INTENT: "질의 의도를 해석하는 중",
        PipelineStage.CLARIFY: "되묻기가 필요한지 확인하는 중",
        PipelineStage.BUILD_HYPOTHETICAL_TIMELINE: "가상 타임라인 구성 중",
        PipelineStage.GENERATE_SEARCH_QUERY: "기사 검색 중",
        PipelineStage.SELECT_ARTICLES: "핵심 기사 선정 중",
        PipelineStage.EXTRACT_RELATED_EVENTS: "선후 사건 확장 중",
        PipelineStage.REVIEW_SUFFICIENCY: "타임라인 충분성 검토 중",
        PipelineStage.GENERATE_HYPOTHESES: "추가 검색 사건 구성 중",
        PipelineStage.MERGE_TIMELINE: "타임라인 구성 중",
        PipelineStage.SAVE_ISSUE: "타임라인 저장 중",
        PipelineStage.CACHED: "저장된 이슈를 재사용합니다",
    }
    payload: dict[str, object] = {
        "stage": progress.stage.value,
        "message": messages[progress.stage],
    }
    if progress.round_number > 0:
        payload["round"] = progress.round_number
    if progress.stage is PipelineStage.SELECT_ARTICLES:
        payload["selected"] = progress.selected_article_count
    return payload


def _raise_mcp_http_error(payload: Mapping[str, object]) -> None:
    if payload.get("ok") is True:
        return
    error = payload.get("error")
    code = error.get("code") if isinstance(error, Mapping) else None
    message = error.get("message") if isinstance(error, Mapping) else "MCP 요청에 실패했습니다."
    if code == "ISSUE_NOT_FOUND":
        raise HTTPException(status_code=404, detail=message)
    raise HTTPException(status_code=503, detail=message)
