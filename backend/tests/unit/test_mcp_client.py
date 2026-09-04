from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from infra.mcp_client import MCPToolClient


class FakeSession:
    async def list_tools(self, *, params=None):
        assert params is None
        return ListToolsResult(
            tools=[
                Tool(
                    name="echo",
                    description="입력 문자열을 구조화 결과로 돌려줍니다.",
                    inputSchema={
                        "type": "object",
                        "properties": {"value": {"type": "string", "title": "Value"}},
                        "required": ["value"],
                    },
                )
            ]
        )

    async def call_tool(self, name, arguments):
        assert name == "echo"
        assert arguments == {"value": "안녕"}
        return CallToolResult(
            content=[TextContent(type="text", text='{"ok":true,"value":"안녕"}')],
            structuredContent={"ok": True, "value": "안녕"},
        )


class StubMCPToolClient(MCPToolClient):
    @asynccontextmanager
    async def _session(self):
        yield FakeSession()


def test_mcp_v2_client_loads_schema_and_calls_structured_tool() -> None:
    client = StubMCPToolClient()

    async def exercise():
        tools = await client.get_tools()
        payload = await client.call_tool("echo", {"value": "안녕"})
        tool_message = await tools[0].ainvoke(
            {"name": "echo", "args": {"value": "안녕"}, "id": "call-1", "type": "tool_call"}
        )
        return tools, payload, tool_message

    tools, payload, tool_message = asyncio.run(exercise())

    assert [tool.name for tool in tools] == ["echo"]
    assert tools[0].args == {"value": {"title": "Value", "type": "string"}}
    assert payload == {"ok": True, "value": "안녕"}
    assert tool_message.artifact == {"structured_content": payload}
