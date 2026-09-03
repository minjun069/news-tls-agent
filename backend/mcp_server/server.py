"""stdio MCP 서버 조립점."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import MCPServer

from app.search import ArticleSearchService
from core.config import load_settings
from infra.db import create_db_engine, create_session_factory
from infra.embedding import GeminiEmbeddingProvider
from infra.qdrant import QdrantVectorStore
from infra.repository import SqlRepository
from mcp_server.tools import ToolDependencies, register_tools

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_AUDIT_LOG = _REPOSITORY_ROOT / "logs" / "mcp-audit.log"


def configure_logging(env: Mapping[str, str]) -> None:
    """stdio 프로토콜을 건드리지 않도록 stderr와 파일에만 로그를 쓴다."""
    configured_path = env.get("MCP_AUDIT_LOG", "").strip()
    log_path = Path(configured_path) if configured_path else _DEFAULT_AUDIT_LOG
    if not log_path.is_absolute():
        log_path = _REPOSITORY_ROOT / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
        force=True,
    )


def build_dependencies(env: Mapping[str, str]) -> ToolDependencies:
    """환경 설정으로 MS-SQL·Qdrant·임베딩 어댑터를 조립한다."""
    settings = load_settings(env)
    engine = create_db_engine(settings.mssql)
    repository = SqlRepository(create_session_factory(engine))
    vector_store = QdrantVectorStore(settings.qdrant)
    embedding_provider = GeminiEmbeddingProvider(settings.gemini)
    searcher = ArticleSearchService(
        keyword_searcher=vector_store,
        vector_store=vector_store,
        embedding_provider=embedding_provider,
    )
    return ToolDependencies(repository=repository, searcher=searcher)


def create_server(dependencies: ToolDependencies) -> MCPServer:
    """테스트와 실행이 같은 툴 등록 경로를 사용하게 서버를 만든다."""
    server = MCPServer(
        "news-tls-agent",
        description="뉴스 기사와 생성된 사건 타임라인을 근거 중심으로 조회합니다.",
        version="0.1.0",
    )
    register_tools(server, dependencies)
    return server


def main() -> None:
    """프로젝트 .env를 읽고 stdio MCP 서버를 실행한다."""
    load_dotenv(_REPOSITORY_ROOT / ".env")
    configure_logging(os.environ)
    server = create_server(build_dependencies(os.environ))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
