"""이슈 브리핑 PDF·Notion 내보내기 API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.providers import get_tool_client
from core.errors import DataAccessError
from core.ports import ToolClient

router = APIRouter(prefix="/issues", tags=["export"])


class ExportRequest(BaseModel):
    format: Literal["pdf", "notion"]
    parent_page_id: str | None = None


@router.post("/{issue_id}/export", response_model=None)
async def export_issue(
    issue_id: int,
    request: ExportRequest,
    client: ToolClient[object] = Depends(get_tool_client),
) -> dict[str, object] | JSONResponse:
    try:
        payload = await client.call_tool(
            "export_briefing",
            {
                "issue_id": issue_id,
                "format": request.format,
                "parent_page_id": request.parent_page_id,
            },
        )
    except DataAccessError as exc:
        raise HTTPException(
            status_code=503, detail="내보내기 서비스에 연결할 수 없습니다."
        ) from exc
    if payload.get("ok") is True:
        return {key: value for key, value in payload.items() if key not in {"ok", "message"}}

    error = payload.get("error")
    code = error.get("code") if isinstance(error, Mapping) else None
    message = (
        error.get("message") if isinstance(error, Mapping) else "브리핑을 내보내지 못했습니다."
    )
    if code == "ISSUE_NOT_FOUND":
        raise HTTPException(status_code=404, detail=message)
    if code == "EXPORT_NOT_CONFIGURED":
        return JSONResponse(
            status_code=400,
            content={
                "reason": (
                    "notion_not_configured" if request.format == "notion" else "pdf_not_configured"
                ),
                "message": message,
            },
        )
    raise HTTPException(status_code=503, detail=message)
