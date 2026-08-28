"""MS-SQL 엔진·세션 — AGENTS.md §2.

접속 호스트 해석이 여기 있는 이유: WSL 게이트웨이를 알아내는 것은 실행 환경에 대한
지식이라 순수 계층(core)이 알 일이 아니다. core는 값의 형태만 정의한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import ConfigError, MssqlConfig

logger = logging.getLogger(__name__)

_PROC_ROUTE = Path("/proc/net/route")
_DEFAULT_DESTINATION = "00000000"


def _default_gateway() -> str | None:
    """리눅스 기본 게이트웨이 IP. WSL2에서는 이것이 Windows 호스트다.

    `/proc/net/route`를 직접 읽는다. `ip route`를 서브프로세스로 부르는 것보다
    의존이 적고, `/etc/resolv.conf`의 nameserver와 달리 DNS 설정에 영향받지 않는다.
    """
    if not _PROC_ROUTE.exists():
        return None

    for line in _PROC_ROUTE.read_text().splitlines()[1:]:
        fields = line.split()
        if len(fields) < 3 or fields[1] != _DEFAULT_DESTINATION:
            continue
        # 게이트웨이는 리틀엔디언 16진수로 적혀 있다
        raw = int(fields[2], 16)
        return ".".join(str((raw >> (8 * i)) & 0xFF) for i in range(4))
    return None


def resolve_host(config: MssqlConfig) -> str:
    """접속할 호스트를 정한다.

    `.env`의 MSSQL_HOST가 있으면 그대로 쓴다 (모드 B·C: `mssql`, `localhost`).
    비어 있으면 기본 게이트웨이로 해석한다 (모드 A: WSL → Windows 호스트).
    """
    if config.host:
        return config.host

    gateway = _default_gateway()
    if gateway is None:
        raise ConfigError(
            "MSSQL_HOST가 비어 있고 기본 게이트웨이도 찾지 못했습니다. "
            ".env에 MSSQL_HOST를 직접 지정하세요."
        )
    logger.info("MSSQL_HOST 미지정 — 기본 게이트웨이로 해석: %s", gateway)
    return gateway


def build_url(config: MssqlConfig, database: str | None = None) -> str:
    """SQLAlchemy 접속 URL.

    ODBC Driver 18은 Encrypt=yes가 기본이다. 자체 서명 인증서를 쓰는 로컬
    인스턴스에서는 TrustServerCertificate=yes가 없으면 인증서 오류로 실패한다.

    database를 넘기면 설정값 대신 그것으로 붙는다. 대상 DB가 아직 없을 때
    `master`로 붙어 서버 도달 여부만 확인하는 용도다.
    """
    host = resolve_host(config)
    odbc = (
        f"DRIVER={{{config.driver}}};"
        f"SERVER={host},{config.port};"
        f"DATABASE={database or config.database};"
        f"UID={config.user};"
        f"PWD={config.password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate={'yes' if config.trust_cert else 'no'};"
    )
    return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc)}"


def create_db_engine(config: MssqlConfig, database: str | None = None) -> Engine:
    """엔진을 만든다. 모듈 레벨 전역으로 두지 않는다 (docs/engineering/code-conventions.md)."""
    return create_engine(build_url(config, database), pool_pre_ping=True, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """요청·작업 단위로 세션을 만들 팩토리. 세션 자체는 전역으로 공유하지 않는다."""
    return sessionmaker(bind=engine, expire_on_commit=False)
