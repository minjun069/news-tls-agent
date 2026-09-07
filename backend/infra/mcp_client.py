"""MCP SDK v2 stdio 클라이언트와 LangChain 도구 변환 어댑터."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, PaginatedRequestParams, TextContent, Tool

from core.errors import DataAccessError

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SERVER_NAME = "news-tls-agent"


class MCPToolClient:
    """stdio MCP 서버의 구조화 출력을 HTTP와 LangGraph 양쪽에 제공한다."""

    def __init__(
        self,
        *,
        command: str | None = None,
        args: Sequence[str] | None = None,
        cwd: Path = _BACKEND_ROOT,
        env: Mapping[str, str] | None = None,
        read_timeout_seconds: float = 30,
    ) -> None:
        self._server = StdioServerParameters(
            command=command or sys.executable,
            args=list(args or ("-m", "mcp_server.server")),
            cwd=cwd,
            env=dict(env or os.environ),
        )
        self._read_timeout_seconds = read_timeout_seconds

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        try:
            async with stdio_client(self._server) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=self._read_timeout_seconds,
                ) as session:
                    await session.initialize()
                    yield session
        except DataAccessError:
            raise
        except Exception as exc:
            raise DataAccessError("MCP 서버에 연결할 수 없습니다") from exc

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        """도구를 호출하고 MCP structuredContent를 dict로 보존한다."""
        async with self._session() as session:
            try:
                result = await session.call_tool(name, dict(arguments or {}))
            except Exception as exc:
                raise DataAccessError(f"MCP 도구 호출에 실패했습니다: {name}") from exc
        if not isinstance(result, CallToolResult):
            raise DataAccessError(f"MCP 도구가 완료 결과를 반환하지 않았습니다: {name}")
        if result.is_error:
            raise DataAccessError(_text_content(result) or f"MCP 도구 실행에 실패했습니다: {name}")
        if isinstance(result.structured_content, Mapping):
            return dict(result.structured_content)
        text = _text_content(result)
        try:
            decoded = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise DataAccessError(f"MCP 도구가 구조화 출력을 반환하지 않았습니다: {name}") from exc
        if not isinstance(decoded, dict):
            raise DataAccessError(f"MCP 도구 결과가 객체가 아닙니다: {name}")
        return decoded

    async def get_tools(self) -> list[BaseTool]:
        """MCP 입력 스키마를 그대로 쓰는 LangChain StructuredTool을 만든다."""
        definitions: list[Tool] = []
        cursor: str | None = None
        async with self._session() as session:
            while True:
                params = PaginatedRequestParams(cursor=cursor) if cursor else None
                result = await session.list_tools(params=params)
                definitions.extend(result.tools)
                cursor = result.next_cursor
                if not cursor:
                    break
        return [self._to_langchain_tool(definition) for definition in definitions]

    def _to_langchain_tool(self, definition: Tool) -> BaseTool:
        async def invoke_mcp_tool(**kwargs: Any) -> tuple[str, dict[str, object]]:
            payload = dict(await self.call_tool(definition.name, kwargs))
            return (
                json.dumps(payload, ensure_ascii=False, default=str),
                {"structured_content": payload},
            )

        return StructuredTool.from_function(
            coroutine=invoke_mcp_tool,
            name=definition.name,
            description=definition.description or definition.title or definition.name,
            args_schema=definition.input_schema,
            infer_schema=False,
            response_format="content_and_artifact",
            metadata={"mcp_server": _SERVER_NAME},
        )


def _text_content(result: CallToolResult) -> str:
    return "\n".join(item.text for item in result.content if isinstance(item, TextContent))
