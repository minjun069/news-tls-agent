from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from core.models import Article

loader = importlib.import_module("scripts.02_load_mssql")


def raw_article(article_id: int, title: str) -> dict[str, object]:
    return {
        "article_id": article_id,
        "article_title": title,
        "article_service_daytime": "2025-01-02 09:00:00",
        "text": f"{title} 본문",
    }


class FakeRepository:
    def __init__(self) -> None:
        self.batches: list[list[Article]] = []
        self.stored: dict[int, Article] = {}

    def upsert_articles(self, articles: list[Article]) -> int:
        self.batches.append(articles)
        self.stored.update({article.article_id: article for article in articles})
        return len(articles)


def test_load_raw_articles_streams_raw_records_and_keeps_last_valid_duplicate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "raw.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in [
                raw_article(1, "첫 기사"),
                raw_article(2, "둘째 기사"),
                raw_article(1, "마지막 기사"),
                raw_article(3, "셋째 기사"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    repository = FakeRepository()

    report = loader.load_raw_articles([source], batch_size=3, repository=repository)

    assert [[article.article_id for article in batch] for batch in repository.batches] == [
        [1, 2, 3]
    ]
    assert repository.stored[1].title == "마지막 기사"
    assert report.upserted_row_count == 3
    assert report.validation.valid_article_count == 4
    assert report.validation.duplicate_article_id_count == 1


def test_load_raw_articles_rejects_zero_batch_size(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="batch_size는 1 이상이어야 합니다"):
        loader.load_raw_articles(
            [tmp_path / "unused.jsonl"], batch_size=0, repository=FakeRepository()
        )
