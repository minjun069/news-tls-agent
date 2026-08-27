# 개발 로드맵 — news-tls-agent

관련 PRD: [`REQUIREMENTS.md`](REQUIREMENTS.md)

각 스프린트는 **완료 시점에 동작하는 상태**로 끝난다. 중간에 멈춰도 버려지는 산출물이 없도록 순서를 잡았다.

---

## 의존 관계

```
S1 기반 ─┬─ S2 데이터 계층 ─┬─ S4 MCP 서버 ─ S5 생성 ─ S6 API ─┬─ S7 프론트 ─ S9 마무리
         └─ S3 벡터 계층  ─┘                                   └─ S8 그래프·내보내기 ─┘
```

---

## S1 · 기반 구축

### S1-1 프로젝트 초기화
- [x] GitHub 리포 `news-tls-agent` 생성
- [x] 디렉토리 스켈레톤 (`AGENTS.md` §2), `.env.example`, `.gitignore`
- [x] `backend/pyproject.toml` — `backend/`가 Python 소스 루트이며 자체 패키지는 아니다
- [x] `CLAUDE.md` — `@AGENTS.md` 한 줄
- [x] `data/raw/.gitkeep` — 원본 데이터 투입 위치

### S1-2 개발 하네스
- [x] `AGENTS.md` — 코드 컨벤션, 디렉토리 구조, 검증 명령, 금지사항
- [x] ruff 규칙이 §3 컨벤션을 강제 (ANN·I002·G·BLE/TRY·N·S)
- [x] **import-linter 계약이 §1 경계와 §2.1 계층을 강제** — 계약 5개
- [x] `Makefile` — `make check`가 커밋 전 게이트
- [x] `.claude/settings.json` — 권한 allowlist
- [x] 편집 후 검사 훅 (`.claude/hooks/on-edit.sh`, exit 2로 에이전트에 피드백)
- [x] **가드 검증** — 일부러 위반을 넣어 5개 계약과 8개 린트 규칙이 잡는 것을 확인
- [x] **문서 토큰 예산 확인** — 현재 2,744 / 3,000 토큰 (PRD §3.4)

> 계층 계약을 코드가 0줄일 때 도입한 이유: 위반이 없는 상태에서 켜면 통과하지만,
> 코드가 쌓인 뒤 켜면 그때부터는 리팩터링이다.

### S1-3 CI 골격
- [x] `.github/workflows/backend.yml` — ruff, pytest, **계층 규칙 검사** (`AGENTS.md` §2.1)
- [x] `main` 브랜치 보호 (PR 필수, `check` 잡을 required status check으로 지정)

> `web.yml`은 S7로 미룬다. `web/`이 비어 있는 동안 만들면 아무것도 검사하지 않는
> 워크플로가 된다 — 게이트가 한 번도 울리지 않으면 게이트가 없는 것과 같다.

> CI를 지금 붙이는 이유: 코드가 쌓인 뒤 도입하면 이미 깨진 상태에서 시작한다.

### S1-4 인프라 기동
- [x] SQL Server Developer Edition + SSMS 설치, **TCP/IP 프로토콜 활성화**
- [x] ODBC Driver 18 확인, DB `newsagent` 생성
- [x] Docker Desktop 설치
- [x] `docker-compose.yml` — `qdrant`(기본) · `mssql`(profile `full`), 이후 서비스는 해당 스프린트에서 추가
- [x] `.env.example` — 모드 A/B/C 접속 정보 (TECH_DESIGN §4.1)

**완료 기준**: WSL에서 pyodbc로 Windows 호스트 SQL Server 접속 성공. Qdrant 대시보드 접속 성공. 빈 스켈레톤 PR에서 CI 초록불.

---

## S2 · 데이터 계층

| 관련 | ISS-003~005, ART-001~003, NFR-08, NFR-09, NFR-02 |
|---|---|

- [x] `backend/db/migrations/` — [`ERD.md`](ERD.md) 기준. 테이블 6개, 인덱스 7종
- [x] `backend/db/migrate.sh` — 미적용 번호만 실행, 스크립트당 트랜잭션
- [x] `000_bootstrap.sql` — 멱등. `CREATE DATABASE ... COLLATE` + `schema_migrations`
- [x] `scripts/01_extract_seed.py` — 원본 → 시드 JSONL
- [x] `scripts/02_load_mssql.py` — 배치 upsert, 멱등성
- [x] `core/models.py`·`core/ports.py` — 데이터 모델과 Repository Protocol
- [x] `infra/db.py`·`infra/entities.py` — 엔진, 세션, ORM
- [x] `infra/repository.py` — ports 구현
- [x] `core/ranking.py` — 대표 기사 선정 3단 타이브레이커 (PRD §7.1). 순수 함수
- [x] `tests/unit/test_ranking.py` · `tests/integration/test_repository.py`

**완료 기준**
- [x] 이슈 → 이벤트 → 기사 3단 조인 질의 동작
- [x] **역방향 조회**("기사 X가 인용된 이슈") 동작
- [x] 대표 기사 선정이 결정론적 (같은 입력 → 같은 결과)
- [ ] 실제 시드 적재 후 SSMS 실행계획에서 인덱스 사용 확인
- [x] 저장 중 외래키 예외 발생 시 부분 데이터 잔존 없음

> 사용자 선행 작업: 원본 데이터를 `data/raw/`에 투입하고 시드 토픽 2~3개를 선정해야 한다.

---

## S3 · 벡터 계층

| 관련 | NFR-04, NFR-05, ADR-0003 |
|---|---|

- [ ] Qdrant `articles` 컬렉션 생성 (Cosine, payload 4종)
- [ ] `scripts/03_build_vectors.py` — 임베딩 적재, 배치·재시도
- [ ] `infra/qdrant.py`·`infra/embedding.py`
- [ ] `core/ranking.py` — RRF 결합 (순수 계산)
- [ ] `app/search.py` — 3종 검색 유스케이스
- [ ] 기간 필터를 검색 단계에서 적용
- [ ] `tests/unit/test_ranking.py` — RRF 단위 테스트 (컨테이너 불필요)

**완료 기준**
- 세 방식이 각각 호출 가능하고 결과가 다름
- 기간 필터가 벡터 검색 단계에서 적용됨

---

## S4 · MCP 서버

| 관련 | CHAT-002, NFR-06, NFR-12, EX-06, ADR-0001 |
|---|---|

- [ ] `mcp_server/server.py`·`mcp_server/tools/` — FastMCP
- [ ] 툴 5종 + **description 문구** ([`MCP_TOOLS.md`](MCP_TOOLS.md) §7 작성 규칙)
- [ ] 응답 규약 `{ok, ...}` / `{ok:false, error:{code,message}}` ([`MCP_TOOLS.md`](MCP_TOOLS.md))
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

가장 복잡한 스프린트다. LLM 호출이 8종 들어간다 ([`AI_SPEC.md`](AI_SPEC.md) §2).

- [ ] `core/models.py`·`core/errors.py` — 도메인 스키마와 예외
- [ ] P1 질의 의도 해석 + 되묻기
- [ ] P2 가상 타임라인 생성
- [ ] P3 검색 쿼리 생성 (방식 선택 포함)
- [ ] P4 핵심 이벤트 선정 (배치 판정)
- [ ] P5 선후 이벤트 추출
- [ ] P6 충분성 검토
- [ ] P7 가상 이벤트 생성
- [ ] P8 타임라인 병합
- [ ] 수집 루프 오케스트레이션 + **종료 조건 4가지** (PRD §7.2)
- [ ] 인용 검증 → 트랜잭션 저장
- [ ] 파이프라인 실행 로그 (NFR-14)
- [ ] CLI 진입점
- [ ] `app/pipeline.py` — 수집 루프 오케스트레이션
- [ ] `tests/unit/test_pipeline.py` — LLM 모킹. 허구 ID 주입, 무한 루프 방지

**완료 기준**
- CLI로 토픽 입력 시 MS-SQL에 이슈·이벤트·기사연결 저장
- 허구 ID를 반환하는 모의 LLM으로도 미실재 기사가 저장되지 않음
- **가상 이벤트가 최종 결과에 포함되지 않음** ([`AI_SPEC.md`](AI_SPEC.md) §5.1)
- 종료 조건 4가지가 각각 동작 (모의 LLM으로 검증)
- 검색 0건 시 근거 없는 이슈가 저장되지 않음 (EX-01, EX-02)

> **선행 검증**: 착수 직후 Gemini 구조화 출력과 도구 호출 최소 예제를 먼저 확인한다 (PRD §8).

---

## S6 · API 서버

| 관련 | ISS-001~006, ART-002, CHAT-001~006, NFR-07, EX-06 |
|---|---|

- [ ] `api/main.py`·`api/routes/` — FastAPI, CORS, `/health`
- [ ] `api/deps.py` — **core ← infra 주입 지점**
- [ ] `infra/mcp_client.py` — `langchain-mcp-adapters`
- [ ] `app/agent.py` — LangGraph 그래프. `core.ports` 타입으로 주입받는다
- [ ] 출처 구분 응답 (CHAT-004) — `token` 이벤트의 `source` 필드
- [ ] 엔드포인트 ([`API.md`](API.md))
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

| 관련 | 전 기능. 화면 기준은 [`SCREENS.md`](SCREENS.md) |
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
- [ ] P9 엔티티·관계 추출 ([`AI_SPEC.md`](AI_SPEC.md) §2.10)
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
- [ ] E2E 테스트 — 생성 → 조회 → 근거 확인 → 대화 → 내보내기 (PRD §3.4)
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
| 시드 토픽 2~3개 선정 | S2 이전 |
| Notion 통합 토큰 발급 | S8 이전 |
