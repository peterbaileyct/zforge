"""ZWorld Manager — CRUD operations on ZWorlds.

ZWorlds are stored as JSON .zworld files in the configured zworld_folder.

Implements: src/zforge/managers/zworld_manager.py per
docs/User Experience.md and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from zforge.models.zworld import ZWorld


class ZWorldManager:
    """Singleton manager for ZWorld CRUD operations."""

    def __init__(self, zworld_folder: str) -> None:
        self._folder = Path(zworld_folder)
        self._on_created: list[Callable[[ZWorld], None]] = []

    def add_on_created_listener(
        self, callback: Callable[[ZWorld], None]
    ) -> None:
        self._on_created.append(callback)

    def create(
        self, zworld: ZWorld, suppress_event: bool = False
    ) -> None:
        """Create and save a ZWorld. Optionally suppress the created event."""
        os.makedirs(self._folder, exist_ok=True)
        path = self._folder / f"{zworld.id}.zworld"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(zworld.to_dict(), f, indent=2)
        if not suppress_event:
            for cb in self._on_created:
                cb(zworld)

    def read(self, zworld_id: str) -> ZWorld | None:
        """Load a ZWorld by id. Returns None if not found."""
        path = self._folder / f"{zworld_id}.zworld"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ZWorld.from_dict(data)

    def update(self, zworld: ZWorld) -> None:
        """Update an existing ZWorld on disk."""
        path = self._folder / f"{zworld.id}.zworld"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(zworld.to_dict(), f, indent=2)

    def delete(self, zworld_id: str) -> None:
        """Delete a ZWorld file."""
        path = self._folder / f"{zworld_id}.zworld"
        if path.exists():
            path.unlink()

    def list_all(self) -> list[ZWorld]:
        """List all available ZWorlds."""
        if not self._folder.exists():
            return []
        worlds = []
        for p in sorted(self._folder.glob("*.zworld")):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            worlds.append(ZWorld.from_dict(data))
        return worlds
