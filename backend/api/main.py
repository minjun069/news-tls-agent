"""news-tls-agent FastAPI 애플리케이션."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import deps, providers
from api.routes.articles import router as articles_router
from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from api.routes.issues import router as issues_router
from core.config import load_api_config

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_API_LOG = _REPOSITORY_ROOT / "logs" / "api.log"


def configure_logging() -> None:
    configured_path = os.environ.get("API_LOG", "").strip()
    log_path = Path(configured_path) if configured_path else _DEFAULT_API_LOG
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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield


def create_app() -> FastAPI:
    load_dotenv(_REPOSITORY_ROOT / ".env")
    api_config = load_api_config(os.environ)
    application = FastAPI(
        title="news-tls-agent API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(api_config.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.dependency_overrides[providers.get_health_checker] = deps.provide_health_checker
    application.dependency_overrides[providers.get_pipeline_factory] = deps.provide_pipeline_factory
    application.dependency_overrides[providers.get_tool_client] = deps.provide_tool_client
    application.dependency_overrides[providers.get_chat_agent] = deps.provide_chat_agent
    application.include_router(health_router)
    application.include_router(issues_router)
    application.include_router(articles_router)
    application.include_router(chat_router)
    return application


app = create_app()
