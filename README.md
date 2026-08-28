# news-tls-agent

뉴스 아카이브를 근거로 사건 타임라인을 만들고, 각 분기점에 근거 기사를 귀속시켜 신뢰 가능한 형태로 제공한다.

- 무엇을 만드는가 → [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md)
- 어떻게 만드는가 → [`docs/architecture/overview.md`](docs/architecture/overview.md)
- 작업 규칙 → [`AGENTS.md`](AGENTS.md)

---

## 구조

```
web/       Vue 3 + Vite
  ↓ REST + SSE
backend/api/         에이전트 오케스트레이션 · MCP 클라이언트
  ↓ MCP (stdio)
backend/mcp_server/  데이터 접근 계약 · 감사 지점 (LLM 호출 없음)
  ↓
MS-SQL (기사·이슈)   Qdrant (임베딩)
```

**에이전트는 저장소에 직접 접근하지 않는다.** 모든 데이터 접근은 MCP 서버를 경유한다 ([ADR-0001](docs/decisions/0001-mcp-data-access.md)).

## 실행 모드

| 모드 | 앱 | 저장소 | 용도 |
|---|---|---|---|
| A. 개발 | 로컬 프로세스 | MS-SQL 네이티브 + Qdrant 컨테이너 | 핫리로드 |
| B. 전체 컨테이너 | 컨테이너 | 전부 컨테이너 | 클린 클론 검증 · 데모 |
| C. CI | 러너 | 서비스 컨테이너 | 통합 테스트 |

상세는 [`docs/architecture/overview.md`](docs/architecture/overview.md) §4.

## 시작하기

### 모드 B — 클린 클론 (NFR-13)

```bash
cp .env.example .env      # 값을 채운다
docker compose --profile full up -d
```

### 모드 A — 개발

```bash
make install              # .venv 생성 (uv)
cp .env.example .env
docker compose up -d      # qdrant만
make migrate              # 미적용 마이그레이션 실행
make check                # 린트 · 계층 규칙 · 단위 테스트
```

MS-SQL은 네이티브로 설치한다 ([ADR-0002](docs/decisions/0002-mssql-native-qdrant-container.md)).
WSL 개발에서는 `MSSQL_HOST`를 비워두면 실행 시 Windows 호스트 주소를 자동 해석한다.
고정 주소가 필요한 경우에만 값을 지정한다. 상세는 `.env.example` 주석을 따른다.

## 데이터

원본 뉴스 데이터는 저장소에 포함되지 않는다. `data/raw/`에 직접 투입한다.

```bash
cd backend
uv run python scripts/01_extract_seed.py
uv run python scripts/02_load_mssql.py
uv run python scripts/03_build_vectors.py
```

적재 순서와 제외 기준은 [`docs/data/source-and-ingestion.md`](docs/data/source-and-ingestion.md).

## 검증

```bash
make check      # 커밋 전 게이트
make arch       # 계층 규칙만
make test-all   # 통합 포함
```

계층 규칙은 문서가 아니라 `pyproject.toml`의 import-linter 계약으로 강제된다.
각 검사가 무엇을 잡는지는 [`docs/engineering/agent-workflow.md`](docs/engineering/agent-workflow.md).

## 진행 상황

[`docs/engineering/roadmap.md`](docs/engineering/roadmap.md) — 현재 **S2 데이터 계층**.
