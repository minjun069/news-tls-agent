"""원본 JSONL 전체를 검증하고 정규화·제외 집계를 보고한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.raw_ingestion import validate_raw


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="원본 JSONL 파일")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = validate_raw(args.inputs)
    print(json.dumps({"inputs": [str(path) for path in args.inputs], **report.as_dict()}))


if __name__ == "__main__":
    main()
