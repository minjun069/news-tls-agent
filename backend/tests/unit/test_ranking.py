from __future__ import annotations

from datetime import date

import pytest

from core.models import Article, EventArticle
from core.ranking import choose_representative


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
