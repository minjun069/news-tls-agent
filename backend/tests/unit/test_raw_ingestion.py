from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.raw_ingestion import (
    RawIngestionStats,
    iter_valid_articles,
    normalize_record,
    validate_raw,
)


def raw_article(article_id: object = 1, **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "article_id": article_id,
        "article_title": "반도체 공급망 변화",
        "article_sub_title": "  부제목  ",
        "article_service_daytime": "2025-01-02 09:00:00",
        "article_summary": "  요약  ",
        "text": "국내 반도체 기업의 공급망 관련 기사 본문",
        "article_url": "https://example.test/articles/1",
        "category_large_nm": "산업",
        "category_middle_nm": "반도체",
        "category_small_nm": "장비",
    }
    record.update(overrides)
    return record


def write_jsonl(path: Path, rows: list[object]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )


def test_normalize_maps_actual_raw_fields_and_optional_blanks() -> None:
    result = normalize_record(
        raw_article(article_sub_title=" ", article_summary="", category_small_nm="")
    )

    assert result.exclusion_reason is None
    assert result.article is not None
    assert result.article.article_id == 1
    assert result.article.title == "반도체 공급망 변화"
    assert result.article.service_date.isoformat() == "2025-01-02"
    assert result.article.content == "국내 반도체 기업의 공급망 관련 기사 본문"
    assert result.article.sub_title is None
    assert result.article.summary is None
    assert result.article.category_small is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"article_id": None}, "missing_article_id"),
        ({"article_id": "not-an-id"}, "invalid_article_id"),
        ({"article_title": ""}, "missing_title"),
        ({"article_service_daytime": "invalid"}, "invalid_service_date"),
        ({"text": "\t"}, "missing_content"),
        ({"article_url": "x" * 1001}, "field_validation_error"),
    ],
)
def test_normalize_reports_required_field_exclusion_reason(
    overrides: dict[str, object], reason: str
) -> None:
    result = normalize_record(raw_article(**overrides))

    assert result.article is None
    assert result.exclusion_reason == reason


def test_validate_raw_aggregates_all_exclusions_and_valid_id_duplicates(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    rows = [
        raw_article(20),
        raw_article("not-an-id"),
        raw_article(2, article_title=""),
        raw_article(3, article_service_daytime="2025-99-01 09:00:00"),
        raw_article(4, text=" "),
        raw_article(20, article_title="마지막 유효 중복 기사"),
    ]
    write_jsonl(source, rows)
    source.write_text(
        "\n{broken json}\n[]\n" + source.read_text(encoding="utf-8"), encoding="utf-8"
    )

    report = validate_raw([source])

    assert report.source_line_count == 9
    assert report.blank_line_count == 1
    assert report.parsed_object_count == 6
    assert report.json_error_count == 1
    assert report.non_object_count == 1
    assert report.valid_article_count == 2
    assert report.duplicate_article_id_count == 1
    assert report.exclusion_counts == {
        "invalid_article_id": 1,
        "invalid_service_date": 1,
        "missing_content": 1,
        "missing_title": 1,
    }


def test_valid_article_iterator_preserves_source_order_for_last_valid_upsert(
    tmp_path: Path,
) -> None:
    source = tmp_path / "raw.jsonl"
    write_jsonl(
        source,
        [
            raw_article(1, article_title="첫 기사"),
            raw_article(2, article_title="둘째 기사"),
            raw_article(1, article_title="마지막 유효 기사"),
        ],
    )
    stats = RawIngestionStats()

    articles = list(iter_valid_articles([source], stats))

    assert [article.article_id for article in articles] == [1, 2, 1]
    assert articles[-1].title == "마지막 유효 기사"
    assert stats.report().duplicate_article_id_count == 1
