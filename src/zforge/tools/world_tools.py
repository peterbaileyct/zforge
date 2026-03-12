"""Shared helpers for world creation.

Provides the ZWorldManager injection point used by the finalizer node
in world_creation_graph.py.

Implements: src/zforge/tools/world_tools.py per
docs/World Generation.md and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zforge.managers.zworld_manager import ZWorldManager

# Module-level reference set by the graph builder before compilation.
_zworld_manager: ZWorldManager | None = None


def set_zworld_manager(manager: ZWorldManager) -> None:
    """Inject the ZWorldManager dependency for tool functions."""
    global _zworld_manager
    _zworld_manager = manager


def get_zworld_manager() -> ZWorldManager | None:
    """Return the injected ZWorldManager (used by the finalizer node)."""
    return _zworld_manager
