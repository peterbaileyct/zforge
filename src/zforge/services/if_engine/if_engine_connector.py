"""IF Engine Connector abstract base class.

Defines the interface for interactive fiction engine implementations.
Implements: src/zforge/services/if_engine/if_engine_connector.py per
docs/IF Engine Abstraction Layer.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from zforge.models.results import ActionResult, BuildResult


class IfEngineConnector(ABC):
    """Abstract base class for IF engine connectors."""

    @abstractmethod
    def get_engine_name(self) -> str:
        """Return the canonical name of the IF engine (e.g., 'ink')."""

    @abstractmethod
    def get_file_extension(self) -> str:
        """Return the file extension for compiled output (e.g., '.ink.json')."""

    @abstractmethod
    def get_script_prompt(self) -> str:
        """Return engine-specific guidance for LLM agents writing scripts."""

    @abstractmethod
    async def build(self, script: str) -> BuildResult:
        """Compile a script into a runnable format."""

    @abstractmethod
    async def start_experience(self, compiled_data: bytes) -> str:
        """Initialize a new playthrough; return opening text."""

    @abstractmethod
    async def take_action(self, input: str) -> ActionResult:
        """Process player input and advance the experience state."""

    @abstractmethod
    async def save_state(self) -> bytes:
        """Serialize the current playthrough state."""

    @abstractmethod
    async def restore_state(self, saved_state: bytes) -> ActionResult:
        """Restore a playthrough from saved state; return current position."""
