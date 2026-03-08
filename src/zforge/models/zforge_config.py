"""Configuration models.

ZForgeConfig and PlayerPreferences per docs/Data and File Specifications.md
and docs/Player Preferences.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlayerPreferences:
    """Player preference scales (1-10, default 5)."""

    character_to_plot: int = 5
    narrative_to_dialog: int = 5
    puzzle_complexity: int = 5
    levity: int = 5
    general_preferences: str = ""
    logical_vs_mood: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "characterToPlot": self.character_to_plot,
            "narrativeToDialog": self.narrative_to_dialog,
            "puzzleComplexity": self.puzzle_complexity,
            "levity": self.levity,
            "generalPreferences": self.general_preferences,
            "logicalVsMood": self.logical_vs_mood,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlayerPreferences:
        return cls(
            character_to_plot=data.get("characterToPlot", 5),
            narrative_to_dialog=data.get("narrativeToDialog", 5),
            puzzle_complexity=data.get("puzzleComplexity", 5),
            levity=data.get("levity", 5),
            general_preferences=data.get("generalPreferences", ""),
            logical_vs_mood=data.get("logicalVsMood", 5),
        )


@dataclass
class ZForgeConfig:
    """Application configuration persisted as JSON via platformdirs."""

    bundles_root: str = ""
    experience_folder: str = ""
    default_if_engine: str = "ink"
    chat_model_path: str = ""
    chat_context_size: int = 8192
    chat_gpu_layers: int = 0
    embedding_model_path: str = ""
    embedding_context_size: int = 512
    embedding_gpu_layers: int = 0
    preferences: PlayerPreferences = field(default_factory=PlayerPreferences)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundles_root": self.bundles_root,
            "experience_folder": self.experience_folder,
            "default_if_engine": self.default_if_engine,
            "chat_model_path": self.chat_model_path,
            "chat_context_size": self.chat_context_size,
            "chat_gpu_layers": self.chat_gpu_layers,
            "embedding_model_path": self.embedding_model_path,
            "embedding_context_size": self.embedding_context_size,
            "embedding_gpu_layers": self.embedding_gpu_layers,
            "preferences": self.preferences.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ZForgeConfig:
        prefs_data = data.get("preferences", {})
        return cls(
            bundles_root=data.get("bundles_root", ""),
            experience_folder=data.get("experience_folder", ""),
            default_if_engine=data.get("default_if_engine", "ink"),
            chat_model_path=data.get("chat_model_path", ""),
            chat_context_size=data.get("chat_context_size", 8192),
            chat_gpu_layers=data.get("chat_gpu_layers", 0),
            embedding_model_path=data.get("embedding_model_path", ""),
            embedding_context_size=data.get("embedding_context_size", 512),
            embedding_gpu_layers=data.get("embedding_gpu_layers", 0),
            preferences=PlayerPreferences.from_dict(prefs_data),
        )
