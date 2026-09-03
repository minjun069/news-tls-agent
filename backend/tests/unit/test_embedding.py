from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.config import GeminiConfig
from infra.embedding import GeminiEmbeddingProvider


class FakeModels:
    def __init__(self, responses=None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def embed_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models


def response(*vectors: list[float]):
    return SimpleNamespace(embeddings=[SimpleNamespace(values=vector) for vector in vectors])


def config() -> GeminiConfig:
    return GeminiConfig(api_key="test-key", model="test-llm", embedding_model="test-embedding")


def test_provider_builds_sdk_client_with_configured_api_key(monkeypatch) -> None:
    captured = {}
    fake_client = FakeClient(FakeModels())

    def build_client(*, api_key: str):
        captured["api_key"] = api_key
        return fake_client

    monkeypatch.setattr("infra.embedding.genai.Client", build_client)

    GeminiEmbeddingProvider(config())

    assert captured == {"api_key": "test-key"}


def test_embed_documents_batches_inputs_with_retrieval_document_task() -> None:
    models = FakeModels([response([0.1, 0.2], [0.3, 0.4])])
    provider = GeminiEmbeddingProvider(config(), client=FakeClient(models))

    vectors = provider.embed_documents(["첫 기사", "둘째 기사"])

    assert vectors == [(0.1, 0.2), (0.3, 0.4)]
    assert models.calls[0]["model"] == "test-embedding"
    assert models.calls[0]["contents"] == ["첫 기사", "둘째 기사"]
    assert models.calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"


def test_embed_documents_returns_without_call_for_empty_batch() -> None:
    models = FakeModels()
    provider = GeminiEmbeddingProvider(config(), client=FakeClient(models))

    assert provider.embed_documents([]) == []
    assert models.calls == []


def test_embed_query_uses_retrieval_query_task() -> None:
    models = FakeModels([response([0.5, 0.6])])
    provider = GeminiEmbeddingProvider(config(), client=FakeClient(models))

    vector = provider.embed_query("계엄 해제 절차")

    assert vector == (0.5, 0.6)
    assert models.calls[0]["contents"] == "계엄 해제 절차"
    assert models.calls[0]["config"].task_type == "RETRIEVAL_QUERY"


def test_embed_query_rejects_blank_without_call() -> None:
    models = FakeModels()
    provider = GeminiEmbeddingProvider(config(), client=FakeClient(models))

    with pytest.raises(ValueError, match="빈 문자열"):
        provider.embed_query("  ")
    assert models.calls == []


def test_embedding_response_count_and_dimensions_are_validated() -> None:
    models = FakeModels([response([0.1]), response([0.1], [0.2, 0.3])])
    provider = GeminiEmbeddingProvider(config(), client=FakeClient(models))

    with pytest.raises(ValueError, match="응답 개수"):
        provider.embed_documents(["하나", "둘"])
    with pytest.raises(ValueError, match="차원"):
        provider.embed_documents(["하나", "둘"])


def test_embedding_sdk_error_is_not_swallowed() -> None:
    provider = GeminiEmbeddingProvider(
        config(),
        client=FakeClient(FakeModels(error=RuntimeError("quota exceeded"))),
    )

    with pytest.raises(RuntimeError, match="quota exceeded"):
        provider.embed_query("질의")
