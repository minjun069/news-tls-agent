#!/usr/bin/env python3
"""AGENTS.md의 현재 크기를 보고한다. 목표 예산은 사용자 결정 전까지 강제하지 않는다."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def estimate_tokens(text: str) -> int:
    korean = len(re.findall(r"[가-힣]", text))
    return round(korean * 1.1 + (len(text) - korean) * 0.28)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-tokens", type=int)
    args = parser.parse_args()
    path = ROOT / "AGENTS.md"
    text = path.read_text(encoding="utf-8")
    tokens = estimate_tokens(text)
    print(f"AGENTS.md: {len(text.splitlines())}줄, {len(text.encode('utf-8'))}바이트, 약 {tokens}토큰")
    if args.max_tokens is not None and tokens > args.max_tokens:
        print(f"목표 {args.max_tokens}토큰을 {tokens - args.max_tokens}토큰 초과")
        return 1
    if args.max_tokens is None:
        print("강제 예산 없음 — 측정 결과 검토 후 목표를 결정합니다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
