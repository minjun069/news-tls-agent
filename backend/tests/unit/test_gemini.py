from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors
from pydantic import BaseModel

from core.config import GeminiConfig
from core.errors import LLMGenerationError, LLMRateLimitError
from infra.gemini import GeminiStructuredGenerator


class Probe(BaseModel):
    ok: bool


class FakeModels:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def generator(models: FakeModels) -> GeminiStructuredGenerator:
    client = SimpleNamespace(models=models)
    config = GeminiConfig(
        api_key="test-key",
        model="gemini-test",
        embedding_model="embedding-test",
        embedding_dimensions=768,
    )
    return GeminiStructuredGenerator(config, client=client)


def test_gemini_generator_uses_response_schema_and_returns_parsed_model() -> None:
    models = FakeModels(response=SimpleNamespace(parsed=Probe(ok=True), text=None))

    result = generator(models).generate("probe", Probe)

    assert result == Probe(ok=True)
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is Probe


def test_gemini_generator_revalidates_json_and_rejects_empty_response() -> None:
    json_models = FakeModels(response=SimpleNamespace(parsed=None, text='{"ok": true}'))
    assert generator(json_models).generate("probe", Probe).ok is True

    empty_models = FakeModels(response=SimpleNamespace(parsed=None, text=None))
    with pytest.raises(LLMGenerationError, match="비어 있는"):
        generator(empty_models).generate("probe", Probe)


def test_gemini_generator_maps_rate_limit_separately() -> None:
    models = FakeModels(error=errors.ClientError(429, {"error": {"message": "limit"}}))

    with pytest.raises(LLMRateLimitError):
        generator(models).generate("probe", Probe)


def test_gemini_generator_maps_transport_failure_for_pipeline_retry() -> None:
    models = FakeModels(error=httpx.ConnectError("dns failure"))

    with pytest.raises(LLMGenerationError, match="네트워크"):
        generator(models).generate("probe", Probe)
