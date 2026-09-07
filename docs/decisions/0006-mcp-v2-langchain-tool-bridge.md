---
id: ADR-0006
관련 요구사항: CHAT-002, CHAT-005, NFR-12, EX-06
일자: 2026-09-04
상태: 채택
보완: ADR-0001
---

## 배경

ADR-0001은 API 서버의 대화 에이전트가 stdio MCP 서버를 통해서만 데이터를 읽도록 정했다.
S4 서버는 MCP Python SDK v2의 `MCPServer`로 구현되어 있어 S6 클라이언트도 같은 프로토콜
세대를 유지해야 한다.

로드맵은 `langchain-mcp-adapters` 사용을 예정했지만 2026-09-04에 `mcp 2.1.1`과 함께
해석하면 0.3.2의 `mcp<2` 제약 때문에 0.3.1이 선택되고, 이를 import한 결과
`mcp.shared.context.RequestContext`가 없어 즉시 실패했다.
업스트림 이슈 [#589](https://github.com/langchain-ai/langchain-mcp-adapters/issues/589)와 병합된
수정 [#590](https://github.com/langchain-ai/langchain-mcp-adapters/pull/590)은 MCP v2 지원 전까지
어댑터의 의존성을 `mcp<2`로 제한한다. 즉 한 Python 환경에서 현재 공개 버전의 어댑터와 이
프로젝트의 MCP v2 서버를 함께 사용할 수 없다.

## 선택지

1. **MCP SDK를 v1으로 낮춘다** — 기존 어댑터를 그대로 쓸 수 있지만 S4의 v2 서버 계약과 학습
   목표를 되돌린다.
2. **어댑터와 MCP 서버를 별도 Python 환경으로 분리한다** — 두 버전을 유지할 수 있지만 API와
   MCP 사이에 추가 브리지 프로세스·배포·장애 지점이 생긴다.
3. **MCP v2 클라이언트로 도구를 읽고 LangChain 도구로 변환한다** — `tools/list`의
   `inputSchema`와 description을 `StructuredTool`에 옮기고 호출 때 `tools/call`을 실행한다.

## 결정

3안을 채택한다. `infra/mcp_client.py`가 다음만 담당한다.

- MCP SDK v2 `ClientSession`으로 stdio 서버를 초기화한다.
- `tools/list`의 이름·description·JSON 입력 스키마를 LangChain `StructuredTool`로 변환한다.
- 도구 실행마다 `tools/call`의 `structuredContent`를 보존해 에이전트와 HTTP 어댑터에 돌려준다.
- 프로세스·전송·응답 형식 실패는 `DataAccessError`로 바꾸며 저장소 직접 조회로 우회하지 않는다.

도구의 판단 문구와 입력·출력 계약은 계속 MCP 서버가 단일 원천이다. 브리지는 도구별 스키마나
검색 구현을 복제하지 않는다. `app/agent.py`는 `core.ports.ToolClient`만 받는다.

## 결과

- S4 MCP v2 서버를 낮추지 않고 LangGraph 에이전트가 같은 다섯 도구를 사용할 수 있다.
- 추가 프로세스 없이 stdio 프로토콜 경계와 감사 로그가 유지된다.
- 공개 어댑터가 MCP v2를 정식 지원하면 브리지를 해당 라이브러리로 교체할 수 있다. 이때
  `ToolClient` 포트와 상위 에이전트 코드는 바뀌지 않는다.
- 라이브러리가 해주던 입력 스키마 변환을 프로젝트가 소유하므로 MCP SDK·LangChain 업그레이드 시
  `tests/unit/test_mcp_client.py`와 실제 MCP Inspector 검증을 함께 실행해야 한다.
