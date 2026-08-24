# news-tls-agent — 진입점
# 각 검사가 무엇을 잡는지는 docs/FEEDBACK_LOOPS.md
# 규칙 원본은 AGENTS.md. 여기는 그 규칙을 실행하는 곳이다.
#
# backend/ 가 소스 루트이자 uv 프로젝트다. 파이썬 관련 명령은 그 안에서 돈다.

BE := backend

.PHONY: help install check fmt lint arch test test-all up up-full down migrate mcp-inspect web-check

help:
	@echo "install    .venv 생성 (uv)"
	@echo "check      커밋 전 게이트 — 린트 · 계층 · 단위테스트"
	@echo "fmt        포맷 + 자동 수정"
	@echo "arch       계층 규칙만 (AGENTS.md §1 · §2.1)"
	@echo "test-all   통합 포함 (MS-SQL · Qdrant 필요)"
	@echo "up         개발: qdrant만"
	@echo "up-full    클린 클론 검증 · 데모 (NFR-13)"
	@echo "migrate    미적용 마이그레이션만 실행"

install:
	cd $(BE) && uv sync

check: lint arch test

fmt:
	cd $(BE) && uv run ruff format .
	cd $(BE) && uv run ruff check --fix .

lint:
	cd $(BE) && uv run ruff check .
	cd $(BE) && uv run ruff format --check .

arch:
	cd $(BE) && uv run lint-imports

# pytest는 테스트가 없으면 exit 5를 반환한다. 스켈레톤 단계에서는 실패로 보지 않는다.
test:
	@cd $(BE) && uv run pytest tests/unit || [ $$? -eq 5 ]

test-all:
	cd $(BE) && uv run pytest tests

up:
	docker compose up -d

up-full:
	docker compose --profile full up -d

down:
	docker compose --profile full down

migrate:
	bash $(BE)/db/migrate.sh

mcp-inspect:
	cd $(BE) && npx @modelcontextprotocol/inspector uv run python mcp_server/server.py

web-check:
	cd web && npx vue-tsc --noEmit && npm run build
