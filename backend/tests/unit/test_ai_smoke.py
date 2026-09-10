from __future__ import annotations

from types import SimpleNamespace

from google.genai import errors

from scripts.ai_smoke import (
    EXIT_CONFIGURATION,
    EXIT_FUNCTION_CALLING,
    EXIT_MODEL_ID,
    EXIT_STRUCTURED_OUTPUT,
    SmokeProbe,
    main,
)


class FakeModels:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes) -> None:
        self.models = FakeModels(outcomes)


def env() -> dict[str, str]:
    return {"GOOGLE_API_KEY": "test-key", "GEMINI_MODEL": "gemini-smoke"}


def test_ai_smoke_calls_structured_output_and_function_call(capsys) -> None:
    client = FakeClient(
        [
            SimpleNamespace(parsed=SmokeProbe(status="ok"), text=None),
            SimpleNamespace(
                function_calls=[
                    SimpleNamespace(name="report_ai_smoke_status", args={"status": "ok"})
                ]
            ),
        ]
    )

    exit_code = main(env(), client_factory=lambda **_kwargs: client)

    output = capsys.readouterr()
    assert exit_code == 0
    assert "PASS model_id: gemini-smoke" in output.out
    assert "PASS structured_output: status=ok" in output.out
    assert "PASS function_calling: report_ai_smoke_status" in output.out
    assert len(client.models.calls) == 2


def test_ai_smoke_reports_configuration_failure(capsys) -> None:
    exit_code = main({}, client_factory=lambda **_kwargs: FakeClient([]))

    output = capsys.readouterr()
    assert exit_code == EXIT_CONFIGURATION
    assert f"FAIL configuration (exit={EXIT_CONFIGURATION})" in output.err


def test_ai_smoke_reports_model_id_failure(capsys) -> None:
    missing_model = errors.ClientError(404, {"error": {"message": "missing model"}})

    exit_code = main(
        env(),
        client_factory=lambda **_kwargs: FakeClient([missing_model]),
    )

    output = capsys.readouterr()
    assert exit_code == EXIT_MODEL_ID
    assert f"FAIL model_id (exit={EXIT_MODEL_ID})" in output.err


def test_ai_smoke_reports_structured_output_failure(capsys) -> None:
    client = FakeClient([SimpleNamespace(parsed={"status": "wrong"}, text=None)])

    exit_code = main(env(), client_factory=lambda **_kwargs: client)

    output = capsys.readouterr()
    assert exit_code == EXIT_STRUCTURED_OUTPUT
    assert f"FAIL structured_output (exit={EXIT_STRUCTURED_OUTPUT})" in output.err


def test_ai_smoke_reports_function_calling_failure(capsys) -> None:
    client = FakeClient(
        [
            SimpleNamespace(parsed=SmokeProbe(status="ok"), text=None),
            SimpleNamespace(function_calls=None),
        ]
    )

    exit_code = main(env(), client_factory=lambda **_kwargs: client)

    output = capsys.readouterr()
    assert exit_code == EXIT_FUNCTION_CALLING
    assert f"FAIL function_calling (exit={EXIT_FUNCTION_CALLING})" in output.err
