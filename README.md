# news-tls-agent

[![backend](https://github.com/minjun069/news-tls-agent/actions/workflows/backend.yml/badge.svg)](https://github.com/minjun069/news-tls-agent/actions/workflows/backend.yml)
[![web](https://github.com/minjun069/news-tls-agent/actions/workflows/web.yml/badge.svg)](https://github.com/minjun069/news-tls-agent/actions/workflows/web.yml)
[![release-images](https://github.com/minjun069/news-tls-agent/actions/workflows/release.yml/badge.svg)](https://github.com/minjun069/news-tls-agent/actions/workflows/release.yml)

뉴스 아카이브를 사건 단위 타임라인으로 조직하고, 각 분기점에 근거 기사를 귀속해 조회·대화·
지식 그래프·PDF/Notion 내보내기로 이어 주는 프로젝트다. 학습 목표인 MCP, MS-SQL, Qdrant,
AI 에이전트를 실제 서비스 경계로 사용한다.

- 제품 범위: [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md)
- 아키텍처와 실행 모드: [`docs/architecture/overview.md`](docs/architecture/overview.md)
- 스프린트 상태: [`docs/engineering/roadmap.md`](docs/engineering/roadmap.md)
- 작업 규칙: [`AGENTS.md`](AGENTS.md)

## 아키텍처

```text
Vue 3 web
    │ REST + SSE
    ▼
FastAPI api ── stdio MCP client
                    │ 요청별 MCP 자식 프로세스
                    ▼
              MCPServer v2
                 │       │
                 ▼       ▼
              MS-SQL   Qdrant
```

프론트엔드는 API만 호출하고, 에이전트의 조회·검색·내보내기는 MCP 서버를 통과한다. API가 MCP에
연결할 수 없을 때 저장소를 직접 조회하는 우회 경로는 없다. 전체 계층 규칙은 import-linter가
검사한다.

## 요구 환경

전체 컨테이너 모드에는 Docker Engine과 Docker Compose v2가 필요하다. 개발 모드는 추가로
Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 22.19 이상, Microsoft ODBC Driver 18,
네이티브 SQL Server Developer Edition을 사용한다.

비밀값은 저장소에 넣지 않고 루트 `.env`에만 둔다. 시작 전에 예시 파일을 복사하고 최소한
`GOOGLE_API_KEY`, `MSSQL_PASSWORD`를 채운다. SQL Server의 `sa` 정책을 통과하는 강한 암호를
사용해야 한다.

```bash
cp .env.example .env
```

## 클린 클론 기동 — 모드 B

`.env` 설정 뒤 다음 한 줄이 MS-SQL, Qdrant, 마이그레이션, API, 독립 MCP 진입점, 웹을 모두
준비한다. 마이그레이션 컨테이너가 성공 종료한 뒤 API/MCP가 시작되고, 웹은 API 헬스 통과 뒤
시작한다.

```bash
docker compose --profile full up -d
```

상태와 로그를 확인한다.

```bash
docker compose --profile full ps
docker compose --profile full logs migrate api mcp web
curl http://localhost:8000/health
```

- 웹: `http://localhost:5173`
- Swagger UI: `http://localhost:8000/docs`
- Qdrant 대시보드: `http://localhost:6333/dashboard`

중지는 `docker compose --profile full down`이다. 데이터 볼륨까지 지우는 `down -v`는 MS-SQL과
Qdrant 데이터를 삭제하므로 이 README의 일반 종료 명령에 포함하지 않는다.

## 개발 실행 — 모드 A

모드 A에서는 앱을 WSL 로컬 프로세스로 실행하고 Qdrant만 컨테이너로 띄운다. MS-SQL은
[ADR-0002](docs/decisions/0002-mssql-native-qdrant-container.md)에 따라 Windows 네이티브
설치를 사용한다.

```bash
make install
make web-install
docker compose up -d
make migrate
make api
```

다른 터미널에서 웹을 실행한다.

```bash
make web
```

WSL에서 `MSSQL_HOST`가 비어 있으면 기본 게이트웨이를 Windows 호스트 주소로 해석한다. 고정
주소가 필요할 때만 `.env`에 직접 지정한다.

MCP 서버는 `.mcp.json`에 등록되어 있다. 다음 명령은 stdio 서버의 다섯 도구와 입력 스키마를
검사한다.

```bash
make mcp-inspect
```

## 데이터 적재 상태

서비스 기동과 뉴스 적재는 별도다. 현재 저장소에는 실제 원본 `news.jsonl` 필드
(`article_title`, `article_service_daytime`, `text` 등)을 정규화 필드로 바꾸는 S2 매핑과
`scripts/03_build_vectors.py`가 아직 완료되지 않았다. 따라서 S9 E2E는 고정 기사 픽스처로 제품
흐름을 검증하지만 실제 원본 적재 완료를 의미하지 않는다.

완료된 뒤의 정식 순서는 다음과 같다.

```text
data/raw/*.jsonl
  → scripts/01_extract_seed.py
  → scripts/02_load_mssql.py
  → scripts/03_build_vectors.py
```

현 상태와 입력·제외·정합성 계약은
[`docs/data/source-and-ingestion.md`](docs/data/source-and-ingestion.md) 및
[`docs/engineering/roadmap.md`](docs/engineering/roadmap.md)의 S2·S3 체크리스트를 기준으로 한다.
없는 스크립트를 실행 가능한 절차로 제시하지 않는다.

## 검증

```bash
make check             # ruff · import-linter · 단위/API 조립 · 문서 동기화
make web-check         # Vue 타입 검사 · 프로덕션 빌드
make test-integration  # 실제 MS-SQL · Qdrant
make test-e2e          # 생성 → 조회 → 근거 → 대화 → 그래프 → PDF
make compose-check     # 전체 Compose 해석
make images            # api · mcp · web 이미지 빌드
```

`make test-integration`은 실행 가능한 MS-SQL과 Qdrant가 필요하다. E2E는 외부 Gemini·Notion
계정 없이 재현되도록 외부 응답만 고정하고 실제 파이프라인, MCP payload, 그래프, 공용 내보내기
유스케이스를 연결한다. CI에서는 이 둘을 별도 잡으로 모두 실행한다.

## 이미지 게시

`v*` 태그를 push하면 `release-images` 워크플로가 다음 이미지를 GHCR에 게시한다.

```text
ghcr.io/minjun069/news-tls-agent-api:<tag>
ghcr.io/minjun069/news-tls-agent-mcp-server:<tag>
```

실제 서버 배포는 프로젝트 범위 밖이다. API/MCP 이미지 경계와 stdio 배치는
[ADR-0007](docs/decisions/0007-stdio-mcp-container-packaging.md)을 따른다.
