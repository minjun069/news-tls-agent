#!/usr/bin/env python3
"""저장소 Markdown의 상대 링크가 실제 대상을 가리키는지 검사한다."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def target_path(source: Path, raw: str) -> Path | None:
    value = raw.strip().strip("<>")
    if not value or value.startswith(SKIP_PREFIXES):
        return None
    value = unquote(value.split("#", 1)[0].split("?", 1)[0])
    if not value:
        return None
    return (source.parent / value).resolve()


def main() -> int:
    problems: list[str] = []
    sources = [ROOT / "AGENTS.md", ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    for source in sources:
        if not source.is_file():
            continue
        for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            for raw in LINK.findall(line):
                target = target_path(source, raw)
                if target is not None and not target.exists():
                    relative = source.relative_to(ROOT)
                    problems.append(f"{relative}:{line_no} -> {raw}")
    if problems:
        print("[markdown-links] 존재하지 않는 상대 링크")
        print("\n".join(f"  - {item}" for item in problems))
        return 1
    print("Markdown 상대 링크 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
