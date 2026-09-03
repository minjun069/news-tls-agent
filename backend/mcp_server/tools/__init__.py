"""MCP 툴 등록과 순수 payload 구현."""

from __future__ import annotations

from mcp_server.tools.dependencies import ToolDependencies
from mcp_server.tools.registry import register_tools

__all__ = ["ToolDependencies", "register_tools"]
