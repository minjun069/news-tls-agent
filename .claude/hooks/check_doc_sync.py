#!/usr/bin/env python3
"""문서 동반 변경 검사 — AGENTS.md §5 · §7 · docs/FEEDBACK_LOOPS.md L5.

계약을 가진 코드가 바뀌었는데 그 계약 문서가 안 바뀌면 실패한다.
문서가 낡으면 그 문서를 읽히는 라우팅이 오히려 해롭기 때문에,
라우팅(.claude/hooks/require-doc.sh)의 전제 조건으로 이 검사가 먼저 있어야 한다.

기본 비교 대상:
  브랜치 작업 중이면 main과의 분기점 이후 전체 (AGENTS.md §6 — PR 단위)
  main 위면 HEAD (아직 커밋 안 된 변경)
어느 쪽이든 스테이징·미스테이징·미추적 변경을 모두 포함한다.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAP_FILE = ROOT / ".claude" / "doc-map.json"
SETTINGS = ROOT / ".claude" / "settings.json"
MAIN = "main"


def load_map() -> dict[str, list[str]]:
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return data["map"]


def git(*args: str) -> list[str]:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def compare_base() -> str | None:
    """main과의 분기점. main 위이거나 구할 수 없으면 None."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch[0] == MAIN:
        return None
    base = git("merge-base", MAIN, "HEAD")
    return base[0] if base else None


def changed_files(base: str | None) -> set[str]:
    files: set[str] = set()
    if base:
        files |= set(git("diff", "--name-only", f"{base}..HEAD"))
    files |= set(git("diff", "--name-only", "HEAD"))  # 스테이징 + 미스테이징
    files |= set(git("ls-files", "--others", "--exclude-standard"))  # 미추적
    return files


def to_regex(pattern: str) -> re.Pattern[str]:
    """glob → 정규식. `**`는 경로 구분자를 넘고 `*`는 넘지 않는다."""
    out = []
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


def _handlers(event: str) -> list[tuple[str, str, str]]:
    """settings.json에서 (툴, 경로패턴, 명령의 마지막 인자) 목록을 뽑는다."""
    if not SETTINGS.exists():
        return []
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    out = []
    for entry in settings.get("hooks", {}).get(event, []):
        for handler in entry.get("hooks", []):
            cond = handler.get("if")
            cmd = handler.get("command", "")
            if not cond:
                continue
            m = re.match(r"^(\w+)\((.+)\)$", cond)
            if m:
                out.append((m.group(1), m.group(2).lstrip("/"), cmd.split()[-1] if cmd else ""))
    return out


def validate_settings(doc_map: dict[str, list[str]]) -> list[str]:
    """doc-map.json과 settings.json이 어긋나지 않는지 확인한다.

    어긋나면 게이트가 조용히 발화하지 않는다 — 가장 나쁜 실패 방식이다.
    두 방향을 모두 본다:
      1. 모든 코드 경로에 PreToolUse 차단이 걸려 있는가
      2. 모든 계약 문서에 PostToolUse 마커가 걸려 있는가
         (2가 빠지면 읽어도 마커가 안 남아 영구히 막힌다)
    """
    if not SETTINGS.exists():
        return ["  .claude/settings.json 이 없습니다"]

    gates = {(p, doc) for _tool, p, doc in _handlers("PreToolUse")}
    markers = {doc for _tool, _p, doc in _handlers("PostToolUse")}

    problems = []
    for doc, patterns in doc_map.items():
        for pattern in patterns:
            if (pattern, doc) not in gates:
                problems.append(f"  차단 없음: {pattern:<32} → {doc}")
        if doc not in markers:
            problems.append(f"  마커 없음: {doc} — 읽어도 통과되지 않아 영구히 막힙니다")
    return problems


def main() -> int:
    doc_map = load_map()

    if "--validate-settings" in sys.argv:
        problems = validate_settings(doc_map)
        if problems:
            print("[doc-sync] doc-map.json과 settings.json이 어긋납니다:", file=sys.stderr)
            print("\n".join(problems), file=sys.stderr)
            return 1
        print("doc-map.json ↔ settings.json 일치")
        return 0

    base = compare_base()
    files = changed_files(base)
    if not files:
        return 0

    stale: list[tuple[str, str, list[str]]] = []
    for doc, patterns in doc_map.items():
        if doc in files:
            continue
        hits = [f for f in sorted(files) for p in patterns if to_regex(p).match(f)]
        if hits:
            stale.append((doc, ", ".join(patterns), hits))

    if not stale:
        if "--verbose" in sys.argv:
            scope = f"{base[:8]}..HEAD + 작업 트리" if base else "HEAD + 작업 트리"
            print(f"문서 동기화 OK — 비교 범위 {scope}, 변경 {len(files)}개")
        return 0

    print("[doc-sync] 계약 문서가 함께 갱신되지 않았습니다 (AGENTS.md §5 · §7)", file=sys.stderr)
    for doc, _patterns, hits in stale:
        print(f"\n  {doc} 를 갱신해야 합니다. 바뀐 파일:", file=sys.stderr)
        for h in hits[:8]:
            print(f"    - {h}", file=sys.stderr)
        if len(hits) > 8:
            print(f"    … 외 {len(hits) - 8}개", file=sys.stderr)
    print(
        "\n  계약이 실제로 바뀌지 않았더라도, 문서 쪽에 무엇이 그대로인지 적어 두면\n"
        "  다음 세션이 같은 판단을 다시 하지 않습니다.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
