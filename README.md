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
시작한다. Windows 네이티브 SQL Server가 호스트의 1433 포트를 사용 중이면 먼저 중지해야 한다.

최소한 아래 값을 루트 `.env`에 설정한다. 컨테이너 내부의 MS-SQL 사용자·호스트와 Qdrant
호스트는 Compose가 각각 `sa`·`mssql`·`qdrant`로 덮어쓴다.

```dotenv
GOOGLE_API_KEY=발급받은_Gemini_API_키
MSSQL_PASSWORD=SQL_Server_정책을_통과하는_강한_암호
EMBEDDING_PROVIDER=local
QDRANT_COLLECTION=articles_kure_v1
```

```bash
make up-full
```

Dockerfile이나 의존성을 바꾼 뒤에는 새 이미지를 만들며 기동한다.

```bash
docker compose --profile full up -d --build
```

상태와 로그를 확인한다.

```bash
docker compose --profile full ps
docker compose --profile full logs --tail=100 migrate api mcp web
curl --fail http://localhost:8000/health
```

`mssql`, `qdrant`, `api`, `web`은 `running` 또는 `healthy`, `migrate`는 종료 코드 0이어야 한다.
헬스 응답의 `mssql`, `qdrant`, `mcp_server`도 모두 `ok`여야 준비가 끝난 것이다.

- 웹: `http://localhost:5173`
- Swagger UI: `http://localhost:8000/docs`
- Qdrant 대시보드: `http://localhost:6333/dashboard`

전체 컨테이너 모드의 MS-SQL은 Windows 네이티브 MS-SQL과 다른 저장소다. 새 Docker 볼륨에는
스키마만 있고 뉴스 기사는 자동 적재되지 않으므로, 실제 데이터가 필요하면 서비스를 기동한 뒤
`.env`의 `MSSQL_HOST=localhost`, `MSSQL_USER=sa`, `QDRANT_URL=http://localhost:6333`을 사용해
아래의 `scripts/01~03` 적재 절차를 실행한다.

중지는 `docker compose --profile full down`이다. 데이터 볼륨까지 지우는 `down -v`는 MS-SQL,
Qdrant, 모델 캐시를 삭제하므로 이 README의 일반 종료 명령에 포함하지 않는다.

## 개발 실행 — 모드 A

모드 A에서는 앱을 WSL 로컬 프로세스로 실행하고 Qdrant만 컨테이너로 띄운다. MS-SQL은
[ADR-0002](docs/decisions/0002-mssql-native-qdrant-container.md)에 따라 Windows 네이티브
설치를 사용한다. 현재 네이티브 MS-SQL과 Qdrant에 적재된 실제 뉴스 데이터를 그대로 쓰려면
이 모드가 적합하다.

먼저 `node`와 `npm`이 `/mnt/c/Program Files/nodejs`가 아니라 WSL 내부의 Linux 실행 파일인지
확인한다. Node.js는 22.19 이상이어야 한다.

```bash
command -v node npm
node --version
npm --version
```

Windows에서 SQL Server 서비스를 시작하고 루트 `.env`를 모드 A 값으로 둔 다음 의존성과
저장소를 준비한다.

```dotenv
GOOGLE_API_KEY=발급받은_Gemini_API_키
MSSQL_HOST=
MSSQL_USER=sa
MSSQL_PASSWORD=Windows_SQL_Server의_sa_암호
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=articles_kure_v1
EMBEDDING_PROVIDER=local
```

`MSSQL_HOST`를 비우면 실행 시 WSL 기본 게이트웨이를 Windows 호스트 주소로 해석한다.

```bash
make install
make web-install
docker compose up -d
make migrate
```

최초 적재 또는 원본 갱신 시 전체 원본을 검증한 뒤 MS-SQL에 직접 적재한다.

```bash
cd backend
uv run python -m scripts.01_validate_raw ../data/raw/news.jsonl
uv run python -m scripts.02_load_mssql ../data/raw/news.jsonl --batch-size 200
uv run python -m scripts.03_build_vectors ../data/raw/news.jsonl --batch-size 32
```

첫 번째 터미널에서 API를 실행한다. API는 요청마다 stdio MCP 자식 프로세스를 실행하므로 별도
MCP 데몬을 먼저 띄울 필요가 없다.

```bash
make api
```

다른 터미널에서 웹을 실행한다.

```bash
make web
```

브라우저에서 `http://localhost:5173`을 열고, API 상태는
`curl --fail http://localhost:8000/health`로 확인한다. 종료할 때는 API와 웹 터미널에서
`Ctrl+C`를 누르고 `docker compose stop qdrant`로 Qdrant를 중지한다.

WSL에서 `MSSQL_HOST`가 비어 있으면 기본 게이트웨이를 Windows 호스트 주소로 해석한다. 고정
주소가 필요할 때만 `.env`에 직접 지정한다.

MCP 서버는 `.mcp.json`에 등록되어 있다. 다음 명령은 stdio 서버의 다섯 도구와 입력 스키마를
검사한다.

```bash
make mcp-inspect
```

## KURE-v1 캐시와 첫 검색

모드 A에서는 Hugging Face 기본 호스트 캐시를 사용한다. 현재 개발 환경에는 아래 경로에 모델
본체가 약 2.2GB로 캐시돼 있다.

```text
/home/ssafy/.cache/huggingface/hub/models--nlpai-lab--KURE-v1
```

첫 의미·하이브리드 검색 때 Hugging Face 메타데이터를 확인하는 `HEAD`/`GET` 요청이 보일 수 있고,
2.2GB 가중치를 메모리에 올리는 CPU 초기화도 오래 걸릴 수 있다. 캐시 디렉터리와 대용량 모델
blob이 존재한다면 이 현상을 모델 본체의 최초 다운로드로 보지 않는다.

모드 B는 호스트 캐시를 마운트하지 않고 `embedding-models` Docker 볼륨을 `/app/models`로
사용한다. 이 볼륨이 비어 있으면 컨테이너의 첫 검색에서 모델을 내려받고, 이후 API와 MCP
컨테이너가 같은 캐시를 재사용한다.

## Notion 연결

1. Notion Creator dashboard에서 이 워크스페이스용 내부 연결을 만들고, Configuration 탭에서
   Installation access token을 복사한다.
2. 브리핑을 만들 상위 페이지를 열고 `•••` → `Connections` → `Add connection`에서 방금 만든
   연결을 추가한다. 새 내부 연결은 기본적으로 어떤 페이지에도 접근할 수 없다.
3. 루트 `.env`에 토큰과 선택적인 기본 상위 페이지 ID를 넣는다. `.env`는 Git에 커밋하지 않는다.

```dotenv
NOTION_TOKEN=발급받은_Installation_access_token
NOTION_PARENT_PAGE_ID=상위_페이지_ID
```

페이지 ID는 페이지 URL의 마지막 32자리 식별자이며 하이픈 유무와 관계없이 사용할 수 있다.
`NOTION_PARENT_PAGE_ID`를 비우면 이슈 화면의 “Notion 상위 페이지 ID” 입력란이나 API 요청의
`parent_page_id`로 매번 전달해야 한다. 요청값이 있으면 환경변수 기본값보다 우선한다.

설정을 바꾼 뒤 모드 A는 API를 재시작하고, 모드 B는 API와 MCP 컨테이너를 다시 만든다.

```bash
docker compose --profile full up -d --force-recreate api mcp
```

이슈 상세 화면의 내보내기 메뉴에서 확인하거나 API로 검사한다.

```bash
curl --fail --request POST http://localhost:8000/issues/<issue_id>/export \
  --header 'Content-Type: application/json' \
  --data '{"format":"notion"}'
```

기본 상위 페이지를 비워 뒀다면 JSON에 `"parent_page_id":"<page_id>"`를 함께 보낸다. 앱은
Notion SDK 오류를 503 응답으로 감싸므로 실패 시 MCP 감사 로그를 확인한다. 내부 원인이 401이면
토큰을, 403/404이면 해당 상위 페이지가 내부 연결에 공유됐는지를 먼저 확인한다.

## 데이터 적재 상태

서비스 기동과 뉴스 적재는 별도다. 실제 원본 `news.jsonl` 필드(`article_title`,
`article_service_daytime`, `text` 등)를 검증·정규화해 MS-SQL에 직접 배치 적재하는 S2 경로는
완료됐다. `scripts/03_build_vectors.py`는 같은 원본을 스트리밍해 선택한 dense 공급자와 Qdrant
BM25를 배치 적재하고, 재시도·재개·전체 ID 대조 결과를 JSON으로 출력한다. 기본 공급자는 로컬
KURE-v1이라 기사 내용을 외부로 전송하지 않는다. `EMBEDDING_PROVIDER=gemini`를 명시한 경우에만
Google API 전송 권한과 한도를 확인한다. dense 없이 BM25만 준비하려면 `--sparse-only`를 쓴다.

전체 데이터 경로와 현재 경계는 다음과 같다.

```text
data/raw/*.jsonl
  → scripts/01_validate_raw.py
  → scripts/02_load_mssql.py → MS-SQL
  → scripts/03_build_vectors.py → Qdrant
```

기존 `articles` 컬렉션에는 실제 원본과 ID가 일치하는 BM25 포인트 178,887건과 Gemini dense
포인트 900건이 보존돼 있다. 로컬 KURE-v1용 `articles_kure_v1`에는 원본과 ID가 일치하는
1,024차원 dense·BM25 포인트 178,887건이 적재됐으며 `.env`는 이 컬렉션과 로컬 공급자를
가리킨다. 같은 적재 명령을 다시 실행하면 dense 178,887건을 모두 건너뛴다. 선택 근거와 복구 방법은
[`ADR-0008`](docs/decisions/0008-local-kure-embedding.md)을 따른다.

현 상태와 입력·제외·정합성 계약은
[`docs/data/source-and-ingestion.md`](docs/data/source-and-ingestion.md) 및
[`docs/engineering/roadmap.md`](docs/engineering/roadmap.md)의 S2·S3 체크리스트를 기준으로 한다.

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

현재 릴리스 태그와 실제 게시 실행은 없다. 첫 검증에서는 사용할 버전(예: `v0.1.0`)이 원격에
없는지 확인하고, 현재 검증된 `origin/main` 커밋을 직접 태그한다. 로컬 `main`을 강제로 맞추거나
현재 작업 브랜치를 태그하지 않는다.

```bash
git fetch origin
git show --no-patch --oneline origin/main
git ls-remote --tags origin 'refs/tags/v0.1.0'
git tag -a v0.1.0 origin/main -m 'news-tls-agent v0.1.0'
git push origin v0.1.0
```

`git ls-remote`가 비어 있을 때만 그 버전을 사용한다. 태그 push 뒤 GitHub의 `release-images`
워크플로에서 `api`와 `mcp` 행렬 빌드가 모두 성공했는지 확인한다. 성공하면 게시된 두 이미지를
실제로 pull해 레지스트리 접근과 태그를 검증한다.

```bash
docker pull ghcr.io/minjun069/news-tls-agent-api:v0.1.0
docker pull ghcr.io/minjun069/news-tls-agent-mcp-server:v0.1.0
docker image inspect ghcr.io/minjun069/news-tls-agent-api:v0.1.0 --format '{{json .RepoDigests}}'
docker image inspect ghcr.io/minjun069/news-tls-agent-mcp-server:v0.1.0 --format '{{json .RepoDigests}}'
```

pull 권한 오류가 나면 GitHub Packages에서 패키지 공개 범위를 확인하거나 `read:packages` 권한이
있는 토큰으로 `docker login ghcr.io` 후 다시 확인한다. 이미 공개한 태그는 다른 커밋으로 옮기지
않고 수정 릴리스에는 `v0.1.1`처럼 새 패치 버전을 사용한다.

실제 서버 배포는 프로젝트 범위 밖이다. API/MCP 이미지 경계와 stdio 배치는
[ADR-0007](docs/decisions/0007-stdio-mcp-container-packaging.md)을 따른다.
