# 검증 명령

`Makefile`이 실행 명령의 단일 진입점이다.

| 명령 | 검증 대상 | 시점 |
|---|---|---|
| `make install` | backend uv 환경 구성 | 최초 1회·의존성 변경 후 |
| `make web-install` | `npm ci`로 잠금 파일 기준 프론트엔드 의존성 구성 | 최초 1회·의존성 변경 후 |
| `make fmt` | Python 포맷·자동 수정 | 구현 중 |
| `make lint` | ruff 린트·포맷 | 구현 중·커밋 전 |
| `make arch` | import-linter 계층 계약 | 계층 변경·커밋 전 |
| `make test` | 컨테이너 없는 단위 테스트 + 모의 의존성 API 조립 테스트 | 구현 중·커밋 전 |
| `make test-integration` | 실제 MS-SQL·Qdrant 통합 테스트 | 데이터·검색·마이그레이션 변경 후 |
| `make test-e2e` | 생성 → 조회 → 근거 → 대화 → 그래프 → PDF 내보내기 | 사용자 흐름 변경 후 |
| `make test-all` | MS-SQL·Qdrant 포함 통합 테스트 | 데이터·검색·MCP 변경 후 |
| `make doc-sync` | 경로별 계약 문서 동반 변경·링크 | 계약 코드·문서 변경 후 |
| `make doc-ack REASON='근거'` | 계약 문서를 검토했으나 계약 변경이 없다는 파일 해시·근거 기록 | 계약 코드만 변경된 경우 |
| `make check` | lint + arch + unit + docs | 모든 커밋 전 |
| `make agent-budget` | AGENTS.md의 현재 줄·바이트·추정 토큰 | 상위 지침 변경 후; 현재 실패 기준 없음 |
| `make benchmark-embeddings MODEL='모델 ID'` | 실제 뉴스 고정 표본의 CPU 처리량·메모리·검색 결과 | 로컬 임베딩 모델·전처리 변경 전 |
| `make compose-check` | 전체 프로필 Compose 해석·필수 변수·서비스 의존 문법 | 컨테이너 구성 변경 후 |
| `make images` | `api`·`mcp`·`web` 이미지 실제 빌드 | Dockerfile·Compose 변경 후 |
| `make up` | 기본 개발 인프라(Qdrant) | 로컬 개발 |
| `make up-full` | 전체 컨테이너 모드 | 클린 클론·데모 |
| `make migrate` | 미적용 MS-SQL 마이그레이션 | DB 기동·스키마 변경 후 |
| `make mcp-inspect` | MCP Inspector CLI로 툴 5종·입력/출력 스키마 엄격 검사 | S4 이후 MCP 변경 후 |
| `make api` | FastAPI 개발 서버와 Swagger UI 기동 | S6 이후 로컬 개발 |
| `make web` | Vue 개발 서버 기동 | S7 이후 로컬 개발 |
| `make web-check` | vue-tsc + 빌드 | S7 이후 화면 변경 후 |

계약 코드가 바뀌면 `make doc-sync`는 연결된 문서가 함께 바뀌었는지 먼저 확인한다. 문서의 입력·출력·외부 동작이 그대로라면 문서를 의미 없이 수정하지 않고 `make doc-ack REASON='검토한 계약과 변경이 없는 이유'`를 실행한다. 이 명령은 대상 파일의 SHA-256 해시와 근거를 `.harness/doc-review.json`에 기록한다. 파일 내용이 다시 바뀌면 해시가 달라져 확인은 무효가 되고 `make check`가 실패한다.

CI의 `check` 잡은 `make install` 뒤 `make check`를 호출한다. `integration` 잡은 MS-SQL 2022와
Qdrant 1.19 서비스 컨테이너를 기동하고 마이그레이션 뒤 `make test-integration`을 실행한다.
`e2e` 잡은 `make test-e2e`, `images` 잡은 Compose 검사와 실제 이미지 빌드를 실행한다. 웹
워크플로의 `check` 잡은 `make web-check`를 실행한다. 각 잡이 호출할 세부 명령은 Makefile을
단일 진입점으로 사용한다.

`make up`은 `docker-compose.yml`에 고정된 Qdrant `v1.19.0`을 기동한다. S3-P3 단위 테스트는
주입한 모의 SDK client로 컬렉션·적재·검색 요청 계약을 검사하고, 실제 컨테이너와 임베딩 API는
S3-A2·A3에서 `make test-all`과 실제 요청으로 검증한다. 현재 `articles_kure_v1`은 실제 원본
178,887건과 ID가 일치하며 누락·초과·sparse-only가 0건이다. 멱등 재실행은 dense 178,887건을
모두 건너뛰고 임베딩·upsert 0건으로 끝났다. 실제 MCP의 세 검색 방식은 서로 다른 상위 목록을
반환했고, 2024년 기간으로 제한한 질의는 세 방식 모두 0건을 반환했다.

`make test-integration`의 Qdrant 검사는 실행마다 임시 컬렉션을 만들어 dense Cosine, BM25 IDF,
payload 4종, OR·AND 결합, 기간 선필터를 실제 서버에서 확인하고 종료 시 컬렉션을 삭제한다.
MS-SQL 검사는 마이그레이션·Repository 트랜잭션·역방향 조회·그래프 추적성을 실제 DB에서
확인한다.

`make test-e2e`는 외부 API 키 없이 재현되어야 하므로 Gemini 응답과 PDF 바이트 쓰기만
결정론적 대역을 쓴다. HTTP 라우터, 실제 `TimelinePipeline`, MCP payload 함수,
`KnowledgeGraphService`, 공용 `BriefingExportService`를 연결해 사용자 흐름을 한 테스트에서
확인한다. 이는 실제 MS-SQL·Qdrant 검사를 대체하지 않으며 `integration` 잡과 함께 통과해야 한다.

모드 B는 `.env`의 `GOOGLE_API_KEY`와 `MSSQL_PASSWORD`를 채운 뒤
`docker compose --profile full up -d`로 기동한다. Compose는 MS-SQL 헬스 → 마이그레이션 성공 →
API/MCP → 웹 순서로 준비한다. 실제 뉴스 적재는 서비스 기동과 별도이며
[`source-and-ingestion.md`](../data/source-and-ingestion.md)의 상태를 따른다.

`make mcp-inspect`는 `@modelcontextprotocol/inspector@2.5.0`을 고정해 사용하며 Node.js 22.19
이상이 필요하다. WSL에서는 같은 WSL 환경의 Linux용 `node`·`npx`로 실행한다.

RH-01 관측 회귀는 `backend/tests/unit/test_pipeline.py`가 한 실행 ID 아래 P1·P2·P3,
Qdrant 결과 수, MS-SQL 복원 수, P4 선정·탈락 필드를 검사한다. `test_graph.py`는 잘못된 관계
끝점이 있을 때 그래프 실행 ID, 실패 기사 ID, 응답 타입과 Pydantic 검증 오류가 남는지 검사한다.
두 검사 모두 API 키와 기사 본문이 로그에 포함되지 않는지도 확인하며 `make check`에 포함된다.

RH-02 기간 회귀는 `backend/tests/unit/test_pipeline.py`에서 날짜 없는 입력의 첫 검색 옵션에
`date_from`·`date_to`가 없고, 날짜를 명시한 입력은 P2·P3 교집합 기간을 유지하는지 검사한다.
복원 후보가 한 연도뿐이면 계속 생성하고 여러 연도이면 P4 전에 `clarify`로 종료하는 상태 전이도
같이 검사한다.

RH-03 무결과 회귀는 첫 검색이 0건일 때 원래 토픽·`hybrid`·기간 없음으로 두 번째 요청이
정확히 한 번 만들어지는지 검사한다. 두 검색이 모두 비면 `no_articles`, 두 번째 검색에서 실제
기사 ID가 복원되면 P4 이후 생성 흐름이 이어지는지를 별도 사례로 확인한다.

검사를 실행하지 못했으면 통과로 표현하지 않고 이유와 남은 검증을 보고한다. 외부 서비스 상태는 해당 서비스의 실제 헬스·쿼리로 확인한다.
