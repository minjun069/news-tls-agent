"""MCP 툴 데코레이터와 payload 함수를 연결한다."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from datetime import date
from typing import Annotated, Literal

from mcp.server import MCPServer
from pydantic import Field

from mcp_server.tools.dependencies import ToolDependencies
from mcp_server.tools.payloads import (
    export_briefing_payload,
    get_issue_payload,
    list_issues_payload,
    read_article_payload,
    search_articles_payload,
)

audit_logger = logging.getLogger("news_tls_agent.mcp.audit")

_SEARCH_DESCRIPTION = (
    "뉴스 기사를 검색합니다. 구체적 사실(발언, 수치, 날짜, 인과관계)을 확인해야 할 때 "
    "사용하세요. 검색 방식은 질의 성격에 맞게 고르세요 — 인명·기관명·날짜처럼 정확히 "
    "일치해야 하면 `keyword`, 개념이나 상황 서술이면 `semantic`, 판단이 서지 않으면 "
    "`hybrid`입니다."
)
_READ_DESCRIPTION = (
    "기사 전문을 읽습니다. `search_articles` 결과만으로 답하기 어려울 때, 근거를 확인하려는 "
    "기사에 대해 호출하세요."
)
_LIST_DESCRIPTION = (
    "생성된 이슈 목록을 조회합니다. 사용자가 다른 이슈를 언급하거나 비교를 요청할 때 사용하세요."
)
_ISSUE_DESCRIPTION = (
    "이슈의 타임라인과 근거 기사 목록을 조회합니다. 현재 보고 있는 이슈의 내용은 이미 문맥에 "
    "있으므로, 다른 이슈를 확인할 때 사용하세요."
)
_EXPORT_DESCRIPTION = (
    "이슈 브리핑을 PDF로 내보내거나 Notion 페이지로 저장합니다. 사용자가 명시적으로 "
    "저장·내보내기를 요청한 경우에만 호출하세요. 형식을 말하지 않았다면 호출하지 말고, PDF와 "
    "Notion 중 무엇으로 할지 먼저 물어보세요. 대상은 직전 답변이 아니라 이슈 브리핑입니다."
)


def _invoke_audited(
    tool_name: str,
    arguments: Mapping[str, object],
    operation: Callable[[], dict[str, object]],
    result_count: Callable[[dict[str, object]], int],
) -> dict[str, object]:
    result = operation()
    audit_logger.info(
        "tool=%s args=%s result_count=%d ok=%s",
        tool_name,
        json.dumps(arguments, ensure_ascii=False, default=str, sort_keys=True),
        result_count(result),
        result.get("ok") is True,
    )
    return result


def _list_count(key: str) -> Callable[[dict[str, object]], int]:
    def count(result: dict[str, object]) -> int:
        value = result.get(key)
        return len(value) if isinstance(value, list) else 0

    return count


def _single_count(result: dict[str, object]) -> int:
    return int(result.get("ok") is True)


def register_tools(server: MCPServer, dependencies: ToolDependencies) -> None:
    """계약의 다섯 툴을 한 서버 인스턴스에 등록한다."""

    @server.tool(description=_SEARCH_DESCRIPTION, structured_output=True)
    def search_articles(
        query: str,
        method: Literal["keyword", "semantic", "hybrid"] = "hybrid",
        top_k: Annotated[int, Field(ge=1, le=100)] = 5,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, object]:
        """뉴스 기사를 검색합니다. 구체적 사실(발언, 수치, 날짜, 인과관계)을 확인해야 할 때 사용하세요.

        검색 방식은 질의 성격에 맞게 고르세요. 인명·기관명·날짜처럼 정확히 일치해야 하면
        keyword, 개념이나 상황 서술이면 semantic, 판단이 서지 않으면 hybrid입니다.
        """
        arguments = {
            "query": query,
            "method": method,
            "top_k": top_k,
            "date_from": date_from,
            "date_to": date_to,
        }
        return _invoke_audited(
            "search_articles",
            arguments,
            lambda: search_articles_payload(
                dependencies.searcher,
                dependencies.repository,
                query=query,
                method=method,
                top_k=top_k,
                date_from=date_from,
                date_to=date_to,
            ),
            _list_count("articles"),
        )

    @server.tool(description=_READ_DESCRIPTION, structured_output=True)
    def read_article(article_id: int) -> dict[str, object]:
        """기사 전문을 읽습니다. search_articles 결과만으로 답하기 어려울 때,
        근거를 확인하려는 기사에 대해 호출하세요.
        """
        return _invoke_audited(
            "read_article",
            {"article_id": article_id},
            lambda: read_article_payload(dependencies.repository, article_id),
            _single_count,
        )

    @server.tool(description=_LIST_DESCRIPTION, structured_output=True)
    def list_issues() -> dict[str, object]:
        """생성된 이슈 목록을 조회합니다. 사용자가 다른 이슈를 언급하거나 비교를 요청할 때 사용하세요."""
        return _invoke_audited(
            "list_issues",
            {},
            lambda: list_issues_payload(dependencies.repository),
            _list_count("issues"),
        )

    @server.tool(description=_ISSUE_DESCRIPTION, structured_output=True)
    def get_issue(issue_id: int) -> dict[str, object]:
        """이슈의 타임라인과 근거 기사 목록을 조회합니다.
        현재 보고 있는 이슈의 내용은 이미 문맥에 있으므로, 다른 이슈를 확인할 때 사용하세요.
        """
        return _invoke_audited(
            "get_issue",
            {"issue_id": issue_id},
            lambda: get_issue_payload(dependencies.repository, issue_id),
            _single_count,
        )

    @server.tool(description=_EXPORT_DESCRIPTION, structured_output=True)
    def export_briefing(
        issue_id: int,
        format: Literal["pdf", "notion"],
        parent_page_id: str | None = None,
    ) -> dict[str, object]:
        """이슈 브리핑을 PDF로 내보내거나 Notion 페이지로 저장합니다.

        사용자가 명시적으로 저장·내보내기를 요청한 경우에만 호출하세요. 형식을 말하지 않았다면
        호출하지 말고 PDF와 Notion 중 무엇으로 할지 먼저 물어보세요. 대상은 직전 답변이 아니라
        이슈 브리핑입니다.
        """
        arguments = {
            "issue_id": issue_id,
            "format": format,
            "parent_page_id": parent_page_id,
        }
        return _invoke_audited(
            "export_briefing",
            arguments,
            lambda: export_briefing_payload(
                dependencies.exporter,
                issue_id=issue_id,
                output_format=format,
                parent_page_id=parent_page_id,
            ),
            _single_count,
        )
