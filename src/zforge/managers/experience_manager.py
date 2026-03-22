"""Experience Manager — CRUD operations on experiences.

Experiences are organized by ZWorld id under the configured experience folder.
Enumerated by reading world subfolders (no database index).

Implements: src/zforge/managers/experience_manager.py per
docs/User Experience.md and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

import json
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

    ZFORGE_VERSION = "0.1"

    def create(
        self,
        zworld_id: str,
        name: str,
        compiled_data: bytes,
        suppress_event: bool = False,
        title: str | None = None,
        research_notes: str | None = None,
        outline: str | None = None,
        prose: str | None = None,
        player_preferences: dict[str, object] | None = None,
    ) -> Experience:
        """Save a compiled experience wrapped in the zforge JSON envelope.

        The file format is a JSON object with keys: zforgeVersion, title, slug,
        researchNotes, outline, prose, playerPreferences, and inkJson (the
        native ink compiled JSON).  player_preferences should be the override
        dict only — pass None when the user did not supply an explicit override.
        """
        ext = self._if_engine.get_file_extension()
        world_dir = self._folder / zworld_id
        os.makedirs(world_dir, exist_ok=True)
        file_path = world_dir / f"{name}{ext}"
        ink_json_str = compiled_data.decode("utf-8")
        wrapper = {
            "zforgeVersion": self.ZFORGE_VERSION,
            "title": title,
            "slug": name,
            "researchNotes": research_notes,
            "outline": outline,
            "prose": prose,
            "playerPreferences": player_preferences,
            "inkJson": ink_json_str,
        }
        file_path.write_bytes(json.dumps(wrapper).encode("utf-8"))

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
        """Load compiled experience data by world id and name.

        Detects the zforge wrapper format (presence of ``zforgeVersion`` key)
        and returns only the raw ink JSON bytes.  Legacy files that contain
        raw ink JSON are returned as-is.
        """
        ext = self._if_engine.get_file_extension()
        path = self._folder / zworld_id / f"{name}{ext}"
        if not path.exists():
            return None
        raw = path.read_bytes()
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "zforgeVersion" in data:
                return data["inkJson"].encode("utf-8")
        except (json.JSONDecodeError, KeyError, AttributeError):
            pass
        return raw

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
