"""검색 순위 결합과 대표 기사 선정 정책의 순수 계산."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from core.models import Article, EventArticle, SearchHit

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[SearchHit]],
    *,
    top_k: int,
    k: int = DEFAULT_RRF_K,
) -> list[SearchHit]:
    """검색 목록들의 순위만 사용해 RRF 점수 내림차순으로 결합한다."""
    if top_k < 1:
        raise ValueError("top_k는 1 이상이어야 합니다")
    if k < 0:
        raise ValueError("RRF k는 0 이상이어야 합니다")

    scores: dict[int, float] = {}
    for ranking in rankings:
        seen: set[int] = set()
        for rank, hit in enumerate(ranking, start=1):
            if hit.article_id in seen:
                continue
            seen.add(hit.article_id)
            scores[hit.article_id] = scores.get(hit.article_id, 0.0) + 1 / (k + rank)

    fused = (SearchHit(article_id=article_id, score=score) for article_id, score in scores.items())
    return sorted(fused, key=lambda hit: (-hit.score, hit.article_id))[:top_k]


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
