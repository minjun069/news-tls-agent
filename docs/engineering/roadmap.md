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

## 현재 작업 인수인계 — S2 전처리 착수 전

### 작업 트리

현재 브랜치는 `feat/s2-data-layer`, HEAD는 `3679944 chore(harness): 문서 변경 없음 검토와 CI 게이트 통일`이다. 하네스 변경은 커밋됐으며, 아래는 S2 전처리 구현을 시작하기 전에 확정한 실제 원본·평가 계약과 작업 상태다.

### 문서 라우팅의 정확한 역할

`.harness/doc-routes.json`은 **편집할 코드 경로를 그 코드의 입력·출력·외부 동작을 정의한 문서 경로로 연결하는 역조회 표**다. 예를 들어 `backend/scripts/01_extract_seed.py`를 입력하면 `route_docs.py`가 `docs/data/source-and-ingestion.md`를 출력한다. 에이전트는 편집 전에 그 문서의 원본 필드, 정규화 출력, 제외 조건, 중복 정책을 읽고 코드 변경이 문서 내용까지 바꾸는지 판정한다.

이 라우팅은 `AGENTS.md`의 작업 종류별 문서 흐름을 대체하지 않는다. 작업 흐름은 전처리 작업 전체에 필요한 타임라인 요구사항·수집 문서·스키마를 정하고, 라우팅은 실제 편집 파일이 정해진 시점에 빠뜨리기 쉬운 파일별 문서를 다시 특정한다.

### 확인한 원본과 선정 토픽

`data/raw/news.jsonl`을 전수 파싱한 결과는 178,887행, JSON 파싱 실패 0행, 기사 시각 범위 `2025-01-01 00:12:54`부터 `2025-12-31 23:59:10`까지다. `/home/ssafy` 4단계 범위와 현재 Git 이력에서는 별도의 과거 정답 타임라인·토픽 파일을 찾지 못했다. 따라서 아래 토픽은 실제 원본 제목 빈도와 사건 경계의 명확성, 도메인 다양성을 근거로 선정했다.

| 토픽 | 초기 기간 | 재현율 중심 검색어 | 선정 근거 |
|---|---|---|---|
| 윤석열 대통령 탄핵심판과 파면 | 2025-01-01~2025-04-04 | `탄핵`, `윤석열`, `계엄`, `헌법재판소`, `체포`, `파면` | 제목에 `탄핵` 927건, `계엄` 625건이 있어 다단계 정치 사건의 커버리지를 시험할 수 있다. |
| 2025년 영남권 대형 산불 | 2025-03-21~2025-04-05 | `영남 산불`, `의성 산불`, `경북 산불`, `산림청`, `특별재난지역`, 지역명 조합 | 발화·확산·대피·진화·복구로 사건 단계가 분명하다. 일반 `산불` 757건에는 LA 등 다른 사건이 섞이므로 지역·기간 조건이 필수다. |
| SK텔레콤 유심 정보 유출 사태 | 2025-04-18~2025-07-31 | `SK텔레콤`, `SKT`, `유심`, `해킹`, `개인정보 유출`, `유심보호서비스`, `위약금` | 제목에 `SKT` 318건, `유심` 129건이 있으며 사고 공개·정부 조사·교체 대책·보상으로 이어져 기업 보안 사건을 시험할 수 있다. |

빈도는 제목의 단순 부분 문자열 집계이며 최종 관련 기사 수가 아니다. 초기 기간은 정답 사건을 작성하면서 앞뒤로 확장할 수 있다. 다른 토픽을 다시 승인받지 않고 이 세 토픽으로 진행하되, 사용자가 변경을 요청하면 그때 범위를 바꾼다.

### 평가 정의

- **정답 타임라인**은 기사 후보 검색어·기간을 만들고 결과를 평가하는 데만 사용한다. 타임라인 생성 LLM 입력에는 사건명·설명·정답 기사 ID를 넣지 않는다.
- **커버리지 통과 조건**은 `정답 사건 중 관련 판정을 받은 서로 다른 선별 기사 ≥ 1건인 사건의 비율 = 100%`다. 미충족 사건이 있으면 검색어·인물·기관·기간을 확장하고 다시 선별한다.
- 사건마다 서로 다른 기사 2건 이상은 단일 기사 오류에 덜 의존하기 위한 증거 중복 목표였지만 현재 요구사항의 필수 조건은 아니다. 하드 게이트에서 제외하고 `2건 이상 확보 사건 비율`이라는 보조 지표로만 기록한다.
- `source_gap`이라는 이름은 출판사 다양성 부족인지 기사 부재인지 모호하므로 사용하지 않는다. 정답 사건에 관련 선별 기사가 0건인 상태는 `coverage_gap`으로 기록하고, 출판사 다양성이 필요해지면 별도 `publisher_gap`으로 정의한다.
- 서로 다른 기사는 `article_id`가 다른 기사를 뜻한다. 서로 다른 언론사를 뜻하지 않는다.

### 전처리 구현 순서와 산출물

1. [x] 위 세 토픽의 정답 사건, 기간, 인물, 기관, 검색어를 작성한다.
2. [ ] 실제 `news.jsonl` 필드에 맞춘 정규화 어댑터와 전체 행 검증을 구현한다.
3. [ ] 사건명·인물·기관·검색어·기간으로 재현율 중심 후보 기사를 추출한다.
4. [ ] 후보를 배치 단위로 LLM에 전달해 관련성을 판정하고 판정 근거를 남긴다.
5. [ ] 사건별 커버리지를 계산해 `coverage_gap`이 없어질 때까지 검색 조건을 확장한다.
6. [x] 실행 입력은 `data/seed/<topic>.articles.jsonl`, 평가 정답은 `data/seed/<topic>.gold.json`으로 분리한다. 두 파일은 모두 Git 제외 대상이며 생성 LLM에는 articles 파일만 제공한다.

정답 파일은 `yoon-impeachment.gold.json`, `yeongnam-wildfires.gold.json`,
`skt-usim-breach.gold.json`으로 작성했다. 각 파일은 정답 사건 9개와 사건당 실제 원본 기사
2건, 누락 위험, 단계별 검색어 확장 기준을 포함한다. 형식과 생성 LLM 격리 규칙은
[`source-and-ingestion.md`](../data/source-and-ingestion.md#311-평가-정답-파일)를 따른다.

`backend/scripts/01_extract_seed.py` 구현 전에 `docs/requirements/timeline.md` → `docs/data/source-and-ingestion.md` → `docs/data/schema.md`를 읽고, `python3 .harness/route_docs.py backend/scripts/01_extract_seed.py`가 출력한 수집 문서도 다시 대조한다.

### 검증 상태와 GUI·WSL 주의사항

- 훅 입력에 `backend/scripts/01_extract_seed.py` 패치를 넣었을 때 `hookSpecificOutput.hookEventName=PreToolUse`와 `docs/data/source-and-ingestion.md`가 포함된 `additionalContext`를 확인했다.
- 새 문서 검토 테스트 3개와 기존 단위 테스트를 합쳐 `uv run pytest -s tests/unit`에서 `10 passed`를 확인했다.
- ruff 린트·포맷, import-linter 계약 5개, 문서 동기화, Markdown 링크 검사는 각각 통과했다.
- Codex GUI가 기본 작업 경로를 Windows 앱 경로와 WSL UNC 경로를 합친 잘못된 문자열로 잡았다. 명령마다 `workdir=/home/ssafy/news-tls-agent`를 명시하면 WSL 실행과 읽기는 정상이다.
- 현재 GUI 샌드박스는 실제 WSL 저장소를 읽기 전용으로 분류해 일반 쓰기에서 `Read-only file system`을 반환한다. 저장소 편집은 승인된 WSL 실행이 필요했다.
- 표준 `make check`는 pytest 캡처 종료 중 `FileNotFoundError`가 발생해 한 번에 끝나지 않았다. 정확한 실패 위치는 `_pytest/capture.py`의 `self.tmpfile.truncate()`이며, 캡처를 끈 `pytest -s`에서는 전체 10개가 통과했다. CI의 일반 Ubuntu 환경에서 `make check`가 통과하는지는 아직 미검증이다.

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
- [ ] `scripts/01_extract_seed.py` — 실제 `news.jsonl` 필드 매핑·전체 표본 검증 필요
- [x] `scripts/02_load_mssql.py` — 정규화된 시드의 배치 upsert, 멱등성
- [x] `core/models.py`·`core/ports.py` — 데이터 모델과 Repository Protocol
- [x] `infra/db.py`·`infra/entities.py` — 엔진, 세션, ORM
- [x] `infra/repository.py` — ports 구현
- [x] `core/ranking.py` — [대표 기사 선정 정책](../requirements/issue-view.md#대표-기사-선정-정책)의 순수 함수
- [x] `tests/unit/test_ranking.py` · `tests/integration/test_repository.py`

> `data/raw/news.jsonl`은 실제로 존재하지만 원본 필드명(`article_title`, `article_service_daytime`, `text` 등)이 현재 추출기 입력과 다르다. 매핑과 실제 표본 검증 전에는 전처리 완료로 표시하지 않는다.

**완료 기준**
- [x] 이슈 → 이벤트 → 기사 3단 조인 질의 동작
- [x] **역방향 조회**("기사 X가 인용된 이슈") 동작
- [x] 대표 기사 선정이 결정론적 (같은 입력 → 같은 결과)
- [ ] 실제 시드 적재 후 SSMS 실행계획에서 인덱스 사용 확인
- [x] 저장 중 외래키 예외 발생 시 부분 데이터 잔존 없음

> `data/raw/news.jsonl` 투입, 시드 토픽 3개 선정, 토픽별 정답 사건 작성은 완료됐다. 다음
> 작업은 실제 원본 필드 매핑을 적용한 정규화 어댑터와 전처리 검증 구현이다.

---

## S3 · 벡터 계층

| 관련 | NFR-04, NFR-05, ADR-0003, ADR-0005 |
|---|---|

세부 작업 순서, S2와의 병렬 경계, 작업 단위별 모델·검증 게이트는
[`S3 벡터 계층 실행계획`](s3-vector-layer-plan.md)을 따른다.

- [x] `core/models.py`·`core/ports.py` — 검색 계약과 BM25 구현 위치 결정 (S3-P1)
- [ ] Qdrant `articles` 컬렉션 생성 (`dense` Cosine + `bm25` sparse, payload 4종)
- [ ] `scripts/03_build_vectors.py` — 임베딩 적재, 배치·재시도
- [ ] `infra/qdrant.py`·`infra/embedding.py`
- [x] `core/ranking.py` — RRF 결합 (순수 계산, S3-P2)
- [ ] `app/search.py` — 3종 검색 유스케이스
- [ ] 기간 필터를 검색 단계에서 적용
- [x] `tests/unit/test_ranking.py` — RRF 단위 테스트 (컨테이너 불필요, S3-P2)

**완료 기준**
- 세 방식이 각각 호출 가능하고 결과가 다름
- 기간 필터가 벡터 검색 단계에서 적용됨

---

## S4 · MCP 서버

| 관련 | CHAT-002, NFR-06, NFR-12, EX-06, ADR-0001 |
|---|---|

- [ ] `mcp_server/server.py`·`mcp_server/tools/` — FastMCP
- [ ] 툴 5종 + **description 문구** ([`MCP_TOOLS.md`](../contracts/mcp-tools.md) §7 작성 규칙)
- [ ] 응답 규약 `{ok, ...}` / `{ok:false, error:{code,message}}` ([`MCP_TOOLS.md`](../contracts/mcp-tools.md))
- [ ] 감사 로그
- [ ] payload 함수와 데코레이터 분리
- [ ] `tests/unit/test_mcp_payloads.py` — payload 함수 (MCP 없이)
- [ ] `.mcp.json` — 자기 MCP 서버를 개발 환경에 등록

**완료 기준**
- MCP Inspector에서 툴 5종 모두 정상 응답
- Claude Code 세션에서 등록된 툴이 조회됨
- **이 시점에 API 서버 없이 "MCP 서버를 만들었다"가 독립 증명된다**

```bash
make mcp-inspect
```

---

## S5 · 타임라인 생성 파이프라인

| 관련 | ISS-001, ISS-006, EX-01~EX-05, AC-001~003, AC-008, AC-022, AC-023 |
|---|---|

가장 복잡한 스프린트다. LLM 호출이 8종 들어간다 ([`AI_SPEC.md`](../ai/specification.md) §2).

- [ ] `core/models.py`·`core/errors.py` — 도메인 스키마와 예외
- [ ] P1 질의 의도 해석 + 되묻기
- [ ] P2 가상 타임라인 생성
- [ ] P3 검색 쿼리 생성 (방식 선택 포함)
- [ ] P4 핵심 이벤트 선정 (배치 판정)
- [ ] P5 선후 이벤트 추출
- [ ] P6 충분성 검토
- [ ] P7 가상 이벤트 생성
- [ ] P8 타임라인 병합
- [ ] 수집 루프 오케스트레이션 + **종료 조건 4가지** ([타임라인 종료 정책](../requirements/timeline.md#수집-루프-종료-정책))
- [ ] 인용 검증 → 트랜잭션 저장
- [ ] 파이프라인 실행 로그 (NFR-14)
- [ ] CLI 진입점
- [ ] `app/pipeline.py` — 수집 루프 오케스트레이션
- [ ] `tests/unit/test_pipeline.py` — LLM 모킹. 허구 ID 주입, 무한 루프 방지

**완료 기준**
- CLI로 토픽 입력 시 MS-SQL에 이슈·이벤트·기사연결 저장
- 허구 ID를 반환하는 모의 LLM으로도 미실재 기사가 저장되지 않음
- **가상 이벤트가 최종 결과에 포함되지 않음** ([`AI_SPEC.md`](../ai/specification.md) §5.1)
- 종료 조건 4가지가 각각 동작 (모의 LLM으로 검증)
- 검색 0건 시 근거 없는 이슈가 저장되지 않음 (EX-01, EX-02)

> **선행 검증**: 착수 직후 Gemini 구조화 출력과 도구 호출 최소 예제를 먼저 확인한다 ([PRD 공통 리스크](../REQUIREMENTS.md#7-공통-리스크)).

---

## S6 · API 서버

| 관련 | ISS-001~006, ART-002, CHAT-001~006, NFR-07, EX-06 |
|---|---|

- [ ] `api/main.py`·`api/routes/` — FastAPI, CORS, `/health`
- [ ] `api/deps.py` — **core ← infra 주입 지점**
- [ ] `infra/mcp_client.py` — `langchain-mcp-adapters`
- [ ] `app/agent.py` — LangGraph 그래프. `core.ports` 타입으로 주입받는다
- [ ] 출처 구분 응답 (CHAT-004) — `token` 이벤트의 `source` 필드
- [ ] 엔드포인트 ([`API.md`](../contracts/http-api.md))
- [ ] SSE — 생성 진행(stage/round), 대화 토큰, 되묻기
- [ ] 에이전트 실행 로그 (NFR-15)
- [ ] `tests/integration/test_api.py`
- [ ] 계층 규칙 검사 스크립트 — CI에 편입 (`AGENTS.md` §2.1)

**완료 기준**
- Swagger에서 생성·조회·대화 전 기능 동작
- 되묻기 흐름 동작 (AC-022, AC-023)
- 대화 시 MCP 툴 호출이 감사 로그에 기록됨
- MCP 서버를 내린 상태에서 대화 요청 시 오류 반환, 저장소 직접 조회 없음
- `app/`이 `infra`를 import하지 않음이 CI로 강제됨

---

## S7 · 프론트엔드

| 관련 | 전 기능. 화면 기준은 [`SCREENS.md`](../product/screens.md) |
|---|---|

- [ ] `npm create vite@latest web -- --template vue-ts`
- [ ] `.github/workflows/web.yml` — vue-tsc, build (S1-3에서 이월)
- [ ] API 클라이언트 (SSE 수신 포함)
- [ ] 이슈 목록 화면 — 생성 진행(라운드 표시), 되묻기 UI
- [ ] 이슈 상세 화면 — 타임라인, **대표 기사 즉시 표시**, 근거 기사 목록
- [ ] 대화 패널 — **출처별 표기 구분** (article / general)
- [ ] 마크다운 렌더링

**완료 기준**
- 토픽 입력 → 생성 → 타임라인 → 근거 확인 → 대화 전 흐름 동작
- 기사 근거와 일반 지식이 시각적으로 구분됨
- `npm run build`, `vue-tsc --noEmit` 통과

---

## S8 · 지식 그래프와 내보내기

| 관련 | GRPH-001, EXP-001, EXP-002, CHAT-006, NFR-16, ADR-0004 |
|---|---|

### S8-1 지식 그래프
- [ ] P9 엔티티·관계 추출 ([`AI_SPEC.md`](../ai/specification.md) §2.10)
- [ ] `articles.entities_extracted_at` 기반 추출 여부 판정
- [ ] 기사 1건 단위 트랜잭션 저장
- [ ] `GET /issues/{id}/graph` — SSE 추출 진행 + 기사별 그래프 반환
- [ ] 프론트 그래프 시각화 — **기사별 분리 표시**

### S8-2 내보내기
- [ ] 브리핑 마크다운 구성
- [ ] PDF 변환
- [ ] Notion 저장
- [ ] `POST /issues/{id}/export`
- [ ] MCP `export_briefing` 툴 — 대화 경로 (CHAT-006)
- [ ] 화면 메뉴와 대화가 **같은 구현**을 호출하는지 확인

**완료 기준**
- 기사별 그래프가 출처와 함께 표시됨
- 모든 노드·간선에서 출처 기사를 역추적 가능 (NFR-16)
- 화면 메뉴와 대화 양쪽에서 PDF·Notion 내보내기 동작
- 형식 미지정 시 되물음 (AC-016)

---

## S9 · 마무리

- [ ] CI 확장 — 서비스 컨테이너(MS-SQL, Qdrant)로 통합 테스트
- [ ] E2E 테스트 — 생성 → 조회 → 근거 확인 → 대화 → 내보내기 ([PRD Success Metrics](../REQUIREMENTS.md#36-success-metrics))
- [ ] CD — `api`·`mcp_server` 이미지 빌드 → GHCR 푸시
- [ ] `README.md` — 아키텍처, 실행 절차, CI 배지
- [ ] 클린 클론 재현 테스트 — `docker compose --profile full up -d` 한 줄 (NFR-13, 모드 B)
- [ ] ADR 정리

**완료 기준**
- PR에서 lint·unit·integration·e2e·web 잡 모두 초록불
- 태그 push 시 GHCR에 이미지 게시
- 클린 클론에서 `docker compose --profile full up -d` 로 기동

> CI에서 MS-SQL을 서비스 컨테이너로 띄우는 것이 이 스프린트의 학습 지점이다. 로컬은 네이티브, CI는 컨테이너인 이중 구성을 다루게 된다.

---

## 사용자 직접 처리 항목

| 항목 | 필요 시점 |
|---|---|
| 원본 데이터 투입 (`data/raw/`) | S2 이전 |
| 선정된 시드 토픽·정답 사건 검토(선택) | S2 전처리 구현 전 |
| Notion 통합 토큰 발급 | S8 이전 |
