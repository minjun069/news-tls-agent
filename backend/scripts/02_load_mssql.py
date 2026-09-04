"""원본 JSONL을 검증·정규화해 MS-SQL articles에 배치 upsert한다."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv

from core.config import load_mssql_config
from core.models import Article
from infra.db import create_db_engine, create_session_factory
from infra.repository import SqlRepository
from scripts.raw_ingestion import RawIngestionStats, RawValidationReport, iter_valid_articles

_REPO_ROOT = Path(__file__).resolve().parents[2]


class ArticleUpserter(Protocol):
    """원본 적재가 필요한 Repository 최소 기능."""

    def upsert_articles(self, articles: Sequence[Article]) -> int:
        """기사 배치를 멱등 upsert하고 처리한 행 수를 반환한다."""


@dataclass(frozen=True)
class RawLoadReport:
    """한 번의 전체 원본 순회·DB 적재 결과."""

    validation: RawValidationReport
    upserted_row_count: int

    def as_dict(self) -> dict[str, object]:
        return {**self.validation.as_dict(), "upserted_row_count": self.upserted_row_count}


def _batches(items: Iterable[Article], size: int) -> Iterable[list[Article]]:
    """한 DB 배치 안의 중복 ID를 마지막 유효 기사 하나로 합친다."""
    batch: dict[int, Article] = {}
    for item in items:
        batch[item.article_id] = item
        if len(batch) >= size:
            yield list(batch.values())
            batch = {}
    if batch:
        yield list(batch.values())


def load_raw_articles(
    paths: Sequence[Path], batch_size: int, repository: ArticleUpserter
) -> RawLoadReport:
    """중간 seed 파일 없이 원본 전체를 한 번 읽어 검증·적재한다."""
    if batch_size < 1:
        raise ValueError("batch_size는 1 이상이어야 합니다")
    stats = RawIngestionStats()
    upserted_row_count = 0
    for batch in _batches(iter_valid_articles(paths, stats), batch_size):
        upserted_row_count += repository.upsert_articles(batch)
    return RawLoadReport(validation=stats.report(), upserted_row_count=upserted_row_count)


def load_articles(paths: Sequence[Path], batch_size: int) -> RawLoadReport:
    load_dotenv(_REPO_ROOT / ".env")
    engine = create_db_engine(load_mssql_config(os.environ))
    repository = SqlRepository(create_session_factory(engine))
    try:
        return load_raw_articles(paths, batch_size, repository)
    finally:
        engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="원본 JSONL 파일")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size는 1 이상이어야 합니다")
    return args


def main() -> None:
    args = _parse_args()
    report = load_articles(args.inputs, args.batch_size)
    print(json.dumps({"inputs": [str(path) for path in args.inputs], **report.as_dict()}))


if __name__ == "__main__":
    main()
