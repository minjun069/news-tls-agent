#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
backend_dir="$(dirname "$script_dir")"

cd "$backend_dir"
exec uv run python -m db.migrate
