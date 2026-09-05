---
id: ADR-0008
관련 요구사항: NFR-04, NFR-05
일자: 2026-09-05
상태: 채택
대체: ADR-0005의 dense 임베딩 공급자 고정
---

## 배경

[ADR-0005](0005-qdrant-dense-sparse-search.md)는 dense named vector를 Google 임베딩으로
고정했다. 실제 원본은 178,887건이지만 `gemini-embedding-2` 무료 사용 환경은 분당 100건,
일일 1,000건으로 제한됐고 Batch API도 `400 FAILED_PRECONDITION`을 반환했다. 900건까지
적재한 뒤에는 같은 환경에서 전체 dense 인덱스를 끝낼 수 없었다.

현재 개발 머신은 Intel i7-13700H, 논리 CPU 20개, RAM 15GiB이며 WSL에 GPU가 노출되지 않는다.
따라서 기사 1건당 포인트 1개와 Qdrant 학습 목표를 유지하면서 CPU에서 전체 적재 가능한 로컬
임베딩을 선택해야 한다.

## 선택지와 실측

실제 `data/raw/news.jsonl`에서 고정 해시 일반 표본과 계엄 해제·SK텔레콤 유심 유출·의대 정원
갈등·산불 복구 표본을 만들었다. `backend/scripts/benchmark_local_embeddings.py`로 두 모델을
별도 프로세스에서 CPU 10스레드, 256 또는 512토큰, L2 정규화 조건으로 측정했다.

| 모델·조건 | 표본 | 캐시 후 로딩 | 관측 피크 RSS | 처리량 | 전체 예상 | 차원 |
|---|---:|---:|---:|---:|---:|---:|
| KURE-v1, 512토큰, batch 4 | 160건 | 8.7초 | 2,244MiB | 0.920건/초 | 54.0시간 | 1,024 |
| KURE-v1, 256토큰, batch 4 | 160건 | 8.7초 | 2,067MiB | 1.792건/초 | 27.7시간 | 1,024 |
| Qwen3-Embedding-0.6B, 512토큰, batch 4 | 32건 | 7.8초 | 1,789MiB | 0.145건/초 | 343.3시간 | 1,024 |

KURE-v1의 첫 다운로드를 포함한 로딩은 404.4초였다. 이후 표의 캐시 후 로딩 시간을 사용한다.
Qwen은 배치당 약 27초가 재현되어 품질 확인 표본을 32건으로 줄였으므로 두 모델의 품질 수치를
동일 모집단의 정량 평가로 해석하지 않는다. 두 모델 모두 고유명사·사건 표본을 찾았지만,
KURE-v1 256토큰은 네 질의 모두 관련 표본을 상위 5건에 유지했고 산불 질의에서 국내 피해 복구·
기부 기사를 상위에 배치했다. KURE-v1은 한국어 검색 데이터로 BGE-M3를 미세 조정한 모델이며,
공식 모델 카드는 1,024차원과 최대 8,192토큰을 명시한다.

근거: [KURE-v1 모델 카드](https://huggingface.co/nlpai-lab/KURE-v1),
[Qwen3-Embedding-0.6B 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)

## 결정

운영 dense 공급자는 로컬 `nlpai-lab/KURE-v1`으로 바꾼다.

- 기존 `core.ports.EmbeddingProvider`는 바꾸지 않는다.
- 기본 로컬 출력은 1,024차원 float32이며 코사인 검색 전에 L2 정규화한다.
- 문서는 `title + summary + content` 순서로 결합하고 접두어를 붙이지 않는다.
- 결합 문자열은 KURE 토크나이저에서 256토큰으로 자른다. 기사와 포인트의 1:1 대응은 유지한다.
- 질의는 앞뒤 공백만 제거하고 접두어나 지시문을 붙이지 않은 뒤 같은 모델·정규화를 적용한다.
- CPU 10스레드, 모델 내부 배치 4를 기본으로 한다.
- `EMBEDDING_PROVIDER=gemini`를 지정하면 기존 Gemini 문서·질의 전처리와 3,072차원 경로를
  그대로 사용할 수 있다.
- Linux PyTorch는 CPU 전용 인덱스의 wheel로 잠가 CUDA 런타임 의존성을 설치하지 않는다.

기존 `articles`는 3,072차원 Gemini dense 900건과 BM25 178,887건을 보존한다. 로컬 인덱스는
별도 `articles_kure_v1` 컬렉션에 완성한 뒤 `QDRANT_COLLECTION`만 전환한다. 전환 실패 시
`QDRANT_COLLECTION=articles`, `EMBEDDING_PROVIDER=gemini`로 되돌리면 기존 컬렉션을 그대로
사용할 수 있으므로, 기존 컬렉션 삭제나 복원 작업은 필요하지 않다.

## 결과

- Gemini 일일 한도와 기사 본문 외부 전송 없이 전체 dense 적재를 재개할 수 있다.
- 원시 dense float32 저장량은 약 699MiB이며 Qdrant 인덱스·payload 공간이 추가된다.
- CPU 전체 적재는 실측 기준 약 27.7시간이므로 중단 후 재개와 포인트 ID 대조가 필수다.
- 256토큰 이후의 본문은 dense에 반영되지 않는다. 제목·요약·본문 앞부분을 우선하는 비용-품질
  절충이며, BM25는 계속 전체 결합 문자열을 사용한다.
- 모델 캐시가 없는 환경의 첫 의미 검색은 약 2.3GB 모델 다운로드가 먼저 필요하다.
