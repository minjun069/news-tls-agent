"""MCP 도구만 사용하는 LangGraph 기반 이슈 질의 에이전트."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import ClassVar, Protocol

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.tools import BaseTool

from core.errors import DataAccessError
from core.models import (
    ChatDone,
    ChatEvent,
    ChatMessage,
    ChatSource,
    ChatToken,
    ChatToolProgress,
)
from core.ports import ToolClient

logger = logging.getLogger("news_tls_agent.agent")

_TOOL_LABELS = {
    "search_articles": "기사 검색",
    "read_article": "기사 읽기",
    "list_issues": "이슈 목록",
    "get_issue": "이슈 조회",
    "export_briefing": "브리핑 내보내기",
}


class AgentGraph(Protocol):
    def astream(
        self,
        input: Mapping[str, object],
        *,
        stream_mode: Sequence[str],
        version: str,
    ) -> AsyncIterator[Mapping[str, object]]:
        """LangGraph 실행 이벤트를 비동기로 반환한다."""
        ...


GraphFactory = Callable[[BaseChatModel, Sequence[BaseTool], str], AgentGraph]


def _default_graph_factory(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
) -> AgentGraph:
    return create_agent(model=model, tools=tools, system_prompt=system_prompt)


class IssueChatAgent:
    """현재 이슈 문맥과 클라이언트 이력으로 세션 없는 도구 호출 대화를 실행한다."""

    def __init__(
        self,
        model: BaseChatModel,
        tool_client: ToolClient[BaseTool],
        *,
        graph_factory: GraphFactory = _default_graph_factory,
    ) -> None:
        self._model = model
        self._tool_client = tool_client
        self._graph_factory = graph_factory

    async def stream(
        self,
        issue: Mapping[str, object],
        message: str,
        history: Sequence[ChatMessage] = (),
    ) -> AsyncIterator[ChatEvent]:
        """도구 진행, 출처별 텍스트, 최종 인용을 순서대로 전달한다."""
        normalized_message = message.strip()
        if not normalized_message:
            raise ValueError("message는 빈 문자열일 수 없습니다")

        try:
            tools = await self._tool_client.get_tools()
        except DataAccessError:
            raise
        except Exception as exc:
            raise DataAccessError("MCP 도구 목록을 불러오지 못했습니다") from exc

        graph = self._graph_factory(self._model, tools, _system_prompt(issue))
        messages: list[dict[str, str]] = [item.model_dump() for item in history]
        messages.append({"role": "user", "content": normalized_message})
        source_parser = SourceTagParser()
        emitted_tools: set[str] = set()
        streamed_text = False
        final_state: Mapping[str, object] = {}

        async for part in graph.astream(
            {"messages": messages},
            stream_mode=("messages", "values"),
            version="v2",
        ):
            part_type = part.get("type")
            data = part.get("data")
            if part_type == "messages" and isinstance(data, tuple) and data:
                chunk = data[0]
                for tool_name in _tool_names(chunk):
                    if tool_name in emitted_tools:
                        continue
                    emitted_tools.add(tool_name)
                    logger.info("agent tool call: name=%s", tool_name)
                    yield ChatToolProgress(
                        name=tool_name,
                        label=_TOOL_LABELS.get(tool_name, tool_name),
                    )
                if isinstance(chunk, AIMessageChunk):
                    text = chunk.text
                    if text:
                        streamed_text = True
                        for source, token in source_parser.feed(text):
                            yield ChatToken(text=token, source=source)
            elif part_type == "values" and isinstance(data, Mapping):
                final_state = data

        for source, token in source_parser.flush():
            yield ChatToken(text=token, source=source)

        final_messages = final_state.get("messages", ())
        if isinstance(final_messages, Sequence) and not streamed_text:
            fallback_text = _last_answer_text(final_messages)
            fallback_parser = SourceTagParser()
            for source, token in fallback_parser.feed(fallback_text):
                yield ChatToken(text=token, source=source)
            for source, token in fallback_parser.flush():
                yield ChatToken(text=token, source=source)

        article_ids, exports = _collect_tool_results(final_messages)
        logger.info(
            "agent completed: tool_calls=%s article_ids=%s exports=%s",
            len(emitted_tools),
            len(article_ids),
            len(exports),
        )
        yield ChatDone(article_ids=tuple(article_ids), exports=tuple(exports))


class SourceTagParser:
    """분할된 ARTICLE:/GENERAL: 표식을 제거하고 문단 출처를 보존한다."""

    _MARKERS: ClassVar[dict[str, ChatSource]] = {
        "ARTICLE:": ChatSource.ARTICLE,
        "GENERAL:": ChatSource.GENERAL,
    }

    def __init__(self) -> None:
        self._buffer = ""
        self._source: ChatSource | None = None

    def feed(self, text: str) -> list[tuple[ChatSource, str]]:
        self._buffer += text
        emitted: list[tuple[ChatSource, str]] = []
        while self._buffer:
            if self._source is None:
                stripped = self._buffer.lstrip()
                leading = len(self._buffer) - len(stripped)
                marker = next((item for item in self._MARKERS if stripped.startswith(item)), None)
                if marker is not None:
                    self._source = self._MARKERS[marker]
                    self._buffer = stripped[len(marker) :].lstrip(" ")
                    continue
                if any(marker.startswith(stripped) for marker in self._MARKERS):
                    break
                self._source = ChatSource.GENERAL
                if leading:
                    self._buffer = stripped

            boundary = _find_source_boundary(self._buffer)
            if boundary is not None:
                index, marker = boundary
                token = self._buffer[:index]
                if token:
                    emitted.append((self._source, token))
                self._source = self._MARKERS[marker]
                self._buffer = self._buffer[index + 2 + len(marker) :].lstrip(" ")
                continue

            held = _partial_boundary_suffix(self._buffer, tuple(self._MARKERS))
            split_at = len(self._buffer) - held
            if split_at:
                emitted.append((self._source, self._buffer[:split_at]))
                self._buffer = self._buffer[split_at:]
            break
        return emitted

    def flush(self) -> list[tuple[ChatSource, str]]:
        if not self._buffer:
            return []
        source = self._source or ChatSource.GENERAL
        token = self._buffer
        self._buffer = ""
        self._source = None
        return [(source, token)]


def _find_source_boundary(buffer: str) -> tuple[int, str] | None:
    found = [
        (buffer.find(f"\n\n{marker}"), marker)
        for marker in SourceTagParser._MARKERS
        if buffer.find(f"\n\n{marker}") >= 0
    ]
    return min(found, default=None, key=lambda item: item[0])


def _partial_boundary_suffix(buffer: str, markers: tuple[str, ...]) -> int:
    candidates = tuple(f"\n\n{marker}" for marker in markers)
    return max(
        (
            length
            for length in range(1, min(len(buffer), max(map(len, candidates))) + 1)
            if any(candidate.startswith(buffer[-length:]) for candidate in candidates)
        ),
        default=0,
    )


def _tool_names(message: object) -> list[str]:
    names: list[str] = []
    for attribute in ("tool_call_chunks", "tool_calls"):
        calls = getattr(message, attribute, ()) or ()
        for call in calls:
            name = call.get("name") if isinstance(call, Mapping) else None
            if isinstance(name, str) and name:
                names.append(name)
    return names


def _last_answer_text(messages: Sequence[object]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.text:
            return message.text
    return ""


def _collect_tool_results(messages: object) -> tuple[list[int], list[dict[str, object]]]:
    if not isinstance(messages, Sequence):
        return [], []
    article_ids: list[int] = []
    exports: list[dict[str, object]] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        payload = _tool_payload(message)
        error = payload.get("error")
        if isinstance(error, Mapping) and error.get("code") == "STORAGE_UNAVAILABLE":
            raise DataAccessError("MCP 저장소에 연결할 수 없습니다")
        article = payload.get("article")
        if isinstance(article, Mapping):
            _append_article_id(article_ids, article.get("article_id"))
        articles = payload.get("articles")
        if isinstance(articles, Sequence):
            for item in articles:
                if isinstance(item, Mapping):
                    _append_article_id(article_ids, item.get("article_id"))
        if payload.get("ok") is True and payload.get("format") in {"pdf", "notion"}:
            exports.append(
                {key: value for key, value in payload.items() if key not in {"ok", "message"}}
            )
    return article_ids, exports


def _tool_payload(message: ToolMessage) -> dict[str, object]:
    artifact = message.artifact
    if isinstance(artifact, Mapping):
        structured = artifact.get("structured_content")
        if isinstance(structured, Mapping):
            return dict(structured)
    if isinstance(message.content, str):
        try:
            decoded = json.loads(message.content)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def _append_article_id(article_ids: list[int], value: object) -> None:
    if isinstance(value, int) and value not in article_ids:
        article_ids.append(value)


def _system_prompt(issue: Mapping[str, object]) -> str:
    context = json.dumps(issue, ensure_ascii=False, default=str)
    return f"""당신은 현재 보고 있는 뉴스 이슈를 설명하는 근거 기반 에이전트입니다.

현재 이슈 문맥:
{context}

규칙:
- 이슈 문맥으로 답할 수 있는 일반 질문은 바로 답합니다.
- 발언, 수치, 날짜, 인과관계 같은 구체적 사실은 MCP 기사 검색·조회 도구로 확인합니다.
- 도구 결과가 없거나 확인할 수 없으면 추측하지 않습니다.
- 기사에서 확인한 문단은 반드시 `ARTICLE:`로 시작하고 기사 ID를 함께 적습니다.
- 기사에 없는 배경 개념 문단은 반드시 `GENERAL:`로 시작하고 일반 지식임을 밝힙니다.
- 한 문단에 두 출처를 섞지 않습니다. 표식 앞에는 다른 텍스트를 출력하지 않습니다.
- 내보내기는 사용자가 명시적으로 요청했을 때만 수행하며 형식이 없으면 먼저 묻습니다.
"""
