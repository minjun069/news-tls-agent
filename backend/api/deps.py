"""FastAPI 조립점 — core/app에 infra 구현을 주입한다."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI
from qdrant_client import QdrantClient
from sqlalchemy.engine import Engine

from api.providers import GraphFactory, HealthChecker, PipelineFactory
from app.agent import IssueChatAgent
from app.graph import GraphProgressSink, KnowledgeGraphService
from app.pipeline import ProgressSink, TimelinePipeline
from app.search import ArticleSearchService
from core.config import Settings, load_settings
from core.ports import EmbeddingProvider
from infra.db import create_db_engine, create_session_factory
from infra.embedding import create_embedding_provider
from infra.gemini import GeminiStructuredGenerator
from infra.mcp_client import MCPToolClient
from infra.qdrant import QdrantVectorStore
from infra.repository import SqlRepository


@lru_cache
def get_settings() -> Settings:
    return load_settings(os.environ)


@lru_cache
def _engine() -> Engine:
    return create_db_engine(get_settings().mssql)


@lru_cache
def _repository() -> SqlRepository:
    return SqlRepository(create_session_factory(_engine()))


@lru_cache
def _vector_store() -> QdrantVectorStore:
    return QdrantVectorStore(get_settings().qdrant)


@lru_cache
def _embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    return create_embedding_provider(settings.embedding, settings.gemini)


@lru_cache
def _searcher() -> ArticleSearchService:
    vector_store = _vector_store()
    return ArticleSearchService(vector_store, vector_store, _embedding_provider())


@lru_cache
def _generator() -> GeminiStructuredGenerator:
    return GeminiStructuredGenerator(get_settings().gemini)


@lru_cache
def _tool_client() -> MCPToolClient:
    return MCPToolClient()


async def provide_tool_client() -> MCPToolClient:
    return _tool_client()


async def provide_pipeline_factory() -> PipelineFactory:
    def build(progress_sink: ProgressSink) -> TimelinePipeline:
        return TimelinePipeline(
            _repository(),
            _searcher(),
            _generator(),
            get_settings().timeline,
            progress_sink=progress_sink,
        )

    return build


@lru_cache
def _chat_agent() -> IssueChatAgent:
    config = get_settings().gemini
    model = ChatGoogleGenerativeAI(
        model=config.model,
        api_key=config.api_key,
        temperature=1.0,
        retries=2,
    )
    return IssueChatAgent(model, _tool_client())


async def provide_chat_agent() -> IssueChatAgent:
    return _chat_agent()


async def provide_graph_factory() -> GraphFactory:
    def build(progress_sink: GraphProgressSink) -> KnowledgeGraphService:
        return KnowledgeGraphService(
            _repository(),
            _generator(),
            progress_sink=progress_sink,
        )

    return build


class DefaultHealthChecker:
    def __init__(
        self,
        engine: Engine,
        qdrant_client: QdrantClient,
        tool_client: MCPToolClient,
    ) -> None:
        self._engine = engine
        self._qdrant = qdrant_client
        self._tool_client = tool_client

    async def check(self) -> Mapping[str, str]:
        mssql, qdrant, mcp_server = await asyncio.gather(
            asyncio.to_thread(self._check_mssql),
            asyncio.to_thread(self._check_qdrant),
            self._check_mcp(),
        )
        return {"mssql": mssql, "qdrant": qdrant, "mcp_server": mcp_server}

    def _check_mssql(self) -> str:
        try:
            with self._engine.connect():
                return "ok"
        except Exception:  # noqa: BLE001 - 헬스 응답은 연결별 상태를 모두 반환해야 한다
            return "error"

    def _check_qdrant(self) -> str:
        try:
            self._qdrant.get_collections()
        except Exception:  # noqa: BLE001 - 헬스 응답은 연결별 상태를 모두 반환해야 한다
            return "error"
        return "ok"

    async def _check_mcp(self) -> str:
        try:
            await self._tool_client.get_tools()
        except Exception:  # noqa: BLE001 - 헬스 응답은 연결별 상태를 모두 반환해야 한다
            return "error"
        return "ok"


@lru_cache
def _health_checker() -> HealthChecker:
    return DefaultHealthChecker(
        _engine(),
        QdrantClient(url=get_settings().qdrant.url),
        _tool_client(),
    )


async def provide_health_checker() -> HealthChecker:
    return _health_checker()
