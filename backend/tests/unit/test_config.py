from __future__ import annotations

import pytest

from core.config import (
    ConfigError,
    load_api_config,
    load_embedding_config,
    load_embedding_dimensions,
    load_export_config,
    load_gemini_config,
    load_qdrant_config,
    load_settings,
)


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
    assert settings.gemini.embedding_dimensions == 3072
    assert settings.gemini.rate_limit_max_attempts == 2
    assert settings.gemini.service_unavailable_max_attempts == 4
    assert settings.embedding.provider == "gemini"
    assert settings.embedding.dimensions == 3072
    assert settings.timeline.max_rounds == 4
    assert settings.timeline.max_chain_depth == 2
    assert settings.timeline.max_clarifications == 2
    assert settings.timeline.search_top_k == 20
    assert settings.api.cors_origins == ("http://localhost:5173",)
    assert settings.export.download_dir == "downloads"
    assert settings.export.notion_token == ""


def test_timeline_limits_must_be_positive_integers() -> None:
    env = required_env() | {"TIMELINE_MAX_ROUNDS": "0"}
    with pytest.raises(ConfigError, match="1 이상"):
        load_settings(env)

    env = required_env() | {"TIMELINE_MAX_ROUNDS": "four"}
    with pytest.raises(ConfigError, match="정수"):
        load_settings(env)


def test_vector_only_settings_do_not_require_mssql_credentials() -> None:
    gemini = load_gemini_config({"GOOGLE_API_KEY": "test-key"})
    qdrant = load_qdrant_config({})

    assert gemini.embedding_dimensions == 3072
    assert qdrant.collection == "articles"


def test_embedding_dimensions_must_be_positive() -> None:
    with pytest.raises(ConfigError, match="1 이상"):
        load_gemini_config({"GOOGLE_API_KEY": "test-key", "GEMINI_EMBEDDING_DIMENSIONS": "0"})

    assert load_embedding_dimensions({}) == 3072


def test_local_embedding_defaults_match_benchmarked_contract() -> None:
    config = load_embedding_config({"EMBEDDING_PROVIDER": "local"})

    assert config.model == "nlpai-lab/KURE-v1"
    assert config.dimensions == 1024
    assert config.normalize is True
    assert config.max_seq_length == 256
    assert config.batch_size == 4
    assert config.device == "cpu"
    assert config.threads == 10
    assert config.query_prompt == ""
    assert load_embedding_dimensions({"EMBEDDING_PROVIDER": "local"}) == 1024


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"EMBEDDING_PROVIDER": "unknown"}, "gemini 또는 local"),
        (
            {"EMBEDDING_PROVIDER": "local", "LOCAL_EMBEDDING_NORMALIZE": "sometimes"},
            "true 또는 false",
        ),
        (
            {"EMBEDDING_PROVIDER": "local", "LOCAL_EMBEDDING_MAX_SEQ_LENGTH": "0"},
            "1 이상",
        ),
    ],
)
def test_local_embedding_settings_reject_invalid_values(env: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_embedding_config(env)


def test_api_origins_are_split_trimmed_and_deduplicated() -> None:
    config = load_api_config(
        {"CORS_ORIGINS": ("http://localhost:5173, https://example.com, http://localhost:5173")}
    )

    assert config.cors_origins == ("http://localhost:5173", "https://example.com")


def test_export_settings_are_optional_and_trimmed() -> None:
    config = load_export_config(
        {
            "EXPORT_DOWNLOAD_DIR": " output ",
            "PDF_FONT_PATH": " /fonts/korean.ttf ",
            "NOTION_TOKEN": " token ",
            "NOTION_PARENT_PAGE_ID": " parent ",
        }
    )

    assert config.download_dir == "output"
    assert config.pdf_font_path == "/fonts/korean.ttf"
    assert len(config.notion_token) == 5
    assert config.notion_parent_page_id == "parent"
