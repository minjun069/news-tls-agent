# news-tls-agent — 실행과 검증의 단일 진입점
# 상세: docs/engineering/validation.md

BE := backend
WEB := web
NPM ?= npm

.PHONY: help install web-install check fmt lint arch test test-integration test-e2e test-all doc-sync doc-ack docs-for agent-budget benchmark-embeddings ai-smoke compose-check images up up-full down migrate mcp-inspect api web web-check

help:
	@echo "install       backend .venv 생성 (uv)"
	@echo "check         커밋 전 게이트 — lint · arch · unit · docs"
	@echo "fmt           Python 포맷 + 자동 수정"
	@echo "arch          계층 의존 계약"
	@echo "doc-sync      계약 문서 동반 변경 + Markdown 링크"
	@echo "doc-ack       REASON='근거'로 계약 변경 없음 검토 기록"
	@echo "docs-for      PATHS='경로 ...'에 필요한 계약 문서 출력"
	@echo "agent-budget  AGENTS.md 현재 크기 보고(강제 기준 없음)"
	@echo "benchmark-embeddings  MODEL='모델 ID' 실제 뉴스 CPU 임베딩 표본 측정"
	@echo "ai-smoke      현재 Gemini 모델의 구조화 출력 · 함수 호출 실제 점검"
	@echo "test-all      MS-SQL · Qdrant 포함 통합 테스트"
	@echo "test-integration  실제 MS-SQL · Qdrant 통합 테스트"
	@echo "test-e2e      생성부터 그래프·내보내기까지 사용자 흐름"
	@echo "compose-check 전체 컨테이너 구성 문법 검사"
	@echo "images        api · mcp · web 컨테이너 이미지 빌드"
	@echo "up            개발 인프라: qdrant"
	@echo "up-full       클린 클론 · 데모 전체 컨테이너"
	@echo "migrate       미적용 MS-SQL 마이그레이션 실행"
	@echo "api           FastAPI 개발 서버 기동"
	@echo "web-install   프론트엔드 의존성 설치 (npm ci)"
	@echo "web           Vue 개발 서버 기동"
	@echo "web-check     Vue 타입 검사 + 프로덕션 빌드"

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
	@cd $(BE) && uv run pytest tests/unit tests/integration/test_api.py || [ $$? -eq 5 ]

test-integration:
	cd $(BE) && uv run pytest tests/integration

test-e2e:
	cd $(BE) && uv run pytest tests/e2e

test-all:
	cd $(BE) && uv run pytest tests

doc-sync:
	@python3 .harness/check_doc_sync.py --validate-map > /dev/null
	@python3 .harness/check_doc_sync.py
	@python3 .harness/check_markdown_links.py

doc-ack:
	@test -n "$(REASON)" || (echo "REASON에 계약이 유지되는 구체적 근거를 입력하세요" >&2; exit 2)
	@python3 .harness/check_doc_sync.py --acknowledge-no-contract-change "$(REASON)"

docs-for:
	@python3 .harness/route_docs.py $(PATHS)

agent-budget:
	@python3 .harness/report_agent_budget.py

benchmark-embeddings:
	cd $(BE) && uv run python -m scripts.benchmark_local_embeddings "$(MODEL)" ../data/raw/news.jsonl

ai-smoke:
	cd $(BE) && uv run python -m scripts.ai_smoke

compose-check:
	docker compose --profile full config --quiet

images:
	docker compose --profile full build api mcp web

up:
	docker compose up -d

up-full:
	docker compose --profile full up -d

down:
	docker compose --profile full down

migrate:
	bash $(BE)/db/migrate.sh

mcp-inspect:
	npx @modelcontextprotocol/inspector@2.5.0 --cli --config .mcp.json --server news-tls-agent --method tools/list --strict

api:
	cd $(BE) && uv run uvicorn api.main:app --reload

web-install:
	cd $(WEB) && $(NPM) ci

web:
	cd $(WEB) && $(NPM) run dev

web-check:
	cd $(WEB) && $(NPM) run type-check && $(NPM) run build
