# ERD — news-tls-agent

관련 PRD: [`REQUIREMENTS.md`](../REQUIREMENTS.md) · 기술 설계서: [`TECH_DESIGN.md`](../architecture/overview.md)

DBMS: MS-SQL Server

---

## 1. 관계도

```
                         ┌──────────────┐
              ┌──────────┤   articles   ├──────────┐
              │          │ article_id PK│          │
              │          └──────┬───────┘          │
              │ 1                │ 1               │ 1
              │                  │                 │
              │ N                │ N               │ N
   ┌──────────┴──────────┐  ┌────┴─────────┐  ┌───┴──────────────┐
   │issue_event_articles │  │article_       │  │article_relations │
   │ event_id   PK,FK    │  │entities       │  │ relation_id  PK  │
   │ article_id PK,FK    │  │ entity_id PK  │  │ article_id   FK  │
   └──────────┬──────────┘  │ article_id FK │  │ source_id    FK  │
              │ N           └───────────────┘  │ target_id    FK  │
              │                                └──────────────────┘
              │ 1
       ┌──────┴────────┐
       │  issue_events │
       │ event_id   PK │
       │ issue_id   FK │
       └──────┬────────┘
              │ N
              │ 1
       ┌──────┴────────┐
       │    issues     │
       │ issue_id   PK │
       │ topic      UQ │
       └───────────────┘
```

---

## 2. Entity

### 2.1 `articles` — 기사

뉴스 기사 원본. 전체 원본을 직접 읽는 적재 스크립트로만 채워지며 애플리케이션이 수정하지 않는다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `article_id` | BIGINT | PK | 원본 데이터의 기사 식별자를 그대로 사용 |
| `title` | NVARCHAR(500) | NOT NULL | 제목 |
| `sub_title` | NVARCHAR(500) | NULL | 부제목 |
| `service_date` | DATE | NOT NULL | 서비스 일자 |
| `summary` | NVARCHAR(MAX) | NULL | 기사 요약 |
| `content` | NVARCHAR(MAX) | NULL | 본문 |
| `url` | NVARCHAR(1000) | NULL | 원문 URL |
| `category_large` | NVARCHAR(100) | NULL | 대분류 |
| `category_middle` | NVARCHAR(100) | NULL | 중분류 |
| `category_small` | NVARCHAR(100) | NULL | 소분류 |
| `entities_extracted_at` | DATETIME2 | NULL | 엔티티·관계 추출 시각. NULL이면 미추출 |

> `article_id`를 IDENTITY로 두지 않는 이유: 원본 ID를 보존해야 벡터 DB payload 및 재적재 시 정합성이 유지된다.
>
> `entities_extracted_at`이 지식 그래프의 **추출 여부 판정 기준**이다. 이 값이 NULL인 대표 기사가 하나라도 있으면 추출을 수행한다 ([지식 그래프 요구사항](../requirements/knowledge-graph.md)).

### 2.2 `issues` — 이슈

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `issue_id` | INT | PK, IDENTITY | |
| `topic` | NVARCHAR(500) | NOT NULL, UNIQUE | 사용자가 입력한 토픽. 재사용 판정 기준 (ISS-003) |
| `title` | NVARCHAR(500) | NULL | 표시용 제목 |
| `summary` | NVARCHAR(MAX) | NULL | 이슈 요약 (마크다운) |
| `generated_at` | DATETIME2 | NOT NULL | 생성 시각 |

> `topic`의 UNIQUE가 ISS-003(기존 이슈 재사용)의 구현 근거다. 애플리케이션 조회에 앞서 DB가 중복을 막는다.
>
> 심층 분석과 핵심 용어는 생성하지 않는다 ([PRD 비목표](../REQUIREMENTS.md#35-비목표)).

### 2.3 `issue_events` — 타임라인 이벤트

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `event_id` | INT | PK, IDENTITY | |
| `issue_id` | INT | FK → `issues`, NOT NULL | ON DELETE CASCADE |
| `event_order` | INT | NOT NULL | 표시 순서 |
| `event_date` | DATE | NOT NULL | 이벤트 발생 일자 |
| `title` | NVARCHAR(500) | NOT NULL | 이벤트 제목 |
| `summary` | NVARCHAR(MAX) | NULL | 이벤트 설명 |

### 2.4 `issue_event_articles` — 이벤트–기사 연결

**근거 귀속의 실체다.**

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `event_id` | INT | PK, FK → `issue_events` | ON DELETE CASCADE |
| `article_id` | BIGINT | PK, FK → `articles` | |
| `relevance_score` | FLOAT | NULL | 검색 관련도. 대표 기사 선정에 사용 ([대표 기사 선정 정책](../requirements/issue-view.md#대표-기사-선정-정책)) |

복합 기본키 `(event_id, article_id)`가 같은 기사의 중복 인용을 DB 수준에서 막는다.

`article_id`의 외래키가 **할루시네이션 방어의 최종 계층**이다 (NFR-09, [AI_SPEC §5.3](../ai/specification.md)).

### 2.5 `article_entities` — 기사에서 추출한 엔티티

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `entity_id` | INT | PK, IDENTITY | |
| `article_id` | BIGINT | FK → `articles`, NOT NULL | ON DELETE CASCADE |
| `name` | NVARCHAR(300) | NOT NULL | 기사에 등장한 **표기 그대로** |
| `entity_type` | NVARCHAR(50) | NOT NULL | 인물 / 기관 / 장소 / 사건 등 |

> 엔티티가 기사에 종속된다. 같은 인물이 두 기사에 나오면 두 행이 생긴다.
> `(article_id, entity_id)` UNIQUE는 관계 테이블의 복합 외래키가 참조하며, 기사 경계를 넘는 관계를 DB에서 차단한다.

### 2.6 `article_relations` — 기사에서 추출한 관계

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `relation_id` | INT | PK, IDENTITY | |
| `article_id` | BIGINT | FK → `articles`, NOT NULL | ON DELETE CASCADE |
| `source_entity_id` | INT | FK → `article_entities`, NOT NULL | 주체 |
| `target_entity_id` | INT | FK → `article_entities`, NOT NULL | 대상 |
| `relation_type` | NVARCHAR(100) | NOT NULL | 관계 서술 |

`article_id` 외래키가 **NFR-16(그래프 요소 추적성)의 구현**이다. 출처 없는 관계는 삽입할 수 없다. `(article_id, source_entity_id)`와 `(article_id, target_entity_id)` 복합 외래키가 두 엔티티의 기사 귀속까지 강제한다.

> `source_entity_id`와 `target_entity_id`는 같은 `article_id`에 속한 엔티티여야 한다. 기사 경계를 넘는 관계를 만들지 않는다.

---

## 3. 인덱스

| 인덱스 | 대상 | 목적 | 관련 |
|---|---|---|---|
| `PK_articles` | `articles(article_id)` | 기사 단건 조회 | ART-002 |
| `IX_articles_service_date` | `articles(service_date)` | 기간 필터 검색 | NFR-05 |
| `UQ_issues_topic` | `issues(topic)` | 이슈 재사용 판정 | ISS-003 |
| `IX_issue_events_issue_order` | `issue_events(issue_id, event_order)` | 타임라인 정렬 조회 | ISS-005, AC-006 |
| `IX_iea_article` | `issue_event_articles(article_id)` | **역방향 조회** (기사 → 이슈) | — |
| `UQ_entities_article_entity` | `article_entities(article_id, entity_id)` | 기사별 엔티티 조회·기사 귀속 FK | GRPH-001, NFR-16 |
| `IX_relations_article` | `article_relations(article_id)` | 기사별 관계 조회 | GRPH-001 |

### 역방향 조회

기존 구조에서는 이벤트와 근거 기사를 JSON 문자열로 저장해 아래 질의가 불가능했다. 정규화의 실질적 이득이 여기에 있다.

```sql
-- 특정 기사가 근거로 인용된 모든 이슈
SELECT DISTINCT i.issue_id, i.topic, e.event_date, e.title
FROM issue_event_articles ea
JOIN issue_events e ON e.event_id = ea.event_id
JOIN issues       i ON i.issue_id = e.issue_id
WHERE ea.article_id = @article_id
ORDER BY e.event_date;
```

---

## 4. 대표 질의

### 4.1 이슈 상세 + 대표 기사

대표 기사 선정 기준은 [대표 기사 선정 정책](../requirements/issue-view.md#대표-기사-선정-정책)을 따른다.

```sql
WITH ranked AS (
  SELECT ea.event_id, ea.article_id, ea.relevance_score,
         ROW_NUMBER() OVER (
           PARTITION BY ea.event_id
           ORDER BY ea.relevance_score DESC,
                    ABS(DATEDIFF(day, a.service_date, e.event_date)),
                    ea.article_id
         ) AS rn
  FROM issue_event_articles ea
  JOIN articles     a ON a.article_id = ea.article_id
  JOIN issue_events e ON e.event_id   = ea.event_id
)
SELECT e.event_order, e.event_date, e.title,
       a.article_id, a.title AS article_title, a.service_date
FROM issue_events e
JOIN ranked   r ON r.event_id   = e.event_id AND r.rn = 1
JOIN articles a ON a.article_id = r.article_id
WHERE e.issue_id = @issue_id
ORDER BY e.event_order;
```

### 4.2 이슈 목록

```sql
SELECT i.issue_id, i.topic, i.title, i.generated_at,
       COUNT(e.event_id) AS event_count
FROM issues i
LEFT JOIN issue_events e ON e.issue_id = i.issue_id
GROUP BY i.issue_id, i.topic, i.title, i.generated_at
ORDER BY i.generated_at DESC;
```

### 4.3 지식 그래프 — 미추출 기사 확인

```sql
SELECT DISTINCT a.article_id
FROM issue_event_articles ea
JOIN articles a ON a.article_id = ea.article_id
JOIN issue_events e ON e.event_id = ea.event_id
WHERE e.issue_id = @issue_id
  AND a.entities_extracted_at IS NULL;
```

### 4.4 지식 그래프 — 기사별 요소 조회

```sql
SELECT r.relation_id, r.relation_type,
       s.entity_id AS source_id, s.name AS source_name, s.entity_type AS source_type,
       t.entity_id AS target_id, t.name AS target_name, t.entity_type AS target_type
FROM article_relations r
JOIN article_entities s ON s.entity_id = r.source_entity_id
JOIN article_entities t ON t.entity_id = r.target_entity_id
WHERE r.article_id = @article_id;
```

---

## 5. 트랜잭션 경계

| 작업 | 범위 |
|---|---|
| 이슈 생성 | `issues` → `issue_events` → `issue_event_articles`를 **하나의 트랜잭션**으로 (NFR-08, EX-05) |
| 엔티티 추출 | 기사 1건의 `article_entities` → `article_relations` → `articles.entities_extracted_at` 갱신을 하나의 트랜잭션으로 |

엔티티 추출도 원자적이어야 한다. 엔티티만 저장되고 관계가 실패하면, `entities_extracted_at`이 갱신되지 않아 다음 조회에서 재추출되고 중복 엔티티가 쌓인다.

---

## 6. 벡터 저장소와의 관계

Qdrant는 별도 저장소이며 외래키로 연결되지 않는다. `articles.article_id`를 payload에 두어 **논리적으로만 대응**시킨다.

| | MS-SQL | Qdrant |
|---|---|---|
| 보관 | 원문·메타데이터·이슈·엔티티 | dense 의미 벡터·BM25 sparse 벡터 |
| 키 | `article_id` (PK) | payload `article_id` |
| 정합성 | 외래키로 강제 | **적재 스크립트가 보장** |

키워드·의미 검색은 Qdrant에서 `article_id` 목록을 얻고 원문은 MS-SQL에서 조회하는 순서로
동작한다. 조회되지 않는 ID는 결과에서 제외한다. Qdrant payload에는 기사 원문을 저장하지 않는다.
