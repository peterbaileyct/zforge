"""External MCP Server.

Exposes Z-Forge operations to external agents via the Python mcp library.
Internal orchestration uses LangGraph @tool functions directly — never
routes through this MCP server.

Implements: src/zforge/services/mcp/zforge_mcp_server.py per
docs/Managers, Processes, and MCP Server.md and docs/LLM Abstraction Layer.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server import Server
from mcp.types import Tool, TextContent

if TYPE_CHECKING:
    from zforge.managers.zworld_manager import ZWorldManager


class ZForgeMcpServer:
    """External MCP server exposing Z-Forge tools to external agents.

    NOTE: The old ``CreateZWorld`` tool (which delegated to
    ``world_create_zworld``) has been removed.  World creation is now
    driven by the full LangGraph pipeline via ``ZForgeManager``.
    MCP tools for the new pipeline will be added in a future update.
    """

    def __init__(self) -> None:
        self._server = Server("zforge")
        self._zworld_manager: ZWorldManager | None = None
        self._setup_tools()

    def set_zworld_manager(self, manager: ZWorldManager) -> None:
        self._zworld_manager = manager

    def _setup_tools(self) -> None:
        @self._server.list_tools()
        async def list_tools() -> list[Tool]:
            return []

        @self._server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    @property
    def server(self) -> Server:
        return self._server
