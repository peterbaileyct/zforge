"""Shared utilities for LangGraph state machine graphs.

Provides the :func:`log_node` decorator for uniform observability across
all graph node functions: logs entry, exit (with elapsed time), and
exceptions so the log stream fully describes graph execution without
requiring manual instrumentation in each node body.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from typing import Any, Callable

log = logging.getLogger(__name__)


def log_node(name: str) -> Callable:
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

    def decorator(fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):
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

            return async_wrapper

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

        return wrapper

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


def make_retrieve_graph_tool(z_bundle_root: str):
    """Factory that returns a ``retrieve_graph`` LangChain tool for a Z-Bundle.

    The returned tool has two execution branches:

    1. **Cypher** — if *query* starts with ``MATCH``, ``WITH``, ``CALL``,
       ``OPTIONAL``, or ``UNWIND``, it is executed directly via
       ``KuzuGraph.query()``.  On error or empty results the graph schema is
       appended so the caller can write a corrected query.

    2. **Keyword / entity-name search** — otherwise, each word in *query* is
       matched case-insensitively against the ``id`` property of every
       standard entity node table (Character, Location, Faction, Event, …).
       For every hit the tool expands one hop of outgoing and incoming
       relationships (Chunk nodes excluded), returning relationship type,
       neighbour type, and neighbour id.  Schema is only returned when no
       entities are found.

    Args:
        z_bundle_root: Filesystem path to the Z-Bundle root directory,
            used to open ``{root}/propertygraph``.
    """
    from langchain_core.tools import tool

    _ENTITY_LABELS = [
        "Character", "Location", "Faction", "Event", "Occupation",
        "Species", "Concept", "Artifact", "Prophecy", "Era",
        "Culture", "Deity", "Trope", "Mechanic",
    ]
    _CYPHER_STARTS = {"MATCH", "WITH", "CALL", "OPTIONAL", "UNWIND"}

    @tool
    def retrieve_graph(query: str) -> str:
        """Query the Z-Bundle's property graph for structured entity data.

        Pass a Cypher query (starting with MATCH / WITH / CALL) to execute it
        directly, or pass a keyword or entity name to search for matching
        entities and their 1-hop relationships.

        Args:
            query: A Cypher query or a keyword / entity name to look up.
        """
        import kuzu
        from langchain_community.graphs import KuzuGraph

        graph_path = f"{z_bundle_root}/propertygraph"
        db = kuzu.Database(graph_path)
        graph = KuzuGraph(db, allow_dangerous_requests=True)

        q = query.strip()
        first_word = q.split()[0].upper() if q.split() else ""

        # --- Branch 1: Direct Cypher execution ---
        if first_word in _CYPHER_STARTS:
            try:
                rows = graph.query(q)
                if not rows:
                    return f"No results.\n\nSchema for reference:\n{graph.get_schema}"
                return "\n".join(str(r) for r in rows[:50])
            except Exception as exc:
                return f"Cypher error: {exc}\n\nSchema for reference:\n{graph.get_schema}"

        # --- Branch 2: Keyword / entity-name search + 1-hop expansion ---
        keyword = q.lower()
        hits: list[tuple[str, str]] = []
        for label in _ENTITY_LABELS:
            try:
                rows = graph.query(
                    f"MATCH (n:{label}) WHERE toLower(n.id) CONTAINS $kw RETURN n.id LIMIT 8",
                    params={"kw": keyword},
                )
                hits.extend((label, row["n.id"]) for row in rows if row.get("n.id"))
            except Exception:
                pass  # table may not exist in this world's graph

        if not hits:
            return f"No entities found matching '{q}'.\n\nSchema for reference:\n{graph.get_schema}"

        parts: list[str] = []
        for label, node_id in hits[:10]:
            lines = [f"[{label}] {node_id}"]
            # Outgoing edges
            try:
                for row in graph.query(
                    f"MATCH (n:{label})-[r]->(m) WHERE n.id = $id "
                    f"RETURN type(r) AS rel, label(m) AS m_label, m.id AS target LIMIT 20",
                    params={"id": node_id},
                ):
                    if row.get("m_label") == "Chunk":
                        continue
                    lines.append(
                        f"  -[{row.get('rel')}]-> [{row.get('m_label')}] {row.get('target')}"
                    )
            except Exception:
                pass
            # Incoming edges
            try:
                for row in graph.query(
                    f"MATCH (m)-[r]->(n:{label}) WHERE n.id = $id "
                    f"RETURN type(r) AS rel, label(m) AS m_label, m.id AS source LIMIT 20",
                    params={"id": node_id},
                ):
                    if row.get("m_label") == "Chunk":
                        continue
                    lines.append(
                        f"  <-[{row.get('rel')}]- [{row.get('m_label')}] {row.get('source')}"
                    )
            except Exception:
                pass
            parts.append("\n".join(lines))

        return "\n\n".join(parts)

    return retrieve_graph


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
