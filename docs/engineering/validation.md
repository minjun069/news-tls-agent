# 검증 명령

`Makefile`이 실행 명령의 단일 진입점이다.

| 명령 | 검증 대상 | 시점 |
|---|---|---|
| `make install` | backend uv 환경 구성 | 최초 1회·의존성 변경 후 |
| `make fmt` | Python 포맷·자동 수정 | 구현 중 |
| `make lint` | ruff 린트·포맷 | 구현 중·커밋 전 |
| `make arch` | import-linter 계층 계약 | 계층 변경·커밋 전 |
| `make test` | 컨테이너 없는 단위 테스트 | 구현 중·커밋 전 |
| `make test-all` | MS-SQL·Qdrant 포함 통합 테스트 | 데이터·검색·MCP 변경 후 |
| `make doc-sync` | 경로별 계약 문서 동반 변경·링크 | 계약 코드·문서 변경 후 |
| `make doc-ack REASON='근거'` | 계약 문서를 검토했으나 계약 변경이 없다는 파일 해시·근거 기록 | 계약 코드만 변경된 경우 |
| `make check` | lint + arch + unit + docs | 모든 커밋 전 |
| `make agent-budget` | AGENTS.md의 현재 줄·바이트·추정 토큰 | 상위 지침 변경 후; 현재 실패 기준 없음 |
| `make up` | 기본 개발 인프라(Qdrant) | 로컬 개발 |
| `make up-full` | 전체 컨테이너 모드 | 클린 클론·데모 |
| `make migrate` | 미적용 MS-SQL 마이그레이션 | DB 기동·스키마 변경 후 |
| `make mcp-inspect` | MCP 툴 호출·payload | S4 이후 MCP 변경 후 |
| `make web-check` | vue-tsc + 빌드 | S7 이후 화면 변경 후 |

계약 코드가 바뀌면 `make doc-sync`는 연결된 문서가 함께 바뀌었는지 먼저 확인한다. 문서의 입력·출력·외부 동작이 그대로라면 문서를 의미 없이 수정하지 않고 `make doc-ack REASON='검토한 계약과 변경이 없는 이유'`를 실행한다. 이 명령은 대상 파일의 SHA-256 해시와 근거를 `.harness/doc-review.json`에 기록한다. 파일 내용이 다시 바뀌면 해시가 달라져 확인은 무효가 되고 `make check`가 실패한다.

CI는 검사 명령을 별도로 나열하지 않고 `make install` 뒤 `make check`를 호출한다. 로컬과 CI의 검사 범위는 Makefile 한 곳에서만 정의한다.

검사를 실행하지 못했으면 통과로 표현하지 않고 이유와 남은 검증을 보고한다. 외부 서비스 상태는 해당 서비스의 실제 헬스·쿼리로 확인한다.
