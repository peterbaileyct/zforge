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

    zworld_folder: str = ""
    experience_folder: str = ""
    default_if_engine: str = "ink"
    preferences: PlayerPreferences = field(default_factory=PlayerPreferences)

    def to_dict(self) -> dict[str, Any]:
        return {
            "zworld_folder": self.zworld_folder,
            "experience_folder": self.experience_folder,
            "default_if_engine": self.default_if_engine,
            "preferences": self.preferences.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ZForgeConfig:
        prefs_data = data.get("preferences", {})
        return cls(
            zworld_folder=data.get("zworld_folder", ""),
            experience_folder=data.get("experience_folder", ""),
            default_if_engine=data.get("default_if_engine", "ink"),
            preferences=PlayerPreferences.from_dict(prefs_data),
        )
