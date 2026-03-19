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
# database on every query_world tool call.

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
) -> tuple[Any, Any]:
    """Factory that returns ``(query_world, retrieve_source)`` LangChain tools.

    Both tools query the Z-Bundle at *z_bundle_root*.  ``query_world`` is the
    primary tool — it combines semantic entity matching, 1-hop graph expansion,
    and optional neighbour hydration into a single call.  ``retrieve_source``
    returns verbatim source passages from the ``chunks`` table.

    Args:
        z_bundle_root: Filesystem path to the Z-Bundle root directory.
        allowed_node_labels: PascalCase node type names used at ingest time.
        embedding_connector: Embedding connector (provides ``get_embeddings()``).

    Returns:
        A ``(query_world, retrieve_source)`` tuple of LangChain tools.
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

    async def _vector_search(table_name: str, query: str, k: int,
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
        try:
            tbl = await db.open_table(table_name)
        except Exception:
            if table_name == "entities":
                try:
                    tbl = await db.open_table("chunks")
                except Exception:
                    return []
            else:
                return []

        search_q = await tbl.search(query_vec, query_type="vector")
        if entity_type:
            search_q = search_q.where(f"entity_type = '{entity_type}'")
        results_arrow = await search_q.limit(k).to_arrow()
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

    # ---- Tool: query_world ----------------------------------------------

    @tool
    async def query_world(
        query: str,
        entity_type: str | None = None,
        k: int = 3,
        include_neighbors: bool = False,
    ) -> str:
        """Look up entities in the world by description or name.

        Returns entity summaries, relationships, and optionally adjacent entity
        details.  Use entity_type to restrict to a specific type.  Set
        include_neighbors=True for network or connection questions.

        Args:
            query: Natural language search query or entity name.
            entity_type: Optional entity type filter (snake_case, e.g. "character").
            k: Number of top entity matches to return (default 3).
            include_neighbors: If True, also return summaries and relationships
                for each matched entity's 1-hop neighbours.
        """
        # Step 1: Semantic match against entities table
        rows = await _vector_search("entities", query, k, entity_type)
        if not rows:
            return "No matching entities found."

        graph = _get_kuzu_graph()
        parts: list[str] = []

        for row in rows:
            eid = row.get("entity_id", "")
            etype = row.get("entity_type", "")
            summary = row.get("text", "")

            # Determine the PascalCase label for graph queries
            pascal_label = None
            for lbl in allowed_node_labels:
                if lbl.lower() == etype.replace("_", ""):
                    pascal_label = lbl
                    break
            if not pascal_label:
                # Try matching by converting snake_case → PascalCase
                candidate = "".join(w.capitalize() for w in etype.split("_"))
                if candidate in allowed_node_labels:
                    pascal_label = candidate

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
                            f"LIMIT {k * 3}",
                            params={"nid": eid},
                        ):
                            if r.get("mid") and r.get("mlabel"):
                                neighbour_ids.append((r["mlabel"], r["mid"]))
                    except Exception:
                        pass

                    # Hydrate up to k neighbours
                    for n_label, n_id in neighbour_ids[:k]:
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
        k: int = 5,
    ) -> str:
        """Retrieve verbatim source passages from the world text.

        Use when exact wording is required — contradictions, rumours, specific
        quotes, or when entity summaries may over-synthesize.

        Args:
            query: Natural language search query.
            entity_type: Optional entity type filter (snake_case, e.g. "character").
            k: Number of passages to return (default 5).
        """
        rows = await _vector_search("chunks", query, k, entity_type)
        if not rows:
            return "No source passages found."
        texts = [r.get("text", "") for r in rows if r.get("text")]
        if not texts:
            return "No source passages found."
        return "\n\n---\n\n".join(texts)

    return query_world, retrieve_source


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
