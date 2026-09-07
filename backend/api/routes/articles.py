"""기사 원문 조회 API."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, Depends, HTTPException

from api.providers import get_tool_client
from core.errors import DataAccessError
from core.ports import ToolClient

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("/{article_id}")
async def get_article(
    article_id: int,
    client: ToolClient[object] = Depends(get_tool_client),
) -> dict[str, object]:
    try:
        payload = await client.call_tool("read_article", {"article_id": article_id})
    except DataAccessError as exc:
        raise HTTPException(status_code=503, detail="자료를 불러오지 못했습니다.") from exc
    if payload.get("ok") is not True:
        error = payload.get("error")
        code = error.get("code") if isinstance(error, Mapping) else None
        message = error.get("message") if isinstance(error, Mapping) else "MCP 요청에 실패했습니다."
        status = 404 if code == "ARTICLE_NOT_FOUND" else 503
        raise HTTPException(status_code=status, detail=message)
    article = payload.get("article")
    if not isinstance(article, Mapping):
        raise HTTPException(status_code=502, detail="MCP 기사 응답 형식이 올바르지 않습니다.")
    return dict(article)
