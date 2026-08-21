# MCP 툴 명세 — news-tls-agent

관련 PRD: [`REQUIREMENTS.md`](REQUIREMENTS.md) · HTTP 계약: [`API.md`](API.md)

> **`API.md`와 역할이 다르다.** `API.md`는 프론트엔드가 읽는 HTTP 계약이고, 이 문서는 **에이전트가 읽는 툴 계약**이다.
> 특히 각 툴의 `description`은 **곧 프롬프트**다. 에이전트가 그 문장을 읽고 호출 여부를 판단하므로 문구 자체가 설계 대상이다.

전송: stdio
구현: `backend/mcp_server/tools/`
검증: `npx @modelcontextprotocol/inspector python backend/mcp_server/server.py`

---

## 1. 공통 규약

### 1.1 출력

모든 툴은 `structured_output=True`로 **dict를 반환**한다. 자연어 문자열을 반환하지 않는다.

성공

```json
{ "ok": true, "...": "...", "message": "사람이 읽을 요약" }
```

실패

```json
{ "ok": false, "error": { "code": "ARTICLE_NOT_FOUND", "message": "해당 기사를 찾을 수 없습니다." } }
```

`message`는 에이전트가 사용자에게 전달할 수 있는 문장이다. 에러도 예외를 던지지 않고 `ok: false`로 돌려준다 — 에이전트가 판단해 다음 행동을 정할 수 있어야 하기 때문이다.

### 1.2 에러 코드

| code | 의미 | 에이전트의 기대 행동 |
|---|---|---|
| `ARTICLE_NOT_FOUND` | 기사 없음 | 다른 기사를 조회하거나 사용자에게 알림 |
| `ISSUE_NOT_FOUND` | 이슈 없음 | 사용자에게 알림 |
| `STORAGE_UNAVAILABLE` | 저장소 연결 실패 | 재시도하지 않고 사용자에게 알림 |
| `INVALID_ARGUMENT` | 인자 형식 오류 | 인자를 고쳐 재호출 |
| `EXPORT_NOT_CONFIGURED` | 내보내기 연결 설정 없음 | 사용자에게 설정 안내 |

### 1.3 감사 로그

모든 호출은 시각·툴 이름·인자·결과 건수를 기록한다 (NFR-06).

```
2026-08-21T14:23:11 search_articles method=hybrid query="국회 표결" top_k=5 -> 5건
2026-08-21T14:23:13 read_article article_id=1234567 -> 1건
```

### 1.4 구현 규칙

payload 함수와 `@mcp.tool` 데코레이터를 분리한다. payload 함수는 MCP 없이 단위 테스트할 수 있어야 한다.

```python
def search_articles_payload(query: str, ...) -> dict: ...

@mcp.tool(structured_output=True)
def search_articles(query: str, ...) -> dict:
    """..."""            # ← 이 docstring이 description이 된다
    return search_articles_payload(query=query, ...)
```

---

## 2. `search_articles`

### description

> 뉴스 기사를 검색합니다. 구체적 사실(발언, 수치, 날짜, 인과관계)을 확인해야 할 때 사용하세요.
> 검색 방식은 질의 성격에 맞게 고르세요 — 인명·기관명·날짜처럼 정확히 일치해야 하면 `keyword`,
> 개념이나 상황 서술이면 `semantic`, 판단이 서지 않으면 `hybrid`입니다.

### 입력

| 인자 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `query` | string | ✅ | 검색어 또는 검색용 문장 |
| `method` | enum | | `keyword` \| `semantic` \| `hybrid` (기본 `hybrid`) |
| `top_k` | int | | 반환 건수 (기본 5) |
| `date_from` | date | | 서비스 일자 하한 |
| `date_to` | date | | 서비스 일자 상한 |

### 출력

```json
{
  "ok": true,
  "method": "hybrid",
  "articles": [
    { "article_id": 1234567, "title": "긴급 대국민 담화", "service_date": "2024-12-03",
      "summary": "...", "score": 0.83 }
  ],
  "message": "3건을 찾았습니다."
}
```

본문(`content`)은 반환하지 않는다. 필요하면 `read_article`을 호출한다.

### 비고

- `method`는 NFR-04의 세 방식에 대응한다. 선택 결과가 감사 로그에 남는다
- 기간 필터는 검색 단계에서 적용된다 (NFR-05)
- 결과 0건도 `ok: true`다. `articles`가 빈 배열이고 `message`가 그 사실을 알린다

관련: CHAT-002, [ADR-0003](decisions/0003-search-strategies.md)

---

## 3. `read_article`

### description

> 기사 전문을 읽습니다. `search_articles` 결과만으로 답하기 어려울 때,
> 근거를 확인하려는 기사에 대해 호출하세요.

### 입력

| 인자 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `article_id` | int | ✅ | 기사 식별자 |

### 출력

```json
{
  "ok": true,
  "article": {
    "article_id": 1234567,
    "title": "긴급 대국민 담화",
    "sub_title": "",
    "service_date": "2024-12-03",
    "content": "...",
    "url": "https://...",
    "truncated": true
  },
  "message": "기사를 읽었습니다. 본문 일부만 포함되어 있습니다."
}
```

본문은 표시 상한까지만 반환하고 `truncated`로 알린다. 잘렸다는 사실을 `message`에도 담는 이유는 에이전트가 그 한계를 답변에 반영할 수 있어야 하기 때문이다.

관련: ART-002, AC-009

---

## 4. `list_issues`

### description

> 생성된 이슈 목록을 조회합니다. 사용자가 다른 이슈를 언급하거나 비교를 요청할 때 사용하세요.

### 입력

없음.

### 출력

```json
{
  "ok": true,
  "issues": [
    { "issue_id": 1, "topic": "...", "title": "...", "generated_at": "2026-08-21T14:23:11", "event_count": 7 }
  ],
  "message": "이슈 1건이 있습니다."
}
```

관련: ISS-004

---

## 5. `get_issue`

### description

> 이슈의 타임라인과 근거 기사 목록을 조회합니다.
> 현재 보고 있는 이슈의 내용은 이미 문맥에 있으므로, 다른 이슈를 확인할 때 사용하세요.

### 입력

| 인자 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `issue_id` | int | ✅ | 이슈 식별자 |

### 출력

```json
{
  "ok": true,
  "issue": {
    "issue_id": 1,
    "topic": "...",
    "title": "...",
    "summary": "...",
    "events": [
      { "event_order": 1, "event_date": "2024-12-03", "title": "...", "summary": "...",
        "article_ids": [1234567, 1234890] }
    ]
  },
  "message": "이벤트 7건을 포함한 이슈입니다."
}
```

이벤트는 `event_order` 오름차순이다. 기사 본문은 포함하지 않는다.

관련: ISS-005

---

## 6. `export_briefing`

### description

> 이슈 브리핑을 PDF로 내보내거나 Notion 페이지로 저장합니다.
> 사용자가 **명시적으로 저장·내보내기를 요청한 경우에만** 호출하세요.
> 형식을 말하지 않았다면 호출하지 말고, PDF와 Notion 중 무엇으로 할지 먼저 물어보세요.
> 대상은 직전 답변이 아니라 이슈 브리핑입니다.

### 입력

| 인자 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `issue_id` | int | ✅ | 이슈 식별자 |
| `format` | enum | ✅ | `pdf` \| `notion` |
| `parent_page_id` | string | | Notion 상위 페이지. 비우면 환경변수 기본값 |

### 출력

PDF

```json
{
  "ok": true,
  "format": "pdf",
  "file_name": "비상계엄_타임라인.pdf",
  "download_url": "/downloads/...",
  "message": "PDF를 생성했습니다."
}
```

Notion

```json
{
  "ok": true,
  "format": "notion",
  "page_id": "def456...",
  "url": "https://www.notion.so/...",
  "message": "Notion 페이지를 생성했습니다."
}
```

미설정

```json
{ "ok": false, "error": { "code": "EXPORT_NOT_CONFIGURED", "message": "Notion 연결 설정이 필요합니다." } }
```

### 비고

이 툴이 **의도 분류를 대신한다.** 정규식이나 키워드 매칭으로 LLM 앞단에서 내보내기 의도를 판별하지 않는다. description의 "명시적으로 요청한 경우에만"과 "형식을 말하지 않았다면 묻기"가 판단 기준 전부다.

화면 메뉴 경로(`POST /issues/{id}/export`)와 **같은 구현**을 호출한다.

관련: CHAT-006, AC-015, AC-016, EXP-001, EXP-002, [ADR-0004](decisions/0004-export-intent-via-tool.md)

---

## 7. description 작성 규칙

툴 설명은 에이전트에게 전달되는 지시문이다. 아래를 지킨다.

| 규칙 | 이유 |
|---|---|
| **언제 쓰는지**를 먼저 쓴다 | 에이전트가 판단하는 건 "무엇을 하는가"가 아니라 "지금 부를까"다 |
| 호출하지 **말아야 할** 조건도 쓴다 | 과잉 호출이 과소 호출보다 흔하다 |
| 인자 선택 기준을 쓴다 | `method` 같은 enum은 기준이 없으면 항상 기본값만 쓴다 |
| 구현 세부를 쓰지 않는다 | RRF·인덱스 같은 건 판단에 쓸모없고 토큰만 먹는다 |

description을 고치는 것은 **동작을 고치는 것**이다. 코드 변경과 같은 무게로 다루고, 바꿀 때 이 문서를 함께 갱신한다.
