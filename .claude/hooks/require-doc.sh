#!/usr/bin/env bash
# PreToolUse — 계약 문서를 읽기 전에는 그 계약이 지배하는 코드를 편집할 수 없다.
#
# AGENTS.md §5의 "정보 → 단일 원천" 표를 경로 기준으로 강제한다.
# 어느 경로가 어느 문서에 묶이는지는 .claude/doc-map.json 과 settings.json 의 if 필터에 있다.
#
# 사용: require-doc.sh docs/ERD.md
#
# 원칙 (on-edit.sh와 동일): 환경 문제로는 절대 막지 않는다.
# 세션을 식별할 수 없거나 마커를 쓸 수 없으면 통과시킨다.
# 막는 경우는 "문서가 있는데 이번 세션에 안 읽었다" 하나뿐이다.

set -uo pipefail

DOC="${1:-}"
[ -n "$DOC" ] || exit 0

payload="$(cat 2>/dev/null || true)"
sid="$(printf '%s' "$payload" | tr -d '\n' \
  | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
[ -n "$sid" ] || exit 0   # 세션 식별 불가 — 막지 않는다

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 0
[ -f "$ROOT/$DOC" ] || exit 0   # 문서가 아직 없으면 요구하지 않는다

marker="$ROOT/.claude/.state/$sid/$(printf '%s' "$DOC" | tr '/' '_')"
[ -f "$marker" ] && exit 0

cat >&2 <<MSG
[doc-routing] 이 파일의 계약 문서는 ${DOC} 입니다 (AGENTS.md §5).

편집 전에 Read 도구로 ${DOC} 를 읽으십시오. 읽은 뒤 같은 편집을 다시 시도하면 통과합니다.
세션당 문서마다 한 번만 요구합니다.

문서 내용이 코드와 다르면, 고칠 쪽을 먼저 정하십시오 —
코드를 문서에 맞출지, 문서를 갱신할지. 둘 다 안 하고 진행하지 않습니다.
MSG
exit 2
