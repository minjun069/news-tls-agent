from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors
from pydantic import BaseModel

from core.config import GeminiConfig
from core.errors import (
    LLMGenerationError,
    LLMModelConfigurationError,
    LLMOutputValidationError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
)
from core.models import ArticleGraphExtraction
from infra.gemini import GeminiStructuredGenerator


class Probe(BaseModel):
    ok: bool


class FakeModels:
    def __init__(self, response=None, error=None, outcomes=None) -> None:
        self.response = response
        self.error = error
        self.outcomes = list(outcomes or [])
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        if self.error is not None:
            raise self.error
        return self.response


def generator(
    models: FakeModels,
    *,
    sleeper=lambda _delay: None,
    jitter=lambda: 0.0,
) -> GeminiStructuredGenerator:
    client = SimpleNamespace(models=models)
    config = GeminiConfig(
        api_key="test-key",
        model="gemini-test",
        embedding_model="embedding-test",
        embedding_dimensions=768,
    )
    return GeminiStructuredGenerator(config, client=client, sleeper=sleeper, jitter=jitter)


def test_gemini_generator_uses_response_schema_and_returns_parsed_model() -> None:
    models = FakeModels(response=SimpleNamespace(parsed=Probe(ok=True), text=None))
    subject = generator(models)

    result = subject.generate("probe", Probe)

    assert result == Probe(ok=True)
    assert subject.model_name == "gemini-test"
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


def test_gemini_generator_preserves_response_type_raw_output_and_invalid_endpoints() -> None:
    raw_output = {
        "entities": [{"name": "기관", "entity_type": "기관"}],
        "relations": [
            {"source": "기관", "target": "없는 사건", "relation_type": "발표"},
        ],
    }
    models = FakeModels(response=SimpleNamespace(parsed=raw_output, text=None))

    with pytest.raises(LLMOutputValidationError) as caught:
        generator(models).generate("probe", ArticleGraphExtraction)

    error = caught.value
    assert error.response_type == "ArticleGraphExtraction"
    assert error.raw_output == raw_output
    assert error.invalid_endpoints == (("기관", "없는 사건"),)
    assert "없는 사건" in error.validation_error


def api_error(code: int, *, retry_after: str | None = None) -> errors.APIError:
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    response = httpx.Response(code, headers=headers)
    error_type = errors.ServerError if code >= 500 else errors.ClientError
    return error_type(code, {"error": {"message": "failure"}}, response)


def valid_response() -> SimpleNamespace:
    return SimpleNamespace(parsed=Probe(ok=True), text=None)


def test_gemini_generator_does_not_retry_missing_model() -> None:
    delays: list[float] = []
    models = FakeModels(error=api_error(404))

    with pytest.raises(LLMModelConfigurationError, match="gemini-test"):
        generator(models, sleeper=delays.append).generate("probe", Probe)

    assert len(models.calls) == 1
    assert delays == []


def test_gemini_generator_obeys_retry_after_once() -> None:
    delays: list[float] = []
    models = FakeModels(outcomes=[api_error(429, retry_after="2.5"), valid_response()])

    result = generator(models, sleeper=delays.append).generate("probe", Probe)

    assert result.ok is True
    assert len(models.calls) == 2
    assert delays == [2.5]


def test_gemini_generator_stops_after_two_rate_limit_calls() -> None:
    delays: list[float] = []
    models = FakeModels(outcomes=[api_error(429, retry_after="3"), api_error(429, retry_after="7")])

    with pytest.raises(LLMRateLimitError) as caught:
        generator(models, sleeper=delays.append).generate("probe", Probe)

    assert len(models.calls) == 2
    assert delays == [3.0]
    assert caught.value.retry_after_seconds == 7.0


def test_gemini_generator_retries_service_unavailable_four_calls_with_backoff() -> None:
    delays: list[float] = []
    models = FakeModels(outcomes=[api_error(503) for _ in range(4)])

    with pytest.raises(LLMServiceUnavailableError):
        generator(models, sleeper=delays.append, jitter=lambda: 0.25).generate("probe", Probe)

    assert len(models.calls) == 4
    assert delays == [1.25, 2.25, 4.25]


def test_gemini_generator_maps_transport_failure_for_pipeline_retry() -> None:
    models = FakeModels(error=httpx.ConnectError("dns failure"))

    with pytest.raises(LLMGenerationError, match="네트워크"):
        generator(models).generate("probe", Probe)
