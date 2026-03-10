"""Static metadata describing all LLM-backed processes and their nodes.

This module is the single authoritative source for the slug→display-name
mapping used both by ConfigService defaults and the LLM configuration UI.

Implements: src/zforge/models/process_config.py per docs/World Generation.md
and docs/LLM Abstraction Layer.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeSpec:
    """Metadata for a single LLM node within a process."""

    slug: str
    display: str
    default_provider: str
    default_model: str


@dataclass(frozen=True)
class ProcessSpec:
    """Metadata for a LangGraph process that uses one or more LLM nodes."""

    slug: str
    display: str
    nodes: tuple[NodeSpec, ...]


# Ordered list of all implemented processes.
PROCESSES: list[ProcessSpec] = [
    ProcessSpec(
        slug="document_parsing",
        display="Document Parsing",
        nodes=(
            NodeSpec(
                slug="contextualizer",
                display="Contextualizer",
                default_provider="Groq",
                default_model="llama-3.3-70b-versatile",
            ),
            NodeSpec(
                slug="graph_extractor",
                display="Graph Extractor",
                default_provider="Google",
                default_model="gemini-2.5-flash-lite",
            ),
        ),
    ),
    ProcessSpec(
        slug="world_generation",
        display="World Generation",
        nodes=(
            NodeSpec(
                slug="summarizer",
                display="Summarizer",
                default_provider="Google",
                default_model="gemini-2.5-flash-lite",
            ),
        ),
    ),
    ProcessSpec(
        slug="ask_about_world",
        display="Ask About World",
        nodes=(
            NodeSpec(
                slug="librarian",
                display="Librarian",
                default_provider="Groq",
                default_model="llama-3.3-70b-versatile",
            ),
        ),
    ),
]

# RemoteConnector → keyring key for its API key.  Used by the config UI to
# read/write credentials without hardcoding connector internals.
REMOTE_CONNECTOR_KEYS: dict[str, tuple[str, str]] = {
    "OpenAI": ("zforge", "llm.openai.api_key"),
    "Google": ("zforge", "llm.google.api_key"),
    "Anthropic": ("zforge", "llm.anthropic.api_key"),
    "Groq": ("zforge", "llm.groq.api_key"),
}
