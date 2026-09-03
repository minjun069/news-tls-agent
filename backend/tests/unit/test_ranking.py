from __future__ import annotations

from datetime import date

import pytest

from core.models import Article, EventArticle, SearchHit
from core.ranking import DEFAULT_RRF_K, choose_representative, reciprocal_rank_fusion


def hit(article_id: int, score: float = 0.0) -> SearchHit:
    return SearchHit(article_id=article_id, score=score)


def test_rrf_combines_shared_and_single_source_articles() -> None:
    fused = reciprocal_rank_fusion(
        [
            [hit(1, 100.0), hit(2, 50.0)],
            [hit(2, 0.99), hit(3, 0.75)],
        ],
        top_k=3,
    )

    assert [result.article_id for result in fused] == [2, 1, 3]
    assert fused[0].score == pytest.approx(1 / (DEFAULT_RRF_K + 2) + 1 / (DEFAULT_RRF_K + 1))


def test_rrf_accepts_empty_and_single_ranking() -> None:
    assert reciprocal_rank_fusion([], top_k=5) == []
    assert reciprocal_rank_fusion([[]], top_k=5) == []

    fused = reciprocal_rank_fusion([[hit(20), hit(10)]], top_k=5)
    assert [result.article_id for result in fused] == [20, 10]


def test_rrf_counts_duplicate_article_only_at_its_first_rank() -> None:
    fused = reciprocal_rank_fusion(
        [[hit(1), hit(1), hit(2)]],
        top_k=2,
        k=0,
    )

    assert [(result.article_id, result.score) for result in fused] == [
        (1, pytest.approx(1.0)),
        (2, pytest.approx(1 / 3)),
    ]


def test_rrf_breaks_score_ties_by_article_id() -> None:
    fused = reciprocal_rank_fusion([[hit(20)], [hit(10)]], top_k=2)
    assert [result.article_id for result in fused] == [10, 20]


def test_rrf_applies_top_k_without_mutating_inputs() -> None:
    first = [hit(1), hit(2)]
    second = [hit(2), hit(3)]
    before = [first.copy(), second.copy()]

    fused = reciprocal_rank_fusion([first, second], top_k=1)

    assert [result.article_id for result in fused] == [2]
    assert [first, second] == before


@pytest.mark.parametrize(("top_k", "k"), [(0, 60), (1, -1)])
def test_rrf_rejects_invalid_parameters(top_k: int, k: int) -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([], top_k=top_k, k=k)


def candidate(article_id: int, service_date: date, score: float | None) -> EventArticle:
    return EventArticle(
        article=Article(
            article_id=article_id,
            title=f"기사 {article_id}",
            service_date=service_date,
        ),
        relevance_score=score,
    )


def test_relevance_score_has_first_priority() -> None:
    event_date = date(2026, 1, 10)
    selected = choose_representative(
        [
            candidate(1, event_date, 0.8),
            candidate(2, date(2020, 1, 1), 0.9),
        ],
        event_date,
    )
    assert selected.article_id == 2


def test_nearest_date_breaks_relevance_tie() -> None:
    event_date = date(2026, 1, 10)
    selected = choose_representative(
        [
            candidate(1, date(2026, 1, 1), 0.9),
            candidate(2, date(2026, 1, 9), 0.9),
        ],
        event_date,
    )
    assert selected.article_id == 2


def test_article_id_breaks_equal_score_and_distance_tie() -> None:
    event_date = date(2026, 1, 10)
    selected = choose_representative(
        [
            candidate(20, date(2026, 1, 11), 0.9),
            candidate(10, date(2026, 1, 9), 0.9),
        ],
        event_date,
    )
    assert selected.article_id == 10


def test_missing_score_ranks_after_any_score() -> None:
    event_date = date(2026, 1, 10)
    selected = choose_representative(
        [
            candidate(1, event_date, None),
            candidate(2, date(2020, 1, 1), -1.0),
        ],
        event_date,
    )
    assert selected.article_id == 2


def test_empty_candidates_are_rejected() -> None:
    with pytest.raises(ValueError, match="후보"):
        choose_representative([], date(2026, 1, 10))
