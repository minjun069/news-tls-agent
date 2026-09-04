from __future__ import annotations

import pytest

from core.config import ConfigError, load_settings


def required_env() -> dict[str, str]:
    return {
        "GOOGLE_API_KEY": "test-key",
        "MSSQL_USER": "sa",
        "MSSQL_PASSWORD": "test-password",
    }


def test_s5_defaults_use_verified_models_and_loop_limits() -> None:
    settings = load_settings(required_env())

    assert settings.gemini.model == "gemini-3.6-flash"
    assert settings.gemini.embedding_model == "gemini-embedding-2"
    assert settings.timeline.max_rounds == 4
    assert settings.timeline.max_chain_depth == 2
    assert settings.timeline.max_clarifications == 2
    assert settings.timeline.search_top_k == 20


def test_timeline_limits_must_be_positive_integers() -> None:
    env = required_env() | {"TIMELINE_MAX_ROUNDS": "0"}
    with pytest.raises(ConfigError, match="1 이상"):
        load_settings(env)

    env = required_env() | {"TIMELINE_MAX_ROUNDS": "four"}
    with pytest.raises(ConfigError, match="정수"):
        load_settings(env)
