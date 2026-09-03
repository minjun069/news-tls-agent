from __future__ import annotations

import asyncio
import logging

from mcp_server.server import create_server
from mcp_server.tools.dependencies import ToolDependencies
from mcp_server.tools.registry import _invoke_audited
from tests.unit.test_mcp_payloads import FakeRepository, FakeSearcher


def test_server_advertises_exactly_five_structured_tools_with_descriptions() -> None:
    server = create_server(ToolDependencies(FakeRepository(), FakeSearcher()))

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == [
        "search_articles",
        "read_article",
        "list_issues",
        "get_issue",
        "export_briefing",
    ]
    assert all(tool.description for tool in tools)
    assert all(tool.output_schema is not None for tool in tools)
    search_tool = tools[0]
    assert search_tool.input_schema["properties"]["method"]["enum"] == [
        "keyword",
        "semantic",
        "hybrid",
    ]
    assert search_tool.input_schema["properties"]["top_k"]["minimum"] == 1
    assert search_tool.input_schema["properties"]["top_k"]["maximum"] == 100
    assert "정확히 일치" in search_tool.description


def test_tool_invocation_writes_audit_log(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="news_tls_agent.mcp.audit"):
        result = _invoke_audited(
            "list_issues",
            {},
            lambda: {"ok": True, "issues": [{"issue_id": 7}]},
            lambda payload: len(payload["issues"]),
        )

    assert result["issues"][0]["issue_id"] == 7
    assert "tool=list_issues" in caplog.text
    assert "result_count=1" in caplog.text
