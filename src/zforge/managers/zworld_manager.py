"""ZWorld Manager — CRUD operations on Z-World bundles.

Z-Worlds are stored as Z-Bundles at bundles/world/{slug}/ containing:
- kvp.json: title, slug, UUID, summary, embedding model identity
- vector/: LanceDB vector store with entity embeddings
- propertygraph/: KùzuDB property graph with entity relationships

Implements: src/zforge/managers/zworld_manager.py per
docs/Z-World.md, docs/RAG and GRAG Implementation.md,
docs/User Experience.md, and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid as uuid_mod
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from zforge.models.zworld import (
    Character,
    CharacterName,
    Event,
    Location,
    Mechanic,
    Occupation,
    Relationship,
    Species,
    Trope,
    ZWorld,
)

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
        self, zworld: ZWorld, suppress_event: bool = False
    ) -> None:
        """Encode a full Z-Bundle for the given ZWorld."""
        if not zworld.uuid:
            zworld.uuid = str(uuid_mod.uuid4())

        root = self._world_root(zworld.slug)
        os.makedirs(root, exist_ok=True)

        self._write_kvp(root, zworld)
        self._write_vector_store(root, zworld)
        self._write_property_graph(root, zworld)

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
            "embedding_model_name": identity["embedding_model_name"],
            "embedding_model_size_bytes": identity["embedding_model_size_bytes"],
        }
        kvp_path = root / "kvp.json"
        with open(kvp_path, "w", encoding="utf-8") as f:
            json.dump(kvp, f, indent=2)

    def _write_vector_store(self, root: Path, zworld: ZWorld) -> None:
        import lancedb
        import pyarrow as pa

        entities = zworld.all_entities()
        if not entities:
            log.warning("ZWorldManager: no entities to embed for %s", zworld.slug)
            return

        texts = [e[3] for e in entities]
        embeddings_model = self._embedding.get_embeddings()
        vectors = embeddings_model.embed_documents(texts)

        db = lancedb.connect(str(root / "vector"))
        data = [
            {
                "vector": vectors[i],
                "entity_id": entities[i][0],
                "entity_type": entities[i][1],
                "text": entities[i][3],
            }
            for i in range(len(entities))
        ]
        db.create_table("entities", data, mode="overwrite")

    def _write_property_graph(self, root: Path, zworld: ZWorld) -> None:
        import kuzu

        graph_dir = root / "propertygraph"
        os.makedirs(graph_dir, exist_ok=True)
        db = kuzu.Database(str(graph_dir))
        conn = kuzu.Connection(db)

        conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS Entity("
            "entity_id STRING, entity_type STRING, PRIMARY KEY(entity_id))"
        )
        conn.execute(
            "CREATE REL TABLE IF NOT EXISTS Relationship("
            "FROM Entity TO Entity, type STRING)"
        )

        entities = zworld.all_entities()
        for eid, etype, _, _ in entities:
            conn.execute(
                "MERGE (e:Entity {entity_id: $id}) SET e.entity_type = $type",
                parameters={"id": eid, "type": etype},
            )

        for rel in zworld.relationships:
            conn.execute(
                "MATCH (a:Entity {entity_id: $from_id}), "
                "(b:Entity {entity_id: $to_id}) "
                "CREATE (a)-[:Relationship {type: $type}]->(b)",
                parameters={
                    "from_id": rel.from_id,
                    "to_id": rel.to_id,
                    "type": rel.type,
                },
            )

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------

    def read(self, slug: str) -> ZWorld | None:
        """Reconstruct a ZWorld from its Z-Bundle. Returns None if not found."""
        root = self._world_root(slug)
        kvp_path = root / "kvp.json"
        if not kvp_path.exists():
            return None

        with open(kvp_path, "r", encoding="utf-8") as f:
            kvp = json.load(f)

        zworld = ZWorld(
            title=kvp["title"],
            slug=kvp["slug"],
            uuid=kvp.get("uuid", ""),
            summary=kvp.get("summary", ""),
        )

        # Reconstruct entities from vector store metadata (no re-embedding)
        vector_dir = root / "vector"
        if vector_dir.exists():
            self._read_entities_from_vector(vector_dir, zworld)

        # Reconstruct relationships from property graph
        graph_dir = root / "propertygraph"
        if graph_dir.exists():
            self._read_relationships_from_graph(graph_dir, zworld)

        return zworld

    def _read_entities_from_vector(
        self, vector_dir: Path, zworld: ZWorld
    ) -> None:
        import lancedb

        db = lancedb.connect(str(vector_dir))
        try:
            table = db.open_table("entities")
        except Exception:
            return

        rows = table.to_pandas()
        for _, row in rows.iterrows():
            eid = row["entity_id"]
            etype = row["entity_type"]
            text = row["text"]

            if etype == "character":
                name_part = text.split(": ", 1)[1].split(". ")[0] if ": " in text else eid
                history = text.split(". ", 1)[1] if ". " in text else ""
                zworld.characters.append(
                    Character(id=eid, names=[CharacterName(name=name_part)], history=history)
                )
            elif etype == "location":
                name_part = text.split(": ", 1)[1].split(". ")[0] if ": " in text else eid
                desc = text.split(". ", 1)[1] if ". " in text else ""
                zworld.locations.append(Location(id=eid, name=name_part, description=desc))
            elif etype == "event":
                desc = text.replace("Event: ", "").split(". Time: ")[0] if "Event: " in text else text
                time_str = text.split(". Time: ")[1] if ". Time: " in text else ""
                zworld.events.append(Event(description=desc, time=time_str))
            elif etype == "mechanic":
                zworld.mechanics.append(Mechanic(text=text.replace("Mechanic: ", "")))
            elif etype == "trope":
                zworld.tropes.append(Trope(text=text.replace("Trope: ", "")))
            elif etype == "species":
                zworld.species.append(Species(text=text.replace("Species: ", "")))
            elif etype == "occupation":
                zworld.occupations.append(Occupation(text=text.replace("Occupation: ", "")))

    def _read_relationships_from_graph(
        self, graph_dir: Path, zworld: ZWorld
    ) -> None:
        import kuzu

        db = kuzu.Database(str(graph_dir))
        conn = kuzu.Connection(db)
        try:
            result = conn.execute(
                "MATCH (a:Entity)-[r:Relationship]->(b:Entity) "
                "RETURN a.entity_id, b.entity_id, r.type"
            )
            while result.has_next():
                row = result.get_next()
                zworld.relationships.append(
                    Relationship(from_id=row[0], to_id=row[1], type=row[2])
                )
        except Exception:
            log.debug("No relationships found in graph for %s", graph_dir)

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
        """List all Z-Worlds (lightweight: KVP data only, no vector/graph)."""
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
                )
            )
        return worlds

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    def delete(self, slug: str) -> None:
        """Remove the entire Z-Bundle directory for the given world."""
        root = self._world_root(slug)
        if root.exists():
            shutil.rmtree(root)
