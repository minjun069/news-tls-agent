"""MCP 없이 단위 검증할 수 있는 툴 payload 함수."""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal, cast

from pydantic import ValidationError

from core.models import SearchMethod, SearchOptions
from core.ports import Repository
from mcp_server.tools.dependencies import ArticleSearcher, BriefingExporter

logger = logging.getLogger(__name__)

ARTICLE_CONTENT_LIMIT = 20_000


def _error(code: str, message: str) -> dict[str, object]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _invalid_argument(exc: ValueError) -> dict[str, object]:
    return _error("INVALID_ARGUMENT", str(exc))


def _storage_unavailable(tool_name: str, exc: Exception) -> dict[str, object]:
    logger.error(
        "MCP payload 저장소 접근 실패: tool=%s",
        tool_name,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _error("STORAGE_UNAVAILABLE", "저장소에 연결할 수 없습니다.")


def search_articles_payload(
    searcher: ArticleSearcher,
    repository: Repository,
    *,
    query: str,
    method: str = "hybrid",
    top_k: int = 5,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, object]:
    """검색 결과 ID를 실제 기사와 대조해 목록 payload로 만든다."""
    if not query.strip():
        return _error("INVALID_ARGUMENT", "query는 빈 문자열일 수 없습니다.")
    try:
        search_method = SearchMethod(method)
        options = SearchOptions(top_k=top_k, date_from=date_from, date_to=date_to)
    except (ValidationError, ValueError) as exc:
        return _invalid_argument(exc)

    try:
        result = searcher.search(query, search_method, options)
        articles = repository.get_articles([hit.article_id for hit in result.hits])
    # 저장소·Qdrant·임베딩 SDK는 공통 예외 기반이 없어 MCP 경계에서 모두 규약으로 바꾼다.
    except Exception as exc:  # noqa: BLE001
        return _storage_unavailable("search_articles", exc)

    scores = {hit.article_id: hit.score for hit in result.hits}
    items = [
        {
            "article_id": article.article_id,
            "title": article.title,
            "service_date": article.service_date.isoformat(),
            "summary": article.summary or "",
            "score": scores[article.article_id],
        }
        for article in articles
    ]
    return {
        "ok": True,
        "method": result.method.value,
        "articles": items,
        "message": f"{len(items)}건을 찾았습니다.",
    }


def read_article_payload(repository: Repository, article_id: int) -> dict[str, object]:
    """기사 본문을 표시 상한과 잘림 여부를 포함해 반환한다."""
    try:
        article = repository.get_article(article_id)
    except Exception as exc:  # noqa: BLE001 - 저장소 예외를 MCP 오류 규약으로 변환
        return _storage_unavailable("read_article", exc)
    if article is None:
        return _error("ARTICLE_NOT_FOUND", "해당 기사를 찾을 수 없습니다.")

    content = article.content or ""
    truncated = len(content) > ARTICLE_CONTENT_LIMIT
    item = {
        "article_id": article.article_id,
        "title": article.title,
        "sub_title": article.sub_title or "",
        "service_date": article.service_date.isoformat(),
        "summary": article.summary or "",
        "content": content[:ARTICLE_CONTENT_LIMIT],
        "url": article.url or "",
        "truncated": truncated,
    }
    message = "기사를 읽었습니다."
    if truncated:
        message = "기사를 읽었습니다. 본문 일부만 포함되어 있습니다."
    return {"ok": True, "article": item, "message": message}


def list_issues_payload(repository: Repository) -> dict[str, object]:
    """생성 시각 내림차순 이슈 목록을 직렬화한다."""
    try:
        issues = repository.list_issues()
    except Exception as exc:  # noqa: BLE001 - 저장소 예외를 MCP 오류 규약으로 변환
        return _storage_unavailable("list_issues", exc)
    items = [
        {
            "issue_id": issue.issue_id,
            "topic": issue.topic,
            "title": issue.title or issue.topic,
            "generated_at": issue.generated_at.isoformat(),
            "event_count": issue.event_count,
        }
        for issue in issues
    ]
    return {"ok": True, "issues": items, "message": f"이슈 {len(items)}건이 있습니다."}


def get_issue_payload(repository: Repository, issue_id: int) -> dict[str, object]:
    """이슈와 날짜순 이벤트·대표 기사·근거 기사 순위를 직렬화한다."""
    try:
        issue = repository.get_issue(issue_id)
    except Exception as exc:  # noqa: BLE001 - 저장소 예외를 MCP 오류 규약으로 변환
        return _storage_unavailable("get_issue", exc)
    if issue is None:
        return _error("ISSUE_NOT_FOUND", "해당 이슈를 찾을 수 없습니다.")

    events = []
    for event in issue.events:
        articles = sorted(
            event.articles,
            key=lambda link: (
                -(link.relevance_score if link.relevance_score is not None else float("-inf")),
                link.article.article_id,
            ),
        )
        representative = event.representative_article
        events.append(
            {
                "event_order": event.event_order,
                "event_date": event.event_date.isoformat(),
                "title": event.title,
                "summary": event.summary or "",
                "primary_article": {
                    "article_id": representative.article_id,
                    "title": representative.title,
                    "service_date": representative.service_date.isoformat(),
                },
                "articles": [
                    {
                        "article_id": link.article.article_id,
                        "title": link.article.title,
                        "service_date": link.article.service_date.isoformat(),
                        "relevance_score": link.relevance_score,
                    }
                    for link in articles
                ],
            }
        )
    item = {
        "issue_id": issue.issue_id,
        "topic": issue.topic,
        "title": issue.title or issue.topic,
        "summary": issue.summary or "",
        "generated_at": issue.generated_at.isoformat(),
        "events": events,
    }
    return {
        "ok": True,
        "issue": item,
        "message": f"이벤트 {len(events)}건을 포함한 이슈입니다.",
    }


def export_briefing_payload(
    repository: Repository,
    exporter: BriefingExporter | None,
    *,
    issue_id: int,
    output_format: str,
    parent_page_id: str | None = None,
) -> dict[str, object]:
    """이슈 존재 여부와 구현 설정을 확인한 뒤 공용 내보내기 유스케이스를 호출한다."""
    if output_format not in {"pdf", "notion"}:
        return _error("INVALID_ARGUMENT", "format은 pdf 또는 notion이어야 합니다.")
    try:
        issue = repository.get_issue(issue_id)
    except Exception as exc:  # noqa: BLE001 - 저장소 예외를 MCP 오류 규약으로 변환
        return _storage_unavailable("export_briefing", exc)
    if issue is None:
        return _error("ISSUE_NOT_FOUND", "해당 이슈를 찾을 수 없습니다.")
    if exporter is None:
        return _error("EXPORT_NOT_CONFIGURED", "내보내기 기능이 아직 설정되지 않았습니다.")

    validated_format = cast(Literal["pdf", "notion"], output_format)
    try:
        payload = dict(
            exporter.export_briefing(
                issue_id,
                validated_format,
                parent_page_id,
            )
        )
    except Exception:
        logger.exception("MCP payload 내보내기 실패: format=%s", output_format)
        return _error("STORAGE_UNAVAILABLE", "브리핑을 내보내지 못했습니다.")
    return {"ok": True, **payload}
