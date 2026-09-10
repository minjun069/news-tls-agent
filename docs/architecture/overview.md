# 기술 설계서 — news-tls-agent

관련 PRD: [`REQUIREMENTS.md`](../REQUIREMENTS.md)

> PRD가 **무엇을 만드는가**를 정의한다면, 이 문서는 **어떻게 만드는가**를 담는다.
> 구현 방식·최적화·파라미터는 PRD가 아니라 여기에 기록한다.

---

## 1. 아키텍처

```
┌──────────────────────────────────────────────┐
│  web/   Vue 3 + Vite + TS                     │
│    이슈 목록 · 타임라인 · 브리핑 · 대화 · 그래프│
└───────────────┬──────────────────────────────┘
                │ REST + SSE
                ▼
┌──────────────────────────────────────────────┐
│  api/   FastAPI                               │
│    · REST 엔드포인트                          │
│    · SSE 스트리밍 (에이전트 응답, 생성 진행)   │
│    · 에이전트 루프 (LangGraph ReAct + Gemini) │
│    · 타임라인 생성 파이프라인                  │
│    · MCP 클라이언트                            │
└───────────────┬──────────────────────────────┘
                │ MCP (stdio)
                ▼
┌──────────────────────────────────────────────┐
│  mcp_server/   MCPServer (Python SDK v2)      │
│    search_articles · read_article             │
│    list_issues · get_issue · export_briefing  │
│    ※ LLM 호출 없음. 데이터 접근 계약 + 감사점  │
└──────┬─────────────────────────┬─────────────┘
       ▼                         ▼
┌─────────────┐          ┌──────────────┐
│  MS-SQL     │          │   Qdrant     │
│  (네이티브)  │          │  (컨테이너)   │
│ 기사·이슈    │          │ dense·BM25   │
│ 엔티티·관계  │          │              │
└─────────────┘          └──────────────┘
```

### 1.1 계층 책임

| 계층 | 책임 | 하지 않는 것 |
|---|---|---|
| web | 표시, 사용자 입력 | LLM·저장소를 알지 못함 |
| api | 에이전트 오케스트레이션, 파이프라인, 세션 없는 REST/SSE | 저장소에 직접 접근하지 않음 |
| mcp_server | 데이터 접근 계약, 검색, 감사 로그 | **LLM을 호출하지 않음** |
| MS-SQL | 기사·이슈·엔티티·관계 원본 | — |
| Qdrant | dense 의미 벡터, sparse BM25, 페이로드 필터 | 원문 보관하지 않음 |

### 1.2 의존 방향

`web → api → mcp_server → 저장소` 단방향. 역방향 의존을 금지한다.

관련 결정: [ADR-0001](../decisions/0001-mcp-data-access.md)

### 1.3 인프라 구성 근거

| 구성요소 | 방식 | 근거 |
|---|---|---|
| MS-SQL | Developer Edition 네이티브 + SSMS | 국내 SI·ERP 현장의 실제 배포 형태 |
| Qdrant | Docker 컨테이너 | Qdrant의 표준 배포 형태. 로컬 파일 모드는 프로토타입용 |

관련 결정: [ADR-0002](../decisions/0002-mssql-native-qdrant-container.md)

---

## 2. 기술 스택

| 구분 | 선택 | 비고 |
|---|---|---|
| FE | Vue 3 + Vite + TypeScript | 메타프레임워크 없음. SSR 불필요 |
| BE | FastAPI (Python) | SSE 스트리밍 |
| DB | MS-SQL Server Developer Edition | 로컬 네이티브 설치 |
| DB 드라이버 | SQLAlchemy + pyodbc (ODBC Driver 18) | |
| Vector DB | Qdrant | Docker 컨테이너 |
| Search Engine | Qdrant BM25 · dense 벡터 · core RRF **3종 모두 구현** | 에이전트가 선택하거나 전부 수행 (NFR-04) |
| AI | Google Gemini (`gemini-3.6-flash`) | 보유 키와 실제 API 가용성 기준 |
| Embedding | 로컬 `nlpai-lab/KURE-v1` (Gemini 선택 가능) | CPU 실측으로 1,024차원·정규화 계약 채택, [ADR-0008](../decisions/0008-local-kure-embedding.md) |
| Agent | LangGraph 기반 LangChain `create_agent` | MCP 도구 호출·토큰 스트리밍 |
| MCP | `mcp` v2 (`MCPServer`, `ClientSession`) + LangChain 도구 브리지 | stdio 전송, [ADR-0006](../decisions/0006-mcp-v2-langchain-tool-bridge.md) |
| PDF 생성 | `fpdf2` + 환경별 한글 TTF 포함 | EXP-001 |
| Notion 연동 | 공식 `notion-client` | EXP-002 |
| 그래프 시각화 | Vue 네이티브 SVG 원형 배치 | GRPH-001 |
| Authentication | 없음 | 단일 사용자 전제 |
| Cache | 없음 | 이슈 재사용은 DB 조회로 처리 |
| Queue | 없음 | 생성이 짧아 작업 큐 불필요 |
| 품질 | ruff, pytest, vue-tsc | |
| CI/CD | GitHub Actions + GHCR | |

---

## 3. 비기능 요구사항

### 3.1 성능

#### NFR-01 · 타임라인 생성 시간
생성 요청부터 완료까지 3분 이내에 끝난다.

- 우선순위: Should
- 기준 조건: 시드 데이터 규모([PRD MVP 범위](../REQUIREMENTS.md#34-mvp-범위)), 외부 API 정상 응답
- 관련: ISS-001

수집 루프 기본 상한은 4라운드, 선후 이벤트 연쇄 깊이 2, 라운드당 검색 결과 20건이다. P1
되묻기는 2회까지 허용한다. `TIMELINE_MAX_ROUNDS`, `TIMELINE_MAX_CHAIN_DEPTH`,
`TIMELINE_SEARCH_TOP_K`, `TIMELINE_MAX_CLARIFICATIONS` 환경변수가 이 값을 덮어쓰며 모두 1
이상이어야 한다. 기본값은 종료 조건 네 가지를 모의 LLM으로 각각 실행하는 단위 테스트의
기준이기도 하다.

#### NFR-02 · 조회 응답 시간
이슈 목록 및 상세 조회는 1초 이내에 응답한다.

- 우선순위: Should
- 관련: ISS-004, ISS-005

#### NFR-03 · 첫 응답 지연
대화 요청 후 5초 이내에 첫 출력(도구 호출 표시 포함)이 시작된다.

- 우선순위: Could
- 관련: CHAT-005

### 3.2 검색

#### NFR-04 · 검색 방식
기사 검색은 아래 세 가지를 모두 구현하고, 에이전트가 상황에 맞게 선택하거나 전부 수행한다.

| 방식 | 내용 |
|---|---|
| 키워드 검색 | BM25. 키워드 선정 후 OR / AND 조합 |
| 의미 검색 | 문장 생성 후 벡터 유사도 |
| 결합 검색 | 위 둘을 RRF(Reciprocal Rank Fusion)로 결합 |

- 우선순위: Must
- 검증: 세 방식이 각각 호출 가능하고, 에이전트가 방식을 선택한 기록이 남음
- 관련: CHAT-002, [타임라인 요구사항](../requirements/timeline.md), [ADR-0003](../decisions/0003-search-strategies.md)

BM25와 의미 검색은 공급자별 Qdrant 컬렉션의 sparse `bm25`와 dense `dense` named vector로
구현한다. 로컬 기본 컬렉션은 `articles_kure_v1`이고 기존 Gemini `articles`는 보존한다. 두
검색 결과는 core 타입으로 변환한 뒤 애플리케이션의 순수 RRF 함수로 결합한다.
상세 결정은 [ADR-0005](../decisions/0005-qdrant-dense-sparse-search.md)와 dense 공급자를 보완한
[ADR-0008](../decisions/0008-local-kure-embedding.md)을 따른다.

> 한 방식으로 고정하지 않는 이유: 뉴스 도메인은 고유명사·날짜처럼 정확 일치가 필요한 질의와, 표현이 다른 개념 질의가 섞여 있다. 어느 하나가 항상 낫지 않다.

#### NFR-05 · 기간 필터
기사 검색은 서비스 일자 범위로 결과를 제한할 수 있다. 필터는 검색 단계에서 적용한다.

- 우선순위: Should
- 비고: 검색 후 필터링하면 상위 k개가 걸러져 결과가 빌 수 있다
- 관련: [타임라인 요구사항](../requirements/timeline.md) 가상 타임라인 기간

### 3.3 로깅 및 모니터링

#### NFR-06 · 데이터 접근 감사 로그
MCP 툴 호출은 호출 시각, 툴 이름, 인자, 결과 건수가 기록된다.

- 우선순위: Must
- 관련: CHAT-002, AC-011, [ADR-0001](../decisions/0001-mcp-data-access.md)

#### NFR-07 · 헬스체크
각 저장소의 연결 상태를 조회할 수 있는 엔드포인트를 제공한다.

- 우선순위: Should
- 관련: EX-06

#### NFR-14 · 파이프라인 실행 로그
타임라인 생성의 각 단계와 라운드 진행을 로그로 남긴다.

- 우선순위: Should
- 공통 기록 항목: 실행 ID, 모델명, 응답 타입
- 타임라인 기록 항목: P1 판단, P2 기간, P3 검색어·요청 기간·적용 기간, Qdrant 결과 수,
  MS-SQL 복원 수, P4 선정·탈락 기사 ID와 탈락 사유, 라운드·단계·선정 기사 수·종료 사유
- 그래프 기록 항목: 실패 기사 ID, 응답 타입, 구조 검증 오류
- 금지 항목: API 키, 기사 본문
- 목적: **동작 확인과 장애 추적.** 방식 비교를 위한 계측이 아니다
- 관련: [PRD 목표](../REQUIREMENTS.md#3-목표와-비목표) 모니터링 체계, [타임라인 종료 정책](../requirements/timeline.md#수집-루프-종료-정책)

#### NFR-15 · 에이전트 실행 로그
대화 요청의 도구 호출과 응답 완료를 로그로 남긴다.

- 우선순위: Should
- 기록 항목: 호출한 도구, 호출 횟수, 응답 완료 여부
- 관련: [PRD 목표](../REQUIREMENTS.md#3-목표와-비목표) 모니터링 체계

### 3.4 데이터 무결성

#### NFR-08 · 저장 원자성
이슈·이벤트·기사연결은 단일 트랜잭션으로 저장한다. 부분 저장을 허용하지 않는다.

- 우선순위: Must
- 관련: EX-05

#### NFR-09 · 참조 무결성
이벤트-기사 연결은 외래키로 강제한다. 존재하지 않는 기사를 참조할 수 없다.

- 우선순위: Must
- 관련: AC-008

#### NFR-16 · 그래프 요소 추적성
지식 그래프의 모든 노드와 간선은 어느 기사에서 추출됐는지 추적할 수 있다.

- 우선순위: Must
- 검증: 임의의 노드·간선에서 출처 기사 ID를 역추적할 수 있음
- 관련: GRPH-001, [지식 그래프 요구사항](../requirements/knowledge-graph.md)

> §2.2의 신뢰성 요건은 타임라인뿐 아니라 그래프에도 적용된다. 출처를 잃은 관계는 근거 없는 서술과 같다.

### 3.5 보안 및 개인정보

#### NFR-10 · 자격증명 관리
API 키와 DB 접속 정보는 환경변수로만 주입한다. 저장소에 커밋하지 않는다.

- 우선순위: Must

#### NFR-11 · 개인정보
사용자 개인정보를 수집하지 않는다. 기사 본문에 등장하는 인물명은 원문 그대로 보관한다.

- 우선순위: Must

### 3.6 확장성

#### NFR-12 · 확장 대비
데이터 접근을 MCP 서버로 단일화해, 클라이언트가 늘어도 접근 계층을 재구현하지 않는다.

- 우선순위: Should
- 검증: MCP Inspector와 API 서버 두 클라이언트가 같은 서버에 연결

> 가용성·백업은 **범위 밖**이다. 운영 배포 대상이 없다.

### 3.7 재현성

#### NFR-13 · 클린 클론 기동
클론 후 아래 한 줄로 서비스 전체가 기동된다.

```bash
docker compose --profile full up -d
```

- 우선순위: Must
- 검증 기준은 **모드 B**(§6)다. 일상 개발 모드가 아니라 전체 컨테이너 구성으로 판정한다
- 데이터 적재는 별도 절차다: `backend/db/migrate.sh` → `scripts/01~03`

---

## 4. 실행 모드

세 가지 모드가 있다. **기본은 A**이며, NFR-13의 검증 기준은 B다.

| 모드 | 앱 | 저장소 | 용도 | 기동 |
|---|---|---|---|---|
| **A. 개발** | 로컬 프로세스 | MS-SQL 네이티브 + Qdrant 컨테이너 | 핫리로드 | `docker compose up -d` |
| **B. 전체 컨테이너** | 컨테이너 | 전부 컨테이너 | 클린 클론 검증·데모 | `docker compose --profile full up -d` |
| **C. CI** | 러너 | 서비스 컨테이너 | 통합 테스트 | GitHub Actions |

`docker-compose.yml`에서 `qdrant`만 프로필이 없고, `mssql`·`api`·`mcp`·`web`은 `full` 프로필에 속한다.
따라서 모드 A에서는 Qdrant만 뜬다 — ADR-0002의 "MS-SQL은 네이티브"가 유지된다.

모드 B의 API와 독립 MCP 컨테이너는 `embedding-models` 볼륨을 `/app/models`에 함께 마운트한다.
KURE-v1을 한 컨테이너가 처음 내려받은 뒤 다른 컨테이너와 재기동에서도 같은 모델 캐시를 쓴다.

모드 B에서는 `migrate`가 MS-SQL 헬스 통과 뒤 스키마를 적용하고 성공 종료한 다음 `api`와
`mcp`가 시작한다. `web`은 API 헬스 통과 뒤 시작한다. API 컨테이너는 stdio MCP 모듈을 자식
프로세스로 실행하고, 독립 `mcp` 컨테이너는 Inspector 같은 별도 stdio 클라이언트가 같은
이미지를 사용할 수 있음을 보장한다. 두 실행 역할의 경계는
[ADR-0007](../decisions/0007-stdio-mcp-container-packaging.md)을 따른다.

### 4.1 접속 정보

WSL에서 개발하므로 모드에 따라 호스트가 달라진다. `.env.example`에 두 벌을 모두 적는다.

| | 모드 A (WSL) | 모드 B (compose) | 모드 C (CI) |
|---|---|---|---|
| MS-SQL | Windows 호스트 IP | `mssql` | `localhost` |
| Qdrant | `localhost:6333` | `qdrant:6333` | `localhost:6333` |

WSL2는 별도 네트워크라 Windows 호스트의 SQL Server에 `localhost`로 닿지 않는다.

### 4.2 collation 고정

네이티브 설치와 리눅스 컨테이너의 기본 collation이 다르다. 한글 정렬뿐 아니라 `NVARCHAR` 비교와 `LIKE` 동작이 달라져, **로컬은 통과하고 CI만 깨지는** 상황이 생긴다.

두 겹으로 고정한다.

- 컨테이너: `MSSQL_COLLATION` 환경변수
- `000_bootstrap.sql`: `CREATE DATABASE ... COLLATE`

### 4.3 API 프로세스 조립

`api/routes/`는 `api/providers.py`의 포트만 의존한다. `api/main.py`가 FastAPI dependency
override로 `api/deps.py` 구현을 연결하고, `api/deps.py`만 `infra`를 import한다. 따라서 라우터가
조립점을 경유해 저장소 구현에 간접 의존하는 경로도 import-linter가 차단한다.

조회·대화 요청은 `infra/mcp_client.py`가 stdio MCP 서버를 호출한다. 타임라인 생성은 S5의
`TimelinePipeline`을 요청별 진행 sink와 함께 조립하며, 동기 파이프라인은 작업 스레드에서
실행해 이벤트 루프가 SSE 진행 프레임을 계속 보낼 수 있게 한다.

S8의 그래프 조회는 타임라인 생성과 같은 애플리케이션 파이프라인이다. `app/graph.py`가 대표
기사의 본문을 P9에 전달하고 `core.ports.Repository`로 기사 단위 트랜잭션 저장을 요청한다.
라우터는 저장소 구현을 import하지 않으며 `api/deps.py`만 구현을 주입한다. 반면 내보내기 메뉴는
`export_briefing` MCP 툴을 호출한다. 따라서 대화 에이전트와 화면 메뉴가 모두 MCP 서버에서
조립한 `app/exporting.py`의 같은 브리핑 구성·변환 유스케이스를 실행한다.

---

## 5. 구현 지침

PRD에서 다루지 않는 구현 수준의 규칙이다. 사용자가 겪는 것은 달라지지 않지만, 구현 시 지켜야 한다.

### 5.1 타임라인 생성 파이프라인

| 항목 | 방침 |
|---|---|
| 적합성 판정 단위 | **배치.** 검색 결과를 한 번에 넣고 통과 기사 ID 목록을 받는다. 건당 호출은 비용이 통제되지 않는다 |
| 탈락 기사 | 이후 라운드의 재검색 대상에서 제외한다 |
| 적합성 판정 결과 | 병합 단계로 전달한다. 근거 귀속을 재계산하지 않는다 |
| 이벤트 중복 병합 | 날짜와 근거 기사 집합이 같으면 하나로 병합한다 |
| 검색 방식 선택 | 에이전트가 판단한다. 판단 결과를 로그에 남긴다 (NFR-14) |

### 5.2 에이전트

| 항목 | 방침 |
|---|---|
| 대화 세션 | 서버에 두지 않는다. 클라이언트가 이력을 보관해 매 요청에 전달한다 |
| 내보내기 의도 | **도구 호출로 처리한다.** 정규식·키워드 매칭으로 LLM 앞단에서 분류하지 않는다 |
| 컨텍스트 주입 범위 | 이번 범위에서 정하지 않는다 ([PRD MVP 범위](../REQUIREMENTS.md#34-mvp-범위)) |

> 내보내기 의도 분류를 앞단에 두지 않는 이유: 프롬프트와 코드가 같은 판단을 두 번 하면 반드시 어긋난다. 프롬프트는 "명시적 요청일 때만 도구를 쓰라"고 지시하는데 정규식이 그 요청을 먼저 가로채는 상황이 발생한다.
>
> 관련 결정: [ADR-0004](../decisions/0004-export-intent-via-tool.md)

### 5.3 내보내기

| 항목 | 방침 |
|---|---|
| 진입점 | 화면 메뉴와 대화 두 가지. **두 경로가 같은 구현을 호출한다** |
| 브리핑 구성 | 마크다운으로 먼저 만들고 형식별로 변환한다 |
| PDF | `EXPORT_DOWNLOAD_DIR`에 원자적으로 교체 저장하고 `/downloads/{file}`로 제공한다 |
| PDF 한글 글꼴 | `PDF_FONT_PATH` 또는 알려진 NanumGothic·맑은 고딕 경로의 TTF를 PDF에 포함한다 |
| Notion | 요청의 `parent_page_id`를 우선하고 없으면 `NOTION_PARENT_PAGE_ID`를 사용한다 |

### 5.4 지식 그래프

| 항목 | 방침 |
|---|---|
| 추출 단위 | **기사 단위로 저장한다.** 같은 기사가 여러 이슈에서 인용돼도 추출은 1회 |
| 추출 대상 | 대표 기사 |
| 추출 시점 | 그래프 조회 시. 미추출 기사가 있으면 그때 추출한다 |
| 그래프 구성 | 기사별로 각각 구성한다 ([지식 그래프 요구사항](../requirements/knowledge-graph.md)) |
| 화면 상한 | API는 전부 반환하고 화면은 기사당 노드 30개까지만 그리며 축소 사실을 표시한다 |

---

## 6. 배포

배포 대상 서버가 없다. CI에서 이미지 빌드·푸시까지만 수행하고 실제 배포는 하지 않는다.

| 단계 | 내용 |
|---|---|
| CI | ruff·계층·단위, MS-SQL/Qdrant 서비스 통합, 핵심 흐름 E2E, Vue 타입·빌드, 컨테이너 이미지 빌드 |
| CD | `v*` 태그 push 시 `api`·`mcp_server` 이미지 빌드 → GHCR 푸시 |

통합 테스트는 GitHub Actions 서비스 컨테이너로 MS-SQL과 Qdrant를 기동해 수행한다. 로컬은 네이티브, CI는 컨테이너인 이중 구성이다.

`backend/Dockerfile`은 공통 런타임에서 `api`, `mcp`, `migrate` 대상을 만든다. CD 이미지 이름은
`ghcr.io/<owner>/<repository>-api:<tag>`와
`ghcr.io/<owner>/<repository>-mcp-server:<tag>`다. 웹 이미지는 모드 B 재현용으로 CI에서
빌드하지만 게시 대상은 아니다. 이미지 경계와 stdio 프로세스 배치는
[ADR-0007](../decisions/0007-stdio-mcp-container-packaging.md)의 결정이다.
