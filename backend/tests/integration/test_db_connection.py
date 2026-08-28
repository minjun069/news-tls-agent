"""MS-SQL 접속 검증 — ROADMAP S1-4 완료 기준.

`make test-all`로 실행한다. 저장소가 필요하므로 `make test`(단위)에서는 제외된다.
WSL 재시작이나 네트워크 설정 변경 뒤 이 파일을 돌려 환경을 확인한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import text

from core.config import ConfigError, Settings, load_settings
from infra.db import create_db_engine, resolve_host

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def settings() -> Settings:
    load_dotenv(_REPO_ROOT / ".env")
    try:
        return load_settings(os.environ)
    except ConfigError as exc:
        pytest.skip(f".env가 채워지지 않았습니다: {exc}")


def test_host_resolves(settings: Settings) -> None:
    """MSSQL_HOST가 비어 있으면 기본 게이트웨이로 해석된다 (모드 A)."""
    host = resolve_host(settings.mssql)
    assert host, "호스트를 해석하지 못했습니다"


def test_server_reachable(settings: Settings) -> None:
    """서버에 도달하고 쿼리가 돈다. 대상 DB가 아직 없어도 되도록 master로 붙는다."""
    with create_db_engine(settings.mssql, database="master").connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_collation_matches_config(settings: Settings) -> None:
    """서버 collation이 설정과 일치한다 (docs/architecture/overview.md §4.2).

    네이티브 설치와 컨테이너의 기본값이 달라, 어긋나면 한글 정렬·NVARCHAR 비교·
    LIKE 동작이 환경마다 달라진다. 로컬은 통과하고 CI만 깨지는 원인이 된다.
    """
    with create_db_engine(settings.mssql, database="master").connect() as conn:
        actual = conn.execute(
            text("SELECT CONVERT(nvarchar(128), SERVERPROPERTY('Collation'))")
        ).scalar()
    assert actual == settings.mssql.collation, (
        f"서버 collation={actual!r}, 설정={settings.mssql.collation!r}. "
        ".env의 MSSQL_COLLATION을 서버에 맞추거나 서버를 재구성하세요."
    )


def test_target_database_exists(settings: Settings) -> None:
    """대상 DB가 있다. 없으면 S2의 000_bootstrap.sql이 만든다."""
    with create_db_engine(settings.mssql, database="master").connect() as conn:
        exists = conn.execute(
            text("SELECT DB_ID(:name)"), {"name": settings.mssql.database}
        ).scalar()
    if exists is None:
        pytest.skip(f"{settings.mssql.database} DB가 아직 없습니다 — S2에서 생성합니다")

    with create_db_engine(settings.mssql).connect() as conn:
        assert conn.execute(text("SELECT DB_NAME()")).scalar() == settings.mssql.database


def test_odbc_driver_reports_version(settings: Settings) -> None:
    """진단용 — 실패 시 어느 서버에 붙었는지 로그에 남는다."""
    with create_db_engine(settings.mssql, database="master").connect() as conn:
        version = conn.execute(text("SELECT @@VERSION")).scalar()
    assert "SQL Server" in version
    print(f"\n  접속: {resolve_host(settings.mssql)}\n  {version.splitlines()[0]}")
