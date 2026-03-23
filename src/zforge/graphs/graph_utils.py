"""Shared utilities for LangGraph state machine graphs.

Provides the :func:`log_node` decorator for uniform observability across
all graph node functions: logs entry, exit (with elapsed time), and
exceptions so the log stream fully describes graph execution without
requiring manual instrumentation in each node body.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from langchain_core.tools import BaseTool

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zforge.services.embedding.embedding_connector import EmbeddingConnector

# ---------------------------------------------------------------------------
# Z-World entity schema — authoritative per docs/Z-World.md § allowed_nodes
# Centralised here (rather than world_creation_graph) so experience_generation
# and ask_about_world graphs can import them at module level without circularity.
# ---------------------------------------------------------------------------

ALLOWED_NODES: list[str] = [
    "Character", "Species", "Organization", "Location",
    "Item", "Event", "TimePeriod", "Culture", "BeliefSystem",
    "Law", "Myth", "Concept", "Conflict", "Goal",
]

ALLOWED_RELATIONSHIPS: list[str] = [
    "is_a", "instance_of", "subtype_of", "lives_in", "located_in",
    "originates_from", "born_in", "died_at", "contains",
    "adjacent_to", "native_to", "occurs_within", "born_during",
    "died_during", "overlaps", "preceded_by", "named_after", "owns",
    "controls", "rules", "created_by", "knows", "related_to",
    "descended_from", "allied_with", "enemy_of", "loyal_to", "betrayed",
    "mentored", "affiliated_with", "loves", "fears", "member_of",
    "employed_by", "opposes", "operates_through", "founded_by", "based_in",
    "participated_in", "witnessed", "caused", "triggered_by", "resulted_in",
    "occurred_at", "founded", "created", "destroyed", "affected_by",
    "wants", "targets", "seeks", "believes_in", "follows", "governed_by",
    "belongs_to", "practices", "practised_in", "knows_about", "hides",
    "reveals", "misinformed_about", "symbol_of", "part_of", "originated_in",
    "conflicts_with", "derived_from", "governs", "embodies", "believed_by",
    "about", "involves", "between",
]

# Cache open KuzuGraph connections keyed by graph_path to avoid re-opening the
# database on every query_entities tool call.

_KUZU_GRAPH_CACHE: dict[str, Any] = {}

# Single-thread executor for all llama.cpp / local-model work.
# llama.cpp's Metal (GPU) backend on macOS binds its command queue to the OS
# thread on which the model is first loaded. Using asyncio.to_thread() risks
# dispatching to a different thread on each call, causing a silent hang.
# Using a max_workers=1 executor guarantees every call lands on the same thread.
LLAMA_EXECUTOR: concurrent.futures.ThreadPoolExecutor = (
    concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="llama")
)

_F = TypeVar("_F", bound=Callable[..., Any])


def log_node(name: str) -> Callable[[_F], _F]:
    """Decorator factory that wraps a LangGraph node function with structured logging.

    Usage::

        @log_node("my_node")
        def my_node(state: MyState) -> dict:
            ...

    Or inside a factory (where the function is defined at runtime)::

        def _make_my_node(dep):
            @log_node("my_node")
            def my_node(state: MyState) -> dict:
                ...
            return my_node

    Each invocation emits three possible log lines at INFO level:

    * ``[node:NAME] START  status=<value>`` — logged immediately on entry.
    * ``[node:NAME] END    status=<value>  returned=<keys>  elapsed=<s>s`` — on
      successful return.
    * ``[node:NAME] EXCEPTION  status=<value>  elapsed=<s>s`` — on any unhandled
      exception; the full traceback is included via ``log.exception``, and the
      exception is re-raised so LangGraph's own error handling is unaffected.

    Args:
        name: Human-readable node name used in every log message.

    Returns:
        A decorator that wraps the node function.
    """

    def decorator(fn: _F) -> _F:
        if asyncio.iscoroutinefunction(fn):  # type: ignore[deprecated]
            @functools.wraps(fn)
            async def async_wrapper(state: Any) -> Any:
                status = state.get("status") if isinstance(state, dict) else "?"
                log.info("[node:%s] START  status=%r", name, status)
                t0 = time.perf_counter()
                try:
                    result = await fn(state)
                    elapsed = time.perf_counter() - t0
                    keys = (
                        list(result.keys())
                        if isinstance(result, dict)
                        else type(result).__name__
                    )
                    log.info(
                        "[node:%s] END    status=%r  returned=%r  elapsed=%.2fs",
                        name,
                        status,
                        keys,
                        elapsed,
                    )
                    return result
                except Exception:
                    elapsed = time.perf_counter() - t0
                    log.exception(
                        "[node:%s] EXCEPTION  status=%r  elapsed=%.2fs",
                        name,
                        status,
                        elapsed,
                    )
                    raise

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(state: Any) -> Any:
            status = state.get("status") if isinstance(state, dict) else "?"
            log.info("[node:%s] START  status=%r", name, status)
            t0 = time.perf_counter()
            try:
                result = fn(state)
                elapsed = time.perf_counter() - t0
                keys = (
                    list(result.keys())
                    if isinstance(result, dict)
                    else type(result).__name__
                )
                log.info(
                    "[node:%s] END    status=%r  returned=%r  elapsed=%.2fs",
                    name,
                    status,
                    keys,
                    elapsed,
                )
                return result
            except Exception:
                elapsed = time.perf_counter() - t0
                log.exception(
                    "[node:%s] EXCEPTION  status=%r  elapsed=%.2fs",
                    name,
                    status,
                    elapsed,
                )
                raise

        return wrapper  # type: ignore[return-value]

    return decorator


def chunk_text(text: str, max_chars: int, overlap_chars: int = 200) -> list[str]:
    """Split *text* into chunks of at most *max_chars*, overlapping by *overlap_chars*.

    Splits are made at paragraph boundaries (``\\n\\n``) wherever possible,
    falling back to sentence boundaries (``'. '``), then hard-cutting at the
    character limit when no natural boundary exists.

    Args:
        text: The full input text to split.
        max_chars: Maximum characters per chunk.
        overlap_chars: Characters of trailing context carried into the next
            chunk, so a sentence split across a boundary is not lost.

    Returns:
        A list of one or more text chunks.  If *text* fits entirely within
        *max_chars*, a single-element list is returned.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Prefer a paragraph break
            boundary = text.rfind("\n\n", start, end)
            if boundary > start:
                end = boundary + 2
            else:
                # Fall back to sentence break
                boundary = text.rfind(". ", start, end)
                if boundary > start:
                    end = boundary + 2
                # else: hard cut at max_chars
        chunks.append(text[start:end])
        if end >= len(text):
            break
        # Always advance past the current start to prevent an infinite loop
        # when a boundary is found close to start (overlap would go backward).
        start = max(end - overlap_chars, start + 1)
    return chunks


def make_world_query_tools(
    z_bundle_root: str,
    allowed_node_labels: list[str],
    embedding_connector: EmbeddingConnector,
) -> tuple[BaseTool, BaseTool, BaseTool, BaseTool, BaseTool, BaseTool, BaseTool, BaseTool]:
    """Factory that returns all eight Z-Bundle query tools as LangChain tools.

    The returned tools are:

    1. ``query_entities`` — semantic entity matching + graph expansion + optional
       neighbour hydration.
    2. ``retrieve_source`` — verbatim source passage retrieval from the chunks
       table.
    3. ``find_relationship`` — direct edges and shared 1-hop neighbours between
       two known entity IDs.
    4. ``find_relationship_by_name`` — name-resolution wrapper around
       ``find_relationship``; resolves plain-text names via vector lookup.
    5. ``list_entities`` — deterministic catalog scan of a single entity type.
    6. ``get_neighbors`` — targeted 1-hop graph traversal from a known entity ID.
    7. ``find_path`` — shortest-path traversal between two known entity IDs.
    8. ``get_source_passages`` — raw source chunks mentioning a known entity via
       MENTIONS edges.

    Args:
        z_bundle_root: Filesystem path to the Z-Bundle root directory.
        allowed_node_labels: PascalCase node type names used at ingest time.
        embedding_connector: Embedding connector (provides ``get_embeddings()``).

    Returns:
        An 8-tuple of LangChain ``BaseTool`` instances.
    """
    from langchain_core.tools import tool

    _CYPHER_STARTS = {"MATCH", "WITH", "CALL", "OPTIONAL", "UNWIND"}

    # ---- Internal helpers ------------------------------------------------

    def _get_kuzu_graph() -> Any:
        """Return a cached KuzuGraph for this Z-Bundle's property graph."""
        import kuzu
        from langchain_community.graphs import KuzuGraph

        graph_path = f"{z_bundle_root}/propertygraph"
        if graph_path not in _KUZU_GRAPH_CACHE:
            db = kuzu.Database(graph_path)
            _KUZU_GRAPH_CACHE[graph_path] = KuzuGraph(
                db, allow_dangerous_requests=True
            )
        return _KUZU_GRAPH_CACHE[graph_path]

    def _graph_expand_entity(graph: Any, label: str, node_id: str) -> list[str]:
        """Return formatted 1-hop relationship lines for a single entity.

        Each line has the form:
          → rel_type → Neighbour Name (neighbour_type)  [prop: val, ...]
        or
          ← rel_type ← Neighbour Name (neighbour_type)  [prop: val, ...]
        """
        _REL_PROPS = ("from_time", "to_time", "role", "perspective", "canonical")
        lines: list[str] = []

        # Outgoing edges
        try:
            for row in graph.query(
                f"MATCH (n:{label})-[r]->(m) WHERE n.id = $nid "
                f"RETURN type(r) AS rel, label(m) AS m_label, m.id AS target, "
                + ", ".join(f"r.{p} AS r_{p}" for p in _REL_PROPS)
                + " LIMIT 50",
                params={"nid": node_id},
            ):
                if row.get("m_label") == "Chunk":
                    continue
                props = {
                    p: row.get(f"r_{p}")
                    for p in _REL_PROPS
                    if row.get(f"r_{p}")
                }
                prop_str = (
                    "  [" + ", ".join(f'{k}: "{v}"' for k, v in props.items()) + "]"
                    if props
                    else ""
                )
                m_type = (row.get("m_label") or "").lower()
                lines.append(
                    f"  → {row.get('rel')} → {row.get('target')} ({m_type}){prop_str}"
                )
        except Exception:
            pass

        # Incoming edges
        try:
            for row in graph.query(
                f"MATCH (m)-[r]->(n:{label}) WHERE n.id = $nid "
                f"RETURN type(r) AS rel, label(m) AS m_label, m.id AS source, "
                + ", ".join(f"r.{p} AS r_{p}" for p in _REL_PROPS)
                + " LIMIT 50",
                params={"nid": node_id},
            ):
                if row.get("m_label") == "Chunk":
                    continue
                props = {
                    p: row.get(f"r_{p}")
                    for p in _REL_PROPS
                    if row.get(f"r_{p}")
                }
                prop_str = (
                    "  [" + ", ".join(f'{k}: "{v}"' for k, v in props.items()) + "]"
                    if props
                    else ""
                )
                m_type = (row.get("m_label") or "").lower()
                lines.append(
                    f"  ← {row.get('rel')} ← {row.get('source')} ({m_type}){prop_str}"
                )
        except Exception:
            pass

        return lines

    # ---- Async vector helpers -------------------------------------------

    async def _vector_search(table_name: str, query: str, take_top_matches: int,
                             entity_type: str | None = None) -> list[dict[str, Any]]:
        """Run ANN search on a LanceDB table. Returns list of row dicts."""
        import lancedb

        vector_path = f"{z_bundle_root}/vector"
        loop = asyncio.get_running_loop()
        query_vec = await loop.run_in_executor(
            LLAMA_EXECUTOR,
            lambda: embedding_connector.get_embeddings().embed_query(query),  # type: ignore[union-attr]
        )
        db = await lancedb.connect_async(vector_path)
        entity_type_filterable = (table_name == "entities")
        try:
            tbl = await db.open_table(table_name)
        except Exception:
            if table_name == "entities":
                try:
                    tbl = await db.open_table("chunks")
                    entity_type_filterable = False  # chunks table has no entity_type column
                except Exception:
                    return []
            else:
                return []

        search_q = await tbl.search(query_vec, query_type="vector")
        if entity_type and entity_type_filterable:
            search_q = search_q.where(f"entity_type = '{entity_type}'")
        results_arrow = await search_q.limit(take_top_matches).to_arrow()
        # Convert to list of dicts
        cols = results_arrow.column_names
        rows: list[dict[str, Any]] = []
        for i in range(results_arrow.num_rows):
            row: dict[str, Any] = {}
            for col in cols:
                val = results_arrow.column(col)[i].as_py()
                row[col] = val
            rows.append(row)
        return rows

    # ---- Internal helpers: PascalCase resolution --------------------------

    def _resolve_pascal_label(entity_type: str) -> str | None:
        """Convert a snake_case entity type to its PascalCase node label.

        Returns ``None`` if no matching label is found in *allowed_node_labels*.
        """
        lowered = entity_type.replace("_", "")
        for lbl in allowed_node_labels:
            if lbl.lower() == lowered:
                return lbl
        candidate = "".join(w.capitalize() for w in entity_type.split("_"))
        if candidate in allowed_node_labels:
            return candidate
        return None

    # ---- Tool: query_entities -------------------------------------------

    @tool
    async def query_entities(
        query: str,
        entity_type: str | None = None,
        take_top_matches: int = 1,
        include_neighbors: bool = False,
    ) -> str:
        """Look up entities in the world by description or name.

        Returns entity summaries, relationships, and optionally adjacent entity
        details.  Use entity_type to restrict to a specific type.  Set
        include_neighbors=True for network or connection questions.

        Args:
            query: Natural language search query or entity name.
            entity_type: Optional entity type filter (snake_case, e.g. "character").
            take_top_matches: Number of top entity matches to return (default 1).
            include_neighbors: If True, also return summaries and relationships
                for each matched entity's 1-hop neighbours.
        """
        # Step 1: Semantic match against entities table
        rows = await _vector_search("entities", query, take_top_matches, entity_type)
        if not rows:
            return "No matching entities found."

        graph = _get_kuzu_graph()
        parts: list[str] = []

        for row in rows:
            eid = row.get("entity_id", "")
            etype = row.get("entity_type", "")
            summary = row.get("text", "")

            # Determine the PascalCase label for graph queries
            pascal_label = _resolve_pascal_label(etype)

            entity_block = f'[Entity: "{eid}" ({etype})]\nSummary: {summary}'

            # Step 2: Graph expansion
            if pascal_label:
                rel_lines = _graph_expand_entity(graph, pascal_label, eid)
                if rel_lines:
                    entity_block += "\n\nRelationships:\n" + "\n".join(rel_lines)

                # Step 3: Neighbour hydration (optional)
                if include_neighbors and pascal_label:
                    # Collect unique neighbour ids from the rel_lines
                    neighbour_ids: list[tuple[str, str]] = []
                    try:
                        for r in graph.query(
                            f"MATCH (n:{pascal_label})-[r]-(m) WHERE n.id = $nid "
                            f"AND NOT label(m) = 'Chunk' "
                            f"RETURN DISTINCT m.id AS mid, label(m) AS mlabel "
                            f"LIMIT {take_top_matches * 3}",
                            params={"nid": eid},
                        ):
                            if r.get("mid") and r.get("mlabel"):
                                neighbour_ids.append((r["mlabel"], r["mid"]))
                    except Exception:
                        pass

                    # Hydrate up to take_top_matches neighbours
                    for n_label, n_id in neighbour_ids[:take_top_matches]:
                        n_type = n_label.lower()
                        # Fetch summary from entities table
                        n_rows = await _vector_search(
                            "entities", n_id, 1, n_type
                        )
                        n_summary = ""
                        if n_rows and n_rows[0].get("entity_id") == n_id:
                            n_summary = n_rows[0].get("text", "")

                        n_block = f'\n[Neighbour: "{n_id}" ({n_type})]'
                        if n_summary:
                            n_block += f"\nSummary: {n_summary}"
                        n_rels = _graph_expand_entity(graph, n_label, n_id)
                        if n_rels:
                            n_block += "\nRelationships:\n" + "\n".join(n_rels)
                        entity_block += n_block

            parts.append(entity_block)

        return "\n\n".join(parts)

    # ---- Tool: retrieve_source ------------------------------------------

    @tool
    async def retrieve_source(
        query: str,
        entity_type: str | None = None,
        take_top_matches: int = 5,
    ) -> str:
        """Retrieve verbatim source passages from the world text.

        Use when exact wording is required — contradictions, rumours, specific
        quotes, or when entity summaries may over-synthesize.

        Args:
            query: Natural language search query.
            entity_type: Optional entity type filter (snake_case, e.g. "character").
            take_top_matches: Number of passages to return (default 5).
        """
        rows = await _vector_search("chunks", query, take_top_matches, entity_type)
        if not rows:
            return "No source passages found."
        texts = [r.get("text", "") for r in rows if r.get("text")]
        if not texts:
            return "No source passages found."
        return "\n\n---\n\n".join(texts)

    # ---- Tool: find_relationship ----------------------------------------

    @tool
    async def find_relationship(
        entity_id_a: str,
        entity_id_b: str,
    ) -> str:
        """Find the graph relationship between two known entity IDs.

        Executes two Cypher queries: direct edges in either direction and
        shared 1-hop neighbours.  Use when entity IDs are already known from
        a prior query_entities response.

        Args:
            entity_id_a: First entity ID.
            entity_id_b: Second entity ID.
        """
        graph = _get_kuzu_graph()
        parts: list[str] = []

        # Direct edges (either direction, excluding Chunk nodes)
        direct_lines: list[str] = []
        try:
            for row in graph.query(
                "MATCH (a)-[r]-(b) "
                "WHERE a.id = $id_a AND b.id = $id_b "
                "AND NOT label(a) = 'Chunk' AND NOT label(b) = 'Chunk' "
                "RETURN type(r) AS rel, label(a) AS a_label, a.id AS a_id, "
                "label(b) AS b_label, b.id AS b_id",
                params={"id_a": entity_id_a, "id_b": entity_id_b},
            ):
                direct_lines.append(
                    f"  {row.get('a_id')} → {row.get('rel')} → {row.get('b_id')}"
                )
        except Exception:
            pass

        # Shared neighbours (1-hop common ground)
        shared_lines: list[str] = []
        try:
            for row in graph.query(
                "MATCH (a)-[r1]-(m)-[r2]-(b) "
                "WHERE a.id = $id_a AND b.id = $id_b "
                "AND NOT label(m) = 'Chunk' "
                "RETURN label(m) AS m_label, m.id AS m_id, "
                "type(r1) AS r1_type, type(r2) AS r2_type",
                params={"id_a": entity_id_a, "id_b": entity_id_b},
            ):
                m_label = (row.get("m_label") or "").lower()
                m_id = row.get("m_id", "")
                shared_lines.append(
                    f"  both connected via: {m_id} ({m_label})\n"
                    f"    {entity_id_a} → {row.get('r1_type')} → {m_id}\n"
                    f"    {entity_id_b} → {row.get('r2_type')} → {m_id}"
                )
        except Exception:
            pass

        if not direct_lines and not shared_lines:
            return (
                f"No graph relationship found between "
                f'"{entity_id_a}" and "{entity_id_b}".'
            )

        header = (
            f'[Relationship: "{entity_id_a}" ↔ "{entity_id_b}"]'
        )
        parts.append(header)
        if direct_lines:
            parts.append("\nDirect edges:\n" + "\n".join(direct_lines))
        if shared_lines:
            parts.append("\nShared neighbours:\n" + "\n".join(shared_lines))

        return "\n".join(parts)

    # ---- Tool: find_relationship_by_name --------------------------------

    @tool
    async def find_relationship_by_name(
        name_a: str,
        name_b: str,
        entity_type_a: str | None = None,
        entity_type_b: str | None = None,
    ) -> str:
        """Find the relationship between two entities by name.

        Resolves plain-text names to entity IDs via vector search, then calls
        find_relationship.  Use when you have names rather than stable IDs.

        Args:
            name_a: Name or description of the first entity.
            name_b: Name or description of the second entity.
            entity_type_a: Optional type filter for the first entity (snake_case).
            entity_type_b: Optional type filter for the second entity (snake_case).
        """
        results_a, results_b = await asyncio.gather(
            _vector_search("entities", name_a, 1, entity_type_a),
            _vector_search("entities", name_b, 1, entity_type_b),
        )

        if not results_a:
            return f'Could not resolve entity: "{name_a}"'
        if not results_b:
            return f'Could not resolve entity: "{name_b}"'

        id_a = results_a[0].get("entity_id", "")
        type_a = results_a[0].get("entity_type", "")
        id_b = results_b[0].get("entity_id", "")
        type_b = results_b[0].get("entity_type", "")

        resolved_header = (
            f'Resolved: "{name_a}" → "{id_a}" ({type_a})\n'
            f'Resolved: "{name_b}" → "{id_b}" ({type_b})\n'
        )

        relationship_result = await find_relationship.ainvoke(
            {"entity_id_a": id_a, "entity_id_b": id_b}
        )
        return resolved_header + "\n" + str(relationship_result)

    # ---- Tool: list_entities --------------------------------------------

    @tool
    async def list_entities(
        entity_type: str,
        limit: int = 20,
    ) -> str:
        """List entities of a given type from the world graph.

        Deterministic catalog scan — no vector search.  Use for questions like
        "who are all the characters?" or when building a roster.

        Args:
            entity_type: Entity type in snake_case (e.g. "character", "location").
            limit: Maximum number of entities to return (default 20).
        """
        pascal_label = _resolve_pascal_label(entity_type)
        if not pascal_label:
            return f'Unknown entity type: "{entity_type}"'

        graph = _get_kuzu_graph()
        entries: list[str] = []
        try:
            for row in graph.query(
                f"MATCH (n:{pascal_label}) "
                f"RETURN n.id AS id, n.type AS type, n.text AS text "
                f"LIMIT {int(limit)}",
            ):
                eid = row.get("id", "")
                etype = (row.get("type") or entity_type).lower()
                text = row.get("text", "")
                entries.append(f'- "{eid}" ({etype}): {text}')
        except Exception:
            return f'Error querying entity type: "{entity_type}"'

        if not entries:
            return f'No entities of type "{entity_type}" found.'

        header = f"[Entity Catalog: {entity_type} ({len(entries)} results)]"
        return header + "\n" + "\n".join(entries)

    # ---- Tool: get_neighbors --------------------------------------------

    @tool
    async def get_neighbors(
        entity_id: str,
        relationship_type: str | None = None,
        neighbor_type: str | None = None,
    ) -> str:
        """Get the 1-hop graph neighbours of a known entity.

        More surgical than query_entities with include_neighbors — no vector search
        or summary fetching.  Use for "what characters are at this location?"
        or "what items does this character carry?"

        Args:
            entity_id: The entity ID to traverse from.
            relationship_type: Optional filter for relationship type.
            neighbor_type: Optional filter for neighbour entity type (snake_case).
        """
        graph = _get_kuzu_graph()
        lines: list[str] = []

        # Build optional WHERE clauses for filters
        extra_where = ""
        if relationship_type:
            extra_where += f" AND type(r) = '{relationship_type}'"
        if neighbor_type:
            pascal_nt = _resolve_pascal_label(neighbor_type)
            if pascal_nt:
                extra_where += f" AND label(m) = '{pascal_nt}'"

        # Outgoing
        try:
            for row in graph.query(
                "MATCH (n)-[r]->(m) "
                f"WHERE n.id = $nid AND NOT label(m) = 'Chunk'{extra_where} "
                "RETURN type(r) AS rel, label(m) AS m_label, m.id AS m_id "
                "LIMIT 50",
                params={"nid": entity_id},
            ):
                m_type = (row.get("m_label") or "").lower()
                lines.append(
                    f"  → {row.get('rel')} → {row.get('m_id')} ({m_type})"
                )
        except Exception:
            pass

        # Incoming
        try:
            for row in graph.query(
                "MATCH (m)-[r]->(n) "
                f"WHERE n.id = $nid AND NOT label(m) = 'Chunk'{extra_where} "
                "RETURN type(r) AS rel, label(m) AS m_label, m.id AS m_id "
                "LIMIT 50",
                params={"nid": entity_id},
            ):
                m_type = (row.get("m_label") or "").lower()
                lines.append(
                    f"  ← {row.get('rel')} ← {row.get('m_id')} ({m_type})"
                )
        except Exception:
            pass

        if not lines:
            return f'No neighbours found for entity "{entity_id}".'

        header = f'[Neighbours of "{entity_id}"]'
        return header + "\n" + "\n".join(lines)

    # ---- Tool: find_path ------------------------------------------------

    @tool
    async def find_path(
        entity_id_a: str,
        entity_id_b: str,
        max_depth: int = 4,
    ) -> str:
        """Find the shortest graph path between two known entity IDs.

        Use when find_relationship returns no results or when the question
        concerns indirect connections.

        Args:
            entity_id_a: Starting entity ID.
            entity_id_b: Target entity ID.
            max_depth: Maximum path depth (default 4).
        """
        graph = _get_kuzu_graph()

        try:
            results = graph.query(
                f"MATCH p = shortestPath((a)-[*1..{int(max_depth)}]-(b)) "
                "WHERE a.id = $id_a AND b.id = $id_b "
                "AND ALL(n IN nodes(p) WHERE NOT label(n) = 'Chunk') "
                "RETURN [n IN nodes(p) | {id: n.id, type: label(n)}] AS path_nodes, "
                "[r IN relationships(p) | type(r)] AS path_rels",
                params={"id_a": entity_id_a, "id_b": entity_id_b},
            )
        except Exception:
            return (
                f"No path found between "
                f'"{entity_id_a}" and "{entity_id_b}" within depth {max_depth}.'
            )

        if not results:
            return (
                f"No path found between "
                f'"{entity_id_a}" and "{entity_id_b}" within depth {max_depth}.'
            )

        row = results[0]
        path_nodes: list[dict[str, str]] = row.get("path_nodes", [])
        path_rels: list[str] = row.get("path_rels", [])

        if not path_nodes:
            return (
                f"No path found between "
                f'"{entity_id_a}" and "{entity_id_b}" within depth {max_depth}.'
            )

        first_node = path_nodes[0]
        last_node = path_nodes[-1]
        header = (
            f'[Path: "{first_node.get("id", "")}" ({first_node.get("type", "").lower()}) '
            f'→ "{last_node.get("id", "")}" ({last_node.get("type", "").lower()})]'
        )
        depth = len(path_rels)
        lines = [header, f"Depth: {depth}"]

        for i, rel in enumerate(path_rels):
            src = path_nodes[i]
            dst = path_nodes[i + 1] if i + 1 < len(path_nodes) else path_nodes[-1]
            lines.append(
                f"  {src.get('id', '')} → {rel} → {dst.get('id', '')} "
                f"({dst.get('type', '').lower()})"
            )

        return "\n".join(lines)

    # ---- Tool: get_source_passages --------------------------------------

    @tool
    async def get_source_passages(
        entity_id: str,
        take_top_matches: int = 5,
    ) -> list[str]:
        """Retrieve raw source chunks that mention a known entity.

        Follows MENTIONS edges in the graph — no vector search.  More precise
        and cheaper than retrieve_source when the entity is already identified.

        Args:
            entity_id: The entity ID to find source passages for.
            take_top_matches: Maximum number of passages to return (default 5).
        """
        graph = _get_kuzu_graph()
        texts: list[str] = []
        try:
            for row in graph.query(
                "MATCH (c:Chunk)-[:MENTIONS]->(n) "
                "WHERE n.id = $entity_id "
                "RETURN c.text AS text "
                f"LIMIT {int(take_top_matches)}",
                params={"entity_id": entity_id},
            ):
                text = row.get("text", "")
                if text:
                    texts.append(text)
        except Exception:
            pass

        return texts if texts else ["No source passages found."]

    return (
        query_entities,
        retrieve_source,
        find_relationship,
        find_relationship_by_name,
        list_entities,
        get_neighbors,
        find_path,
        get_source_passages,
    )


def extract_text_content(content: Any) -> str:  # noqa: ANN401
    """Extract plain text from an LLM ``response.content`` value.

    Different LLM connectors return different types for ``response.content``:

    * OpenAI / Google — a plain ``str``.
    * Anthropic — a **list** of typed content-block dicts, e.g.::

        [{'type': 'text', 'text': '...', 'extras': {'signature': '...'}}]

    Calling ``str()`` on the list produces the repr of that list rather than
    the answer text.  This helper normalises both cases.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)
