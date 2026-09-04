"""Gemini 구조화 출력 어댑터."""

from __future__ import annotations

from typing import TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from core.config import GeminiConfig
from core.errors import LLMGenerationError, LLMRateLimitError

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class GeminiStructuredGenerator:
    """response schema와 Pydantic 재검증을 한 호출 경계에서 강제한다."""

    def __init__(self, config: GeminiConfig, client: genai.Client | None = None) -> None:
        self._model = config.model
        self._client = client or genai.Client(api_key=config.api_key)

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

        try:
            if isinstance(response.parsed, response_type):
                return response.parsed
            if response.parsed is not None:
                return response_type.model_validate(response.parsed)
            if response.text:
                return response_type.model_validate_json(response.text)
        except ValidationError as exc:
            raise LLMGenerationError("Gemini 구조화 출력 검증에 실패했습니다") from exc
        raise LLMGenerationError("Gemini가 비어 있는 응답을 반환했습니다")
