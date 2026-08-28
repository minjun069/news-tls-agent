# news-tls-agent — 실행과 검증의 단일 진입점
# 상세: docs/engineering/validation.md

BE := backend

.PHONY: help install check fmt lint arch test test-all doc-sync docs-for agent-budget up up-full down migrate mcp-inspect web-check

help:
	@echo "install       backend .venv 생성 (uv)"
	@echo "check         커밋 전 게이트 — lint · arch · unit · docs"
	@echo "fmt           Python 포맷 + 자동 수정"
	@echo "arch          계층 의존 계약"
	@echo "doc-sync      계약 문서 동반 변경 + Markdown 링크"
	@echo "docs-for      PATHS='경로 ...'에 필요한 계약 문서 출력"
	@echo "agent-budget  AGENTS.md 현재 크기 보고(강제 기준 없음)"
	@echo "test-all      MS-SQL · Qdrant 포함 통합 테스트"
	@echo "up            개발 인프라: qdrant"
	@echo "up-full       클린 클론 · 데모 전체 컨테이너"
	@echo "migrate       미적용 MS-SQL 마이그레이션 실행"

install:
	cd $(BE) && uv sync

check: lint arch test doc-sync

fmt:
	cd $(BE) && uv run ruff format .
	cd $(BE) && uv run ruff check --fix .

lint:
	cd $(BE) && uv run ruff check .
	cd $(BE) && uv run ruff format --check .

arch:
	cd $(BE) && uv run lint-imports

test:
	@cd $(BE) && uv run pytest tests/unit || [ $$? -eq 5 ]

test-all:
	cd $(BE) && uv run pytest tests

doc-sync:
	@python3 .harness/check_doc_sync.py --validate-map > /dev/null
	@python3 .harness/check_doc_sync.py
	@python3 .harness/check_markdown_links.py

docs-for:
	@python3 .harness/route_docs.py $(PATHS)

agent-budget:
	@python3 .harness/report_agent_budget.py

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
