---
id: ADR-0005
관련 요구사항: NFR-04, NFR-05
일자: 2026-08-29
상태: 채택
보완: ADR-0003
---

## 배경

[ADR-0003](0003-search-strategies.md)은 BM25·의미·RRF 결합 세 검색 방식을 모두 제공한다고
결정했지만, BM25 인덱스와 실행 위치는 정하지 않았다. 위치를 정해야 검색 포트, 적재 스크립트,
기간 필터, 장애 경계를 같은 계약으로 구현할 수 있다.

현재 네이티브 SQL Server에서
`FULLTEXTSERVICEPROPERTY('IsFullTextInstalled')`를 조회한 결과는 `0`이다. SQL Server의
`FREETEXTTABLE`은 OKAPI BM25 순위를 제공하지만, 지금 선택하면 Full-Text Search 기능 설치와
별도 전문 인덱스 운영이 먼저 필요하다.

Qdrant는 dense와 sparse named vector를 같은 포인트에 저장하고, sparse vector에 BM25를
적용할 수 있다. multilingual tokenizer는 비라틴 문자와 공백으로 분리되지 않는 언어를
지원한다. 근거는 [Qdrant Full-Text Search](https://qdrant.tech/documentation/search/text-search/full-text-search/)와
[Microsoft SQL Server 순위 문서](https://learn.microsoft.com/en-us/sql/relational-databases/search/limit-search-results-with-rank?view=sql-server-ver17)다.

## 선택지

1. **SQL Server Full-Text Search** — 기사 원문과 같은 저장소에서 BM25를 수행하지만 현재 기능
   설치가 없고, S3 전에 서버 기능을 추가해야 한다.
2. **프로세스 내부 BM25 인덱스** — 구현은 독립적이지만 프로세스마다 인덱스를 재구축하고 별도
   토큰화·통계·메모리 수명주기를 운영해야 한다.
3. **Qdrant dense + sparse BM25** — 필수 학습 대상인 Qdrant 한 컬렉션에서 두 검색 표현을
   관리하고, 기간 payload 필터를 두 경로에 동일하게 적용한다.

## 결정

3안을 채택한다.

- `articles` 컬렉션의 한 포인트가 기사 한 건에 대응한다.
- named vector `dense`는 Google 임베딩과 Cosine 거리를 사용한다.
- named sparse vector `bm25`는 Qdrant BM25와 IDF modifier를 사용한다.
- BM25 처리 옵션은 ingest와 query 모두 multilingual tokenizer, stemmer 없음, stopwords 없음으로
  고정한다. 이를 지원하는 Qdrant 1.19 이상을 사용한다.
- `title + summary + content` 결합 문자열은 dense 임베딩과 BM25 sparse vector 생성 입력으로
  사용하되 payload에는 저장하지 않는다.
- payload는 `article_id`, `service_date`, `title`, `category_middle` 네 필드만 유지한다.
- OR 검색은 term별 BM25 결과의 합집합, AND 검색은 교집합이며 같은 기사 점수는 합산한다.
  각 term 검색에 동일한 기간 필터를 먼저 적용하고, 집합 결합 뒤 최종 `top_k`를 자른다.
- 의미 검색과 키워드 검색 결과는 SDK 객체가 아닌 `SearchHit(article_id, score)`로 core 경계를
  통과한다.
- hybrid는 Qdrant 내장 fusion을 쓰지 않고 `core.ranking`의 RRF로 결합한다. 기본 `k=60`,
  순위는 1부터 시작하고, 최종 동률은 `article_id` 오름차순이다.

Dense 임베딩이 실패한 기사는 `bm25` sparse vector만 저장할 수 있다. 따라서 의미 검색에서는
빠지지만 키워드 검색에는 남는다.

## 결과

- SQL Server 기능 설치 없이 실제 BM25와 의미 검색을 구현할 수 있다.
- 기간 필터가 두 검색 경로에서 같은 Qdrant payload를 사용한다.
- dense와 sparse 적재를 `03_build_vectors.py` 한 곳에서 멱등하게 관리할 수 있다.
- Qdrant 장애 시 키워드와 의미 검색이 함께 실패한다. MCP 계층은 이를 저장소 장애로 보고한다.
- AND 검색은 term별 후보를 모두 확인한 뒤 교집합해야 하므로 OR보다 호출량이 많다. MVP 시드
  규모에서는 정확성을 우선하고, 후보 제한 최적화는 실제 계측 뒤 별도 결정한다.
- multilingual tokenizer가 필요한 계약이 생기므로 Docker 이미지와 클라이언트 호환 버전을
  P3에서 고정하고 검증해야 한다.
