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
    def contextualizer_node(state: DocumentParsingState) -> dict:
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
        response = model.invoke(
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
    def vector_ingestion_node(state: DocumentParsingState) -> dict:
        import lancedb
        from langchain_community.vectorstores import LanceDB as LanceDBVectorStore

        documents = state["documents"]
        z_bundle_root = state["z_bundle_root"]
        vector_path = f"{z_bundle_root}/vector"

        log.info(
            "vector_ingestion_node: writing %d documents to %s",
            len(documents),
            vector_path,
        )

        embeddings = embedding_connector.get_embeddings()
        db = lancedb.connect(vector_path)
        LanceDBVectorStore.from_documents(
            documents,
            embeddings,
            connection=db,
            table_name="chunks",
        )

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
    def graph_ingestion_node(state: DocumentParsingState) -> dict:
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
        graph_documents = transformer.convert_to_graph_documents(documents)

        log.info(
            "graph_ingestion_node: extracted %d graph documents",
            len(graph_documents),
        )

        db = kuzu.Database(graph_path)
        graph = KuzuGraph(db)
        graph.add_graph_documents(graph_documents, include_source=True)

        log.info("graph_ingestion_node: done")
        return {
            "status_message": "Property graph populated",
        }

    return graph_ingestion_node


def _make_fan_out_node(vector_node, graph_node):
    """Return a node that runs vector and graph ingestion concurrently."""

    @log_node("fan_out")
    def fan_out_node(state: DocumentParsingState) -> dict:
        sem = asyncio.Semaphore(_FAN_OUT_CONCURRENCY)

        async def _run_with_sem(fn):
            async with sem:
                return await asyncio.get_event_loop().run_in_executor(None, fn, state)

        async def _gather():
            return await asyncio.gather(
                _run_with_sem(vector_node),
                _run_with_sem(graph_node),
            )

        # Use existing loop if available, otherwise create one
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(vector_node, state)
                f2 = pool.submit(graph_node, state)
                f1.result()
                f2.result()
        except RuntimeError:
            asyncio.run(_gather())

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
