"""Gemini 구조화 출력 어댑터."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from core.config import GeminiConfig
from core.errors import LLMGenerationError, LLMOutputValidationError, LLMRateLimitError

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class GeminiStructuredGenerator:
    """response schema와 Pydantic 재검증을 한 호출 경계에서 강제한다."""

    def __init__(self, config: GeminiConfig, client: genai.Client | None = None) -> None:
        self._model = config.model
        self._client = client or genai.Client(api_key=config.api_key)

    @property
    def model_name(self) -> str:
        """프롬프트나 자격증명 없이 실행 모델만 관측 계층에 노출한다."""
        return self._model

    def generate(self, prompt: str, response_type: type[ResponseModel]) -> ResponseModel:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_type,
                    temperature=0,
                ),
            )
        except errors.APIError as exc:
            if exc.code == 429:
                raise LLMRateLimitError("Gemini 호출 한도를 초과했습니다") from exc
            raise LLMGenerationError(f"Gemini API 호출에 실패했습니다: {exc.code}") from exc
        except httpx.HTTPError as exc:
            raise LLMGenerationError("Gemini 네트워크 호출에 실패했습니다") from exc

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
