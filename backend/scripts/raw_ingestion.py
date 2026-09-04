"""원본 JSONL 검증·정규화를 01 검증기와 02 MS-SQL 적재기가 공유한다."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.models import Article


@dataclass(frozen=True)
class NormalizationResult:
    """원본 한 행의 정규화 결과 또는 적재 제외 사유."""

    article: Article | None
    exclusion_reason: str | None


@dataclass(frozen=True)
class RawValidationReport:
    """전체 원본 검증 결과와 적재 가능한 기사 수."""

    source_line_count: int
    blank_line_count: int
    parsed_object_count: int
    json_error_count: int
    non_object_count: int
    valid_article_count: int
    duplicate_article_id_count: int
    exclusion_counts: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_line_count": self.source_line_count,
            "blank_line_count": self.blank_line_count,
            "parsed_object_count": self.parsed_object_count,
            "json_error_count": self.json_error_count,
            "non_object_count": self.non_object_count,
            "valid_article_count": self.valid_article_count,
            "duplicate_article_id_count": self.duplicate_article_id_count,
            "exclusion_counts": dict(self.exclusion_counts),
        }


@dataclass
class RawIngestionStats:
    """한 번의 원본 순회에서 누적하는 가변 집계값."""

    source_line_count: int = 0
    blank_line_count: int = 0
    parsed_object_count: int = 0
    json_error_count: int = 0
    non_object_count: int = 0
    valid_article_count: int = 0
    duplicate_article_id_count: int = 0
    exclusion_counts: Counter[str] = field(default_factory=Counter)
    _seen_article_ids: set[int] = field(default_factory=set)

    def record_valid_article(self, article_id: int) -> None:
        self.valid_article_count += 1
        if article_id in self._seen_article_ids:
            self.duplicate_article_id_count += 1
        self._seen_article_ids.add(article_id)

    def report(self) -> RawValidationReport:
        return RawValidationReport(
            source_line_count=self.source_line_count,
            blank_line_count=self.blank_line_count,
            parsed_object_count=self.parsed_object_count,
            json_error_count=self.json_error_count,
            non_object_count=self.non_object_count,
            valid_article_count=self.valid_article_count,
            duplicate_article_id_count=self.duplicate_article_id_count,
            exclusion_counts=dict(sorted(self.exclusion_counts.items())),
        )


def _text(value: object) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _article_id(value: object) -> tuple[int | None, str | None]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing_article_id"
    if isinstance(value, bool):
        return None, "invalid_article_id"
    if isinstance(value, int):
        return value, None
    if isinstance(value, str):
        try:
            return int(value), None
        except ValueError:
            return None, "invalid_article_id"
    return None, "invalid_article_id"


def _service_date(value: object) -> tuple[date | None, str | None]:
    text = _text(value)
    if text is None:
        return None, "invalid_service_date"
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").date(), None
    except ValueError:
        return None, "invalid_service_date"


def normalize_record(record: Mapping[str, Any]) -> NormalizationResult:
    """실제 원본 필드를 Article로 바꾸거나 계약된 제외 사유를 반환한다."""
    article_id, article_id_error = _article_id(record.get("article_id"))
    if article_id_error is not None:
        return NormalizationResult(article=None, exclusion_reason=article_id_error)

    title = _text(record.get("article_title"))
    if title is None:
        return NormalizationResult(article=None, exclusion_reason="missing_title")

    service_date, service_date_error = _service_date(record.get("article_service_daytime"))
    if service_date_error is not None:
        return NormalizationResult(article=None, exclusion_reason=service_date_error)

    content = _text(record.get("text"))
    if content is None:
        return NormalizationResult(article=None, exclusion_reason="missing_content")

    try:
        return NormalizationResult(
            article=Article(
                article_id=article_id,
                title=title,
                sub_title=_text(record.get("article_sub_title")),
                service_date=service_date,
                summary=_text(record.get("article_summary")),
                content=content,
                url=_text(record.get("article_url")),
                category_large=_text(record.get("category_large_nm")),
                category_middle=_text(record.get("category_middle_nm")),
                category_small=_text(record.get("category_small_nm")),
            ),
            exclusion_reason=None,
        )
    except ValidationError:
        return NormalizationResult(article=None, exclusion_reason="field_validation_error")


def iter_valid_articles(paths: Sequence[Path], stats: RawIngestionStats) -> Iterable[Article]:
    """원본을 한 번만 읽어 유효 기사를 순서대로 내보내고 모든 제외를 집계한다."""
    for path in paths:
        with path.open(encoding="utf-8") as source:
            for line in source:
                stats.source_line_count += 1
                if not line.strip():
                    stats.blank_line_count += 1
                    continue
                try:
                    record: Any = json.loads(line)
                except json.JSONDecodeError:
                    stats.json_error_count += 1
                    continue
                if not isinstance(record, dict):
                    stats.non_object_count += 1
                    continue
                stats.parsed_object_count += 1

                result = normalize_record(record)
                if result.article is None:
                    stats.exclusion_counts[result.exclusion_reason or "unknown"] += 1
                    continue
                stats.record_valid_article(result.article.article_id)
                yield result.article


def validate_raw(paths: Sequence[Path]) -> RawValidationReport:
    """DB를 건드리지 않고 원본 전체의 적재 가능 여부만 확인한다."""
    stats = RawIngestionStats()
    for _article in iter_valid_articles(paths, stats):
        pass
    return stats.report()
