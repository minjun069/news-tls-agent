from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.config import ConfigError, EmbeddingConfig, GeminiConfig
from infra.embedding import (
    GeminiEmbeddingProvider,
    LocalEmbeddingProvider,
    create_embedding_provider,
)


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
    return GeminiConfig(
        api_key="test-key",
        model="test-llm",
        embedding_model="test-embedding",
        embedding_dimensions=768,
    )


def local_config(**overrides: object) -> EmbeddingConfig:
    values: dict[str, object] = {
        "provider": "local",
        "model": "nlpai-lab/KURE-v1",
        "dimensions": 2,
        "normalize": True,
        "max_seq_length": 256,
        "batch_size": 4,
        "device": "cpu",
        "threads": 10,
        "query_prompt": "",
    }
    values.update(overrides)
    return EmbeddingConfig(**values)


class FakeLocalModel:
    def __init__(self) -> None:
        self.max_seq_length = 8192
        self.calls: list[tuple[object, dict[str, object]]] = []

    def encode(self, sentences, **kwargs):
        self.calls.append((sentences, kwargs))
        if isinstance(sentences, str):
            return [0.6, 0.8]
        return [[1.0, 0.0] for _ in sentences]


def test_provider_builds_sdk_client_with_configured_api_key(monkeypatch) -> None:
    captured = {}
    fake_client = FakeClient(FakeModels())

    def build_client(*, api_key: str):
        captured["api_key"] = api_key
        return fake_client

    monkeypatch.setattr("infra.embedding.genai.Client", build_client)

    GeminiEmbeddingProvider(config())

    assert captured == {"api_key": "test-key"}


def test_embed_documents_wraps_separate_contents_with_retrieval_prefix() -> None:
    models = FakeModels([response([0.1, 0.2], [0.3, 0.4])])
    provider = GeminiEmbeddingProvider(config(), client=FakeClient(models))

    vectors = provider.embed_documents(["첫 기사", "둘째 기사"])

    assert vectors == [(0.1, 0.2), (0.3, 0.4)]
    assert models.calls[0]["model"] == "test-embedding"
    contents = models.calls[0]["contents"]
    assert [content.parts[0].text for content in contents] == [
        "title: none | text: 첫 기사",
        "title: none | text: 둘째 기사",
    ]
    assert models.calls[0]["config"].task_type is None
    assert models.calls[0]["config"].output_dimensionality == 768


def test_embed_documents_returns_without_call_for_empty_batch() -> None:
    models = FakeModels()
    provider = GeminiEmbeddingProvider(config(), client=FakeClient(models))

    assert provider.embed_documents([]) == []
    assert models.calls == []


def test_embed_query_uses_retrieval_query_prefix() -> None:
    models = FakeModels([response([0.5, 0.6])])
    provider = GeminiEmbeddingProvider(config(), client=FakeClient(models))

    vector = provider.embed_query("계엄 해제 절차")

    assert vector == (0.5, 0.6)
    assert models.calls[0]["contents"] == "task: search result | query: 계엄 해제 절차"
    assert models.calls[0]["config"].task_type is None
    assert models.calls[0]["config"].output_dimensionality == 768


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


def test_local_provider_lazily_loads_once_and_applies_document_contract() -> None:
    model = FakeLocalModel()
    loads: list[EmbeddingConfig] = []

    def factory(local: EmbeddingConfig) -> FakeLocalModel:
        loads.append(local)
        model.max_seq_length = local.max_seq_length
        return model

    provider = LocalEmbeddingProvider(local_config(), model_factory=factory)

    assert loads == []
    assert provider.embed_documents(["첫 기사", "둘째 기사"]) == [(1.0, 0.0), (1.0, 0.0)]
    assert provider.embed_documents(["셋째 기사"]) == [(1.0, 0.0)]
    assert len(loads) == 1
    assert model.max_seq_length == 256
    assert model.calls[0] == (
        ["첫 기사", "둘째 기사"],
        {
            "batch_size": 4,
            "normalize_embeddings": True,
            "convert_to_numpy": True,
            "show_progress_bar": False,
        },
    )


def test_local_query_uses_configured_prompt_and_rejects_blank() -> None:
    model = FakeLocalModel()
    provider = LocalEmbeddingProvider(local_config(query_prompt="retrieve: "), model=model)

    assert provider.embed_query("  계엄 해제  ") == (0.6, 0.8)
    assert model.calls[0] == (
        "계엄 해제",
        {
            "prompt": "retrieve: ",
            "normalize_embeddings": True,
            "convert_to_numpy": True,
            "show_progress_bar": False,
        },
    )
    with pytest.raises(ValueError, match="빈 문자열"):
        provider.embed_query(" ")


def test_local_provider_validates_dimensions_and_factory_selection() -> None:
    model = FakeLocalModel()
    provider = LocalEmbeddingProvider(local_config(dimensions=3), model=model)

    with pytest.raises(ValueError, match="차원"):
        provider.embed_documents(["기사"])
    assert isinstance(create_embedding_provider(local_config()), LocalEmbeddingProvider)


def test_gemini_factory_requires_gemini_config() -> None:
    gemini_embedding = local_config(
        provider="gemini",
        model="gemini-embedding-2",
        dimensions=3072,
    )

    with pytest.raises(ConfigError, match="GOOGLE_API_KEY"):
        create_embedding_provider(gemini_embedding)
