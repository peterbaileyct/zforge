"""ZWorld Manager — CRUD operations on Z-World bundles.

Z-Worlds are stored as Z-Bundles at bundles/world/{slug}/ containing:
- kvp.json: title, slug, UUID, summary, setting_era, source_canon,
  content_advisories, embedding model identity
- source.txt: original raw input text
- vector/: LanceDB vector store (populated by document_parsing_graph)
- propertygraph: KùzuDB property graph file (populated by document_parsing_graph)

Implements: src/zforge/managers/zworld_manager.py per
docs/Z-World.md, docs/RAG and GRAG Implementation.md,
docs/World Generation.md, and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from zforge.models.zworld import ZWorld

if TYPE_CHECKING:
    from zforge.services.embedding.embedding_connector import EmbeddingConnector

log = logging.getLogger(__name__)


class ZWorldManager:
    """Manages Z-World bundles (KVP + vector store + property graph)."""

    def __init__(
        self, bundles_root: str, embedding_connector: EmbeddingConnector
    ) -> None:
        self._bundles_root = Path(bundles_root)
        self._embedding = embedding_connector
        self._on_created: list[Callable[[ZWorld], None]] = []

    def _world_root(self, slug: str) -> Path:
        return self._bundles_root / "world" / slug

    def add_on_created_listener(
        self, callback: Callable[[ZWorld], None]
    ) -> None:
        self._on_created.append(callback)

    # ------------------------------------------------------------------
    # CREATE
    # ------------------------------------------------------------------

    def create(
        self, zworld: ZWorld, raw_text: str, suppress_event: bool = False
    ) -> None:
        """Write the KVP store and raw source text for a Z-World bundle.

        The vector store and property graph are populated by the
        document_parsing_graph before this method is called; ``create()``
        only writes ``kvp.json`` and ``source.txt``.
        """
        root = self._world_root(zworld.slug)
        os.makedirs(root, exist_ok=True)

        self._write_kvp(root, zworld)
        self._write_source(root, raw_text)

        log.info("ZWorldManager.create: wrote Z-Bundle at %s", root)
        if not suppress_event:
            for cb in self._on_created:
                cb(zworld)

    def _write_kvp(self, root: Path, zworld: ZWorld) -> None:
        identity = self._embedding.model_identity()
        kvp = {
            "title": zworld.title,
            "slug": zworld.slug,
            "uuid": zworld.uuid,
            "summary": zworld.summary,
            "setting_era": zworld.setting_era,
            "source_canon": zworld.source_canon,
            "content_advisories": zworld.content_advisories,
            "embedding_model_name": identity["embedding_model_name"],
            "embedding_model_size_bytes": identity["embedding_model_size_bytes"],
        }
        kvp_path = root / "kvp.json"
        with open(kvp_path, "w", encoding="utf-8") as f:
            json.dump(kvp, f, indent=2)

    def _write_source(self, root: Path, raw_text: str) -> None:
        source_path = root / "source.txt"
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(raw_text)

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------

    def read(self, slug: str) -> ZWorld | None:
        """Reconstruct a ZWorld from its Z-Bundle KVP store.

        Returns None if the bundle does not exist.
        """
        root = self._world_root(slug)
        kvp_path = root / "kvp.json"
        if not kvp_path.exists():
            return None

        with open(kvp_path, "r", encoding="utf-8") as f:
            kvp = json.load(f)

        return ZWorld(
            title=kvp["title"],
            slug=kvp["slug"],
            uuid=kvp.get("uuid", ""),
            summary=kvp.get("summary", ""),
            setting_era=kvp.get("setting_era", ""),
            source_canon=kvp.get("source_canon", []),
            content_advisories=kvp.get("content_advisories", []),
        )

    # ------------------------------------------------------------------
    # CHECK EMBEDDING MISMATCH
    # ------------------------------------------------------------------

    def check_embedding_mismatch(self, slug: str) -> bool:
        """Return True if stored embedding model differs from the current config."""
        root = self._world_root(slug)
        kvp_path = root / "kvp.json"
        if not kvp_path.exists():
            return False

        with open(kvp_path, "r", encoding="utf-8") as f:
            kvp = json.load(f)

        current = self._embedding.model_identity()
        return (
            kvp.get("embedding_model_name") != current["embedding_model_name"]
            or kvp.get("embedding_model_size_bytes") != current["embedding_model_size_bytes"]
        )

    # ------------------------------------------------------------------
    # LIST ALL
    # ------------------------------------------------------------------

    def list_all(self) -> list[ZWorld]:
        """List all Z-Worlds (lightweight: KVP data only)."""
        world_dir = self._bundles_root / "world"
        if not world_dir.exists():
            return []
        worlds = []
        for kvp_path in sorted(world_dir.glob("*/kvp.json")):
            with open(kvp_path, "r", encoding="utf-8") as f:
                kvp = json.load(f)
            worlds.append(
                ZWorld(
                    title=kvp["title"],
                    slug=kvp["slug"],
                    uuid=kvp.get("uuid", ""),
                    summary=kvp.get("summary", ""),
                    setting_era=kvp.get("setting_era", ""),
                    source_canon=kvp.get("source_canon", []),
                    content_advisories=kvp.get("content_advisories", []),
                )
            )
        return worlds

    # ------------------------------------------------------------------
    # ASK (Agentic RAG)
    # ------------------------------------------------------------------

    async def ask(
        self,
        slug: str,
        question: str,
        llm_connector,
        model_name: str | None = None,
    ) -> str:
        """Answer a question about a world using agentic RAG.

        Reads the Z-Bundle KVP, builds the Ask About World graph, and
        returns the plain-text answer.

        Parameters
        ----------
        slug:
            Z-World slug identifying the Z-Bundle.
        question:
            Raw user question text.
        llm_connector:
            Pre-resolved LLM connector for the Librarian node.
        model_name:
            Optional model name override.

        Returns
        -------
        str
            Plain-text answer string.
        """
        root = self._world_root(slug)
        kvp_path = root / "kvp.json"
        if not kvp_path.exists():
            return f"World '{slug}' not found."

        with open(kvp_path, "r", encoding="utf-8") as f:
            zworld_kvp = json.load(f)

        from zforge.graphs.ask_about_world_graph import run_ask_about_world

        return await run_ask_about_world(
            z_bundle_root=str(root),
            zworld_kvp=zworld_kvp,
            user_question=question,
            llm_connector=llm_connector,
            embedding_connector=self._embedding,
            model_name=model_name,
        )

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    def delete(self, slug: str) -> None:
        """Remove the entire Z-Bundle directory for the given world."""
        root = self._world_root(slug)
        if root.exists():
            shutil.rmtree(root)
