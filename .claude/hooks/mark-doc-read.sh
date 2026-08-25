#!/usr/bin/env bash
# PostToolUse — 계약 문서를 읽었다는 사실을 세션 단위로 기록한다.
# require-doc.sh 가 이 마커를 보고 편집을 통과시킨다.
#
# 사용: mark-doc-read.sh docs/ERD.md
#
# 마커는 .claude/.state/<session_id>/ 아래에 남고 Git에서 제외된다.
# 세션이 바뀌면 다시 읽어야 한다 — 컨텍스트가 새로 시작하므로 그것이 맞다.

set -uo pipefail

DOC="${1:-}"
[ -n "$DOC" ] || exit 0

payload="$(cat 2>/dev/null || true)"
sid="$(printf '%s' "$payload" | tr -d '\n' \
  | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
[ -n "$sid" ] || exit 0

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 0
dir="$ROOT/.claude/.state/$sid"
mkdir -p "$dir" 2>/dev/null || exit 0
: > "$dir/$(printf '%s' "$DOC" | tr '/' '_')" 2>/dev/null || exit 0
exit 0
