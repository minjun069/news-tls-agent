from __future__ import annotations

import pytest

from scripts.search_regression import SearchRegressionError, validate_search_result


def test_search_regression_accepts_mcp_articles_within_2025() -> None:
    result = validate_search_result(
        {
            "ok": True,
            "articles": [
                {"article_id": 10, "service_date": "2025-03-24"},
                {"article_id": 20, "service_date": "2025-12-31"},
            ],
        }
    )

    assert result.count == 2
    assert result.article_ids == (10, 20)


def test_search_regression_rejects_empty_mcp_result() -> None:
    with pytest.raises(SearchRegressionError, match="0건"):
        validate_search_result({"ok": True, "articles": []})


def test_search_regression_rejects_article_outside_2025() -> None:
    with pytest.raises(SearchRegressionError, match="기간을 벗어났습니다"):
        validate_search_result(
            {
                "ok": True,
                "articles": [{"article_id": 10, "service_date": "2024-03-24"}],
            }
        )


def test_search_regression_preserves_mcp_error() -> None:
    with pytest.raises(SearchRegressionError, match="STORAGE_UNAVAILABLE"):
        validate_search_result(
            {
                "ok": False,
                "error": {"code": "STORAGE_UNAVAILABLE", "message": "offline"},
            }
        )
