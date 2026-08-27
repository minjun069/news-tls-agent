"""대표 기사 선정 규칙 — PRD §7.1의 순수 계산."""

from __future__ import annotations

from datetime import date

from core.models import Article, EventArticle


def representative_sort_key(candidate: EventArticle, event_date: date) -> tuple[float, int, int]:
    """관련도 내림차순 → 날짜 근접 → 기사 ID 오름차순 정렬 키."""
    relevance = candidate.relevance_score
    return (
        -(relevance if relevance is not None else float("-inf")),
        abs((candidate.article.service_date - event_date).days),
        candidate.article.article_id,
    )


def choose_representative(
    candidates: tuple[EventArticle, ...] | list[EventArticle], event_date: date
) -> Article:
    """후보 중 대표 기사 한 건을 결정론적으로 고른다."""
    if not candidates:
        raise ValueError("대표 기사를 고르려면 후보가 한 건 이상 필요합니다")
    return min(
        candidates, key=lambda candidate: representative_sort_key(candidate, event_date)
    ).article
