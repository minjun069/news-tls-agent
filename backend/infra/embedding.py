"""Google Gen AI 임베딩 어댑터."""

from __future__ import annotations

from collections.abc import Sequence

from google import genai
from google.genai import types

from core.config import GeminiConfig

_DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"
_QUERY_TASK = "RETRIEVAL_QUERY"


class GeminiEmbeddingProvider:
    """문서와 질의의 검색 역할을 구분해 Gemini 임베딩을 생성한다."""

    def __init__(self, config: GeminiConfig, client: genai.Client | None = None) -> None:
        self._model = config.embedding_model
        self._client = client if client is not None else genai.Client(api_key=config.api_key)

    def embed_documents(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        response = self._client.models.embed_content(
            model=self._model,
            contents=list(texts),
            config=types.EmbedContentConfig(task_type=_DOCUMENT_TASK),
        )
        return _extract_vectors(response, expected_count=len(texts))

    def embed_query(self, text: str) -> tuple[float, ...]:
        if not text.strip():
            raise ValueError("임베딩 질의는 빈 문자열일 수 없습니다")
        response = self._client.models.embed_content(
            model=self._model,
            contents=text,
            config=types.EmbedContentConfig(task_type=_QUERY_TASK),
        )
        return _extract_vectors(response, expected_count=1)[0]


def _extract_vectors(
    response: types.EmbedContentResponse,
    *,
    expected_count: int,
) -> list[tuple[float, ...]]:
    embeddings = response.embeddings
    if embeddings is None or len(embeddings) != expected_count:
        raise ValueError(
            f"임베딩 응답 개수가 요청과 다릅니다: expected={expected_count}, "
            f"actual={0 if embeddings is None else len(embeddings)}"
        )

    vectors: list[tuple[float, ...]] = []
    vector_size: int | None = None
    for embedding in embeddings:
        values = embedding.values
        if not values:
            raise ValueError("임베딩 응답에 벡터 값이 없습니다")
        vector = tuple(values)
        if vector_size is None:
            vector_size = len(vector)
        elif len(vector) != vector_size:
            raise ValueError("한 배치의 임베딩 벡터 차원이 서로 다릅니다")
        vectors.append(vector)
    return vectors
