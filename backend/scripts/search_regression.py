"""실제 MCP 검색으로 영남권 산불 2025년 회귀를 확인한다."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from core.errors import DataAccessError
from infra.mcp_client import MCPToolClient

_QUERY = "영남권 산불"
_DATE_FROM = date(2025, 1, 1)
_DATE_TO = date(2025, 12, 31)
_METHOD = "hybrid"
_TOP_K = 20

EXIT_MCP_UNAVAILABLE = 2
EXIT_REGRESSION_FAILED = 3


@dataclass(frozen=True)
class SearchRegressionResult:
    count: int
    article_ids: tuple[int, ...]


class SearchRegressionError(Exception):
    """MCP 호출은 끝났지만 검색 회귀 완료 조건을 만족하지 못했다."""


def validate_search_result(payload: Mapping[str, object]) -> SearchRegressionResult:
    """MCP 계약과 2025년 기사 1건 이상의 완료 조건을 검증한다."""
    if payload.get("ok") is not True:
        raise SearchRegressionError(f"MCP search_articles failed: {payload.get('error')}")
    articles = payload.get("articles")
    if not isinstance(articles, Sequence) or isinstance(articles, (str, bytes)):
        raise SearchRegressionError("MCP search_articles articles가 배열이 아닙니다")
    if not articles:
        raise SearchRegressionError("영남권 산불 2025년 검색 결과가 0건입니다")

    article_ids: list[int] = []
    for item in articles:
        if not isinstance(item, Mapping):
            raise SearchRegressionError("검색 기사 항목이 객체가 아닙니다")
        article_id = item.get("article_id")
        service_date = item.get("service_date")
        if not isinstance(article_id, int) or not isinstance(service_date, str):
            raise SearchRegressionError("검색 기사 ID 또는 서비스 일자 형식이 올바르지 않습니다")
        try:
            parsed_date = date.fromisoformat(service_date)
        except ValueError as exc:
            raise SearchRegressionError(
                f"검색 기사 {article_id}의 서비스 일자가 ISO 형식이 아닙니다"
            ) from exc
        if not _DATE_FROM <= parsed_date <= _DATE_TO:
            raise SearchRegressionError(
                f"검색 기사 {article_id}가 2025년 기간을 벗어났습니다: {service_date}"
            )
        article_ids.append(article_id)
    return SearchRegressionResult(count=len(article_ids), article_ids=tuple(article_ids))


async def run_search_regression(client: MCPToolClient) -> SearchRegressionResult:
    payload = await client.call_tool(
        "search_articles",
        {
            "query": _QUERY,
            "method": _METHOD,
            "top_k": _TOP_K,
            "date_from": _DATE_FROM.isoformat(),
            "date_to": _DATE_TO.isoformat(),
        },
    )
    return validate_search_result(payload)


def main() -> int:
    client = MCPToolClient(read_timeout_seconds=180)
    try:
        result = asyncio.run(run_search_regression(client))
    except DataAccessError as exc:
        print(f"FAIL mcp_search (exit={EXIT_MCP_UNAVAILABLE}): {exc}", file=sys.stderr)
        return EXIT_MCP_UNAVAILABLE
    except SearchRegressionError as exc:
        print(f"FAIL search_regression (exit={EXIT_REGRESSION_FAILED}): {exc}", file=sys.stderr)
        return EXIT_REGRESSION_FAILED

    ids = ",".join(str(article_id) for article_id in result.article_ids)
    print(
        f"PASS search_regression: query={_QUERY!r} year=2025 method={_METHOD} "
        f"top_k={_TOP_K} count={result.count} article_ids={ids}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
