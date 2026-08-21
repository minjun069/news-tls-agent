# AGENTS.md — news-tls-agent

작업 전에 이 문서를 읽는다. 상세는 `docs/`를 참조한다.

## 1. 아키텍처 경계 — 위반 금지

이 프로젝트의 존재 이유가 이 경계다. 편의를 위해 넘지 않는다.

- **에이전트는 저장소에 직접 접근하지 않는다.** 모든 데이터 접근은 MCP 서버 경유
- **MCP 서버는 LLM을 호출하지 않는다.** 검색·조회만 한다
- **프론트엔드는 DB·LLM을 알지 못한다.** API 서버만 호출한다

MCP 서버가 죽어도 저장소 직접 조회로 우회하지 않는다. 장애 시 우회를 한 번 허용하면 그 경로가 영구화된다.

근거: [ADR-0001](docs/decisions/0001-mcp-data-access.md)

## 2. 디렉토리

```
AGENTS.md              규칙 원본 (CLAUDE.md가 @로 참조)
Makefile               진입점
docker-compose.yml     qdrant(기본) · mssql·api·mcp·web(profile: full)
data/raw/              원본 (Git 제외, 사용자 투입)
docs/                  분리 문서 · decisions/

backend/
├─ core/               순수 계층. 외부 프레임워크 0
│  ├─ models.py        Pydantic 도메인 스키마
│  ├─ errors.py        도메인 예외
│  ├─ ports.py         Repository · VectorStore · LLM · ToolClient Protocol
│  └─ ranking.py       점수 결합·정렬 (RRF, 대표 기사 선정) — 순수 계산
│
├─ app/                오케스트레이션. 프레임워크를 알아도 됨
│  ├─ pipeline.py      타임라인 생성 흐름
│  ├─ agent.py         LangGraph 그래프
│  └─ search.py        검색 유스케이스
│
├─ infra/              외부 연동
│  ├─ db.py            엔진·세션
│  ├─ entities.py      SQLAlchemy ORM
│  ├─ repository.py    ports 구현
│  ├─ qdrant.py
│  ├─ embedding.py     Gemini
│  └─ mcp_client.py
│
├─ api/                HTTP 어댑터 + 조립
│  ├─ main.py
│  ├─ deps.py          ★ core ← infra 주입 지점
│  └─ routes/
│
├─ mcp_server/         MCP 어댑터 + 조립
│  ├─ server.py
│  └─ tools/
│
├─ db/                 migrate.sh · schema.sql · migrations/
├─ scripts/            01_extract_seed · 02_load_mssql · 03_build_vectors
└─ tests/              unit/ (컨테이너 불필요) · integration/

web/                   Vue 3 + Vite
```

### 2.1 계층 규칙

의존은 `api·mcp_server → app → core`, `infra → core` 한 방향이다.
`app`은 `infra`를 import하지 않고 `core.ports` 타입으로 받는다.

| 계층 | 금지 |
|---|---|
| `core` | 모든 외부 프레임워크 (fastapi · langgraph · sqlalchemy · qdrant_client · google.genai) |
| `app` | 웹 프레임워크 (fastapi · starlette), `infra` 직접 import |
| `infra` | `app`·`api` 참조 |

**`infra` import는 `api/deps.py`, `mcp_server/server.py`, `scripts/`, `tests/integration/` 에서만 허용한다.**

| 무엇을 | 어디에 |
|---|---|
| SQL 작성 | `infra/repository.py` — 다른 곳에서 쓰지 않는다 |
| 점수 계산·정렬 | `core/ranking.py` |
| 프롬프트 | `app/pipeline.py`, `app/agent.py` |
| MCP 툴 | `mcp_server/tools/` |

## 3. 코드 컨벤션

- 포맷·린트: `ruff` · 타입 힌트 필수 · `from __future__ import annotations`
- 데이터 구조는 Pydantic 모델. dict를 그대로 넘기지 않는다
- 예외를 삼키지 않는다. 로깅 후 재발생 또는 명시적 처리
- **모듈 레벨 전역 커넥션·캐시 금지.** 의존성 주입을 쓴다
- 로깅은 `logger.info("...: %s", v)` 지연 포맷

| 대상 | 규칙 |
|---|---|
| 요구사항 ID | `ISS-` `ART-` `CHAT-` `EXP-` `GRPH-` / `NFR-` `EX-` `AC-` `ADR-` |
| DB | `snake_case` |
| Python | `snake_case`, 클래스는 `PascalCase` |
| Vue | `PascalCase.vue`, Composition API + `<script setup lang="ts">` |

## 4. 명령

```bash
docker compose up -d                   # 개발: qdrant만
docker compose --profile full up -d    # 클린 클론 검증·데모 (NFR-13)
backend/db/migrate.sh                  # 미적용 마이그레이션만 실행

ruff check . && ruff format .
pytest backend/tests/unit              # 저장소 불필요
pytest backend/tests                   # 통합 포함

npx @modelcontextprotocol/inspector python backend/mcp_server/server.py
cd web && npx vue-tsc --noEmit && npm run build
```

커밋 전 `ruff check .`와 `pytest backend/tests/unit`이 통과해야 한다.

## 5. 문서 규칙

| 정보 | 단일 원천 |
|---|---|
| 기능 요구사항·우선순위·상태 | `docs/REQUIREMENTS.md` |
| 비기능 요구사항·구현 지침 | `docs/TECH_DESIGN.md` |
| **디렉토리 구조·계층 규칙** | **이 문서 §2** |
| 상태값 | `docs/DATA.md` |
| 화면 표기 | `docs/SCREENS.md` |
| 스키마 | `docs/ERD.md` + `backend/db/migrations/` |
| HTTP 계약 | `docs/API.md` |
| MCP 툴 계약 | `docs/MCP_TOOLS.md` |
| 프롬프트 | `docs/AI_SPEC.md` |

**구조를 바꾸는 변경은 같은 커밋에서 관련 문서를 갱신한다.** 이전 프로젝트에서 구조 문서가 삭제된 모듈을 계속 설명하는 상태로 방치되어, 새 세션이 매번 잘못된 전제로 시작하는 문제가 있었다.

문서에 변경 이력 표를 두지 않는다. 이력은 git이 갖는다. 결정의 배경은 `docs/decisions/`에 ADR로 남긴다. **채택된 ADR의 본문은 수정하지 않는다.**

**이 문서와 `CLAUDE.md`의 합계는 3,000 토큰을 넘지 않는다.** 매 세션 소비되므로 비대해지면 순손실이다.

## 6. 커밋

```
<type>(<요구사항 ID>): <요약>

<본문>

ADR-0003 참조
```

`feat` `fix` `refactor` `test` `docs` `chore`

## 7. 금지

| 금지 | 이유 |
|---|---|
| 에이전트에 파이썬 함수를 툴로 직접 주입 | §1 |
| MCP 서버에서 LLM 호출 | §1 |
| `core`에 외부 프레임워크 import | §2.1 |
| `app`에서 `infra` 직접 import | §2.1 |
| `infra/repository.py` 밖에서 SQL 작성 | 접근 계층 우회 |
| 모듈 레벨 전역 DB 커넥션 | 스레드 안전성 |
| API 키·접속정보 하드코딩 | NFR-10 |
| 이슈·이벤트·기사연결의 분리 저장 | 원자성 위반 (NFR-08) |
| 문자열을 반환하는 MCP 툴 | 구조화 출력 규약 위반 |
| **정규식으로 사용자 의도 분류** | [ADR-0004](docs/decisions/0004-export-intent-via-tool.md) |
| **가상 이벤트를 최종 타임라인에 포함** | 신뢰성 요건 위반 |
| 적용된 마이그레이션 파일 수정 | 되돌리기는 새 번호로 |
| 문서 없이 스키마·API 변경 | §5 |
| 요구사항에 없는 기능 추가 | 범위는 PRD가 정한다 |

## 8. 작업 시작 전

1. 어느 요구사항 ID에 대응하는가? 없으면 PRD에 먼저 추가
2. `docs/ROADMAP.md`의 어느 스프린트인가?
3. §1 경계와 §2.1 계층 규칙을 넘지 않는가?
4. 설계 결정이 필요하면 ADR을 먼저 쓴다
