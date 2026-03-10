"""LangGraph document parsing graph.

Two-phase pipeline that transforms raw text into a Z-Bundle's vector store
(LanceDB) and property graph (KùzuDB).

Phase 1 — Sequential contextualization:
    Text Splitter → Contextualizer loop (one iteration per chunk)

Phase 2 — Parallel ingestion (fan-out):
    Vector Ingestion (LanceDB.from_documents) ‖ Graph Ingestion
    (LLMGraphTransformer → KuzuGraph.add_graph_documents)

Implements: src/zforge/graphs/document_parsing_graph.py per
docs/Parsing Documents to Z-Bundles.md.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from typing import TYPE_CHECKING

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, StateGraph

from zforge.graphs.graph_utils import log_node
from zforge.graphs.state import DocumentParsingState

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings

    from zforge.services.llm.llm_connector import LlmConnector

log = logging.getLogger(__name__)

_CONTEXTUALIZER_PROMPT_TEMPLATE = (
    "You are summarizing a passage from a source document. "
    "List the key named entities ({allowed_nodes}) and any significant facts, "
    "events, or status changes introduced in this passage. Be concise — your "
    "output will be prepended as context when processing the next passage."
)

# Default concurrency limit for the fan-out semaphore.
_FAN_OUT_CONCURRENCY = 5

# Number of Document objects sent to LLMGraphTransformer per batch.
# LLMGraphTransformer.aconvert_to_graph_documents dispatches one LLM call per
# document concurrently. With thousands of chunks this causes immediate rate-
# limit exhaustion. Batching keeps concurrent calls to a manageable level;
# batches are processed sequentially. See docs/Parsing Documents to
# Z-Bundles.md § Graph extraction batch size.
_GRAPH_EXTRACTION_BATCH_SIZE = 10

# Single-thread executor for all llama.cpp / local-model work.
# llama.cpp's Metal (GPU) backend on macOS binds its command queue to the OS
# thread on which the model is first loaded. Using asyncio.to_thread() risks
# dispatching to a different thread on each call, causing a silent hang.
# Using a max_workers=1 executor guarantees every call lands on the same thread.
_LLAMA_EXECUTOR: concurrent.futures.ThreadPoolExecutor = (
    concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="llama")
)


# ------------------------------------------------------------------
# Node factories
# ------------------------------------------------------------------


def _make_text_splitter_node(chunk_size: int, chunk_overlap: int):
    """Return a node that splits input_text into overlapping chunks."""

    @log_node("text_splitter")
    def text_splitter_node(state: DocumentParsingState) -> dict:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        chunks = splitter.split_text(state["input_text"])
        log.info(
            "text_splitter_node: split %d chars into %d chunk(s)",
            len(state["input_text"]),
            len(chunks),
        )
        return {
            "chunks": chunks,
            "documents": [],
            "retrieval_documents": [],
            "current_chunk_index": 0,
            "status": "contextualizing",
            "status_message": f"Split text into {len(chunks)} chunk(s)",
        }

    return text_splitter_node


def _make_contextualizer_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
    retrieval_chunk_size: int = 500,
    retrieval_chunk_overlap: int = 50,
):
    """Return a node that contextualizes the current chunk.

    Each large context chunk is summarized to produce a breadcrumb for the
    next chunk.  The chunk is then re-split by ``_retrieval_splitter`` into
    smaller sub-chunks for vector-store precision; each sub-chunk inherits
    the current rolling breadcrumb so no additional LLM calls are needed.
    """

    _model_cache: list = []
    _retrieval_splitter = RecursiveCharacterTextSplitter(
        chunk_size=retrieval_chunk_size,
        chunk_overlap=retrieval_chunk_overlap,
    )

    @log_node("contextualizer")
    async def contextualizer_node(state: DocumentParsingState) -> dict:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        idx = state.get("current_chunk_index", 0)
        chunks = state["chunks"]
        documents = list(state.get("documents") or [])

        chunk = chunks[idx]

        # Build breadcrumb from previous iteration's summary
        breadcrumb = ""
        if idx > 0 and documents:
            prev_doc = documents[-1]
            breadcrumb = prev_doc.metadata.get("breadcrumb", "")

        # Ask the LLM for a summary of this chunk (used as breadcrumb for next)
        allowed_nodes_str = ", ".join(state.get("allowed_nodes", []))
        system = _CONTEXTUALIZER_PROMPT_TEMPLATE.format(
            allowed_nodes=allowed_nodes_str
        )
        human_content = chunk
        if breadcrumb:
            human_content = f"[Context from previous passage]: {breadcrumb}\n\n{chunk}"

        log.info(
            "contextualizer_node: chunk %d/%d — %d chars",
            idx + 1,
            len(chunks),
            len(chunk),
        )
        try:
            response = await model.ainvoke(
                [SystemMessage(content=system), HumanMessage(content=human_content)]
            )
            summary = str(getattr(response, "content", ""))
        except Exception as exc:
            # Log the actual provider error body when available (e.g. Groq 400).
            _detail = ""
            _response = getattr(exc, "response", None)
            if _response is not None:
                try:
                    _detail = f" — {_response.json()}"
                except Exception:
                    _detail = f" — {getattr(_response, 'text', '')}"
            log.warning(
                "contextualizer_node: chunk %d/%d LLM call failed (%s%s) "
                "— continuing with empty breadcrumb",
                idx + 1,
                len(chunks),
                exc,
                _detail,
            )
            summary = ""

        # Create a Document with the chunk text and breadcrumb metadata
        doc = Document(
            page_content=chunk,
            metadata={"breadcrumb": summary},
        )
        documents.append(doc)

        # Re-split this context chunk into smaller retrieval chunks for the
        # vector store (two-pass split).  Each sub-chunk inherits the *same*
        # breadcrumb as its parent — context from before this section — so all
        # retrieval chunks carry meaningful rolling context without extra LLM
        # calls.  Graph ingestion continues to use the full context-pass
        # documents (``state["documents"]``) for richer extraction.
        retrieval_documents = list(state.get("retrieval_documents") or [])
        if retrieval_chunk_size < len(chunk):
            sub_chunks = _retrieval_splitter.split_text(chunk)
        else:
            sub_chunks = [chunk]
        for sub_chunk in sub_chunks:
            retrieval_documents.append(
                Document(
                    page_content=sub_chunk,
                    metadata={"breadcrumb": breadcrumb},
                )
            )

        return {
            "documents": documents,
            "retrieval_documents": retrieval_documents,
            "current_chunk_index": 1,  # operator.add increments
            "status": "contextualizing",
            "status_message": f"Contextualized chunk {idx + 1}/{len(chunks)}",
        }

    return contextualizer_node


def _make_vector_ingestion_node(embedding_connector):
    """Return a node that writes Documents to LanceDB."""

    @log_node("vector_ingestion")
    async def vector_ingestion_node(state: DocumentParsingState) -> dict:
        import uuid as _uuid

        import lancedb

        documents = state["documents"]
        z_bundle_root = state["z_bundle_root"]
        vector_path = f"{z_bundle_root}/vector"
        os.makedirs(vector_path, exist_ok=True)

        log.info(
            "vector_ingestion_node: writing %d documents to %s",
            len(documents),
            vector_path,
        )

        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]

        # Truncate text sent to the embedding model to avoid llama_decode overflow.
        # At 3 chars/token a 512-token context clamps to ~1536 chars (~384 tokens),
        # well under any realistic n_ctx. The full chunk text is stored in LanceDB.
        # See docs/Parsing Documents to Z-Bundles.md § Embedding context overflow.
        _CHARS_PER_TOKEN = 3
        embed_max_chars = embedding_connector.get_context_size() * _CHARS_PER_TOKEN
        texts_for_embed = [t[:embed_max_chars] for t in texts]

        # Compute embeddings on the dedicated llama thread so the event loop
        # stays free and Metal always runs on the same OS thread.
        # IMPORTANT: call embed_query() one text at a time rather than passing
        # the full list to embed_documents(). LlamaCppEmbeddings.embed_documents
        # forwards the entire list to llama_cpp.create_embedding() as a batch;
        # llama.cpp then tries to decode all texts in a single decode pass, which
        # overflows n_ctx even for short chunks and raises llama_decode returned -1.
        # embed_query() processes one text per llama_decode call, staying within
        # the context window. See docs/Parsing Documents to Z-Bundles.md
        # § embed_documents batch overflow pitfall.
        loop = asyncio.get_running_loop()
        embedder = embedding_connector.get_embeddings()

        def _embed_one_by_one(embed_texts: list[str]) -> list:
            return [embedder.embed_query(t) for t in embed_texts]

        try:
            vectors = await loop.run_in_executor(
                _LLAMA_EXECUTOR,
                lambda: _embed_one_by_one(texts_for_embed),
            )
        except Exception as exc:
            log.warning(
                "vector_ingestion_node: embedding failed (%s) — "
                "vector store will be empty for this document",
                exc,
            )
            return {"status_message": "Vector store skipped (embedding error)"}

        # Build rows in the schema LanceDBVectorStore expects.
        rows = [
            {
                "id": str(_uuid.uuid4()),
                "text": text,
                "vector": vec,
                "metadata": metadatas[i] if metadatas else {},
            }
            for i, (text, vec) in enumerate(zip(texts, vectors))
        ]

        # Connect and write using the native async API so we stay on the
        # running event loop — lancedb.connect() (sync) internally bridges
        # futures across loops and deadlocks when called from any asyncio
        # context. See docs/Parsing Documents to Z-Bundles.md.
        db = await lancedb.connect_async(vector_path)
        await db.create_table("chunks", data=rows, mode="overwrite")

        log.info("vector_ingestion_node: done")
        return {
            "status_message": "Vector store populated",
        }

    return vector_ingestion_node


def _make_graph_ingestion_node(
    llm_connector: LlmConnector, model_name: str | None = None
):
    """Return a node that extracts graph documents and writes to KuzuDB."""

    _model_cache: list = []

    @log_node("graph_ingestion")
    async def graph_ingestion_node(state: DocumentParsingState) -> dict:
        import kuzu
        from langchain_community.graphs import KuzuGraph
        from langchain_experimental.graph_transformers import LLMGraphTransformer

        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        documents = state["documents"]
        z_bundle_root = state["z_bundle_root"]
        allowed_nodes = state.get("allowed_nodes", [])
        allowed_relationships = state.get("allowed_relationships", [])
        graph_path = f"{z_bundle_root}/propertygraph"
        # KuzuDB creates its own database file — do NOT pre-create this path
        # as a directory, or kuzu.Database() will raise "path cannot be a
        # directory". See docs/Parsing Documents to Z-Bundles.md.

        log.info(
            "graph_ingestion_node: extracting graph from %d documents",
            len(documents),
        )

        transformer = LLMGraphTransformer(
            llm=model,
            allowed_nodes=allowed_nodes,
            allowed_relationships=allowed_relationships,
        )

        # Process documents in sequential batches to avoid issuing thousands of
        # concurrent LLM calls (one per document) which exhausts provider rate
        # limits. Each batch is awaited before the next starts.
        graph_documents: list = []
        batches = [
            documents[i : i + _GRAPH_EXTRACTION_BATCH_SIZE]
            for i in range(0, len(documents), _GRAPH_EXTRACTION_BATCH_SIZE)
        ]
        log.info(
            "graph_ingestion_node: %d document(s) in %d batch(es) of ≤%d",
            len(documents),
            len(batches),
            _GRAPH_EXTRACTION_BATCH_SIZE,
        )
        for batch_idx, batch in enumerate(batches):
            try:
                batch_docs = await transformer.aconvert_to_graph_documents(batch)
                graph_documents.extend(batch_docs)
                log.info(
                    "graph_ingestion_node: batch %d/%d — extracted %d graph doc(s)",
                    batch_idx + 1,
                    len(batches),
                    len(batch_docs),
                )
            except BaseException as exc:
                # Catch BaseException (not just Exception) to handle ExceptionGroup
                # raised by asyncio.TaskGroup on Python 3.11+ when one concurrent
                # document call fails (e.g. Groq/Gemini 400). Log the actual
                # provider error body when available and skip the batch.
                _detail = ""
                _causes = getattr(exc, "exceptions", [exc])  # unwrap ExceptionGroup
                for _cause in _causes:
                    _response = getattr(_cause, "response", None)
                    if _response is not None:
                        try:
                            _detail = f" — {_response.json()}"
                        except Exception:
                            _detail = f" — {getattr(_response, 'text', '')}"
                        break
                log.warning(
                    "graph_ingestion_node: batch %d/%d raised %s%s — skipping batch",
                    batch_idx + 1,
                    len(batches),
                    exc,
                    _detail,
                )

        log.info(
            "graph_ingestion_node: extracted %d graph documents",
            len(graph_documents),
        )

        # KuzuGraph has two schema-staleness bugs when processing multiple documents:
        # 1. _create_entity_relationship_table uses CREATE REL TABLE (single FROM-TO).
        #    IF NOT EXISTS silently skips subsequent pairs → MERGE schema violation.
        # 2. The MENTIONS REL TABLE GROUP is seeded only from the first document's
        #    node labels. IF NOT EXISTS skips re-creation for later documents that
        #    introduce new node types → same MERGE schema violation.
        # Fix: subclass KuzuGraph to (a) pre-create all node/MENTIONS schema from
        # the full allowed_nodes list before add_graph_documents runs, and (b) use
        # REL TABLE GROUP + ALTER TABLE for entity-entity relationships so new
        # FROM-TO pairs can always be appended. See docs/Parsing Documents to
        # Z-Bundles.md § KùzuDB schema staleness pitfalls.
        class _MultiTypeKuzuGraph(KuzuGraph):
            def _pre_create_schema(self, allowed_node_labels: list[str]) -> None:
                """Pre-create all node tables and the MENTIONS group up front."""
                # Entity node tables
                for label in allowed_node_labels:
                    self.conn.execute(
                        f"CREATE NODE TABLE IF NOT EXISTS {label} "
                        f"(id STRING, type STRING, PRIMARY KEY (id))"
                    )
                # Chunk node table (mirrors _create_chunk_node_table)
                self.conn.execute(
                    "CREATE NODE TABLE IF NOT EXISTS Chunk "
                    "(id STRING, text STRING, type STRING, PRIMARY KEY (id))"
                )
                # MENTIONS REL TABLE GROUP covering every allowed node type.
                # Build and execute the full DDL the first time; for subsequent
                # calls (already exists) add any missing FROM-TO pairs.
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

            def _create_entity_relationship_table(self, rel) -> None:  # type: ignore[override]
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

        db = kuzu.Database(graph_path)
        graph = _MultiTypeKuzuGraph(db, allow_dangerous_requests=True)
        graph._pre_create_schema(allowed_nodes)
        # allowed_relationships for add_graph_documents must be List[Tuple[src, rel, tgt]].
        # KuzuGraph derives the actual schema dynamically per relationship, so
        # this parameter is required by the signature but not used in the body.
        rel_triplets = [
            (src, rel, tgt)
            for src in allowed_nodes
            for rel in allowed_relationships
            for tgt in allowed_nodes
        ]
        graph.add_graph_documents(graph_documents, rel_triplets, include_source=True)

        log.info("graph_ingestion_node: done")
        return {
            "status_message": "Property graph populated",
        }

    return graph_ingestion_node


def _make_fan_out_node(vector_node, graph_node):
    """Return a node that runs vector and graph ingestion concurrently."""

    @log_node("fan_out")
    async def fan_out_node(state: DocumentParsingState) -> dict:
        sem = asyncio.Semaphore(_FAN_OUT_CONCURRENCY)

        async def _run_with_sem(coro_fn):
            async with sem:
                return await coro_fn(state)

        await asyncio.gather(
            _run_with_sem(vector_node),
            _run_with_sem(graph_node),
        )

        return {
            "status": "complete",
            "status_message": "Document parsing complete",
        }

    return fan_out_node


# ------------------------------------------------------------------
# Routing
# ------------------------------------------------------------------


def _route_after_contextualizer(state: DocumentParsingState) -> str:
    """Loop back to contextualizer if more chunks remain, else fan out."""
    idx = state.get("current_chunk_index", 0)
    total = len(state.get("chunks", []))
    if idx < total:
        return "contextualizer"
    return "fan_out"


# ------------------------------------------------------------------
# Graph builder
# ------------------------------------------------------------------


def build_document_parsing_graph(
    contextualizer_connector: LlmConnector,
    graph_extractor_connector: LlmConnector,
    embedding_connector,
    config,
    contextualizer_model: str | None = None,
    graph_extractor_model: str | None = None,
):
    """Build and compile the document parsing LangGraph StateGraph.

    Parameters
    ----------
    contextualizer_connector:
        LLM connector for the Phase 1 contextualizer node.
    graph_extractor_connector:
        LLM connector for the Phase 2 graph extraction via LLMGraphTransformer.
    embedding_connector:
        Embedding connector for LanceDB vector ingestion.
    config:
        ZForgeConfig providing parsing_chunk_size, parsing_chunk_overlap,
        parsing_retrieval_chunk_size, and parsing_retrieval_chunk_overlap.
    contextualizer_model / graph_extractor_model:
        Optional model name overrides.
    """
    chunk_size = getattr(config, "parsing_chunk_size", 10000)
    chunk_overlap = getattr(config, "parsing_chunk_overlap", 500)
    retrieval_chunk_size = getattr(config, "parsing_retrieval_chunk_size", 500)
    retrieval_chunk_overlap = getattr(config, "parsing_retrieval_chunk_overlap", 50)

    vector_node_fn = _make_vector_ingestion_node(embedding_connector)
    graph_node_fn = _make_graph_ingestion_node(
        graph_extractor_connector, graph_extractor_model
    )

    graph = StateGraph(DocumentParsingState)

    graph.add_node("text_splitter", _make_text_splitter_node(chunk_size, chunk_overlap))
    graph.add_node(
        "contextualizer",
        _make_contextualizer_node(
            contextualizer_connector,
            contextualizer_model,
            retrieval_chunk_size=retrieval_chunk_size,
            retrieval_chunk_overlap=retrieval_chunk_overlap,
        ),
    )
    graph.add_node("fan_out", _make_fan_out_node(vector_node_fn, graph_node_fn))

    graph.set_entry_point("text_splitter")
    graph.add_edge("text_splitter", "contextualizer")
    graph.add_conditional_edges(
        "contextualizer",
        _route_after_contextualizer,
        {
            "contextualizer": "contextualizer",
            "fan_out": "fan_out",
        },
    )
    graph.add_edge("fan_out", END)

    return graph.compile()
