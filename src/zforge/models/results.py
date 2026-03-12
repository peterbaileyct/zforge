"""Result types for IF engine operations and experience management.

BuildResult, ActionResult per docs/IF Engine Abstraction Layer.md.
Experience per docs/ER Diagram.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BuildResult:
    """Result of compiling a script via an IF engine."""

    output: bytes | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.output is not None and not self.errors


@dataclass
class ActionResult:
    """Result of a player action in a running experience."""

    text: str
    choices: list[str] | None = None
    is_complete: bool = False


@dataclass
class Experience:
    """Metadata for a stored experience."""

    zworld_id: str
    name: str
    engine_extension: str
    file_path: str
