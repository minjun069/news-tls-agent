# API 명세서 — news-tls-agent

관련 PRD: [`REQUIREMENTS.md`](../REQUIREMENTS.md) · 기술 설계서: [`TECH_DESIGN.md`](../architecture/overview.md)

Base URL: `http://localhost:8000`
인증: 없음 (단일 사용자 전제)

---

## 1. 엔드포인트 목록

| Method | Path | 설명 | 관련 요구사항 |
|---|---|---|---|
| GET | `/health` | 저장소 연결 상태 조회 | NFR-07, EX-06 |
| GET | `/issues` | 이슈 목록 조회 | ISS-004 |
| GET | `/issues/{issue_id}` | 이슈 상세 조회 | ISS-005, ART-001 |
| POST | `/issues` | 타임라인 생성 (SSE) | ISS-001, ISS-002, ISS-003, ISS-006 |
| GET | `/articles/{article_id}` | 기사 원문 조회 | ART-002 |
| POST | `/issues/{issue_id}/chat` | 이슈 질의 (SSE) | CHAT-001~006 |
| POST | `/issues/{issue_id}/export` | 브리핑 내보내기 | EXP-001, EXP-002 |
| GET | `/issues/{issue_id}/graph` | 지식 그래프 조회 (SSE) | GRPH-001 |

---

## 2. GET /health

```json
{
  "status": "ok",
  "dependencies": { "mssql": "ok", "qdrant": "ok", "mcp_server": "ok" }
}
```

하나라도 연결되지 않으면 해당 항목이 `"error"`가 되고 전체 `status`는 `"degraded"`가 된다. HTTP 코드는 200을 유지한다 — 헬스체크 자체는 성공했기 때문이다.

---

## 3. GET /issues

```json
{
  "issues": [
    {
      "issue_id": 1,
      "topic": "비상계엄 선포부터 해제까지",
      "title": "비상계엄 선포와 국회 해제 결의",
      "generated_at": "2026-08-19T14:23:11",
      "event_count": 7
    }
  ]
}
```

정렬: `generated_at` 내림차순.

---

## 4. GET /issues/{issue_id}

```json
{
  "issue_id": 1,
  "topic": "비상계엄 선포부터 해제까지",
  "title": "비상계엄 선포와 국회 해제 결의",
  "summary": "## 사건 개요\n...",
  "generated_at": "2026-08-19T14:23:11",
  "events": [
    {
      "event_order": 1,
      "event_date": "2024-12-03",
      "title": "비상계엄 선포",
      "summary": "...",
      "primary_article": {
        "article_id": 1234567,
        "title": "긴급 대국민 담화",
        "service_date": "2024-12-03"
      },
      "articles": [
        { "article_id": 1234567, "title": "긴급 대국민 담화", "service_date": "2024-12-03", "relevance_score": 0.91 },
        { "article_id": 1234890, "title": "계엄사령부 포고령 발표", "service_date": "2024-12-03", "relevance_score": 0.84 }
      ]
    }
  ]
}
```

- `events`는 `event_order` 오름차순 (AC-006)
- `primary_article`은 §7.1 정책으로 선정된 대표 기사 (AC-007)
- `articles`는 `relevance_score` 내림차순 (AC-010)
- 심층 분석과 핵심 용어 필드는 없다 ([PRD 비목표](../REQUIREMENTS.md#35-비목표))

**404** — 이슈 없음

---

## 5. POST /issues

토픽으로 타임라인을 생성한다. SSE로 진행 상황을 전송한다.

**Request**

```json
{ "topic": "비상계엄 선포부터 해제까지", "clarification": null }
```

되묻기에 답할 때는 `clarification`에 사용자 응답을 담아 다시 호출한다.

**Response** — `text/event-stream`

### 5.1 정상 흐름

```
event: stage
data: {"stage": "intent", "message": "질의 의도를 해석하는 중"}

event: stage
data: {"stage": "hypothetical", "message": "가상 타임라인 구성 중", "period": ["2024-12-01", "2024-12-10"]}

event: stage
data: {"stage": "search", "round": 1, "method": "keyword", "found": 18}

event: stage
data: {"stage": "select", "round": 1, "selected": 12}

event: stage
data: {"stage": "expand", "round": 1, "next_events": 3}

event: stage
data: {"stage": "sufficiency", "round": 1, "sufficient": false}

event: stage
data: {"stage": "search", "round": 2, "method": "hybrid", "found": 9}

event: stage
data: {"stage": "merge", "message": "타임라인 구성 중"}

event: stage
data: {"stage": "save", "event_count": 7}

event: done
data: {"issue_id": 1, "termination": "sufficiency_passed"}
```

### 5.2 stage 값

| stage | 의미 | 파이프라인 단계 |
|---|---|---|
| `intent` | 질의 의도 해석 | P1 |
| `clarify` | 되묻기 필요 | P1 |
| `hypothetical` | 가상 타임라인 생성 | P2 |
| `search` | 검색 | P3 + 검색 |
| `select` | 핵심 이벤트 선정 | P4 |
| `expand` | 선후 이벤트 추출 | P5 |
| `sufficiency` | 충분성 검토 | P6 |
| `hypothesize` | 가상 이벤트 생성 | P7 |
| `merge` | 타임라인 병합 | P8 |
| `save` | 저장 | — |
| `cached` | 기존 이슈 재사용 (이후 단계 생략) | — |

`search` 이후 단계는 `round` 번호를 함께 보낸다 (AC-003).

### 5.3 되묻기 — ISS-006

```
event: clarify
data: {"question": "어느 시점의 계엄 관련 사건을 말씀하시나요?", "attempt": 1}
```

스트림을 종료하고 사용자 응답을 기다린다. 사용자는 `clarification`을 채워 다시 `POST /issues`를 호출한다 (AC-022, AC-023).

되묻기 횟수가 상한에 도달하면 되묻지 않고 해석된 의도로 진행한다.

### 5.4 종료 사유

`done` 이벤트의 `termination` 값. [타임라인 종료 정책](../requirements/timeline.md#수집-루프-종료-정책) 정책에 대응한다.

| 값 | 의미 |
|---|---|
| `sufficiency_passed` | 충분성 검토 통과 |
| `converged` | 선정 기사 수 변화 없음 |
| `depth_limit` | 선후 이벤트 연쇄 깊이 상한 |
| `round_limit` | 최대 라운드 도달 |
| `cached` | 기존 이슈 재사용 |

### 5.5 오류

```
event: error
data: {"reason": "no_articles", "message": "관련 기사를 찾지 못했습니다.", "retryable": false}
```

| reason | retryable | 관련 예외 |
|---|---|---|
| `no_articles` | false | EX-01, EX-02 |
| `generation_failed` | true | EX-03, EX-05 |
| `rate_limited` | true | EX-04 |

`no_articles`와 `generation_failed`를 구분하는 이유는 사용자가 취할 다음 행동이 다르기 때문이다. 전자는 토픽을 바꿔야 하고 후자는 재시도하면 된다.

---

## 6. GET /articles/{article_id}

```json
{
  "article_id": 1234567,
  "title": "긴급 대국민 담화",
  "sub_title": "",
  "service_date": "2024-12-03",
  "summary": "...",
  "content": "...",
  "url": "https://...",
  "truncated": true
}
```

본문은 표시 상한까지만 반환하고 `truncated`로 알린다 (AC-009).

**404** — 기사 없음

---

## 7. POST /issues/{issue_id}/chat

**Request**

```json
{
  "message": "국회 표결은 몇 시에 이루어졌나요?",
  "history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

대화 이력은 클라이언트가 보관해 매 요청에 전달한다. 서버는 세션을 두지 않는다.

**Response** — `text/event-stream`

```
event: tool
data: {"name": "search_articles", "label": "기사 검색"}

event: token
data: {"text": "국회 본회의 표결은 ", "source": "article"}

event: token
data: {"text": "12월 4일 새벽 1시경 ", "source": "article"}

event: token
data: {"text": "계엄이란 헌법상 국가긴급권의 하나로 ", "source": "general"}

event: done
data: {"article_ids": [1234567, 1234890], "exports": []}
```

### 7.1 이벤트 종류

| event | 의미 |
|---|---|
| `tool` | 도구 호출 시작 |
| `token` | 응답 텍스트 조각 (AC-014) |
| `done` | 완료. 참조 기사 ID, 생성된 내보내기 결과 |
| `error` | 오류 |

### 7.2 출처 구분 — CHAT-004

`token` 이벤트의 `source` 필드로 문단 단위 출처를 표시한다.

| source | 의미 | 관련 |
|---|---|---|
| `article` | 기사에서 확인된 내용 | AC-011 |
| `general` | 기사에 없는 배경 개념 | AC-012 |

화면 표기 방식은 [`SCREENS.md`](../product/screens.md)를 원천으로 한다.

### 7.3 대화 내 내보내기 — CHAT-006

에이전트가 `export_briefing` 도구를 호출하면 결과가 `done`에 실린다 (AC-015).

```
event: tool
data: {"name": "export_briefing", "label": "브리핑 내보내기"}

event: done
data: {
  "article_ids": [],
  "exports": [{ "format": "pdf", "file_name": "...", "download_url": "/downloads/..." }]
}
```

형식이 명시되지 않으면 도구를 호출하지 않고 되묻는 답변을 생성한다 (AC-016).

### 7.4 오류

```
event: error
data: {"reason": "data_unavailable", "message": "자료를 불러오지 못했습니다.", "retryable": true}
```

데이터 접근 계층에 연결할 수 없으면 오류를 반환한다. 저장소 직접 접근으로 우회하지 않는다 (AC-013, EX-06).

---

## 8. POST /issues/{issue_id}/export

**Request**

```json
{ "format": "pdf" }
```

```json
{ "format": "notion", "parent_page_id": "abc123..." }
```

**Response 200 — PDF**

```json
{ "format": "pdf", "file_name": "비상계엄_타임라인.pdf", "download_url": "/downloads/..." }
```

**Response 200 — Notion** (AC-018)

```json
{ "format": "notion", "page_id": "def456...", "url": "https://www.notion.so/..." }
```

**Response 400 — Notion 연결 없음** (AC-019)

```json
{ "reason": "notion_not_configured", "message": "Notion 연결 설정이 필요합니다." }
```

화면 메뉴와 대화 두 진입점이 같은 구현을 호출한다 ([아키텍처 구현 지침](../architecture/overview.md#5-구현-지침)).

---

## 9. GET /issues/{issue_id}/graph

지식 그래프를 조회한다. 미추출 기사가 있으면 추출을 수행하므로 SSE로 진행을 알린다 (AC-021).

**Response** — `text/event-stream`

```
event: stage
data: {"stage": "extracting", "remaining": 3}

event: done
data: {
  "graphs": [
    {
      "article_id": 1234567,
      "article_title": "긴급 대국민 담화",
      "nodes": [
        { "id": 11, "name": "윤석열 대통령", "type": "인물" },
        { "id": 12, "name": "계엄사령부", "type": "기관" }
      ],
      "edges": [
        { "id": 5, "source": 11, "target": 12, "type": "설치를 지시" }
      ]
    }
  ]
}
```

- 그래프는 **기사별로 하나씩** 반환한다. 통합 그래프를 만들지 않는다 ([지식 그래프 요구사항](../requirements/knowledge-graph.md))
- 모든 노드·간선이 `article_id`에 귀속된다 (NFR-16)

**Response — 이벤트 1건 이하**

```
event: error
data: {"reason": "insufficient_events", "message": "그래프를 표시할 만큼 이벤트가 충분하지 않습니다."}
```

---

## 10. MCP 서버 인터페이스

API 서버가 MCP 클라이언트로 접속하는 내부 인터페이스다. 외부에 HTTP로 노출하지 않는다.

툴 목록·입출력 스키마·description·에러 코드는 [`MCP_TOOLS.md`](mcp-tools.md)를 원천으로 한다.

> 이 문서는 **프론트엔드가 읽는 HTTP 계약**이고, `MCP_TOOLS.md`는 **에이전트가 읽는 툴 계약**이다.
> 독자와 바뀌는 이유가 다르므로 분리해 관리한다.
