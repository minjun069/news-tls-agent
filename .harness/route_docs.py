#!/usr/bin/env python3
"""변경 경로에 대응하는 계약 문서를 찾는다.

CLI에서는 작업 전 문서 선택에, Codex PreToolUse 훅에서는 편집 직전 알림에 쓴다.
라우팅의 단일 원천은 .harness/doc-routes.json이다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_FILE = ROOT / ".harness" / "doc-routes.json"
PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)


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
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return data["routes"]


def normalize_path(raw: str) -> str:
    path = raw.strip().replace("\\", "/")
    root = ROOT.as_posix().rstrip("/")
    if path.startswith(f"{root}/"):
        return path[len(root) + 1 :]
    return path.lstrip("./")


def docs_for(paths: list[str]) -> list[str]:
    normalized = [normalize_path(path) for path in paths]
    docs: list[str] = []
    for route in load_routes():
        patterns = [to_regex(item) for item in route["paths"]]
        if any(pattern.match(path) for pattern in patterns for path in normalized):
            for doc in route["docs"]:
                if doc not in docs:
                    docs.append(doc)
    return docs


def hook_paths(payload: dict[str, object]) -> list[str]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    command = tool_input.get("command", "")
    if not isinstance(command, str):
        return []
    return PATCH_PATH.findall(command)


def run_hook() -> int:
    try:
        payload = json.load(sys.stdin)
        docs = docs_for(hook_paths(payload))
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return 0
    if not docs:
        return 0
    joined = "\n".join(f"- {doc}" for doc in docs)
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                "이 변경의 계약 문서입니다. AGENTS.md §4 흐름과 함께 실제 내용을 "
                f"확인하고, 계약이 바뀌면 같은 변경에서 갱신하세요:\n{joined}"
            ),
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--hook", action="store_true")
    args = parser.parse_args()
    if args.hook:
        return run_hook()
    if not args.paths:
        parser.error("확인할 경로를 하나 이상 입력하세요")
    docs = docs_for(args.paths)
    if docs:
        print("\n".join(docs))
    else:
        print("추가 계약 문서 없음 — AGENTS.md §4의 작업 흐름을 따르세요")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
