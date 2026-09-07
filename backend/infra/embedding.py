"""Google Gen AI와 로컬 Sentence Transformers 임베딩 어댑터."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import Lock
from typing import Protocol, cast

from google import genai
from google.genai import types

from core.config import ConfigError, EmbeddingConfig, GeminiConfig
from core.ports import EmbeddingProvider

_DOCUMENT_PREFIX = "title: none | text: "
_QUERY_PREFIX = "task: search result | query: "


class GeminiEmbeddingProvider:
    """문서와 질의의 검색 역할을 구분해 Gemini 임베딩을 생성한다."""

    def __init__(self, config: GeminiConfig, client: genai.Client | None = None) -> None:
        self._model = config.embedding_model
        self._dimensions = config.embedding_dimensions
        self._client = client if client is not None else genai.Client(api_key=config.api_key)

    def embed_documents(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        response = self._client.models.embed_content(
            model=self._model,
            contents=[
                types.Content(
                    parts=[types.Part.from_text(text=f"{_DOCUMENT_PREFIX}{text}")],
                )
                for text in texts
            ],
            config=types.EmbedContentConfig(output_dimensionality=self._dimensions),
        )
        return _extract_vectors(response, expected_count=len(texts))

    def embed_query(self, text: str) -> tuple[float, ...]:
        if not text.strip():
            raise ValueError("임베딩 질의는 빈 문자열일 수 없습니다")
        response = self._client.models.embed_content(
            model=self._model,
            contents=f"{_QUERY_PREFIX}{text.strip()}",
            config=types.EmbedContentConfig(output_dimensionality=self._dimensions),
        )
        return _extract_vectors(response, expected_count=1)[0]


class _SentenceEncoder(Protocol):
    max_seq_length: int

    def encode(self, sentences: str | Sequence[str], **kwargs: object) -> object: ...


class LocalEmbeddingProvider:
    """모델을 첫 요청에 한 번만 로드해 정규화된 로컬 dense 벡터를 생성한다."""

    def __init__(
        self,
        config: EmbeddingConfig,
        *,
        model: _SentenceEncoder | None = None,
        model_factory: Callable[[EmbeddingConfig], _SentenceEncoder] | None = None,
    ) -> None:
        if config.provider != "local":
            raise ValueError("LocalEmbeddingProvider에는 local 설정이 필요합니다")
        self._config = config
        self._model = model
        self._model_factory = model_factory or _load_local_model
        self._load_lock = Lock()

    def embed_documents(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        encoded = self._get_model().encode(
            list(texts),
            batch_size=self._config.batch_size,
            normalize_embeddings=self._config.normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return _local_vectors(
            encoded,
            expected_count=len(texts),
            expected_dimensions=self._config.dimensions,
        )

    def embed_query(self, text: str) -> tuple[float, ...]:
        query = text.strip()
        if not query:
            raise ValueError("임베딩 질의는 빈 문자열일 수 없습니다")
        encoded = self._get_model().encode(
            query,
            prompt=self._config.query_prompt or None,
            normalize_embeddings=self._config.normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return _local_vectors(
            [encoded],
            expected_count=1,
            expected_dimensions=self._config.dimensions,
        )[0]

    def _get_model(self) -> _SentenceEncoder:
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    self._model = self._model_factory(self._config)
        return self._model


def create_embedding_provider(
    config: EmbeddingConfig,
    gemini_config: GeminiConfig | None = None,
) -> EmbeddingProvider:
    """설정에서 선택한 공급자를 공용 EmbeddingProvider 포트로 조립한다."""
    if config.provider == "local":
        return LocalEmbeddingProvider(config)
    if config.provider == "gemini":
        if gemini_config is None:
            raise ConfigError("Gemini 임베딩에는 GOOGLE_API_KEY가 필요합니다")
        return GeminiEmbeddingProvider(gemini_config)
    raise ConfigError("지원하지 않는 임베딩 공급자입니다")


def _load_local_model(config: EmbeddingConfig) -> _SentenceEncoder:
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(config.threads)
    model = SentenceTransformer(config.model, device=config.device)
    model.max_seq_length = config.max_seq_length
    return cast(_SentenceEncoder, model)


def _local_vectors(
    encoded: object,
    *,
    expected_count: int,
    expected_dimensions: int,
) -> list[tuple[float, ...]]:
    values = encoded.tolist() if hasattr(encoded, "tolist") else encoded
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TypeError("로컬 임베딩 결과가 벡터 배열이 아닙니다")
    if len(values) != expected_count:
        raise ValueError(
            f"임베딩 응답 개수가 요청과 다릅니다: expected={expected_count}, actual={len(values)}"
        )
    vectors: list[tuple[float, ...]] = []
    for raw_vector in values:
        vector_values = raw_vector.tolist() if hasattr(raw_vector, "tolist") else raw_vector
        if not isinstance(vector_values, Sequence) or isinstance(vector_values, (str, bytes)):
            raise TypeError("로컬 임베딩 결과에 벡터 값이 없습니다")
        vector = tuple(float(value) for value in vector_values)
        if len(vector) != expected_dimensions:
            raise ValueError(
                "로컬 임베딩 벡터 차원이 설정과 다릅니다: "
                f"expected={expected_dimensions}, actual={len(vector)}"
            )
        vectors.append(vector)
    return vectors


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
