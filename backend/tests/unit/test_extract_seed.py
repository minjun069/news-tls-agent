from __future__ import annotations

import importlib
import json
from pathlib import Path

extract = importlib.import_module("scripts.01_extract_seed")


def raw_article(article_id: object = 1, **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "article_id": article_id,
        "title": "반도체 공급망 변화",
        "service_date": "2026-01-02T09:00:00",
        "content": "국내 반도체 기업의 공급망 관련 기사 본문",
    }
    record.update(overrides)
    return record


def test_normalize_excludes_missing_required_fields() -> None:
    assert extract.normalize_record(raw_article(content="")) is None
    assert extract.normalize_record(raw_article(title="")) is None
    assert extract.normalize_record(raw_article(article_id="not-an-id")) is None
    assert extract.normalize_record(raw_article(service_date="invalid")) is None


def test_extract_filters_deduplicates_and_sorts(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    target = tmp_path / "seed" / "topic.jsonl"
    rows = [
        raw_article(20),
        raw_article(10, title="다른 제목", content="반도체가 본문에 있음"),
        raw_article(20, summary="중복 ID는 마지막 값으로 덮어씀"),
        raw_article(30, title="무관한 기사", content="다른 내용"),
    ]
    source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))

    count = extract.extract_seed([source], target, ["반도체"])

    saved = [json.loads(line) for line in target.read_text().splitlines()]
    assert count == 2
    assert [row["article_id"] for row in saved] == [10, 20]
    assert saved[1]["summary"] == "중복 ID는 마지막 값으로 덮어씀"
