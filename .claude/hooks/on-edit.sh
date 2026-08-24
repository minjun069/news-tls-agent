#!/usr/bin/env bash
# 편집 직후 검사 — AGENTS.md §4 · docs/FEEDBACK_LOOPS.md L1·L4
#
# 커밋 전(make check)과 같은 검사를 편집 시점에 돌려 위반을 즉시 알린다.
# 위반이 있으면 exit 2로 알려 편집자가 바로 되돌리게 한다.
#
# 원칙: 환경 문제로는 절대 막지 않는다. 실제 규칙 위반일 때만 막는다.
set -uo pipefail

# .venv는 WSL(리눅스)에서 만들어진다. Windows 셸에서는 실행할 수 없다.
case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*) exit 0 ;;
esac

cd "$(dirname "$0")/../.." || exit 0
command -v uv >/dev/null 2>&1 || exit 0
[ -x .venv/bin/ruff ] || exit 0   # 아직 make install 전이면 통과

problems=""
add() { problems="${problems}$1"$'\n'; }

# L1 — 포맷은 자동 수정한다
uv run --quiet ruff format . >/dev/null 2>&1 || true

# L1 — 린트 (AGENTS.md §3)
if ! out=$(uv run --quiet ruff check . 2>&1); then
  add "[ruff] AGENTS.md §3 위반"
  add "$out"
fi

# L2 — 계층 규칙 (AGENTS.md §1 · §2.1)
if ! out=$(uv run --quiet lint-imports 2>&1); then
  add "[import-linter] AGENTS.md §2.1 계층 규칙 위반"
  add "$out"
fi

# L4 — 하네스 문서 토큰 예산 (AGENTS.md §5)
if ! out=$(uv run --quiet python .claude/hooks/check_doc_budget.py 2>&1); then
  add "[budget] $out"
fi

if [ -n "$problems" ]; then
  printf '%s\n' "$problems" >&2
  exit 2
fi
exit 0
