"""LangGraph document parsing graph.

Five-phase pipeline that transforms raw text into a Z-Bundle's vector store
(LanceDB) and property graph (KùzuDB).

Phase 1 — Preprocessing (optional):
    MediaWiki detection + conversion to Markdown.
Phase 2 — Splitting (no LLM):
    Context split (MarkdownTextSplitter + RecursiveCharacterTextSplitter cap)
    Retrieval re-split per section (SemanticChunker, fallback RCTS)
Phase 3 — Per-chunk parallel processing (semaphore-bounded):
    Co-reference resolution (fastcoref) ‖ Graph extraction
    (LLMGraphTransformer → KuzuDB) ‖ Vector ingestion (LanceDB chunks table)
Phase 4 — Entity deduplication (embedding cosine-similarity merge):
    Merge duplicate entity nodes produced by LLMGraphTransformer.
Phase 5 — Entity summarization (parallel, semaphore-bounded):
    Per-entity LLM summary → KuzuDB n.text + LanceDB entities table.

Implements: src/zforge/graphs/document_parsing_graph.py per
docs/Parsing Documents to Z-Bundles.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownTextSplitter, RecursiveCharacterTextSplitter
from langgraph.graph import END, StateGraph

from zforge.graphs.graph_utils import LLAMA_EXECUTOR, log_node
from zforge.graphs.state import DocumentParsingState

if TYPE_CHECKING:
    from zforge.services.embedding.embedding_connector import EmbeddingConnector
    from zforge.services.llm.llm_connector import LlmConnector

log = logging.getLogger(__name__)

# Default concurrency limit for the fan-out semaphore.
_FAN_OUT_CONCURRENCY = 5

# Number of Document objects sent to LLMGraphTransformer per batch.
_GRAPH_EXTRACTION_BATCH_SIZE = 10

# Minimum counts of each wiki-markup token required to trigger the wikitext
# heuristic (non-XML path).  All three must meet or exceed this threshold.
_WIKITEXT_MIN_MARKER_COUNT = 3

# Entity summarization prompt template.
_ENTITY_SUMMARY_PROMPT = (
    "You are summarizing an entity from a fictional world. "
    "Based only on the following source passages, write a 1–5 paragraph "
    "factual summary of {entity_type} \"{entity_id}\". "
    "Do not invent facts not present in the passages."
)

# Node properties extracted alongside each entity (per Z-World.md § Implementation).
_NODE_PROPERTIES = ["traits", "is_divine", "is_synthetic", "is_sapient"]

# Relationship properties extracted alongside each edge.
_RELATIONSHIP_PROPERTIES = ["from_time", "to_time", "role", "perspective", "canonical"]

# Node-type-specific column DDL beyond the base (id STRING, type STRING).
_NODE_EXTRA_COLUMNS: dict[str, str] = {
    "Character": "traits STRING, is_divine BOOL, is_synthetic BOOL",
    "Species": "is_sapient BOOL",
}


# ------------------------------------------------------------------
# MediaWiki preprocessing helpers
# ------------------------------------------------------------------


def _is_mediawiki_dump(text: str) -> bool:
    """Return True if *text* appears to be a MediaWiki dump or raw wikitext.

    Two signals are checked:

    1. **XML dump** — the document begins with a ``<mediawiki`` element
       (standard MediaWiki XML export format).
    2. **Raw wikitext** — the document contains a high density of the three
       most distinctive wiki-markup tokens: ``{{`` (template open), ``[[``
       (wikilink open), and ``==`` (section heading delimiter).  All three
       must appear at least ``_WIKITEXT_MIN_MARKER_COUNT`` times.
    """
    head = text[:2000]
    if re.search(r"<mediawiki[\s>]", head, re.IGNORECASE):
        return True
    counts = [
        text.count("{{"),
        text.count("[["),
        text.count("=="),
    ]
    return all(c >= _WIKITEXT_MIN_MARKER_COUNT for c in counts)


def _wikitext_to_markdown(wikitext: str) -> str:
    """Convert a single wikitext string to Markdown using mwparserfromhell.

    * ``== Heading ==`` and deeper levels → ``## Heading`` (Markdown ATX).
    * ``[[Page|Display]]`` / ``[[Page]]`` wikilinks → display text.
    * ``[URL Title]`` external links → title text (bare URLs are dropped).
    * ``{{Template}}`` blocks are stripped entirely.
    * HTML ``<tag>…</tag>`` content is kept; the tags themselves are dropped.
    * Plain text nodes are passed through unchanged.
    """
    import mwparserfromhell  # lazy import — only needed on the hot path

    wikicode = mwparserfromhell.parse(wikitext)
    parts: list[str] = []
    for node in wikicode.nodes:
        node_type = type(node).__name__
        if node_type == "Heading":
            level = node.level  # type: ignore[attr-defined]
            title = str(node.title.strip_code()).strip()  # type: ignore[attr-defined]
            parts.append(f"\n{'#' * level} {title}\n\n")
        elif node_type == "Wikilink":
            display = (
                str(node.text.strip_code()) if node.text else str(node.title.strip_code())  # type: ignore[attr-defined]
            )
            parts.append(display)
        elif node_type == "ExternalLink":
            title = str(node.title.strip_code()) if node.title else ""  # type: ignore[attr-defined]
            if title:
                parts.append(title)
            # bare URLs without a title are dropped — not useful in a vector store
        elif node_type == "Template":
            pass  # drop infoboxes, navboxes, etc.
        elif node_type == "Tag":
            # Keep tag content; discard the surrounding HTML markup.
            contents = str(node.contents.strip_code()) if node.contents else ""  # type: ignore[attr-defined]
            parts.append(contents)
        elif node_type == "Comment":
            pass  # HTML comments have no retrieval value
        elif node_type == "Text":
            parts.append(str(node.value))  # type: ignore[attr-defined]
        else:
            # HTMLEntity and other rarely-occurring node types
            parts.append(str(node))
    return "".join(parts)


def _mediawiki_to_markdown(text: str) -> str:
    """Detect format and convert MediaWiki content to Markdown.

    For **XML dumps** (``<mediawiki>`` root element):
        Each ``<page>`` is extracted and its ``<text>`` child run through
        :func:`_wikitext_to_markdown`.  Pages are joined with a rule
        (``---``) so the downstream splitter sees one continuous document.

    For **raw wikitext**:
        The entire string is passed directly to :func:`_wikitext_to_markdown`.
    """
    import xml.etree.ElementTree as ET

    head = text[:2000]
    if re.search(r"<mediawiki[\s>]", head, re.IGNORECASE):
        # XML dump — extract page titles and wikitext bodies.
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            log.warning(
                "mediawiki_preprocessor: XML parse failed (%s) — "
                "falling back to raw wikitext processing",
                exc,
            )
            return _wikitext_to_markdown(text)

        # The namespace varies by dump version; extract it from the root tag.
        ns_match = re.match(r"\{(.+?)\}", root.tag)
        ns = {"mw": ns_match.group(1)} if ns_match else {}

        page_texts: list[str] = []
        for page in root.findall(".//mw:page" if ns else ".//page", ns):
            title_el = page.find("mw:title" if ns else "title", ns)
            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            text_el = page.find(
                ".//mw:revision/mw:text" if ns else ".//revision/text", ns
            )
            if text_el is None or not text_el.text:
                continue
            body = _wikitext_to_markdown(text_el.text)
            page_block = f"# {title}\n\n{body}" if title else body
            page_texts.append(page_block)

        log.info(
            "mediawiki_preprocessor: extracted %d page(s) from XML dump",
            len(page_texts),
        )
        return "\n\n---\n\n".join(page_texts)

    # Raw wikitext
    return _wikitext_to_markdown(text)


def _pascal_to_snake(name: str) -> str:
    """Convert PascalCase to snake_case for entity_type casing contract."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# ------------------------------------------------------------------
# KuzuDB subclass — fixes schema staleness bugs
# ------------------------------------------------------------------


class _MultiTypeKuzuGraph:
    """Wrapper around KuzuGraph that pre-creates schema with extended columns.

    KuzuGraph has two schema-staleness bugs when processing multiple documents:
    1. _create_entity_relationship_table uses CREATE REL TABLE (single FROM-TO).
       IF NOT EXISTS silently skips subsequent pairs.
    2. The MENTIONS REL TABLE GROUP is seeded only from the first document's
       node labels.
    Fix: pre-create all node/MENTIONS schema from the full allowed_nodes list
    before add_graph_documents runs, and use REL TABLE GROUP + ALTER TABLE for
    entity-entity relationships.
    """

    def __init__(self, db: Any, allow_dangerous_requests: bool = True) -> None:
        from langchain_community.graphs import KuzuGraph
        self._kuzu_graph = KuzuGraph(db, allow_dangerous_requests=allow_dangerous_requests)

    @property
    def conn(self) -> Any:
        return self._kuzu_graph.conn

    @property
    def graph(self) -> Any:
        return self._kuzu_graph

    def pre_create_schema(self, allowed_node_labels: list[str]) -> None:
        """Pre-create all node tables and the MENTIONS group up front."""
        for label in allowed_node_labels:
            extra = _NODE_EXTRA_COLUMNS.get(label, "")
            # All entity nodes get a text column for entity summarization
            base_cols = "id STRING, type STRING, text STRING"
            if extra:
                cols = f"{base_cols}, {extra}"
            else:
                cols = base_cols
            self.conn.execute(
                f"CREATE NODE TABLE IF NOT EXISTS {label} "
                f"({cols}, PRIMARY KEY (id))"
            )
        # Chunk node table
        self.conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS Chunk "
            "(id STRING, text STRING, type STRING, PRIMARY KEY (id))"
        )
        # MENTIONS REL TABLE GROUP covering every allowed node type.
        from_to_pairs = ", ".join(
            f"FROM Chunk TO {lbl}" for lbl in allowed_node_labels
        )
        try:
            self.conn.execute(
                f"CREATE REL TABLE GROUP MENTIONS "
                f"({from_to_pairs}, label STRING, triplet_source_id STRING)"
            )
        except Exception:
            for label in allowed_node_labels:
                try:
                    self.conn.execute(
                        f"ALTER TABLE MENTIONS ADD FROM Chunk TO {label}"
                    )
                except Exception:
                    pass  # Pair already registered.

    def add_graph_documents(self, graph_documents: list[Any], rel_triplets: list[Any], include_source: bool = True) -> None:
        """Delegate to KuzuGraph, using REL TABLE GROUP for relationships."""
        # Monkey-patch _create_entity_relationship_table for this instance
        original_method = self._kuzu_graph._create_entity_relationship_table  # type: ignore[reportPrivateUsage]

        def _patched(rel: Any) -> None:
            src, rel_type, tgt = rel.source.type, rel.type, rel.target.type
            try:
                self.conn.execute(
                    f"CREATE REL TABLE GROUP {rel_type} (FROM {src} TO {tgt})"
                )
            except Exception:
                try:
                    self.conn.execute(
                        f"ALTER TABLE {rel_type} ADD FROM {src} TO {tgt}"
                    )
                except Exception:
                    pass  # Pair already registered.

        self._kuzu_graph._create_entity_relationship_table = _patched  # type: ignore[reportPrivateUsage]
        try:
            self._kuzu_graph.add_graph_documents(
                graph_documents, rel_triplets, include_source=include_source
            )
        finally:
            self._kuzu_graph._create_entity_relationship_table = original_method  # type: ignore[reportPrivateUsage]

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        return self._kuzu_graph.query(cypher, params=params or {})


# ------------------------------------------------------------------
# Node factories
# ------------------------------------------------------------------


def _make_mediawiki_preprocessor_node():
    """Return a node that optionally converts MediaWiki markup to Markdown.

    If the incoming ``input_text`` looks like a MediaWiki XML dump or dense
    raw wikitext, it is converted to clean Markdown before the downstream
    text-splitter runs.  This substantially reduces noise (template syntax,
    wikilinks, XML tags) ingested into the vector and graph stores.

    If the text does not appear to be MediaWiki content, the node is a
    transparent pass-through — ``input_text`` is returned unchanged.
    """

    @log_node("mediawiki_preprocessor")
    def mediawiki_preprocessor_node(state: DocumentParsingState) -> dict[str, Any]:
        raw = state["input_text"]
        if not _is_mediawiki_dump(raw):
            log.info(
                "mediawiki_preprocessor: not detected — passing through %d chars",
                len(raw),
            )
            return {}

        log.info(
            "mediawiki_preprocessor: MediaWiki detected — converting %d chars",
            len(raw),
        )
        converted = _mediawiki_to_markdown(raw)
        log.info(
            "mediawiki_preprocessor: conversion complete — %d → %d chars (%.0f%% reduction)",
            len(raw),
            len(converted),
            (1 - len(converted) / max(len(raw), 1)) * 100,
        )
        return {"input_text": converted}

    return mediawiki_preprocessor_node


def _make_splitting_node(
    chunk_size: int,
    chunk_overlap: int,
    retrieval_chunk_size: int,
    retrieval_chunk_overlap: int,
    embedding_connector: EmbeddingConnector,
) -> Any:
    """Return a node implementing the two-pass split (Phase 2).

    Context pass: MarkdownTextSplitter → RecursiveCharacterTextSplitter size-cap.
    Retrieval pass: SemanticChunker per context chunk (fallback RCTS).
    """

    @log_node("splitting")
    async def splitting_node(state: DocumentParsingState) -> dict[str, Any]:
        text = state["input_text"]

        # --- Context pass ---
        md_splitter = MarkdownTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        rcts = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        # First split at structural markers (Markdown headers)
        structural_chunks = md_splitter.split_text(text)
        # Then cap oversized sections with RecursiveCharacterTextSplitter
        context_chunks: list[str] = []
        for sc in structural_chunks:
            if len(sc) > chunk_size:
                context_chunks.extend(rcts.split_text(sc))
            else:
                context_chunks.append(sc)

        log.info(
            "splitting_node: context pass produced %d chunk(s) from %d chars",
            len(context_chunks),
            len(text),
        )

        # --- Retrieval pass ---
        retrieval_documents: list[Document] = []
        use_semantic = True
        SemanticChunker: type | None = None
        try:
            from langchain_experimental.text_splitter import SemanticChunker as _SC
            SemanticChunker = _SC
        except ImportError:
            use_semantic = False
            log.info("splitting_node: SemanticChunker unavailable — using RCTS fallback")

        if use_semantic and SemanticChunker is not None:
            loop = asyncio.get_running_loop()
            embedder = embedding_connector.get_embeddings()
            
            # stable_semantic_split: processes sentences one-by-one to avoid 
            # llama_decode -1 batch overflow in llama-cpp-python.
            async def _stable_semantic_split(text: str) -> list[Document]:
                from langchain_text_splitters import RecursiveCharacterTextSplitter
                # 1. Break chunk into sentences (crude but effective)
                # Using a simple splitter to avoid loading yet another model.
                sentence_splitter = RecursiveCharacterTextSplitter(
                    separator=". ", 
                    chunk_size=1, 
                    chunk_overlap=0,
                    keep_separator=True
                )
                sentences = sentence_splitter.split_text(text)
                if len(sentences) <= 1:
                    return [Document(page_content=text)]

                # 2. Embed sentences one-by-one (CPU/GPU bound, but stable)
                def _get_embeddings(sents: list[str]):
                    return [embedder.embed_query(s) for s in sents]
                
                embeddings = await loop.run_in_executor(
                    LLAMA_EXECUTOR, _get_embeddings, sentences
                )
                
                # 3. Group by cosine similarity
                import numpy as np
                def cosine_similarity(a, b):
                    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

                # Use a similarity threshold similar to SemanticChunker default (percentile 95)
                # but fixed at 0.85 for stability across different small models.
                threshold = 0.85
                chunks = []
                current_chunk_sentences = [sentences[0]]
                current_embedding = embeddings[0]

                for i in range(1, len(sentences)):
                    sim = cosine_similarity(current_embedding, embeddings[i])
                    if sim > threshold:
                        current_chunk_sentences.append(sentences[i])
                        # Moving average for the chunk embedding
                        current_embedding = (current_embedding + embeddings[i]) / 2
                    else:
                        chunks.append(" ".join(current_chunk_sentences))
                        current_chunk_sentences = [sentences[i]]
                        current_embedding = embeddings[i]
                
                chunks.append(" ".join(current_chunk_sentences))
                return [Document(page_content=c) for c in chunks]

            rcts_fallback = RecursiveCharacterTextSplitter(
                chunk_size=retrieval_chunk_size,
                chunk_overlap=retrieval_chunk_overlap,
            )
            # Characters-per-token estimate used to bound pre-filter splits.
            _CHARS_PER_TOKEN = 3
            embed_max_chars = embedding_connector.get_context_size() * _CHARS_PER_TOKEN
            semantic_ok = 0
            semantic_fail = 0

            for idx, chunk in enumerate(context_chunks):
                # Pre-filter
                if len(chunk) > embed_max_chars:
                    pre_pieces = RecursiveCharacterTextSplitter(
                        chunk_size=embed_max_chars,
                        chunk_overlap=0,
                    ).split_text(chunk)
                else:
                    pre_pieces = [chunk]

                for piece in pre_pieces:
                    if not piece.strip():
                        continue
                    try:
                        log.debug("splitting_node: _stable_semantic_split on %d chars...", len(piece))
                        docs = await _stable_semantic_split(piece)
                        
                        for doc in docs:
                            doc.metadata["parent_chunk_id"] = idx
                        retrieval_documents.extend(docs)
                        semantic_ok += 1
                    except Exception as exc:
                        # Capture specific chunks causing llama_decode -1.
                        log.error(
                            "splitting_node: SemanticChunker failed for chunk %d "
                            "(%d chars, preview: %r...) — error: %s: %s",
                            idx,
                            len(piece),
                            piece[:100],
                            type(exc).__name__,
                            exc,
                        )
                        semantic_fail += 1
                        for sub in rcts_fallback.split_text(piece):
                            retrieval_documents.append(
                                Document(
                                    page_content=sub,
                                    metadata={"parent_chunk_id": idx},
                                )
                            )

            if semantic_fail:
                log.info(
                    "splitting_node: SemanticChunker succeeded for %d piece(s), "
                    "RCTS fallback used for %d piece(s)",
                    semantic_ok,
                    semantic_fail,
                )
        else:
            fallback = RecursiveCharacterTextSplitter(
                chunk_size=retrieval_chunk_size,
                chunk_overlap=retrieval_chunk_overlap,
            )
            for idx, chunk in enumerate(context_chunks):
                for sub in fallback.split_text(chunk):
                    retrieval_documents.append(
                        Document(
                            page_content=sub,
                            metadata={"parent_chunk_id": idx},
                        )
                    )

        log.info(
            "splitting_node: retrieval pass produced %d sub-chunk(s)",
            len(retrieval_documents),
        )

        return {
            "chunks": context_chunks,
            "documents": [],
            "retrieval_documents": retrieval_documents,
            "current_chunk_index": 0,
            "status": "processing",
            "status_message": (
                f"Split into {len(context_chunks)} context chunks, "
                f"{len(retrieval_documents)} retrieval sub-chunks"
            ),
        }

    return splitting_node


def _make_parallel_processing_node(
    graph_extractor_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    config: Any,
    graph_extractor_model: str | None = None,
) -> Any:
    """Return a node implementing Phase 3: per-chunk parallel processing.

    For each context chunk (concurrently, semaphore-bounded):
    A. Co-reference resolution (fastcoref)
    B. Graph extraction (LLMGraphTransformer → KuzuDB)
    C. Vector ingestion (LanceDB chunks table)
    """

    _model_cache: list[Any] = []
    _coref_model_cache: list[Any] = []

    @log_node("parallel_processing")
    async def parallel_processing_node(state: DocumentParsingState) -> dict[str, Any]:
        import uuid as _uuid

        import kuzu
        import lancedb

        context_chunks = state["chunks"]
        retrieval_docs = state["retrieval_documents"]
        z_bundle_root = state["z_bundle_root"]
        allowed_nodes = state.get("allowed_nodes", [])
        allowed_relationships = state.get("allowed_relationships", [])
        graph_path = f"{z_bundle_root}/propertygraph"
        vector_path = f"{z_bundle_root}/vector"
        os.makedirs(vector_path, exist_ok=True)

        coref_enabled = getattr(config, "coref_resolution_enabled", True)
        coref_max_chars = getattr(config, "coref_max_chars", 60000)
        loop = asyncio.get_running_loop()

        if coref_enabled:
            # Pre-load model once before concurrent chunk processing begins.
            if not _coref_model_cache:
                def _load_coref_model():
                    try:
                        from fastcoref import FCoref
                        log.info("parallel_processing: loading fastcoref model...")
                        return FCoref()
                    except ImportError as _coref_imp_err:
                        # Log error but don't crash the whole pipeline here;
                        # individual chunks will fall back to original text.
                        log.warning(
                            "Co-reference resolution is enabled but fastcoref is not installed. "
                            "Run: pip install fastcoref. Error: %s", _coref_imp_err
                        )
                        return None
                    except Exception as _coref_exc:
                        log.error("Failed to load fastcoref model: %s", _coref_exc)
                        return None

                _coref_model = await loop.run_in_executor(None, _load_coref_model)
                if _coref_model:
                    _coref_model_cache.append(_coref_model)
                    log.info("parallel_processing: [coref:ready] fastcoref model loaded successfully")
                else:
                    # Mark as None so we don't keep trying to load a broken model
                    _coref_model_cache.append(None)

        if not _model_cache:
            _model_cache.append(
                graph_extractor_connector.get_model(graph_extractor_model)
            )
        model = _model_cache[0]

        from langchain_experimental.graph_transformers import LLMGraphTransformer

        transformer = LLMGraphTransformer(
            llm=model,
            allowed_nodes=allowed_nodes,
            allowed_relationships=allowed_relationships,
            node_properties=_NODE_PROPERTIES,
            relationship_properties=_RELATIONSHIP_PROPERTIES,
        )

        # Set up KuzuDB
        db = kuzu.Database(graph_path)
        graph = _MultiTypeKuzuGraph(db)
        graph.pre_create_schema(allowed_nodes)
        rel_triplets = [
            (src, rel, tgt)
            for src in allowed_nodes
            for rel in allowed_relationships
            for tgt in allowed_nodes
        ]

        # Set up embeddings
        embedder = embedding_connector.get_embeddings()
        _CHARS_PER_TOKEN = 3
        embed_max_chars = embedding_connector.get_context_size() * _CHARS_PER_TOKEN

        # Connect LanceDB async
        lance_db = await lancedb.connect_async(vector_path)

        sem = asyncio.Semaphore(_FAN_OUT_CONCURRENCY)

        async def _process_chunk(chunk_idx: int, chunk_text: str):
            async with sem:
                resolved_text = chunk_text

                # A. Co-reference resolution
                coref_model = _coref_model_cache[0] if _coref_model_cache else None
                if coref_enabled and coref_model and len(chunk_text) <= coref_max_chars:
                    try:
                        def _resolve_coref(text: str) -> str:
                            preds = coref_model.predict(texts=[text])
                            res = preds[0]
                            clusters = res.clusters
                            char_map = res.char_map
                            if not clusters:
                                return text

                            # Build replacement map: canonical = longest mention.
                            replacements: list[tuple[int, int, str]] = []
                            for cluster in clusters:
                                if len(cluster) < 2:
                                    continue
                                mentions: list[tuple[int, int, str]] = []
                                for span in cluster:
                                    try:
                                        # Use char_map to translate from token spans to char spans
                                        char_span = char_map.get(span)
                                        if not char_span:
                                            continue
                                        start, end = char_span[1]
                                        mentions.append((start, end, text[start:end]))
                                    except (ValueError, TypeError, IndexError) as span_err:
                                        log.debug("fastcoref span error: %s", span_err)
                                        continue
                                if not mentions:
                                    continue
                                canonical = max(mentions, key=lambda m: len(m[2]))
                                for start, end, mention_text in mentions:
                                    if mention_text != canonical[2]:
                                        replacements.append((start, end, canonical[2]))
                            # Apply replacements in reverse order to preserve offsets
                            replacements.sort(key=lambda r: r[0], reverse=True)
                            result = text
                            for start, end, replacement in replacements:
                                result = result[:start] + replacement + result[end:]
                            return result

                        resolved_text = await loop.run_in_executor(
                            None, _resolve_coref, chunk_text
                        )
                        if resolved_text != chunk_text:
                            log.info(
                                "parallel_processing: [coref:resolved] chunk %d resolved %d → %d chars",
                                chunk_idx, len(chunk_text), len(resolved_text),
                            )
                        else:
                            log.info("parallel_processing: [coref:skipped] chunk %d no clusters found", chunk_idx)
                    except Exception as exc:
                        log.debug(
                            "parallel_processing: chunk %d coref failed (%s) — using original",
                            chunk_idx, exc,
                        )

                # B. Graph extraction
                doc = Document(page_content=resolved_text)
                batches = [
                    [doc][i: i + _GRAPH_EXTRACTION_BATCH_SIZE]
                    for i in range(0, 1, _GRAPH_EXTRACTION_BATCH_SIZE)
                ]
                for batch in batches:
                    try:
                        graph_documents = await transformer.aconvert_to_graph_documents(batch)
                        graph.add_graph_documents(
                            graph_documents, rel_triplets, include_source=True
                        )
                        log.info(
                            "parallel_processing: chunk %d extracted %d graph doc(s)",
                            chunk_idx, len(graph_documents),
                        )
                    except BaseException as exc:
                        _causes = getattr(exc, "exceptions", [exc])
                        _detail = ""
                        for _cause in _causes:
                            _response = getattr(_cause, "response", None)
                            if _response is not None:
                                try:
                                    _detail = f" — {_response.json()}"
                                except Exception:
                                    _detail = f" — {getattr(_response, 'text', '')}"
                                break
                        log.warning(
                            "parallel_processing: chunk %d graph extraction failed (%s%s)",
                            chunk_idx, exc, _detail,
                        )

                # C. Vector ingestion — write retrieval sub-chunks for this context chunk
                chunk_retrieval_docs = [
                    d for d in retrieval_docs
                    if d.metadata.get("parent_chunk_id") == chunk_idx
                ]
                if chunk_retrieval_docs:
                    texts = [d.page_content for d in chunk_retrieval_docs]
                    texts_for_embed = [t[:embed_max_chars] for t in texts]

                    def _embed(embed_texts: list[str]) -> list[list[float]]:
                        return [embedder.embed_query(t) for t in embed_texts]

                    try:
                        vectors: list[list[float]] = await loop.run_in_executor(
                            LLAMA_EXECUTOR, lambda: _embed(texts_for_embed)
                        )
                        rows = [
                            {
                                "vector": vec,
                                "entity_id": str(_uuid.uuid4()),
                                "entity_type": _pascal_to_snake(
                                    allowed_nodes[0] if allowed_nodes else "chunk"
                                ),
                                "text": text,
                            }
                            for text, vec in zip(texts, vectors)
                        ]
                        # Use mode="append" so chunks from different context chunks accumulate
                        try:
                            table = await lance_db.open_table("chunks")
                            await table.add(rows)
                        except Exception:
                            await lance_db.create_table("chunks", data=rows, mode="overwrite")

                        log.info(
                            "parallel_processing: chunk %d wrote %d retrieval docs to LanceDB",
                            chunk_idx, len(rows),
                        )
                    except Exception as exc:
                        log.warning(
                            "parallel_processing: chunk %d vector ingestion failed (%s)",
                            chunk_idx, exc,
                        )

        # Fan out across all context chunks
        tasks = [
            _process_chunk(idx, chunk)
            for idx, chunk in enumerate(context_chunks)
        ]
        await asyncio.gather(*tasks)

        log.info(
            "parallel_processing: all %d chunks processed",
            len(context_chunks),
        )
        return {
            "status": "deduplicating",
            "status_message": f"Processed {len(context_chunks)} chunks; deduplicating entities...",
        }

    return parallel_processing_node


def _make_entity_dedup_node(embedding_connector: EmbeddingConnector, config: Any) -> Any:
    """Return a node implementing Phase 4: entity deduplication.

    For each node table, embed entity ids, cluster by cosine similarity,
    and merge duplicates via Cypher MERGE + DELETE.
    """

    @log_node("entity_dedup")
    async def entity_dedup_node(state: DocumentParsingState) -> dict[str, Any]:
        if not getattr(config, "entity_dedup_enabled", True):
            log.info("entity_dedup_node: disabled — skipping")
            return {
                "status": "summarizing_entities",
                "status_message": "Entity deduplication skipped (disabled)",
            }

        import kuzu
        import lancedb
        import numpy as np

        threshold: float = getattr(config, "entity_dedup_threshold", 0.93)
        z_bundle_root = state["z_bundle_root"]
        allowed_nodes = state.get("allowed_nodes", [])
        graph_path = f"{z_bundle_root}/propertygraph"
        vector_path = f"{z_bundle_root}/vector"

        db = kuzu.Database(graph_path)
        from langchain_community.graphs import KuzuGraph
        graph = KuzuGraph(db, allow_dangerous_requests=True)

        loop = asyncio.get_running_loop()
        embedder = embedding_connector.get_embeddings()

        total_merges = 0

        for label in allowed_nodes:
            try:
                rows = graph.query(
                    f"MATCH (n:{label}) RETURN n.id AS id, n.type AS type"
                )
            except Exception:
                continue
            if not rows:
                continue

            ids = [r["id"] for r in rows if r.get("id")]
            if len(ids) < 2:
                continue

            # Embed all entity ids
            def _embed_ids(id_list: list[str]) -> list[list[float]]:
                return [embedder.embed_query(eid) for eid in id_list]

            vecs: list[list[float]] = await loop.run_in_executor(
                LLAMA_EXECUTOR, lambda: _embed_ids(ids)
            )
            vecs_np = np.array(vecs)

            # Compute cosine similarity matrix
            norms = np.linalg.norm(vecs_np, axis=1, keepdims=True)
            norms[norms == 0] = 1
            normed = vecs_np / norms
            sim_matrix = normed @ normed.T

            # Find duplicate pairs above threshold (same type only)
            merged = set()
            for i in range(len(ids)):
                if ids[i] in merged:
                    continue
                cluster = [i]
                for j in range(i + 1, len(ids)):
                    if ids[j] in merged:
                        continue
                    if sim_matrix[i, j] >= threshold:
                        cluster.append(j)
                if len(cluster) < 2:
                    continue

                # Canonical = longest string; tie-break by id
                cluster_ids = [ids[k] for k in cluster]
                canonical = max(cluster_ids, key=lambda x: (len(x), x))
                duplicates = [cid for cid in cluster_ids if cid != canonical]

                for dup in duplicates:
                    try:
                        # Create canonical if not exists
                        graph.query(
                            f"MERGE (n:{label} {{id: $canonical}}) "
                            f"SET n.type = $type",
                            params={"canonical": canonical, "type": label},
                        )
                        # Repoint outgoing edges
                        graph.query(
                            f"MATCH (old:{label} {{id: $dup}})-[r]->(m) "
                            f"MATCH (new:{label} {{id: $canonical}}) "
                            f"CREATE (new)-[r2:{{type(r)}}]->(m)",
                            params={"dup": dup, "canonical": canonical},
                        )
                        # Repoint incoming edges
                        graph.query(
                            f"MATCH (m)-[r]->(old:{label} {{id: $dup}}) "
                            f"MATCH (new:{label} {{id: $canonical}}) "
                            f"CREATE (m)-[r2:{{type(r)}}]->(new)",
                            params={"dup": dup, "canonical": canonical},
                        )
                        # Delete duplicate
                        graph.query(
                            f"MATCH (n:{label} {{id: $dup}}) DELETE n",
                            params={"dup": dup},
                        )
                        merged.add(dup)
                        total_merges += 1

                        # Update entity_id in LanceDB chunks table
                        try:
                            lance_conn = lancedb.connect(vector_path)
                            chunks_table = lance_conn.open_table("chunks")
                            # LanceDB update: filter and update rows
                            chunks_table.update(
                                where=f"entity_id = '{dup}'",
                                values={"entity_id": canonical},
                            )
                        except Exception:
                            pass  # LanceDB update best-effort

                    except Exception as exc:
                        log.warning(
                            "entity_dedup_node: merge %s → %s in %s failed: %s",
                            dup, canonical, label, exc,
                        )

        log.info("entity_dedup_node: merged %d duplicate(s)", total_merges)
        return {
            "status": "summarizing_entities",
            "status_message": f"Deduplicated entities ({total_merges} merge(s))",
        }

    return entity_dedup_node


def _make_entity_summarization_node(
    entity_summarizer_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    config: Any,
    entity_summarizer_model: str | None = None,
) -> Any:
    """Return a node implementing Phase 5: entity summarization.

    For each entity node in KuzuDB, collect source passages, call LLM to
    summarize, write summary to KuzuDB n.text and LanceDB entities table.
    """

    _model_cache: list[Any] = []

    @log_node("entity_summarization")
    async def entity_summarization_node(state: DocumentParsingState) -> dict[str, Any]:
        if not getattr(config, "entity_summarization_enabled", True):
            log.info("entity_summarization_node: disabled — skipping")
            return {
                "status": "complete",
                "status_message": "Entity summarization skipped (disabled)",
            }

        import kuzu
        import lancedb

        max_passages = getattr(config, "entity_summarization_max_passages", 20)
        z_bundle_root = state["z_bundle_root"]
        allowed_nodes = state.get("allowed_nodes", [])
        graph_path = f"{z_bundle_root}/propertygraph"
        vector_path = f"{z_bundle_root}/vector"

        if not _model_cache:
            _model_cache.append(
                entity_summarizer_connector.get_model(entity_summarizer_model)
            )
        model = _model_cache[0]

        db = kuzu.Database(graph_path)
        from langchain_community.graphs import KuzuGraph
        graph = KuzuGraph(db, allow_dangerous_requests=True)

        loop = asyncio.get_running_loop()
        embedder = embedding_connector.get_embeddings()
        _CHARS_PER_TOKEN = 3
        embed_max_chars = embedding_connector.get_context_size() * _CHARS_PER_TOKEN

        # Collect all entities across all allowed node tables
        entities: list[tuple[str, str]] = []  # (label, id)
        for label in allowed_nodes:
            try:
                rows = graph.query(
                    f"MATCH (n:{label}) RETURN n.id AS id, n.text AS text"
                )
                for row in rows:
                    if row.get("id"):
                        entities.append((label, row["id"]))
            except Exception:
                continue

        log.info(
            "entity_summarization_node: %d entities to summarize", len(entities)
        )

        sem = asyncio.Semaphore(_FAN_OUT_CONCURRENCY)
        entity_rows: list[dict[str, Any]] = []

        async def _summarize_entity(label: str, entity_id: str) -> None:
            async with sem:
                # Collect source passages
                try:
                    passages_rows = graph.query(
                        f"MATCH (c:Chunk)-[:MENTIONS]->(n:{label}) "
                        f"WHERE n.id = $id RETURN c.text",
                        params={"id": entity_id},
                    )
                    passages = [
                        r.get("c.text", "") for r in (passages_rows or [])
                        if r.get("c.text")
                    ][:max_passages]
                except Exception:
                    passages = []

                # Check for existing text on node (seed passage)
                try:
                    node_rows = graph.query(
                        f"MATCH (n:{label}) WHERE n.id = $id RETURN n.text",
                        params={"id": entity_id},
                    )
                    existing_text = (
                        node_rows[0].get("n.text", "") if node_rows else ""
                    )
                    if existing_text:
                        passages.insert(0, existing_text)
                except Exception:
                    pass

                if not passages:
                    return

                # Call LLM
                prompt = _ENTITY_SUMMARY_PROMPT.format(
                    entity_type=label,
                    entity_id=entity_id,
                )
                passage_text = "\n\n---\n\n".join(passages)
                full_prompt = f"{prompt}\n\nSource passages:\n\n{passage_text}"

                try:
                    from zforge.graphs.graph_utils import extract_text_content
                    response = await model.ainvoke(full_prompt)
                    summary = extract_text_content(
                        getattr(response, "content", "")
                    )
                except Exception as exc:
                    log.warning(
                        "entity_summarization: %s '%s' LLM failed: %s",
                        label, entity_id, exc,
                    )
                    return

                # Write summary to KuzuDB
                try:
                    graph.query(
                        f"MATCH (n:{label}) WHERE n.id = $id SET n.text = $text",
                        params={"id": entity_id, "text": summary},
                    )
                except Exception as exc:
                    log.warning(
                        "entity_summarization: %s '%s' KuzuDB write failed: %s",
                        label, entity_id, exc,
                    )

                # Embed summary
                try:
                    def _embed_summary(text: str) -> list[float]:
                        return embedder.embed_query(text[:embed_max_chars])

                    vec: list[float] = await loop.run_in_executor(
                        LLAMA_EXECUTOR, lambda: _embed_summary(summary)
                    )
                    entity_rows.append({
                        "vector": vec,
                        "entity_id": entity_id,
                        "entity_type": _pascal_to_snake(label),
                        "text": summary,
                    })
                except Exception as exc:
                    log.warning(
                        "entity_summarization: %s '%s' embedding failed: %s",
                        label, entity_id, exc,
                    )

        # Fan out across all entities
        tasks = [
            _summarize_entity(label, eid) for label, eid in entities
        ]
        await asyncio.gather(*tasks)

        # Write all entity summaries to LanceDB entities table
        if entity_rows:
            try:
                lance_conn = await lancedb.connect_async(vector_path)
                await lance_conn.create_table(
                    "entities", data=entity_rows, mode="overwrite"
                )
                log.info(
                    "entity_summarization_node: wrote %d entity summaries to LanceDB",
                    len(entity_rows),
                )
            except Exception as exc:
                log.warning(
                    "entity_summarization_node: LanceDB write failed: %s", exc
                )

        log.info("entity_summarization_node: done")
        return {
            "status": "complete",
            "status_message": f"Summarized {len(entity_rows)} entities",
        }

    return entity_summarization_node


# ------------------------------------------------------------------
# Graph builder
# ------------------------------------------------------------------


def build_document_parsing_graph(
    graph_extractor_connector: LlmConnector,
    entity_summarizer_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    config: Any,
    graph_extractor_model: str | None = None,
    entity_summarizer_model: str | None = None,
) -> Any:
    """Build and compile the document parsing LangGraph StateGraph.

    Parameters
    ----------
    graph_extractor_connector:
        LLM connector for Phase 3 graph extraction via LLMGraphTransformer.
    entity_summarizer_connector:
        LLM connector for Phase 5 entity summarization.
    embedding_connector:
        Embedding connector for LanceDB vector ingestion and entity embedding.
    config:
        ZForgeConfig providing parsing_chunk_size, parsing_chunk_overlap,
        parsing_retrieval_chunk_size, parsing_retrieval_chunk_overlap, and
        the coref/dedup/summarization settings.
    graph_extractor_model / entity_summarizer_model:
        Optional model name overrides.
    """
    chunk_size = getattr(config, "parsing_chunk_size", 10000)
    chunk_overlap = getattr(config, "parsing_chunk_overlap", 500)
    retrieval_chunk_size = getattr(config, "parsing_retrieval_chunk_size", 500)
    retrieval_chunk_overlap = getattr(config, "parsing_retrieval_chunk_overlap", 50)

    graph = StateGraph(DocumentParsingState)

    graph.add_node(
        "mediawiki_preprocessor", _make_mediawiki_preprocessor_node()
    )
    graph.add_node(
        "splitting",
        _make_splitting_node(
            chunk_size, chunk_overlap,
            retrieval_chunk_size, retrieval_chunk_overlap,
            embedding_connector,
        ),
    )
    graph.add_node(
        "parallel_processing",
        _make_parallel_processing_node(
            graph_extractor_connector,
            embedding_connector,
            config,
            graph_extractor_model,
        ),
    )
    graph.add_node(
        "entity_dedup",
        _make_entity_dedup_node(embedding_connector, config),
    )
    graph.add_node(
        "entity_summarization",
        _make_entity_summarization_node(
            entity_summarizer_connector,
            embedding_connector,
            config,
            entity_summarizer_model,
        ),
    )

    graph.set_entry_point("mediawiki_preprocessor")
    graph.add_edge("mediawiki_preprocessor", "splitting")
    graph.add_edge("splitting", "parallel_processing")
    graph.add_edge("parallel_processing", "entity_dedup")
    graph.add_edge("entity_dedup", "entity_summarization")
    graph.add_edge("entity_summarization", END)

    return graph.compile()
