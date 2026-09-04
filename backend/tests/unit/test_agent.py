from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.agent import IssueChatAgent, SourceTagParser
from core.errors import DataAccessError
from core.models import ChatDone, ChatSource, ChatToken, ChatToolProgress


def test_source_tag_parser_handles_split_markers_and_paragraph_changes() -> None:
    parser = SourceTagParser()
    chunks = ["ART", "ICLE:기사 근거", "입니다.\n\nGEN", "ERAL:배경 설명"]

    parsed = [item for chunk in chunks for item in parser.feed(chunk)] + parser.flush()

    article = "".join(text for source, text in parsed if source is ChatSource.ARTICLE)
    general = "".join(text for source, text in parsed if source is ChatSource.GENERAL)
    assert article == "기사 근거입니다."
    assert general == "배경 설명"


class FakeToolClient:
    async def get_tools(self):
        return []


class FakeGraph:
    async def astream(self, _input, *, stream_mode, version):
        assert stream_mode == ("messages", "values")
        assert version == "v2"
        yield {
            "type": "messages",
            "data": (
                AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {"name": "search_articles", "args": "", "id": "call-1", "index": 0}
                    ],
                ),
                {},
            ),
        }
        yield {
            "type": "messages",
            "data": (AIMessageChunk(content="ARTICLE:표결은 새벽 1시였습니다."), {}),
        }
        tool_message = ToolMessage(
            content='{"ok":true}',
            tool_call_id="call-1",
            name="search_articles",
            artifact={
                "structured_content": {
                    "ok": True,
                    "articles": [{"article_id": 10}, {"article_id": 20}],
                }
            },
        )
        yield {
            "type": "values",
            "data": {
                "messages": [
                    tool_message,
                    AIMessage(content="ARTICLE:표결은 새벽 1시였습니다."),
                ]
            },
        }


def test_issue_agent_streams_tool_source_tokens_and_citations() -> None:
    def graph_factory(_model, _tools, system_prompt):
        assert "현재 이슈 문맥" in system_prompt
        return FakeGraph()

    agent = IssueChatAgent(object(), FakeToolClient(), graph_factory=graph_factory)

    async def collect():
        return [event async for event in agent.stream({"issue_id": 7}, "표결 시각은?")]

    events = asyncio.run(collect())

    assert isinstance(events[0], ChatToolProgress)
    tokens = [event for event in events if isinstance(event, ChatToken)]
    assert "".join(event.text for event in tokens) == "표결은 새벽 1시였습니다."
    assert all(event.source is ChatSource.ARTICLE for event in tokens)
    assert isinstance(events[-1], ChatDone)
    assert events[-1].article_ids == (10, 20)


def test_issue_agent_does_not_bypass_unavailable_mcp() -> None:
    class OfflineClient:
        async def get_tools(self):
            raise ConnectionError("offline")

    agent = IssueChatAgent(object(), OfflineClient())

    async def collect():
        return [event async for event in agent.stream({"issue_id": 7}, "질문")]

    try:
        asyncio.run(collect())
    except DataAccessError as exc:
        assert "MCP 도구 목록" in str(exc)
    else:
        raise AssertionError("MCP 장애가 DataAccessError로 전달되어야 합니다")
