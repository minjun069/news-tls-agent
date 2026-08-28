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
| `make check` | lint + arch + unit + docs | 모든 커밋 전 |
| `make agent-budget` | AGENTS.md의 현재 줄·바이트·추정 토큰 | 상위 지침 변경 후; 현재 실패 기준 없음 |
| `make up` | 기본 개발 인프라(Qdrant) | 로컬 개발 |
| `make up-full` | 전체 컨테이너 모드 | 클린 클론·데모 |
| `make migrate` | 미적용 MS-SQL 마이그레이션 | DB 기동·스키마 변경 후 |
| `make mcp-inspect` | MCP 툴 호출·payload | S4 이후 MCP 변경 후 |
| `make web-check` | vue-tsc + 빌드 | S7 이후 화면 변경 후 |

검사를 실행하지 못했으면 통과로 표현하지 않고 이유와 남은 검증을 보고한다. 외부 서비스 상태는 해당 서비스의 실제 헬스·쿼리로 확인한다.
