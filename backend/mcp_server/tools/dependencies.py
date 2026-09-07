"""MCP payload가 요구하는 포트 묶음."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from core.models import SearchMethod, SearchOptions, SearchResult
from core.ports import Repository


class ArticleSearcher(Protocol):
    """기사 검색 유스케이스의 MCP 측 계약."""

    def search(
        self,
        query: str,
        method: SearchMethod,
        options: SearchOptions,
    ) -> SearchResult:
        """방식과 기간을 적용한 기사 순위를 반환한다."""
        ...


class BriefingExporter(Protocol):
    """화면 메뉴와 MCP 도구가 함께 사용하는 내보내기 계약."""

    def export_briefing(
        self,
        issue_id: int,
        output_format: Literal["pdf", "notion"],
        parent_page_id: str | None,
    ) -> Mapping[str, object]:
        """계약에 맞는 성공 payload를 반환한다."""
        ...


@dataclass(frozen=True)
class ToolDependencies:
    """서버 조립점이 MCP 툴에 주입하는 의존성."""

    repository: Repository
    searcher: ArticleSearcher
    exporter: BriefingExporter | None = None
