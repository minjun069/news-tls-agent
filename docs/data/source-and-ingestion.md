# 데이터 파이프라인 문서 — news-tls-agent

관련 PRD: [`REQUIREMENTS.md`](../REQUIREMENTS.md) · ERD: [`ERD.md`](schema.md)

> **이 문서가 상태값의 단일 원천이다.** PRD와 API 명세는 여기 정의된 상태값을 참조한다.

---

## 1. 데이터 요구사항

### 1.1 수집 항목

| 데이터 | 목적 | 출처 | 신뢰 기준 |
|---|---|---|---|
| 기사 ID | 기사 식별, 근거 귀속 | 원본 아카이브 | 원본 값 그대로 사용 |
| 제목 / 부제목 | 검색, 표시 | 원본 아카이브 | 원본 값 |
| 서비스 일자 | 시간순 정렬, 기간 필터 | 원본 아카이브 | 원본 값. 파싱 실패 시 적재 제외 |
| 요약 | 검색 대상, 목록 표시 | 원본 아카이브 | 원본 값. 없으면 빈 값 |
| 본문 | 검색·임베딩·근거 확인·엔티티 추출 | 원본 아카이브 | 원본 값. 없으면 적재 제외 |
| 원문 URL | 사용자 검증 경로 | 원본 아카이브 | 원본 값. 없으면 빈 값 |
| 카테고리 3단 | 검색 필터 | 원본 아카이브 | 원본 값 |
| 임베딩 벡터 | 의미 검색 | 임베딩 API 생성 | 실패 시 재시도. 최종 실패 시 벡터 없음 |
| 엔티티·관계 | 지식 그래프 | LLM 추출 | 기사 본문에 서술된 것만 |

### 1.2 적재 제외 기준

| 조건 | 이유 |
|---|---|
| `article_id`가 없거나 정수 변환 불가 | 근거 귀속이 불가능 |
| 제목이 비어 있음 | DB 필수값이며 검색·표시 기준이 없음 |
| 서비스 일자 파싱 실패 | 시간순 정렬이 핵심 기능 |
| 본문이 비어 있음 | 검색·임베딩·근거 확인·엔티티 추출 모두 불가 |

### 1.3 저장 위치

| 데이터 | 저장소 | 비고 |
|---|---|---|
| 원본 JSONL | `data/raw/` | Git 추적 제외. 사용자가 직접 투입 |
| 중간 정규화 파일 | 만들지 않음 | 원본은 검증 뒤 MS-SQL에 직접 배치 적재 |
| 기사·이슈·엔티티·관계 | MS-SQL `newsagent` | |
| 임베딩 벡터 | Qdrant `articles` 컬렉션 | 컨테이너 볼륨 |
| 감사 로그 · 실행 로그 | 로그 파일 | 회전 정책 미적용 |

### 1.4 보존 및 삭제

| 대상 | 정책 |
|---|---|
| 기사 | 삭제하지 않음. 재적재는 멱등(동일 ID 덮어쓰기) |
| 이슈 | 사용자 삭제 기능 없음. 재생성 시 기존 이슈 재사용 |
| 엔티티·관계 | 기사 삭제 시 CASCADE. 개별 삭제 기능 없음 |
| 임베딩 | 컬렉션 재생성으로 전체 교체 |
| 로그 | 보존 기간 정하지 않음 |

### 1.5 개인정보 처리

- **사용자 개인정보를 수집하지 않는다.** 계정 기능이 없다.
- 기사 본문에 등장하는 인물명은 **공개된 보도 내용**이므로 원문 그대로 보관한다. 엔티티로 추출될 때도 표기를 바꾸지 않는다.
- API 키·DB 접속 정보는 환경변수로만 주입하며 저장소에 커밋하지 않는다 (NFR-10).

---

## 2. 상태값 정의

### 2.1 기사 인용 상태

이벤트 병합 결과에 포함된 기사 ID를 실제 기사 집합과 대조한 판정.

| 상태 | 판정 조건 | 처리 |
|---|---|---|
| `인용 확정` | 해당 ID가 저장소에 존재 | 연결 테이블에 저장 |
| `인용 제거` | 해당 ID가 저장소에 없음 | 저장하지 않음 |
| `중복 병합` | 동일 이벤트 내 ID 중복 | 1건으로 병합 |

### 2.2 이벤트 채택 상태

| 상태 | 판정 조건 | 처리 |
|---|---|---|
| `채택` | 인용 확정 기사 ≥ 1건 | 저장 |
| `제외` | 인용 제거 후 근거 0건 | 저장하지 않음 |
| `중복 병합` | 날짜와 근거 기사 집합이 동일 | 1건으로 병합 |

### 2.3 수집 루프 종료 상태

[타임라인 종료 정책](../requirements/timeline.md#수집-루프-종료-정책) 정책에 대응한다. API 응답의 `termination` 값으로 노출된다.

| 상태 | 판정 조건 |
|---|---|
| `sufficiency_passed` | 충분성 검토 통과 |
| `converged` | 충분성 검토를 거친 뒤 선정 기사 수가 달라지지 않음 |
| `depth_limit` | 선후 이벤트 연쇄가 깊이 상한 도달 |
| `round_limit` | 최대 라운드 도달 |
| `cached` | 기존 이슈 재사용 |

### 2.4 이슈 생성 결과 상태

API 오류 응답의 `reason` 값으로 노출된다. 화면 표기는 [`SCREENS.md`](../product/screens.md) §4.1을 따른다.

| 상태 | 판정 조건 | 재시도 |
|---|---|---|
| `생성 완료` | 채택 이벤트 ≥ 1건, 저장 성공 | — |
| `no_articles` | 검색 결과 0건이거나 누적 선정 기사 0건 | **무의미** |
| `generation_failed` | LLM 호출 실패 또는 저장 실패 | 가능 |
| `rate_limited` | 외부 API 한도 초과 | 가능 |

> `no_articles`와 나머지를 구분하는 이유는 사용자의 다음 행동이 다르기 때문이다. 전자는 토픽을 바꿔야 하고, 후자는 같은 토픽으로 재시도하면 된다.

### 2.5 벡터 적재 상태

| 상태 | 의미 | 처리 |
|---|---|---|
| `적재 완료` | dense와 BM25 sparse vector 저장 성공 | 세 검색 방식 대상 |
| `부분 적재` | dense 임베딩 실패, BM25 sparse 저장 성공 | 키워드 검색 대상. dense 재적재 대상 |
| `적재 실패` | Qdrant 포인트 저장 실패 | 검색 제외. 재적재 대상 |

> 벡터가 없는 기사도 **키워드 검색으로는 조회된다.** 검색 방식을 셋 다 갖춘 구성이 한쪽 실패에 강한 이유다 (NFR-04).

### 2.6 엔티티 추출 상태

`articles.entities_extracted_at` 값으로 판정한다.

| 상태 | 판정 조건 | 처리 |
|---|---|---|
| `미추출` | `entities_extracted_at` IS NULL | 그래프 조회 시 추출 수행 |
| `추출 완료` | `entities_extracted_at` NOT NULL | 저장된 엔티티·관계를 그대로 사용 |

> 추출은 **기사 1건 단위 트랜잭션**이다. 엔티티만 저장되고 관계가 실패하면 `entities_extracted_at`이 갱신되지 않아 다음 조회에서 재추출되고 중복이 쌓인다 ([`ERD.md`](schema.md) §5).

---

## 3. 파이프라인

```
data/raw/*.jsonl                       ← 사용자가 투입
      │                    │
      │                    ├──▶ scripts/01_validate_raw.py
      │                    │     전체 검증 보고서(JSON 표준 출력)
      ▼
scripts/02_load_mssql.py               ← 같은 원본을 재순회해 검증·정규화·배치 upsert
      │
      ├──▶ MS-SQL (articles)
      │
      └──▶ scripts/03_build_vectors.py ─▶ Qdrant (articles 컬렉션)
```

엔티티·관계는 이 파이프라인에 포함되지 않는다. **런타임에 그래프를 조회할 때 추출**한다 (§2.6).

### 3.1 원본 검증·정규화

`scripts/01_validate_raw.py`는 원본 JSONL을 끝까지 읽어 적재 가능 여부만 JSON 한 줄로 보고한다.
중간 정규화 JSONL이나 토픽별 시드 파일은 만들지 않는다. `02_load_mssql.py`도 같은 정규화 함수를
사용하므로 검증과 실제 적재의 제외 기준이 다르지 않다.

정규화 필드는 `article_id`, `title`, `sub_title`, `service_date`, `summary`, `content`, `url`,
`category_large`, `category_middle`, `category_small`이다. 빈 행, JSON 파싱 실패 행, JSON 객체가
아닌 행은 각각 집계하고 적재하지 않는다. JSON 객체는 아래 순서로 하나의 대표 제외 사유를 부여한다.

| 제외 사유 | 판정 |
|---|---|
| `missing_article_id` | `article_id`가 없거나 빈 값 |
| `invalid_article_id` | `article_id`가 정수 또는 정수 문자열이 아님 |
| `missing_title` | `article_title`이 비어 있음 |
| `invalid_service_date` | `article_service_daytime`이 `YYYY-MM-DD HH:MM:SS`로 파싱되지 않음 |
| `missing_content` | `text`가 비어 있음 |
| `field_validation_error` | 길이 제한 등 `Article` 도메인 검증 실패 |

검증 보고서는 전체 행 수, 빈 행 수, JSON 오류 수, 객체 오류 수, 유효 기사 수, 유효
`article_id` 중복 수, 제외 사유별 수를 포함한다. 유효 ID가 중복되면 적재 순서상 마지막 유효 행이
MS-SQL의 기존 행을 덮어쓴다. 뒤쪽 행이 유효하지 않으면 적재하지 않으므로 앞선 유효 행을 유지한다.

현재 실제 원본은 `data/raw/news.jsonl`이며 178,887행이다. 확인된 주요 매핑은 다음과 같다.

| 원본 필드 | 정규화 필드 |
|---|---|
| `article_title` | `title` |
| `article_sub_title` | `sub_title` |
| `article_service_daytime` | `service_date` |
| `article_summary` | `summary` |
| `text` | `content` |
| `article_url` | `url` |
| `category_large_nm` | `category_large` |
| `category_middle_nm` | `category_middle` |
| `category_small_nm` | `category_small` |

`2026-09-03` 검증에서 실제 `news.jsonl` 178,887행을 전수 처리해 JSON 오류·비객체·제외·유효
ID 중복이 모두 0건임을 확인했다. 같은 날 MS-SQL `articles`에는 서로 다른 ID 178,887건이
저장됐고, 원본 앞·중간·마지막 표본의 정규화 필드가 일치했다. 토픽별 gold, 후보 기사, 관련성
판정, 커버리지 계산은 검색 로직이 구현된 뒤의 오프라인 평가이며 S2 적재 입력·산출물이 아니다.

### 3.2 MS-SQL 적재

- 입력은 `data/raw/*.jsonl`이며 `scripts/02_load_mssql.py`가 원본을 직접 스트리밍한다.
- `--batch-size`(기본 200) 단위 upsert. 한 배치 안의 중복 ID는 마지막 유효 기사 한 건으로 합친다.
- **멱등성**: 동일 `article_id` 재적재 시 마지막 유효 행으로 덮어쓴다.
- CLI는 §3.1 검증 집계와 DB에 보낸 `upserted_row_count`를 JSON 한 줄로 기록한다. 원본 중복이
  없으면 두 수는 모두 유효 기사 수와 같다.
- 스키마는 [`schema.md`](schema.md) 참조

### 3.3 벡터 적재

- dense·BM25 입력 텍스트: `제목 + 요약 + 본문`
- 청킹하지 않음 (기사 1건 = Qdrant 포인트 1개)
- named vector: `dense`(Cosine), `bm25`(sparse, IDF modifier)
- BM25: multilingual tokenizer, stemmer 없음, stopwords 없음
- payload: `article_id`, `service_date`, `title`, `category_middle`
- 원문·결합 텍스트는 payload에 저장하지 않음
- dense 임베딩 실패 시 BM25 sparse point는 저장하고 dense만 재적재 대상으로 남김
- Qdrant 저장 실패 시 지수 백오프 재시도 (EX-04)

### 3.4 실행 순서

`make migrate` 뒤에 원본 검증과 적재를 순서대로 실행한다.

```bash
cd backend
uv run python -m scripts.01_validate_raw ../data/raw/news.jsonl
uv run python -m scripts.02_load_mssql ../data/raw/news.jsonl --batch-size 200
```

MS-SQL 적재가 벡터 적재보다 **먼저** 수행되어야 한다. 벡터 검색이 반환한 `article_id`로 원문을
조회하므로, 원문이 없으면 검색 결과를 표시할 수 없다.

---

## 4. 정합성

| 항목 | 보장 수단 |
|---|---|
| 이벤트 → 기사 참조 | MS-SQL 외래키 (NFR-09) |
| 엔티티·관계 → 기사 참조 | MS-SQL 외래키 (NFR-16) |
| Qdrant dense·BM25 payload → 기사 | 적재 스크립트가 보장. DB 제약 없음 |
| 재적재 안전성 | 두 적재 스크립트 모두 멱등 |

Qdrant에는 있으나 MS-SQL에 없는 `article_id`가 생길 수 있다. 검색 결과를 원문 조회로 확인하는 단계에서 **조회되지 않는 ID는 결과에서 제외**한다.
