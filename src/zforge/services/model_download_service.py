"""Model download service.

Downloads GGUF model files from Hugging Face CDN with streaming
and progress reporting.

Implements: src/zforge/services/model_download_service.py per
docs/Local LLM Execution.md.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import httpx

from zforge.models.model_catalogue import ModelCatalogueEntry, hf_url

log = logging.getLogger(__name__)

_CHUNK_SIZE = 65_536
_SIZE_TOLERANCE = 0.01  # 1%


class ModelDownloadService:
    """Downloads GGUF model files from the Hugging Face CDN."""

    async def download(
        self,
        entry: ModelCatalogueEntry,
        dest_dir: Path,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> Path:
        """Stream-download a model file, returning the completed path.

        Skips the download if a file of matching size already exists.
        Calls *progress_callback(filename, bytes_received, total_bytes)* after
        each chunk so the UI can update a progress bar.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / entry.filename

        # Skip if already downloaded and size matches within tolerance
        if dest_path.exists():
            actual = dest_path.stat().st_size
            if abs(actual - entry.size_bytes_approx) / max(entry.size_bytes_approx, 1) <= _SIZE_TOLERANCE:
                log.info("Model %s already present at %s, skipping download", entry.filename, dest_path)
                if progress_callback:
                    progress_callback(entry.filename, actual, actual)
                return dest_path

        url = hf_url(entry)
        log.info("Downloading %s from %s", entry.filename, url)

        async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                received = 0

                with open(dest_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=_CHUNK_SIZE):
                        f.write(chunk)
                        received += len(chunk)
                        if progress_callback:
                            progress_callback(entry.filename, received, total)

        log.info("Download complete: %s (%d bytes)", dest_path, received)
        return dest_path
