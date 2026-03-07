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
    from zforge.models.zworld import ZWorld


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
                        "See the ZWorld spec for required fields: "
                        "id, name, locations, characters, relationships, events."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "locations": {"type": "array"},
                            "characters": {"type": "array"},
                            "relationships": {"type": "array"},
                            "events": {"type": "array"},
                        },
                        "required": ["id", "name"],
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
        from zforge.models.zworld import ZWorld

        zworld = ZWorld.from_dict(arguments)
        self._zworld_manager.create(zworld)
        return [
            TextContent(
                type="text",
                text=f"ZWorld '{zworld.name}' created successfully.",
            )
        ]

    @property
    def server(self) -> Server:
        return self._server
