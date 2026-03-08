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
    """External MCP server exposing Z-Forge tools to external agents."""

    def __init__(self) -> None:
        self._server = Server("zforge")
        self._zworld_manager: ZWorldManager | None = None
        self._setup_tools()

    def set_zworld_manager(self, manager: ZWorldManager) -> None:
        self._zworld_manager = manager

    def _setup_tools(self) -> None:
        @self._server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="CreateZWorld",
                    description=(
                        "Create a ZWorld from the provided properties. "
                        "See docs/Z-World.md for the full specification."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Display name"},
                            "summary": {"type": "string", "description": "1-3 paragraph diegetic summary"},
                            "characters": {"type": "array"},
                            "locations": {"type": "array"},
                            "events": {"type": "array"},
                            "mechanics": {"type": "array", "items": {"type": "string"}},
                            "tropes": {"type": "array", "items": {"type": "string"}},
                            "species": {"type": "array", "items": {"type": "string"}},
                            "occupations": {"type": "array", "items": {"type": "string"}},
                            "relationships": {"type": "array"},
                        },
                        "required": ["name", "summary"],
                    },
                ),
            ]

        @self._server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            if name == "CreateZWorld":
                return await self._handle_create_zworld(arguments)
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def _handle_create_zworld(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        if self._zworld_manager is None:
            return [
                TextContent(type="text", text="ZWorldManager not initialized")
            ]
        from zforge.tools.world_tools import world_create_zworld

        # Delegate to the same tool function used by the LangGraph pipeline
        result = world_create_zworld.invoke(arguments)
        title = arguments.get("name", "Unknown")
        return [
            TextContent(
                type="text",
                text=f"ZWorld '{title}' created successfully.",
            )
        ]

    @property
    def server(self) -> Server:
        return self._server
