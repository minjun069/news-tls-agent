"""설정 값의 형태와 환경변수 해석 — AGENTS.md §7 (접속정보 하드코딩 금지, NFR-10).

이 모듈은 순수하다. 환경 매핑을 인자로 받고, 파일이나 프로세스를 건드리지 않는다.
실행 환경에 따라 달라지는 해석(WSL 게이트웨이 등)은 infra가 맡는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(Exception):
    """필수 환경변수가 없거나 값이 잘못됐다."""


@dataclass(frozen=True)
class MssqlConfig:
    host: str  # 빈 문자열이면 infra가 실행 환경에서 해석한다
    port: int
    database: str
    user: str
    password: str
    driver: str
    trust_cert: bool
    collation: str


@dataclass(frozen=True)
class QdrantConfig:
    url: str
    collection: str


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str
    model: str
    embedding_model: str


@dataclass(frozen=True)
class Settings:
    mssql: MssqlConfig
    qdrant: QdrantConfig
    gemini: GeminiConfig


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key}가 .env에 없습니다")
    return value


def _optional(env: Mapping[str, str], key: str, default: str = "") -> str:
    return env.get(key, "").strip() or default


def load_settings(env: Mapping[str, str]) -> Settings:
    """환경 매핑에서 설정을 읽는다. 호출부가 os.environ을 넘긴다."""
    return Settings(
        mssql=MssqlConfig(
            # 비워두면 infra가 해석한다. WSL 게이트웨이 IP는 재시작마다 바뀌므로
            # .env에 적어두면 매번 고쳐야 한다.
            host=_optional(env, "MSSQL_HOST"),
            port=int(_optional(env, "MSSQL_PORT", "1433")),
            database=_optional(env, "MSSQL_DB", "newsagent"),
            user=_required(env, "MSSQL_USER"),
            password=_required(env, "MSSQL_PASSWORD"),
            driver=_optional(env, "MSSQL_DRIVER", "ODBC Driver 18 for SQL Server"),
            trust_cert=_optional(env, "MSSQL_TRUST_CERT", "yes").lower() in {"yes", "true", "1"},
            collation=_optional(env, "MSSQL_COLLATION", "Korean_Wansung_CI_AS"),
        ),
        qdrant=QdrantConfig(
            url=_optional(env, "QDRANT_URL", "http://localhost:6333"),
            collection=_optional(env, "QDRANT_COLLECTION", "articles"),
        ),
        gemini=GeminiConfig(
            api_key=_required(env, "GOOGLE_API_KEY"),
            model=_optional(env, "GEMINI_MODEL", "gemini-2.5-flash"),
            embedding_model=_optional(env, "GEMINI_EMBEDDING_MODEL", "text-embedding-004"),
        ),
    )
