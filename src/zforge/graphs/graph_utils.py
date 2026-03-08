"""Shared utilities for LangGraph state machine graphs.

Provides the :func:`log_node` decorator for uniform observability across
all graph node functions: logs entry, exit (with elapsed time), and
exceptions so the log stream fully describes graph execution without
requiring manual instrumentation in each node body.
"""

from __future__ import annotations

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
