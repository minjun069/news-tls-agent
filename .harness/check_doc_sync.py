#!/usr/bin/env python3
"""계약을 가진 코드와 문서의 동반 변경을 검사한다."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_FILE = ROOT / ".harness" / "doc-routes.json"


def git(*args: str) -> list[str]:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def main_ref() -> str | None:
    for candidate in ("main", "origin/main"):
        if git("rev-parse", "--verify", candidate):
            return candidate
    return None


def compare_base() -> str | None:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    ref = main_ref()
    if not branch or not ref or branch[0] == "main":
        return None
    base = git("merge-base", ref, "HEAD")
    return base[0] if base else None


def changed_files(base: str | None) -> set[str]:
    files: set[str] = set()
    if base:
        files.update(git("diff", "--name-only", f"{base}..HEAD"))
    files.update(git("diff", "--name-only", "HEAD"))
    files.update(git("ls-files", "--others", "--exclude-standard"))
    return files


def to_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile(f"^{''.join(out)}$")


def load_routes() -> list[dict[str, object]]:
    return json.loads(MAP_FILE.read_text(encoding="utf-8"))["routes"]


def validate_map() -> list[str]:
    problems: list[str] = []
    for route in load_routes():
        name = route.get("name", "이름 없음")
        paths = route.get("paths", [])
        docs = route.get("docs", [])
        if not paths or not docs:
            problems.append(f"{name}: paths 또는 docs가 비어 있습니다")
        for doc in docs:
            if not (ROOT / doc).is_file():
                problems.append(f"{name}: 문서 없음 — {doc}")
    return problems


def main() -> int:
    if "--validate-map" in sys.argv:
        problems = validate_map()
        if problems:
            print("[doc-map] 라우팅 오류", file=sys.stderr)
            print("\n".join(f"  - {item}" for item in problems), file=sys.stderr)
            return 1
        print("doc-routes.json 유효")
        return 0

    base = compare_base()
    files = changed_files(base)
    stale: list[tuple[str, list[str]]] = []
    for route in load_routes():
        docs = route["docs"]
        patterns = [to_regex(item) for item in route["paths"]]
        hits = sorted(file for file in files if any(p.match(file) for p in patterns))
        if hits and not all(doc in files for doc in docs):
            stale.append((", ".join(docs), hits))

    if stale:
        print("[doc-sync] 계약 문서가 함께 갱신되지 않았습니다", file=sys.stderr)
        for docs, hits in stale:
            print(f"\n  필요한 문서: {docs}", file=sys.stderr)
            for hit in hits[:8]:
                print(f"    - {hit}", file=sys.stderr)
        return 1

    if "--verbose" in sys.argv:
        scope = f"{base[:8]}..HEAD + 작업 트리" if base else "HEAD + 작업 트리"
        print(f"문서 동기화 OK — {scope}, 변경 {len(files)}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
