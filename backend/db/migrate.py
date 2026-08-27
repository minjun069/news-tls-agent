"""번호 기반 MS-SQL 마이그레이션 실행기.

000은 DB를 만들기 위해 master에서 자동 커밋으로 실행한다. 001부터는 SQL 파일 실행과
schema_migrations 기록을 하나의 트랜잭션으로 묶는다.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Connection, Engine, text

from core.config import MssqlConfig, load_mssql_config
from infra.db import create_db_engine

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parent
_MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_NAME = re.compile(r"^(?P<version>\d{3})_(?P<name>[a-z0-9_]+)\.sql$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GO_LINE = re.compile(r"^\s*GO\s*(?:--.*)?$", re.IGNORECASE | re.MULTILINE)


class MigrationError(RuntimeError):
    """마이그레이션 파일이나 적용 이력이 올바르지 않다."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    sql: str
    checksum: str


def _validate_identifier(value: str, setting_name: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise MigrationError(f"{setting_name}에는 영문자, 숫자, 밑줄만 사용할 수 있습니다")
    return value


def _render_sql(sql: str, config: MssqlConfig) -> str:
    database = _validate_identifier(config.database, "MSSQL_DB")
    collation = _validate_identifier(config.collation, "MSSQL_COLLATION")
    return sql.replace("{{DATABASE}}", database).replace("{{COLLATION}}", collation)


def _load_migrations(config: MssqlConfig) -> list[Migration]:
    migrations: list[Migration] = []
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"마이그레이션 파일 이름이 규칙과 다릅니다: {path.name}")
        raw_sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=match.group("version"),
                name=match.group("name"),
                path=path,
                sql=_render_sql(raw_sql, config),
                checksum=hashlib.sha256(raw_sql.encode()).hexdigest(),
            )
        )

    versions = [migration.version for migration in migrations]
    if not migrations or versions[0] != "000":
        raise MigrationError("000_bootstrap.sql이 필요합니다")
    if len(versions) != len(set(versions)):
        raise MigrationError("중복된 마이그레이션 번호가 있습니다")
    return migrations


def _execute_batches(connection: Connection, sql: str) -> None:
    for batch in _GO_LINE.split(sql):
        if batch.strip():
            connection.exec_driver_sql(batch)


def _applied_checksum(connection: Connection, version: str) -> str | None:
    return connection.execute(
        text("SELECT checksum FROM dbo.schema_migrations WHERE version = :version"),
        {"version": version},
    ).scalar_one_or_none()


def _check_applied(connection: Connection, migration: Migration) -> bool:
    applied = _applied_checksum(connection, migration.version)
    if applied is None:
        return False
    if applied != migration.checksum:
        raise MigrationError(
            f"이미 적용된 {migration.path.name}의 내용이 변경됐습니다. "
            "파일을 복원하고 새 번호로 변경하세요."
        )
    return True


def _record(connection: Connection, migration: Migration) -> None:
    connection.execute(
        text(
            "INSERT INTO dbo.schema_migrations(version, name, checksum) "
            "VALUES (:version, :name, :checksum)"
        ),
        {
            "version": migration.version,
            "name": migration.name,
            "checksum": migration.checksum,
        },
    )


def _bootstrap(config: MssqlConfig, migration: Migration) -> None:
    engine = create_db_engine(config, database="master").execution_options(
        isolation_level="AUTOCOMMIT"
    )
    try:
        with engine.connect() as connection:
            _execute_batches(connection, migration.sql)
    finally:
        engine.dispose()

    target_engine = create_db_engine(config)
    try:
        with target_engine.begin() as connection:
            if not _check_applied(connection, migration):
                _record(connection, migration)
                print(f"적용: {migration.path.name}")
            else:
                print(f"유지: {migration.path.name}")
    finally:
        target_engine.dispose()


def apply_migrations(config: MssqlConfig) -> None:
    """미적용 마이그레이션만 번호 순으로 적용한다."""
    migrations = _load_migrations(config)
    _bootstrap(config, migrations[0])

    engine: Engine = create_db_engine(config)
    try:
        for migration in migrations[1:]:
            with engine.connect() as connection:
                if _check_applied(connection, migration):
                    print(f"유지: {migration.path.name}")
                    continue

            with engine.begin() as connection:
                if _check_applied(connection, migration):
                    continue
                _execute_batches(connection, migration.sql)
                _record(connection, migration)
            print(f"적용: {migration.path.name}")
    finally:
        engine.dispose()


def main() -> None:
    load_dotenv(_REPO_ROOT / ".env")
    apply_migrations(load_mssql_config(os.environ))


if __name__ == "__main__":
    main()
