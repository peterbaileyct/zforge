"""Model catalogue for Z-Forge.

Static catalogue of curated GGUF models available for download from
Hugging Face. Each entry records a role (chat or embedding), display name,
HF repo, filename, approximate download size, and whether it is the default.

Implements: src/zforge/models/model_catalogue.py per docs/Local LLM Execution.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCatalogueEntry:
    """A single entry in the model catalogue."""

    role: str
    display_name: str
    hf_repo: str
    filename: str
    size_bytes_approx: int
    is_default: bool


CATALOGUE: list[ModelCatalogueEntry] = [
    ModelCatalogueEntry(
        role="chat",
        display_name="DeepSeek R1 Distill 1.5B",
        hf_repo="bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
        filename="DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        size_bytes_approx=1_073_741_824,
        is_default=True,
    ),
    ModelCatalogueEntry(
        role="chat",
        display_name="DeepSeek R1 Distill 7B",
        hf_repo="bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        filename="DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
        size_bytes_approx=4_724_464_640,
        is_default=False,
    ),
    ModelCatalogueEntry(
        role="embedding",
        display_name="Nomic Embed Text 1.5",
        hf_repo="nomic-ai/nomic-embed-text-v1.5-GGUF",
        filename="nomic-embed-text-v1.5.Q4_K_M.gguf",
        size_bytes_approx=94_371_840,
        is_default=True,
    ),
]


def hf_url(entry: ModelCatalogueEntry) -> str:
    """Return the Hugging Face CDN download URL for a catalogue entry."""
    return f"https://huggingface.co/{entry.hf_repo}/resolve/main/{entry.filename}"
