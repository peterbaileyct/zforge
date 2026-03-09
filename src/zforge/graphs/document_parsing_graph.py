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
            "current_chunk_index": 0,
            "status": "contextualizing",
            "status_message": f"Split text into {len(chunks)} chunk(s)",
        }

    return text_splitter_node


def _make_contextualizer_node(
    llm_connector: LlmConnector, model_name: str | None = None
):
    """Return a node that contextualizes the current chunk."""

    _model_cache: list = []

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
        response = await model.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=human_content)]
        )
        summary = str(getattr(response, "content", ""))

        # Create a Document with the chunk text and breadcrumb metadata
        doc = Document(
            page_content=chunk,
            metadata={"breadcrumb": summary},
        )
        documents.append(doc)

        return {
            "documents": documents,
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

        log.info(
            "vector_ingestion_node: writing %d documents to %s",
            len(documents),
            vector_path,
        )

        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]

        # Compute embeddings on the dedicated llama thread so the event loop
        # stays free and Metal always runs on the same OS thread.
        loop = asyncio.get_running_loop()
        embedder = embedding_connector.get_embeddings()
        vectors = await loop.run_in_executor(
            _LLAMA_EXECUTOR,
            lambda: embedder.embed_documents(texts),
        )

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

        log.info(
            "graph_ingestion_node: extracting graph from %d documents",
            len(documents),
        )

        transformer = LLMGraphTransformer(
            llm=model,
            allowed_nodes=allowed_nodes,
            allowed_relationships=allowed_relationships,
        )
        graph_documents = await transformer.aconvert_to_graph_documents(documents)

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
        ZForgeConfig providing parsing_chunk_size and parsing_chunk_overlap.
    contextualizer_model / graph_extractor_model:
        Optional model name overrides.
    """
    chunk_size = getattr(config, "parsing_chunk_size", 10000)
    chunk_overlap = getattr(config, "parsing_chunk_overlap", 500)

    vector_node_fn = _make_vector_ingestion_node(embedding_connector)
    graph_node_fn = _make_graph_ingestion_node(
        graph_extractor_connector, graph_extractor_model
    )

    graph = StateGraph(DocumentParsingState)

    graph.add_node("text_splitter", _make_text_splitter_node(chunk_size, chunk_overlap))
    graph.add_node(
        "contextualizer",
        _make_contextualizer_node(contextualizer_connector, contextualizer_model),
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
