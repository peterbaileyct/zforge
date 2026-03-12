"""Experience Manager — CRUD operations on experiences.

Experiences are organized by ZWorld id under the configured experience folder.
Enumerated by reading world subfolders (no database index).

Implements: src/zforge/managers/experience_manager.py per
docs/User Experience.md and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from zforge.models.results import Experience
from zforge.services.if_engine.if_engine_connector import IfEngineConnector


class ExperienceManager:
    """Singleton manager for experience CRUD and IF engine runtime."""

    def __init__(
        self,
        experience_folder: str,
        if_engine_connector: IfEngineConnector,
    ) -> None:
        self._folder = Path(experience_folder)
        self._if_engine = if_engine_connector
        self._on_created: list[Callable[[Experience], None]] = []

    def add_on_created_listener(
        self, callback: Callable[[Experience], None]
    ) -> None:
        self._on_created.append(callback)

    def create(
        self,
        zworld_id: str,
        name: str,
        compiled_data: bytes,
        suppress_event: bool = False,
    ) -> Experience:
        """Save a compiled experience. Optionally suppress the created event."""
        ext = self._if_engine.get_file_extension()
        world_dir = self._folder / zworld_id
        os.makedirs(world_dir, exist_ok=True)
        file_path = world_dir / f"{name}{ext}"
        file_path.write_bytes(compiled_data)

        experience = Experience(
            zworld_id=zworld_id,
            name=name,
            engine_extension=ext,
            file_path=str(file_path),
        )
        if not suppress_event:
            for cb in self._on_created:
                cb(experience)
        return experience

    def list_for_world(self, zworld_id: str) -> list[Experience]:
        """List all experiences for a given ZWorld."""
        world_dir = self._folder / zworld_id
        if not world_dir.exists():
            return []
        ext = self._if_engine.get_file_extension()
        experiences = []
        for p in sorted(world_dir.iterdir()):
            if p.name.endswith(ext) and not p.name.endswith(".save"):
                name = p.name[: -len(ext)]
                experiences.append(
                    Experience(
                        zworld_id=zworld_id,
                        name=name,
                        engine_extension=ext,
                        file_path=str(p),
                    )
                )
        return experiences

    def list_all(self) -> list[Experience]:
        """List all experiences across all worlds."""
        if not self._folder.exists():
            return []
        experiences = []
        for world_dir in sorted(self._folder.iterdir()):
            if world_dir.is_dir():
                experiences.extend(self.list_for_world(world_dir.name))
        return experiences

    def load_experience(self, zworld_id: str, name: str) -> bytes | None:
        """Load compiled experience data by world id and name."""
        ext = self._if_engine.get_file_extension()
        path = self._folder / zworld_id / f"{name}{ext}"
        if path.exists():
            return path.read_bytes()
        return None

    def save_progress(
        self, zworld_id: str, name: str, state_bytes: bytes
    ) -> None:
        """Save playthrough progress."""
        world_dir = self._folder / zworld_id
        os.makedirs(world_dir, exist_ok=True)
        save_path = world_dir / f"{name}.save"
        save_path.write_bytes(state_bytes)

    def load_progress(self, zworld_id: str, name: str) -> bytes | None:
        """Load saved progress. Returns None if no save exists."""
        save_path = self._folder / zworld_id / f"{name}.save"
        if save_path.exists():
            return save_path.read_bytes()
        return None

    def has_saved_progress(self, zworld_id: str, name: str) -> bool:
        """Check if saved progress exists for an experience."""
        return (self._folder / zworld_id / f"{name}.save").exists()

    def list_saved_experiences(self) -> list[Experience]:
        """List all experiences that have saved progress."""
        if not self._folder.exists():
            return []
        saved = []
        ext = self._if_engine.get_file_extension()
        for world_dir in sorted(self._folder.iterdir()):
            if world_dir.is_dir():
                for save_file in world_dir.glob("*.save"):
                    name = save_file.stem
                    exp_file = world_dir / f"{name}{ext}"
                    if exp_file.exists():
                        saved.append(
                            Experience(
                                zworld_id=world_dir.name,
                                name=name,
                                engine_extension=ext,
                                file_path=str(exp_file),
                            )
                        )
        return saved
