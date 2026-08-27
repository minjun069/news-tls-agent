"""정규화된 시드 JSONL을 MS-SQL articles에 배치 upsert한다."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from core.config import load_mssql_config
from core.models import Article
from infra.db import create_db_engine, create_session_factory
from infra.repository import SqlRepository

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _batches(items: Iterable[Article], size: int) -> Iterable[list[Article]]:
    batch: list[Article] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _articles(paths: Sequence[Path]) -> Iterable[Article]:
    for path in paths:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    payload: Any = json.loads(line)
                    yield Article.model_validate(payload)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ValueError(f"{path}:{line_number} 기사 형식 오류") from exc


def load_articles(paths: Sequence[Path], batch_size: int) -> int:
    load_dotenv(_REPO_ROOT / ".env")
    engine = create_db_engine(load_mssql_config(os.environ))
    repository = SqlRepository(create_session_factory(engine))
    total = 0
    try:
        for batch in _batches(_articles(paths), batch_size):
            total += repository.upsert_articles(batch)
    finally:
        engine.dispose()
    return total


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="시드 JSONL 파일")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size는 1 이상이어야 합니다")
    return args


def main() -> None:
    args = _parse_args()
    count = load_articles(args.inputs, args.batch_size)
    print(f"MS-SQL 기사 {count}건 upsert 완료")


if __name__ == "__main__":
    main()
