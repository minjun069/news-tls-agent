"""라우터가 infra를 알지 않도록 제공하는 FastAPI 의존성 포트."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from app.agent import IssueChatAgent
from app.pipeline import TimelinePipeline
from core.models import PipelineProgress
from core.ports import ToolClient


class HealthChecker(Protocol):
    async def check(self) -> Mapping[str, str]:
        """MS-SQL·Qdrant·MCP 연결 상태를 반환한다."""
        ...


class PipelineFactory(Protocol):
    def __call__(self, progress_sink: Callable[[PipelineProgress], None]) -> TimelinePipeline:
        """요청별 진행 sink가 연결된 파이프라인을 만든다."""
        ...


async def get_health_checker() -> HealthChecker:
    raise RuntimeError("api/main.py가 health 의존성을 조립하지 않았습니다")


async def get_pipeline_factory() -> PipelineFactory:
    raise RuntimeError("api/main.py가 pipeline 의존성을 조립하지 않았습니다")


async def get_tool_client() -> ToolClient[object]:
    raise RuntimeError("api/main.py가 MCP 의존성을 조립하지 않았습니다")


async def get_chat_agent() -> IssueChatAgent:
    raise RuntimeError("api/main.py가 agent 의존성을 조립하지 않았습니다")
