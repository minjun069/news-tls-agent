# AGENTS.md — news-tls-agent

Codex는 작업을 시작하기 전에 이 문서를 읽고, §4의 작업별 문서 흐름을 따라 필요한 문서만 추가로 읽는다.

## 0. 프로젝트 개요

뉴스 아카이브를 근거로 사건 타임라인을 만들고, 각 분기점에 근거 기사를 귀속해 신뢰 가능한 형태로 제공한다.
학습 목표는 **MCP · MS-SQL · Qdrant · AI 에이전트 개발 경험**이다. 범위를 줄이더라도 이 기술을 우회하는 대체 구현은 제안하거나 추가하지 않는다.

## 1. 최상위 규칙

1. **계획·검토·설명을 요청받은 단계에서는 구현하지 않는다.** 사용자가 구현을 명시한 범위만 변경한다.
2. **실제 상태를 직접 확인한다.** 파일·원본 데이터·DB·컨테이너·서비스의 존재나 상태를 `git status`로 추론하지 않는다. 대상 자체를 확인하지 않았으면 “없음”이 아니라 “미확인”으로 보고한다.
3. **에이전트는 저장소에 직접 접근하지 않는다.** 런타임 데이터 접근은 MCP 서버를 경유한다. MCP 장애 시 직접 조회로 우회하지 않는다.
4. **MCP 서버는 LLM을 호출하지 않는다.** 검색·조회·저장 계약과 감사 지점만 담당한다.
5. **프론트엔드는 DB·LLM을 알지 못한다.** API 서버만 호출한다.
6. 요구사항에 없는 기능, 임시 대체 DB, 학습 목표를 미루는 관통 슬라이스를 추가하지 않는다.
7. 구조·계약·규칙을 바꾸면 같은 변경에서 해당 문서와 기계 검사를 함께 갱신한다.

근거: [ADR-0001](docs/decisions/0001-mcp-data-access.md)

## 2. 프로젝트 디렉터리

아래는 목표 구조다. 아직 없는 파일은 [로드맵](docs/engineering/roadmap.md)의 해당 스프린트에서 만든다. 새 최상위 디렉터리나 새 계층이 필요하면 이 트리와 아키텍처 문서를 먼저 갱신한다.

```text
news-tls-agent/
├─ AGENTS.md                 Codex가 항상 읽는 상위 규칙·프로젝트 지도
├─ README.md                 클린 클론·로컬 기동 절차
├─ Makefile                  개발·검증 명령의 단일 진입점
├─ docker-compose.yml        qdrant(기본) · 전체 실행(profile: full)
├─ .env.example
├─ .codex/
│  └─ hooks.json             Codex 생명주기와 범용 하네스 연결
├─ .harness/                 도구에 종속되지 않는 검증·문서 라우팅
│  ├─ doc-routes.json
│  ├─ doc-review.json       계약 변경 없음 검토의 파일 해시·근거
│  ├─ route_docs.py
│  ├─ check_doc_sync.py
│  ├─ check_markdown_links.py
│  ├─ report_agent_budget.py
│  └─ on-edit.sh
├─ .github/workflows/
│  ├─ backend.yml
│  └─ web.yml                S7에서 추가
├─ data/
│  └─ raw/                   원본 JSONL, Git 제외, 사용자 투입
├─ docs/
│  ├─ INDEX.md               전체 문서 목차와 단일 원천
│  ├─ REQUIREMENTS.md        문제·목표·범위·사용자·기능 목차
│  ├─ requirements/          기능별 요구사항·AC·정책·예외
│  │  ├─ timeline.md
│  │  ├─ issue-view.md
│  │  ├─ chat.md
│  │  ├─ export.md
│  │  └─ knowledge-graph.md
│  ├─ architecture/
│  │  └─ overview.md         실행 토폴로지·기술 스택·NFR
│  ├─ data/
│  │  ├─ source-and-ingestion.md
│  │  └─ schema.md           ERD·대표 질의·트랜잭션 경계
│  ├─ contracts/
│  │  ├─ http-api.md         프론트엔드가 사용하는 HTTP/SSE 계약
│  │  └─ mcp-tools.md        에이전트가 사용하는 MCP 툴 계약
│  ├─ ai/
│  │  └─ specification.md    프롬프트·생성·검색·근거 전략
│  ├─ product/
│  │  └─ screens.md          화면 흐름·표기 정책
│  ├─ engineering/
│  │  ├─ roadmap.md
│  │  ├─ agent-workflow.md
│  │  ├─ code-conventions.md
│  │  ├─ git-workflow.md
│  │  └─ validation.md
│  └─ decisions/             채택된 ADR; 본문 수정 금지
├─ backend/                  Python 소스 루트
│  ├─ pyproject.toml         의존성·ruff·pytest·import-linter 계약
│  ├─ core/                  도메인 타입·포트·순수 계산
│  │  ├─ config.py
│  │  ├─ models.py           Pydantic 도메인 모델
│  │  ├─ errors.py
│  │  ├─ ports.py            Repository·VectorStore·LLM·ToolClient
│  │  └─ ranking.py
│  ├─ app/                   유스케이스·오케스트레이션
│  │  ├─ pipeline.py
│  │  ├─ agent.py            LangGraph 그래프
│  │  └─ search.py
│  ├─ infra/                 SQLAlchemy·Qdrant·Gemini·MCP 클라이언트
│  │  ├─ db.py
│  │  ├─ entities.py
│  │  ├─ repository.py
│  │  ├─ qdrant.py
│  │  ├─ embedding.py
│  │  └─ mcp_client.py
│  ├─ api/                   FastAPI HTTP 어댑터·조립
│  │  ├─ main.py
│  │  ├─ deps.py             core ← infra 주입 지점
│  │  └─ routes/
│  ├─ mcp_server/            MCP 어댑터·조립
│  │  ├─ server.py
│  │  └─ tools/
│  ├─ db/                    migrate.py·migrate.sh·schema.sql·migrations/
│  ├─ scripts/               01_validate_raw·02_load_mssql·03_build_vectors
│  └─ tests/
│     ├─ unit/               컨테이너 불필요
│     └─ integration/        MS-SQL·Qdrant 필요
└─ web/                      Vue 3 + Vite + TypeScript
```

## 3. 아키텍처 경계

의존 방향은 `api·mcp_server → app → core`, `infra → core`다. `app`은 `infra`를 import하지 않고 `core.ports` 타입으로 의존성을 받는다.

- `core`: DB·웹·에이전트 프레임워크와 I/O를 모른다. **Pydantic은 도메인 검증·불변 모델 용도로 허용한다.**
- `app`: LangGraph 사용 가능. FastAPI·Starlette와 `infra` 직접 import 금지.
- `infra`: `app`·`api`·`mcp_server` 참조 금지.
- `infra` import 허용 조립점: `api/deps.py`, `mcp_server/server.py`, `scripts/`, `tests/integration/`.
- SQL은 `infra/repository.py`와 `backend/db/`의 마이그레이션·관리 스크립트에서만 작성한다.

상세: [아키텍처](docs/architecture/overview.md), [코드 컨벤션](docs/engineering/code-conventions.md). 기계 검사는 `backend/pyproject.toml`의 import-linter·ruff 계약이다.

## 4. 작업 종류별 문서 흐름

모든 작업은 시작과 종료에 `작업 단위 시작·종료` 행을 적용하고, 구현 전에는 해당 작업 종류의 행을 추가로 적용한다. 같은 단계에서 겹치는 문서는 한 번만 읽는다. 예를 들어 전처리 작업은 시작 시 로드맵·타임라인 요구사항·검증 문서를 확인하고, 구현 전에는 이미 읽은 타임라인 요구사항을 제외한 수집·적재 문서와 스키마 문서를 이어서 읽으며, 종료 시 로드맵 완료 기준과 검증 결과를 다시 대조한다.

구현 파일이 정해지면 `python3 .harness/route_docs.py <경로...>`를 실행한다. 이 명령은 변경할 파일 경로를 `.harness/doc-routes.json`과 대조해, 그 파일의 입력·출력 형식이나 외부 동작을 정의하는 계약 문서 경로를 출력한다. 에이전트는 출력된 문서를 실제로 읽고 변경이 계약에 영향을 주는지 판정한다. 작업 종류별 문서 흐름을 대신하는 명령이 아니다.

| 작업 종류 | 읽는 순서 |
|---|---|
| 작업 단위 시작·종료 | `docs/engineering/roadmap.md` → 해당 기능 요구사항 → `docs/engineering/validation.md` |
| 요구사항·범위 변경 | `docs/REQUIREMENTS.md` → `docs/requirements/<기능>.md` → 영향받는 계약·화면 문서 |
| 원본 데이터·전처리·적재 | `docs/requirements/timeline.md` → `docs/data/source-and-ingestion.md` → `docs/data/schema.md` |
| MS-SQL·Repository·마이그레이션 | `docs/data/schema.md` → `docs/data/source-and-ingestion.md` → `docs/architecture/overview.md` |
| 벡터 적재·검색 | 해당 기능 요구사항 → `docs/ai/specification.md` §4 → `docs/decisions/0003-search-strategies.md` |
| 타임라인 생성 AI | `docs/requirements/timeline.md` → `docs/ai/specification.md` §2·§5 → `docs/architecture/overview.md` |
| 대화 에이전트 | `docs/requirements/chat.md` → `docs/ai/specification.md` §3·§5 → `docs/contracts/mcp-tools.md` |
| MCP 서버·툴 | 해당 기능 요구사항 → `docs/contracts/mcp-tools.md` → `docs/decisions/0001-mcp-data-access.md` |
| HTTP API·SSE | 해당 기능 요구사항 → `docs/contracts/http-api.md` → `docs/data/source-and-ingestion.md`의 상태값 |
| 프론트엔드 | `docs/product/screens.md` → 해당 기능 요구사항 → `docs/contracts/http-api.md` |
| PDF·Notion 내보내기 | `docs/requirements/export.md` → HTTP·MCP 계약 → `docs/decisions/0004-export-intent-via-tool.md` |
| 지식 그래프 | `docs/requirements/knowledge-graph.md` → `docs/data/schema.md` → AI·HTTP·화면 문서 |
| 하네스·CI·검증 | `docs/engineering/agent-workflow.md` → `docs/engineering/validation.md` → `docs/engineering/git-workflow.md` |
| 구조·의존 경계 변경 | 이 문서 §2·§3 → `docs/architecture/overview.md` → 관련 ADR |
| 커밋·PR | `docs/engineering/git-workflow.md` → `docs/engineering/validation.md` |

전체 목차와 단일 원천은 [docs/INDEX.md](docs/INDEX.md), 코드 경로별 계약은 [.harness/doc-routes.json](.harness/doc-routes.json)을 따른다.

## 5. 작업·검증 규칙

- 작업 전 요구사항 ID 또는 Project Goal, 지금 필요한 이유, 산출물 위치를 확인한다. 셋 중 하나라도 없으면 제안하지 않는다.
- 파일은 실제 경로·크기·내용을, 데이터는 실제 스키마·행 수·표본 파싱을, DB는 카탈로그·쿼리를, 컨테이너는 실행·헬스 상태를 확인한다. Git은 추적 여부와 이력 확인에만 쓴다.
- 구현 후 변경 파일을 직접 다시 읽고 `make check`를 실행한다. 통합 자원이 필요한 변경은 관련 통합 검사도 실행한다.
- 문서에 변경 이력 표를 두지 않는다. 이력은 Git이 갖는다. 채택된 ADR을 바꾸려면 새 ADR로 대체·보완한다.
- 커밋·PR 규칙은 [Git 워크플로](docs/engineering/git-workflow.md), 코드 규칙은 [코드 컨벤션](docs/engineering/code-conventions.md)을 따른다.
- `S<n>` 종료 보고에는 문제·미검증·사용자 작업·검증 결과를 적고, 없으면 **없음**이라고 쓴다.
- 문제나 미검증 사항은 대상 파일·실행 명령·오류 원문을 정확히 인용하고, **무엇이 문제인지 · 왜 해결하지 못했는지 · 이미 시도한 조치 · 사용자에게 필요한 작업**을 구분해 보고한다. 사용자 작업이 필요 없으면 **사용자 작업 없음**이라고 쓴다.
- 결론뿐 아니라 개념, 필요한 이유, 이 프로젝트에서 작동하는 시점·방식을 설명한다. 처음 쓰는 용어는 풀어 쓴다.
- “추가 확인”, “직접 계약”, “가드레일” 같은 추상 표현만으로 설명을 끝내지 않는다. **누가 · 언제 · 어떤 입력으로 · 어느 파일이나 명령이 · 무엇을 확인하고 · 그 결과 다음 행동이 어떻게 달라지는지**를 실제 경로 또는 예시와 함께 설명한다.

AGENTS.md 목표 예산은 현재 고정하지 않는다. `make agent-budget` 측정값을 본 뒤 사용자가 결정한다.
