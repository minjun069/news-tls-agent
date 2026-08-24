#!/usr/bin/env python3
"""하네스 문서 토큰 예산 검사 — AGENTS.md §5.

AGENTS.md와 CLAUDE.md는 매 세션 소비된다. 비대해지면 정보 이득 없이 비용만 늘어난다.
정확한 토크나이저 대신 근사치를 쓴다. 예산 위반 여부만 판정하면 되므로 충분하다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BUDGET = 3000
TARGETS = ("AGENTS.md", "CLAUDE.md")


def estimate_tokens(text: str) -> int:
    """한글은 문자당 약 1.1토큰, 그 외(ASCII·기호)는 약 0.28토큰으로 추정한다."""
    korean = len(re.findall(r"[가-힣]", text))
    return round(korean * 1.1 + (len(text) - korean) * 0.28)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    total = 0
    lines = []
    for name in TARGETS:
        path = root / name
        if not path.exists():
            lines.append(f"  {name:<12} 없음")
            continue
        tokens = estimate_tokens(path.read_text(encoding="utf-8"))
        total += tokens
        lines.append(f"  {name:<12} {tokens:>5} 토큰")
    lines.append(f"  {'합계':<12} {total:>5} / {BUDGET}")

    if total > BUDGET:
        print("\n".join(lines), file=sys.stderr)
        print(
            f"\n  하네스 문서가 예산을 {total - BUDGET} 토큰 초과했습니다 (AGENTS.md §5).\n"
            "  상세는 docs/ 로 옮기고 여기에는 포인터만 둡니다.",
            file=sys.stderr,
        )
        return 1
    if "--verbose" in sys.argv:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
