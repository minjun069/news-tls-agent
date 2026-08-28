# 문서 지도

이 문서는 문서의 위치와 단일 원천만 정의한다. 작업별 읽기 순서는 루트 [`AGENTS.md`](../AGENTS.md) §4를 따른다.

| 정보 | 단일 원천 |
|---|---|
| 문제·목표·MVP 범위·사용자 | [`REQUIREMENTS.md`](REQUIREMENTS.md) |
| 기능별 요구사항·AC·정책·예외 | [`requirements/`](requirements/) |
| 실행 토폴로지·기술 스택·NFR | [`architecture/overview.md`](architecture/overview.md) |
| 원본 데이터·상태값·적재 절차 | [`data/source-and-ingestion.md`](data/source-and-ingestion.md) |
| MS-SQL 스키마·질의·트랜잭션 | [`data/schema.md`](data/schema.md) + `../backend/db/migrations/` |
| HTTP/SSE 계약 | [`contracts/http-api.md`](contracts/http-api.md) |
| MCP 툴 계약 | [`contracts/mcp-tools.md`](contracts/mcp-tools.md) |
| 프롬프트·생성·검색·근거 전략 | [`ai/specification.md`](ai/specification.md) |
| 화면 흐름·표기 정책 | [`product/screens.md`](product/screens.md) |
| 작업 순서와 완료 기준 | [`engineering/roadmap.md`](engineering/roadmap.md) |
| AI 작업 방식·피드백 루프 | [`engineering/agent-workflow.md`](engineering/agent-workflow.md) |
| 코드 규칙 | [`engineering/code-conventions.md`](engineering/code-conventions.md) |
| Git·커밋·PR 규칙 | [`engineering/git-workflow.md`](engineering/git-workflow.md) |
| 로컬·CI 검증 명령 | [`engineering/validation.md`](engineering/validation.md) |
| 결정 배경 | [`decisions/`](decisions/) |
| 프로젝트 구조·최상위 금지 | [`../AGENTS.md`](../AGENTS.md) §1~§3 |
| 코드 경로 → 계약 문서 | [`../.harness/doc-routes.json`](../.harness/doc-routes.json) |

## 문서 규칙

- 같은 정보의 원천을 둘 이상 만들지 않는다. 다른 문서에서는 링크만 둔다.
- 기능 요구사항 파일은 사용자 관찰 가능 결과를, 기술 문서는 구현 방식과 파라미터를 다룬다.
- 계약을 바꾸는 코드 변경은 같은 커밋에서 계약 문서를 갱신한다.
- 채택된 ADR 본문은 수정하지 않는다. 변경은 새 ADR에서 `대체` 또는 `보완` 관계로 남긴다.
- 문서 자체의 변경 이력 표는 두지 않는다.
