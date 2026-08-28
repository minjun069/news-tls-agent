# 코드 컨벤션

실제 강제 원천은 `backend/pyproject.toml`의 ruff·import-linter 설정이다. 이 문서는 사람이 이해할 규칙과 예외의 이유를 설명한다.

## Python

- Python 3.12, 타입 힌트, `from __future__ import annotations`를 사용한다.
- 함수·변수·모듈은 `snake_case`, 클래스는 `PascalCase`를 사용한다.
- 상대 import를 쓰지 않는다. `backend/`를 소스 루트로 보고 `from core...`처럼 import한다.
- 예외를 삼키지 않는다. 명시적으로 처리하거나 필요한 문맥을 기록한 뒤 다시 발생시킨다.
- 로깅은 `logger.info("...: %s", value)` 형태의 지연 포맷을 쓴다.
- 모듈 레벨 전역 DB 연결·세션·변경 가능한 캐시를 두지 않는다. 조립점에서 주입한다.
- API 키·접속 정보는 환경변수에서 읽고 코드·문서·테스트 값에 실제 비밀을 넣지 않는다.

## Pydantic과 core

`core`에서 Pydantic v2를 허용한다. 이 프로젝트에서 Pydantic 모델은 HTTP DTO가 아니라 **포트 경계를 통과하는 도메인 값**이다. 입력 검증, 불변성(`frozen=True`), ORM 값 변환(`from_attributes=True`)을 한 정의에서 제공해 dict 확산과 중복 검증을 줄인다.

허용 범위는 `BaseModel`, `Field`, 도메인 검증기처럼 데이터 모델링에 필요한 기능이다. FastAPI 요청 객체, SQLAlchemy 엔티티, Qdrant·Gemini SDK 타입은 `core`에 들어오지 않는다. Pydantic 종속을 완전히 없애야 할 요구가 생기면 그때 dataclass와 어댑터 DTO를 분리한다.

따라서 `core`의 정확한 정의는 “외부 라이브러리 0”이 아니라 **I/O·저장소·웹·에이전트 프레임워크를 모르는 도메인 계층**이다.

## 계층

- `core`: Pydantic 허용. FastAPI, Starlette, LangGraph, SQLAlchemy, Qdrant, Gemini SDK 금지.
- `app`: LangGraph 허용. FastAPI·Starlette와 `infra` import 금지.
- `infra`: `app`, `api`, `mcp_server` 참조 금지.
- SQL은 `infra/repository.py`와 `backend/db/`의 DB 관리 코드에만 둔다.
- 프롬프트는 `app/pipeline.py`, `app/agent.py`에 둔다.
- MCP 툴 구현은 `mcp_server/tools/`에 둔다.

## 데이터와 오류

- 경계를 넘는 구조는 Pydantic 모델이나 명시적 타입으로 정의하고 dict를 그대로 전달하지 않는다.
- 이슈·이벤트·기사 연결은 단일 트랜잭션으로 저장한다.
- MCP 툴은 구조화 출력을 반환한다. 성공·실패 스키마는 `docs/contracts/mcp-tools.md`를 따른다.
- 적용된 마이그레이션 파일을 수정하지 않는다. 수정·되돌리기도 새 번호로 작성한다.

## Vue

- Vue 3 Composition API와 `<script setup lang="ts">`를 사용한다.
- 컴포넌트 파일은 `PascalCase.vue`로 작성한다.
- 프론트엔드는 HTTP/SSE 계약만 알고 DB·MCP·LLM SDK를 직접 사용하지 않는다.
