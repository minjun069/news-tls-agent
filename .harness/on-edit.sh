#!/usr/bin/env bash
# Codex PostToolUse — backend 편집 직후 빠른 정적 검사만 수행한다.
set -uo pipefail

payload="$(cat 2>/dev/null || true)"
case "$payload" in
  *"backend/"* | *"backend\\"*) ;;
  *) exit 0 ;;
esac

root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
backend="$root/backend"
command -v uv >/dev/null 2>&1 || exit 0
[ -x "$backend/.venv/bin/ruff" ] || exit 0

problems=""
add() { problems="${problems}$1"$'\n'; }

if ! out=$(cd "$backend" && uv run --quiet ruff check . 2>&1); then
  add "[ruff] 코드 컨벤션 위반"
  add "$out"
fi
if ! out=$(cd "$backend" && uv run --quiet ruff format --check . 2>&1); then
  add "[format] make fmt가 필요합니다"
  add "$out"
fi
if ! out=$(cd "$backend" && uv run --quiet lint-imports 2>&1); then
  add "[import-linter] 아키텍처 경계 위반"
  add "$out"
fi

if [ -n "$problems" ]; then
  printf '%s\n' "$problems" >&2
  exit 2
fi
