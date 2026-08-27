"""원본 JSONL에서 키워드에 맞는 유효 기사만 시드 JSONL로 정규화한다."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.models import Article


def _text(value: object) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def normalize_record(record: Mapping[str, Any]) -> Article | None:
    """DATA §1.2에 맞지 않는 행은 None으로 제외한다."""
    content = _text(record.get("content"))
    title = _text(record.get("title"))
    if content is None or title is None:
        return None
    try:
        article_id = int(record["article_id"])
        service_date = date.fromisoformat(str(record["service_date"])[:10])
        return Article(
            article_id=article_id,
            title=title,
            sub_title=_text(record.get("sub_title")),
            service_date=service_date,
            summary=_text(record.get("summary")),
            content=content,
            url=_text(record.get("url")),
            category_large=_text(record.get("category_large")),
            category_middle=_text(record.get("category_middle")),
            category_small=_text(record.get("category_small")),
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        return None


def matches_keywords(article: Article, keywords: Sequence[str]) -> bool:
    haystack = " ".join(
        value
        for value in (article.title, article.sub_title, article.summary, article.content)
        if value
    ).casefold()
    return any(keyword.casefold() in haystack for keyword in keywords)


def iter_records(paths: Iterable[Path]) -> Iterable[Mapping[str, Any]]:
    for path in paths:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number} JSON 형식 오류") from exc
                if not isinstance(record, dict):
                    raise TypeError(f"{path}:{line_number} 객체가 아닙니다")
                yield record


def extract_seed(input_paths: Sequence[Path], output_path: Path, keywords: Sequence[str]) -> int:
    selected: dict[int, Article] = {}
    for record in iter_records(input_paths):
        article = normalize_record(record)
        if article is not None and matches_keywords(article, keywords):
            selected[article.article_id] = article

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as target:
        for article_id in sorted(selected):
            target.write(selected[article_id].model_dump_json() + "\n")
    return len(selected)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="원본 JSONL 파일")
    parser.add_argument("--output", required=True, type=Path, help="시드 JSONL 출력")
    parser.add_argument(
        "--keyword", required=True, action="append", dest="keywords", help="포함 키워드(반복 가능)"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    count = extract_seed(args.inputs, args.output, args.keywords)
    print(f"시드 기사 {count}건 저장: {args.output}")


if __name__ == "__main__":
    main()
