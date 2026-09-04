"""MCP 도구 기반 이슈 대화 SSE API."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.providers import get_chat_agent, get_tool_client
from api.routes import encode_sse
from app.agent import IssueChatAgent
from core.errors import DataAccessError
from core.models import ChatDone, ChatMessage, ChatToken, ChatToolProgress
from core.ports import ToolClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/issues", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: tuple[ChatMessage, ...] = ()


@router.post("/{issue_id}/chat")
async def chat(
    issue_id: int,
    request: ChatRequest,
    client: ToolClient[object] = Depends(get_tool_client),
    agent: IssueChatAgent = Depends(get_chat_agent),
) -> StreamingResponse:
    try:
        payload = await client.call_tool("get_issue", {"issue_id": issue_id})
    except DataAccessError:
        return _stream_response(_chat_error("data_unavailable", "자료를 불러오지 못했습니다."))
    if payload.get("ok") is not True:
        error = payload.get("error")
        code = error.get("code") if isinstance(error, Mapping) else None
        if code == "ISSUE_NOT_FOUND":
            raise HTTPException(status_code=404, detail="해당 이슈를 찾을 수 없습니다.")
        return _stream_response(_chat_error("data_unavailable", "자료를 불러오지 못했습니다."))
    issue = payload.get("issue")
    if not isinstance(issue, Mapping):
        return _stream_response(_chat_error("data_unavailable", "자료를 불러오지 못했습니다."))
    return _stream_response(_chat_stream(agent, issue, request))


def _stream_response(stream: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _chat_stream(
    agent: IssueChatAgent,
    issue: Mapping[str, object],
    request: ChatRequest,
) -> AsyncIterator[str]:
    try:
        async for event in agent.stream(issue, request.message, request.history):
            if isinstance(event, ChatToolProgress):
                yield encode_sse("tool", {"name": event.name, "label": event.label})
            elif isinstance(event, ChatToken):
                yield encode_sse("token", {"text": event.text, "source": event.source.value})
            elif isinstance(event, ChatDone):
                yield encode_sse(
                    "done",
                    {"article_ids": list(event.article_ids), "exports": list(event.exports)},
                )
    except DataAccessError:
        yield encode_sse(
            "error",
            {
                "reason": "data_unavailable",
                "message": "자료를 불러오지 못했습니다.",
                "retryable": True,
            },
        )
    except Exception:
        logger.exception("대화 에이전트 실행 실패")
        yield encode_sse(
            "error",
            {
                "reason": "generation_failed",
                "message": "답변 생성에 실패했습니다.",
                "retryable": True,
            },
        )


async def _chat_error(reason: str, message: str) -> AsyncIterator[str]:
    yield encode_sse("error", {"reason": reason, "message": message, "retryable": True})
