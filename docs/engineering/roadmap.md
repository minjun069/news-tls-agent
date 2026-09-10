# 개발 로드맵 — news-tls-agent

관련 PRD: [`REQUIREMENTS.md`](../REQUIREMENTS.md)

각 스프린트는 **완료 시점에 동작하는 상태**로 끝난다. 중간에 멈춰도 버려지는 산출물이 없도록 순서를 잡았다.

---

## 의존 관계

```
S1 기반 ─┬─ S2 데이터 계층 ─┬─ S4 MCP 서버 ─ S5 생성 ─ S6 API ─┬─ S7 프론트 ─ S9 마무리
         └─ S3 벡터 계층  ─┘                                   └─ S8 그래프·내보내기 ─┘
```

---

## S2 전체 원본 적재 결과

`data/raw/news.jsonl`은 178,887행이며, 전수 파싱에서 JSON 오류·비객체·필수 필드 제외·유효
`article_id` 중복은 모두 0건이었다. 기사 시각 범위는 `2025-01-01 00:12:54`부터
`2025-12-31 23:59:10`까지다.

S2의 운영 경로는 토픽별 후보를 만들지 않는다. `01_validate_raw.py`가 전체 원본의 정규화 가능
여부를 보고하고, `02_load_mssql.py`가 같은 원본을 직접 MS-SQL에 적재한다. 토픽 gold, 검색
커버리지, 검색어 확장, LLM 관련성 판정은 S3 검색 기능이 생긴 뒤의 오프라인 평가로 미룬다.

문서 라우팅은 작업 흐름을 대체하지 않는다. 예를 들어 `backend/scripts/01_validate_raw.py`와
`backend/scripts/02_load_mssql.py`를 바꾸기 전에는 `docs/data/source-and-ingestion.md`를 읽고,
`python3 .harness/route_docs.py <경로>`의 결과를 대조한다.

---

## S1 · 기반 구축

### S1-1 프로젝트 초기화
- [x] GitHub 리포 `news-tls-agent` 생성
- [x] 디렉토리 스켈레톤 (`AGENTS.md` §2), `.env.example`, `.gitignore`
- [x] `backend/pyproject.toml` — `backend/`가 Python 소스 루트이며 자체 패키지는 아니다
- [x] `data/raw/.gitkeep` — 원본 데이터 투입 위치

### S1-2 개발 하네스
- [x] `AGENTS.md` — 상위 규칙, 상세 프로젝트 트리, 작업별 문서 흐름
- [x] ruff 규칙이 [`code-conventions.md`](code-conventions.md)를 강제 (ANN·I002·G·BLE/TRY·N·S)
- [x] **import-linter 계약이 `AGENTS.md` §1·§3 경계를 강제** — 계약 5개
- [x] `Makefile` — `make check`가 커밋 전 게이트
- [x] `.harness/` — 도구 독립 문서 라우팅·동기화·검증
- [x] `.codex/hooks.json` — Codex 편집 전 문서 안내·편집 후 정적 검사
- [x] **가드 검증** — 일부러 위반을 넣어 5개 계약과 8개 린트 규칙이 잡는 것을 확인
- [x] **AGENTS.md 크기 측정 도구** 추가 — 목표 예산은 재구성 결과를 보고 결정

> 계층 계약을 코드가 0줄일 때 도입한 이유: 위반이 없는 상태에서 켜면 통과하지만,
> 코드가 쌓인 뒤 켜면 그때부터는 리팩터링이다.

### S1-3 CI 골격
- [x] `.github/workflows/backend.yml` — `make install` → `make check`로 ruff·pytest·계층 규칙·문서 검사를 실행
- [x] `main` 브랜치 보호 (PR 필수, `check` 잡을 required status check으로 지정)

> `web.yml`은 S7로 미룬다. `web/`이 비어 있는 동안 만들면 아무것도 검사하지 않는
> 워크플로가 된다 — 게이트가 한 번도 울리지 않으면 게이트가 없는 것과 같다.

> CI를 지금 붙이는 이유: 코드가 쌓인 뒤 도입하면 이미 깨진 상태에서 시작한다.

### S1-4 인프라 기동
- [x] SQL Server Developer Edition + SSMS 설치, **TCP/IP 프로토콜 활성화**
- [x] ODBC Driver 18 확인, DB `newsagent` 생성
- [x] Docker Desktop 설치
- [x] `docker-compose.yml` — `qdrant`(기본) · `mssql`(profile `full`), 이후 서비스는 해당 스프린트에서 추가
- [x] `.env.example` — 모드 A/B/C 접속 정보 ([아키텍처 §4.1](../architecture/overview.md))

**완료 기준**: WSL에서 pyodbc로 Windows 호스트 SQL Server 접속 성공. Qdrant 대시보드 접속 성공. 빈 스켈레톤 PR에서 CI 초록불.

---

## S2 · 데이터 계층

| 관련 | ISS-003~005, ART-001~003, NFR-08, NFR-09, NFR-02 |
|---|---|

- [x] `backend/db/migrations/` — [`schema.md`](../data/schema.md) 기준. 테이블 6개, 인덱스 7종
- [x] `backend/db/migrate.sh` — 미적용 번호만 실행, 스크립트당 트랜잭션
- [x] `000_bootstrap.sql` — 멱등. `CREATE DATABASE ... COLLATE` + `schema_migrations`
- [x] `scripts/01_validate_raw.py`·`scripts/raw_ingestion.py` — 실제 `news.jsonl` 필드 매핑·전체 검증·제외 사유 집계·유효 ID 중복 처리
- [x] `scripts/02_load_mssql.py` — 중간 시드 없이 원본 전체를 배치 upsert, 멱등성
- [x] `core/models.py`·`core/ports.py` — 데이터 모델과 Repository Protocol
- [x] `infra/db.py`·`infra/entities.py` — 엔진, 세션, ORM
- [x] `infra/repository.py` — ports 구현
- [x] `core/ranking.py` — [대표 기사 선정 정책](../requirements/issue-view.md#대표-기사-선정-정책)의 순수 함수
- [x] `tests/unit/test_ranking.py` · `tests/integration/test_repository.py`

> `data/raw/news.jsonl`은 실제 원본 필드명(`article_title`, `article_service_daytime`, `text` 등)을
> 그대로 유지한다. `01_validate_raw.py`와 `02_load_mssql.py`가 같은 정규화 규칙을 공유하며,
> 토픽별 seed 파일을 만들지 않는다.

**완료 기준**
- [x] 이슈 → 이벤트 → 기사 3단 조인 질의 동작
- [x] **역방향 조회**("기사 X가 인용된 이슈") 동작
- [x] 대표 기사 선정이 결정론적 (같은 입력 → 같은 결과)
- [x] 실제 원본 전체 적재 뒤 행 수·기간 인덱스 사용 확인; Repository 통합 테스트로 재실행 멱등성 확인
- [x] 저장 중 외래키 예외 발생 시 부분 데이터 잔존 없음

> S2가 완료되면 토픽 후보·gold 커버리지·검색어 확장은 S3 검색 구현의 오프라인 평가로 진행한다.

---

## S3 · 벡터 계층

| 관련 | NFR-04, NFR-05, ADR-0003, ADR-0005, ADR-0008 |
|---|---|

세부 작업 순서, S2와의 병렬 경계, 작업 단위별 모델·검증 게이트는
[`S3 벡터 계층 실행계획`](s3-vector-layer-plan.md)을 따른다.

- [x] `core/models.py`·`core/ports.py` — 검색 계약과 BM25 구현 위치 결정 (S3-P1)
- [x] Qdrant `articles_kure_v1` 컬렉션 생성 (`dense` Cosine + `bm25` sparse, payload 4종)
- [x] `scripts/03_build_vectors.py` — 원본 직접 임베딩 적재, 배치·재시도·재개·ID 대조
- [x] `infra/qdrant.py`·`infra/embedding.py` — Gemini·로컬 KURE 공급자와 모의 SDK 단위 검증 (S3-P3)
- [x] `core/ranking.py` — RRF 결합 (순수 계산, S3-P2)
- [x] `app/search.py` — 3종 검색 유스케이스
- [x] 기간 필터를 검색 단계에서 적용하는 요청 구현·모의 검증 (S3-P3)
- [x] `tests/unit/test_ranking.py` — RRF 단위 테스트 (컨테이너 불필요, S3-P2)

**완료 기준**
- [x] 실제 원본에서 세 방식이 각각 호출 가능하고 결과가 다름
- [x] 기간 필터가 검색 단계에서 적용됨 — 실제 전체 dense·BM25 MCP 검사

> 기존 `articles`에는 실제 원본 178,887건의 BM25와 Gemini dense 900건을 보존한다. 무료 한도를
> 피하기 위해 CPU 표본 실측으로 로컬 KURE-v1을 선택했다. `articles_kure_v1`에는 원본과 ID가
> 일치하는 dense·BM25 178,887건을 적재했고, 재실행에서 dense 178,887건을 모두 건너뛰며 누락·
> 초과·sparse-only가 0건임을 확인했다. 실제 MCP로 세 검색 방식의 서로 다른 결과, 기간 선필터,
> MS-SQL 기사 복원도 검증했다 ([ADR-0008](../decisions/0008-local-kure-embedding.md)).

---

## S4 · MCP 서버

| 관련 | CHAT-002, NFR-06, NFR-12, EX-06, ADR-0001 |
|---|---|

- [x] `mcp_server/server.py`·`mcp_server/tools/` — Python MCP SDK v2 `MCPServer`
- [x] 툴 5종 + **description 문구** ([`MCP_TOOLS.md`](../contracts/mcp-tools.md) §7 작성 규칙)
- [x] 응답 규약 `{ok, ...}` / `{ok:false, error:{code,message}}` ([`MCP_TOOLS.md`](../contracts/mcp-tools.md))
- [x] 감사 로그
- [x] payload 함수와 데코레이터 분리
- [x] `tests/unit/test_mcp_payloads.py` — payload 함수 (MCP 없이)
- [x] `.mcp.json` — 자기 MCP 서버를 개발 환경에 등록

**완료 기준**
- MCP Inspector에서 툴 5종 모두 정상 응답
- Claude Code 세션에서 등록된 툴이 조회됨
- **이 시점에 API 서버 없이 "MCP 서버를 만들었다"가 독립 증명된다**

```bash
make mcp-inspect
```

`export_briefing`은 S4에서 툴 계약과 주입 포트까지만 제공한다. S8 구현이 주입되기 전에는
`EXPORT_NOT_CONFIGURED` 구조화 오류를 반환하며 PDF·Notion 파일을 임시 생성하지 않는다.

---

## S5 · 타임라인 생성 파이프라인

| 관련 | ISS-001, ISS-006, EX-01~EX-05, AC-001~003, AC-008, AC-022, AC-023 |
|---|---|

가장 복잡한 스프린트다. S5에는 LLM 호출 P1~P8이 들어가고, P9 엔티티·관계 추출은 S8에서
그래프 조회 시 실행한다 ([`AI_SPEC.md`](../ai/specification.md) §2).

- [x] `core/models.py`·`core/errors.py` — 도메인 스키마와 예외
- [x] P1 질의 의도 해석 + 되묻기
- [x] P2 가상 타임라인 생성
- [x] P3 검색 쿼리 생성 (방식 선택 포함)
- [x] P4 핵심 이벤트 선정 (배치 판정)
- [x] P5 선후 이벤트 추출
- [x] P6 충분성 검토
- [x] P7 가상 이벤트 생성
- [x] P8 타임라인 병합
- [x] 수집 루프 오케스트레이션 + **종료 조건 4가지** ([타임라인 종료 정책](../requirements/timeline.md#수집-루프-종료-정책))
- [x] 인용 검증 → 트랜잭션 저장
- [x] 파이프라인 실행 로그 (NFR-14)
- [x] CLI 진입점
- [x] `app/pipeline.py` — 수집 루프 오케스트레이션
- [x] `tests/unit/test_pipeline.py` — LLM 모킹. 허구 ID 주입, 무한 루프 방지

**완료 기준**
- CLI로 토픽 입력 시 MS-SQL에 이슈·이벤트·기사연결 저장
- 허구 ID를 반환하는 모의 LLM으로도 미실재 기사가 저장되지 않음
- **가상 이벤트가 최종 결과에 포함되지 않음** ([`AI_SPEC.md`](../ai/specification.md) §5.1)
- 종료 조건 4가지가 각각 동작 (모의 LLM으로 검증)
- 검색 0건 시 근거 없는 이슈가 저장되지 않음 (EX-01, EX-02)

> **선행 검증**: 착수 직후 Gemini 구조화 출력과 도구 호출 최소 예제를 먼저 확인한다 ([PRD 공통 리스크](../REQUIREMENTS.md#7-공통-리스크)).

`google-genai 1.75.0`과 `gemini-3.6-flash` 실제 API로 구조화 출력 Pydantic 파싱과 함수 호출을
각각 확인했다. `gemini-2.5-flash`는 같은 계정에서 `404 NOT_FOUND`를 반환해 기본 모델과 문서
계약을 함께 갱신했다.

---

## S6 · API 서버

| 관련 | ISS-001~006, ART-002, CHAT-001~006, NFR-07, EX-06 |
|---|---|

- [x] `api/main.py`·`api/routes/` — FastAPI, CORS, `/health`
- [x] `api/deps.py` — **core ← infra 주입 지점**
- [x] `infra/mcp_client.py` — MCP SDK v2 → LangChain 도구 브리지 ([ADR-0006](../decisions/0006-mcp-v2-langchain-tool-bridge.md))
- [x] `app/agent.py` — LangGraph 그래프. `core.ports.ToolClient`로 주입받는다
- [x] 출처 구분 응답 (CHAT-004) — `token` 이벤트의 `source` 필드
- [x] S6 엔드포인트 — health·이슈 생성/목록/상세·기사·대화 ([`API.md`](../contracts/http-api.md))
- [x] SSE — 생성 진행(stage/round), 대화 토큰, 되묻기
- [x] 에이전트 실행 로그 (NFR-15)
- [x] `tests/integration/test_api.py`
- [x] 계층 규칙 검사 — 기존 import-linter 5개 계약과 `make check`에 편입

**완료 기준**
- Swagger에서 생성·조회·대화 전 기능 동작
- 되묻기 흐름 동작 (AC-022, AC-023)
- 대화 시 MCP 툴 호출이 감사 로그에 기록됨
- MCP 서버를 내린 상태에서 대화 요청 시 오류 반환, 저장소 직접 조회 없음
- `app/`이 `infra`를 import하지 않음이 CI로 강제됨

> MCP Python SDK v2를 필수로 유지하기 위해 아직 v2를 지원하지 않는
> `langchain-mcp-adapters` 대신 MCP `inputSchema`를 `StructuredTool`로 변환하는 얇은 브리지를
> 구현했다. 실제 MS-SQL·Qdrant·Gemini 성공 경로는 `.env`와 적재 데이터가 있는 환경에서
> Swagger로 검증해야 하며, 모의 의존성 API 조립·MCP 장애·계층 경계는 자동 검사한다.

---

## S7 · 프론트엔드

| 관련 | 전 기능. 화면 기준은 [`SCREENS.md`](../product/screens.md) |
|---|---|

- [x] `npm create vite@latest web -- --template vue-ts`
- [x] `.github/workflows/web.yml` — vue-tsc, build (S1-3에서 이월)
- [x] API 클라이언트 (SSE 수신 포함)
- [x] 이슈 목록 화면 — 생성 진행(라운드 표시), 되묻기 UI
- [x] 이슈 상세 화면 — 타임라인, **대표 기사 즉시 표시**, 근거 기사 목록
- [x] 대화 패널 — **출처별 표기 구분** (article / general)
- [x] 마크다운 렌더링

**완료 기준**
- [x] 토픽 입력 → 생성 → 타임라인 → 근거 확인 → 대화 전 흐름 연결
- [x] 기사 근거와 일반 지식이 시각적으로 구분됨
- [x] `npm run build`, `vue-tsc --noEmit` 통과

`web/src/api/sse.ts`가 `fetch` 응답 스트림을 청크 경계와 무관하게 SSE 이벤트로 조립한다.
생성 화면은 `clarify`의 `attempt`를 다음 요청의 `clarification_count`로 보내고, 상세 화면은 대화의
참조 기사 ID를 해당 이벤트·기사 패널로 연결한다. 마크다운은 `marked`로 변환한 뒤 DOMPurify로
정화해 표시하며, 웹 CI는 Node.js 22.19.0에서 잠금 파일 설치·타입 검사·빌드를 실행한다.

---

## S8 · 지식 그래프와 내보내기

| 관련 | GRPH-001, EXP-001, EXP-002, CHAT-006, NFR-16, ADR-0004 |
|---|---|

### S8-1 지식 그래프
- [x] P9 엔티티·관계 추출 ([`AI_SPEC.md`](../ai/specification.md) §2.10)
- [x] `articles.entities_extracted_at` 기반 추출 여부 판정
- [x] 기사 1건 단위 트랜잭션 저장
- [x] `GET /issues/{id}/graph` — SSE 추출 진행 + 기사별 그래프 반환
- [x] 프론트 그래프 시각화 — **기사별 분리 표시**

### S8-2 내보내기
- [x] 브리핑 마크다운 구성
- [x] PDF 변환
- [x] Notion 저장
- [x] `POST /issues/{id}/export`
- [x] MCP `export_briefing` 툴 — 대화 경로 (CHAT-006)
- [x] 화면 메뉴와 대화가 **같은 구현**을 호출하는지 확인

**완료 기준**
- 기사별 그래프가 출처와 함께 표시됨
- 모든 노드·간선에서 출처 기사를 역추적 가능 (NFR-16)
- 화면 메뉴와 대화 양쪽에서 PDF·Notion 내보내기 동작
- 형식 미지정 시 되물음 (AC-016)

`app/exporting.py`가 이슈 전체를 마크다운으로 한 번 구성하고 PDF·Notion 어댑터에 전달한다.
HTTP 메뉴도 MCP `export_briefing`을 호출하므로 대화 도구와 구현이 갈라지지 않는다. PDF는
`fpdf2`로 한글 TTF를 포함하고, 그래프 화면은 추가 런타임 의존성 없이 기사별 SVG를 그린다.
기사당 노드가 30개를 넘으면 API 원본은 유지한 채 화면만 줄이고 그 사실을 표시한다.

---

## S9 · 마무리

- [x] CI 확장 — 서비스 컨테이너(MS-SQL, Qdrant)로 통합 테스트
- [x] E2E 테스트 — 생성 → 조회 → 근거 확인 → 대화 → 내보내기 ([PRD Success Metrics](../REQUIREMENTS.md#36-success-metrics))
- [x] CD 워크플로 — `api`·`mcp_server` 이미지 빌드 → GHCR 푸시
- [x] `README.md` — 아키텍처, 실행 절차, CI 배지
- [x] 클린 클론 재현 테스트 — `docker compose --profile full up -d` 한 줄 (NFR-13, 모드 B)
- [x] ADR 정리

**완료 기준**
- PR에서 lint·unit·integration·e2e·web 잡 모두 초록불
- 태그 push 시 GHCR에 이미지 게시
- 클린 클론에서 `docker compose --profile full up -d` 로 기동

> CI에서 MS-SQL을 서비스 컨테이너로 띄우는 것이 이 스프린트의 학습 지점이다. 로컬은 네이티브, CI는 컨테이너인 이중 구성을 다루게 된다.

로컬 완료 검증에서는 별도 빈 Compose 볼륨으로 전체 서비스를 기동해 마이그레이션 종료 코드 0,
API·웹·MS-SQL·Qdrant 헬스 통과, 실제 통합 테스트와 E2E, 세 이미지 빌드를 확인했다. PR 잡과
`v*` 태그의 실제 GHCR 게시 결과는 해당 커밋을 원격에 push한 뒤 GitHub Actions에서 확인한다.
S2 전체 원본 직접 적재는 완료됐지만 S3 `scripts/03_build_vectors.py`의 미완료 상태는 S9
픽스처 E2E가 대신하지 않으며, 위 S3 체크리스트에 계속 남긴다.

---

## 후속 안정화

실제 실행에서 잘못 추정한 기간으로 인한 검색 누락, 후보 전건 탈락 뒤 조기 수렴, Gemini
상태별 재시도 불일치, 지식 그래프 관계 끝점 검증 실패가 확인됐다. 현상별 원인, 변경 범위,
완료 조건과 작업 순서는 [런타임 실패 안정화 실행계획](runtime-reliability-plan.md)을 단일 원천으로
따른다. 계획 항목은 아직 구현되지 않았으며 해당 문서의 종료 게이트를 모두 통과한 뒤 완료로
판정한다.

---

## 사용자 직접 처리 항목

| 항목 | 필요 시점 |
|---|---|
| 원본 데이터 투입 (`data/raw/`) | S2 이전 |
| 선정된 시드 토픽·정답 사건 검토(선택) | S2 전처리 구현 전 |
| Notion 통합 토큰 발급 | S8 이전 |
