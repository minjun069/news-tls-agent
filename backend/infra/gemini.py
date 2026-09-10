"""Gemini 구조화 출력 어댑터."""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable, Mapping, Sequence
from typing import TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from core.config import GeminiConfig
from core.errors import (
    LLMGenerationError,
    LLMModelConfigurationError,
    LLMOutputValidationError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
)

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
Sleeper = Callable[[float], None]
Jitter = Callable[[], float]

logger = logging.getLogger("news_tls_agent.gemini")


class GeminiStructuredGenerator:
    """response schema와 Pydantic 재검증을 한 호출 경계에서 강제한다."""

    def __init__(
        self,
        config: GeminiConfig,
        client: genai.Client | None = None,
        *,
        sleeper: Sleeper = time.sleep,
        jitter: Jitter = random.random,
    ) -> None:
        self._model = config.model
        self._client = client or genai.Client(api_key=config.api_key)
        self._rate_limit_max_attempts = config.rate_limit_max_attempts
        self._service_unavailable_max_attempts = config.service_unavailable_max_attempts
        self._sleeper = sleeper
        self._jitter = jitter

    @property
    def model_name(self) -> str:
        """프롬프트나 자격증명 없이 실행 모델만 관측 계층에 노출한다."""
        return self._model

    def generate(self, prompt: str, response_type: type[ResponseModel]) -> ResponseModel:
        response = self._generate_content(prompt, response_type)

        raw_output = response.parsed
        try:
            if isinstance(raw_output, response_type):
                return raw_output
            if raw_output is None and response.text:
                raw_output = json.loads(response.text)
            if raw_output is not None:
                return response_type.model_validate(raw_output)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMOutputValidationError(
                "Gemini 구조화 출력 검증에 실패했습니다",
                response_type=response_type.__name__,
                validation_error=str(exc),
                raw_output=raw_output,
                invalid_endpoints=_invalid_relation_endpoints(raw_output),
            ) from exc
        raise LLMGenerationError("Gemini가 비어 있는 응답을 반환했습니다")

    def _generate_content(self, prompt: str, response_type: type[ResponseModel]) -> object:
        rate_limit_attempts = 0
        service_attempts = 0
        while True:
            try:
                return self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=response_type,
                        temperature=0,
                    ),
                )
            except errors.APIError as exc:
                if exc.code == 404:
                    raise LLMModelConfigurationError(
                        f"Gemini 모델을 호출할 수 없습니다: {self._model}"
                    ) from exc
                if exc.code == 429:
                    rate_limit_attempts += 1
                    retry_after = _retry_after_seconds(exc)
                    if rate_limit_attempts >= self._rate_limit_max_attempts:
                        raise LLMRateLimitError(
                            "Gemini 호출 한도를 초과했습니다",
                            retry_after_seconds=retry_after,
                        ) from exc
                    self._retry_wait(429, rate_limit_attempts, retry_after)
                    continue
                if exc.code == 503:
                    service_attempts += 1
                    if service_attempts >= self._service_unavailable_max_attempts:
                        raise LLMServiceUnavailableError(
                            "Gemini 서비스를 일시적으로 사용할 수 없습니다"
                        ) from exc
                    delay = float(2 ** (service_attempts - 1)) + max(0.0, self._jitter())
                    self._retry_wait(503, service_attempts, delay)
                    continue
                raise LLMGenerationError(f"Gemini API 호출에 실패했습니다: {exc.code}") from exc
            except httpx.HTTPError as exc:
                raise LLMGenerationError("Gemini 네트워크 호출에 실패했습니다") from exc

    def _retry_wait(self, status_code: int, attempt: int, delay: float) -> None:
        logger.warning(
            "Gemini retry scheduled: model=%s status_code=%s attempt=%s delay_seconds=%s",
            self._model,
            status_code,
            attempt,
            delay,
            extra={
                "event_name": "gemini.retry_scheduled",
                "model_name": self._model,
                "status_code": status_code,
                "attempt": attempt,
                "delay_seconds": delay,
            },
        )
        self._sleeper(delay)


def _invalid_relation_endpoints(payload: object) -> tuple[tuple[str, str], ...]:
    """그래프 형태의 원본이면 목록에 없는 관계 끝점을 감사 정보로 추출한다."""
    if not isinstance(payload, Mapping):
        return ()
    raw_entities = payload.get("entities")
    raw_relations = payload.get("relations")
    if not isinstance(raw_entities, Sequence) or not isinstance(raw_relations, Sequence):
        return ()
    names = {
        item.get("name")
        for item in raw_entities
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    invalid: list[tuple[str, str]] = []
    for item in raw_relations:
        if not isinstance(item, Mapping):
            continue
        source = item.get("source")
        target = item.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        if source not in names or target not in names:
            invalid.append((source, target))
    return tuple(invalid)


def _retry_after_seconds(exc: errors.APIError) -> float:
    response = exc.response
    headers = getattr(response, "headers", None)
    raw_value = headers.get("Retry-After") if isinstance(headers, Mapping) else None
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        return 1.0
