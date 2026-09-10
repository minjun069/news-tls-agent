"""현재 Gemini 모델의 구조화 출력과 함수 호출을 실제로 점검한다."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from core.config import ConfigError, GeminiConfig, load_gemini_config
from core.errors import LLMGenerationError, LLMModelConfigurationError, LLMOutputValidationError
from infra.gemini import GeminiStructuredGenerator

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_FUNCTION_NAME = "report_ai_smoke_status"

EXIT_CONFIGURATION = 2
EXIT_MODEL_ID = 3
EXIT_STRUCTURED_OUTPUT = 4
EXIT_FUNCTION_CALLING = 5


class SmokeProbe(BaseModel):
    status: Literal["ok"]


class GenerateModels(Protocol):
    def generate_content(self, **kwargs: object) -> object: ...


class SmokeClient(Protocol):
    models: GenerateModels


ClientFactory = Callable[..., SmokeClient]


@dataclass(frozen=True)
class AiSmokeResult:
    model: str
    structured_status: str
    function_name: str


class AiSmokeError(Exception):
    def __init__(self, stage: str, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.exit_code = exit_code


def run_ai_smoke(config: GeminiConfig, client: SmokeClient) -> AiSmokeResult:
    """생성 모델 한 개에 대해 두 기능을 순서대로 실제 호출한다."""
    generator = GeminiStructuredGenerator(config, client=client)
    try:
        structured = generator.generate(
            "Return JSON with the single field status set to ok.",
            SmokeProbe,
        )
    except LLMModelConfigurationError as exc:
        raise AiSmokeError("model_id", EXIT_MODEL_ID, str(exc)) from exc
    except LLMOutputValidationError as exc:
        raise AiSmokeError(
            "structured_output",
            EXIT_STRUCTURED_OUTPUT,
            exc.validation_error,
        ) from exc
    except LLMGenerationError as exc:
        raise AiSmokeError("structured_output", EXIT_STRUCTURED_OUTPUT, str(exc)) from exc

    try:
        response = client.models.generate_content(
            model=config.model,
            contents=(
                f"Call {_FUNCTION_NAME} exactly once with status set to ok. "
                "Do not answer with plain text."
            ),
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        function_declarations=[
                            types.FunctionDeclaration(
                                name=_FUNCTION_NAME,
                                description="Report that the AI smoke check reached function calling.",
                                parameters_json_schema={
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string", "enum": ["ok"]},
                                    },
                                    "required": ["status"],
                                },
                            )
                        ]
                    )
                ],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="ANY",
                        allowed_function_names=[_FUNCTION_NAME],
                    )
                ),
                temperature=0,
            ),
        )
    except (errors.APIError, httpx.HTTPError, TypeError, ValueError) as exc:
        raise AiSmokeError("function_calling", EXIT_FUNCTION_CALLING, str(exc)) from exc

    function_calls = getattr(response, "function_calls", None)
    if not function_calls or function_calls[0].name != _FUNCTION_NAME:
        raise AiSmokeError(
            "function_calling",
            EXIT_FUNCTION_CALLING,
            f"expected {_FUNCTION_NAME}, received no matching function call",
        )
    return AiSmokeResult(
        model=config.model,
        structured_status=structured.status,
        function_name=function_calls[0].name,
    )


def main(
    env: Mapping[str, str] | None = None,
    *,
    client_factory: ClientFactory = genai.Client,
) -> int:
    load_dotenv(_REPOSITORY_ROOT / ".env")
    current_env = os.environ if env is None else env
    try:
        config = load_gemini_config(current_env)
    except ConfigError as exc:
        print(f"FAIL configuration (exit={EXIT_CONFIGURATION}): {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION
    try:
        client = client_factory(api_key=config.api_key)
    except (TypeError, ValueError) as exc:
        print(f"FAIL configuration (exit={EXIT_CONFIGURATION}): {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION

    try:
        result = run_ai_smoke(config, client)
    except AiSmokeError as exc:
        print(f"FAIL {exc.stage} (exit={exc.exit_code}): {exc}", file=sys.stderr)
        return exc.exit_code

    print(f"PASS model_id: {result.model}")
    print(f"PASS structured_output: status={result.structured_status}")
    print(f"PASS function_calling: {result.function_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
