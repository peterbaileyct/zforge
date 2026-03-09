# Parsing Documents to Z-Bundles
Z-Forge has a standard [process](Processes.md) for extracting vector and graph data for a [Z-Bundle](RAG%20and%20GRAG%20Implementation.md) from free-text documents via [LLM](LLM%20Abstraction%20Layer.md). The basic process is to break the document into overlapping chunks and use an LLM to prepend the second through final chunks with "breadcrumbs" based on the prior chunk.

Input is always raw UTF-8 plain text.

This is a general pipeline. [World Generation](World%20Generation.md) is one specific instance of it; once this general spec is stable, the World Generation spec will reference it explicitly.

```mermaid
flowchart TD
    subgraph Agents
        A_ctx["Contextualizer\n(Google · gemini-2.5-flash-lite)"]
        A_gext["Graph Extractor\n(Google · gemini-2.5-flash-lite)"]
    end

    subgraph State
        S_input_text[/"input_text"/]
        S_chunks[/"chunks"/]
        S_documents[/"documents"/]
        S_chunk_idx[/"current_chunk_index"/]
    end

    subgraph Repositories
        R_vector[(LanceDB · chunks)]
        R_graph[(KuzuDB · property graph)]
    end

    subgraph Tools
        T_splitter[RecursiveCharacterTextSplitter]
        T_lancedb[LanceDB.from_documents] --> R_vector
        T_llmgt[LLMGraphTransformer]
        T_kuzu[KuzuGraph.add_graph_documents] --> R_graph
    end

    subgraph Process
        P_start(( )) --> P_splitter[Text Splitter]
        P_splitter --> P_contextualizer[Contextualizer]
        P_contextualizer -->|next chunk| P_contextualizer
        P_contextualizer --> P_vector_ingest[Vector Ingestion]
        P_contextualizer --> P_graph_ingest[Graph Ingestion]
        P_vector_ingest --> P_stop(( ))
        P_graph_ingest --> P_stop
    end

    P_splitter <-.-> S_input_text
    P_splitter <-.-> S_chunks
    P_splitter <-.-> T_splitter
    P_contextualizer <-.-> A_ctx
    P_contextualizer <-.-> S_chunk_idx
    P_contextualizer <-.-> S_documents
    P_vector_ingest <-.-> T_lancedb
    P_graph_ingest <-.-> A_gext
    P_graph_ingest <-.-> T_llmgt
    P_graph_ingest <-.-> T_kuzu
```

## Architectural Overview
A two-phase ETL process that transforms a plain-text document into a dual-layered storage system:

- **Vector Layer:** LanceDB (Semantic/Sensory Retrieval)
- **Graph Layer:** KuzuDB (Structural/Relational Retrieval)

Storage paths for both layers follow the Z-Bundle layout defined in [RAG and GRAG Implementation](RAG%20and%20GRAG%20Implementation.md#implementation).

## Phase 1: Sequential Contextualization

**Goal:** Process raw text into `Document` objects containing a "Rolling Context" breadcrumb to preserve narrative continuity across chunks.

### LLM Node: Contextualizer

Each LLM step in this pipeline is a configurable process node (see [Processes](Processes.md) and [LLM Abstraction Layer](LLM%20Abstraction%20Layer.md)). The **Contextualizer** node summarizes each chunk to generate a breadcrumb for the next chunk. Default: `gemini-2.5-flash-lite` (Google).

**Prompt template:**

> You are summarizing a passage from a source document. List the key named entities {allowed nodes, comma-delimited} and any significant facts, events, or status changes introduced in this passage. Be concise — your output will be prepended as context when processing the next passage.

### Implementation Details

- **Text Splitting:** `langchain_text_splitters.RecursiveCharacterTextSplitter`
  - Method: `split_text()` (returns a list of strings)
  - `chunk_size` and `chunk_overlap` are read from application configuration (see [Application Configuration](Application%20Configuration.md#parsing-pipeline)); defaults are **10,000 characters** and **500 characters** respectively.
- **Stateful Loop:** Iterate through chunks sequentially.
- **Object Creation:** Instantiate `langchain_core.documents.Document`
  - `page_content`: the current chunk text
  - `metadata`: dictionary containing the Contextualizer's summary from the *previous* iteration (the "Breadcrumb"); empty for the first chunk.

## Phase 2: Parallel Ingestion (The "Fan-out")

**Goal:** Concurrently populate both databases using the enriched `Document` list from Phase 1.

### A. Vector Ingestion (LanceDB)

- **Class:** `langchain_community.vectorstores.LanceDB`
- **Method:** `from_documents`
- **Params:** `documents` (list), `embedding` (configured embedding model), `connection` (LanceDB connection), `table_name="chunks"` (canonical table name per [RAG and GRAG Implementation](RAG%20and%20GRAG%20Implementation.md#implementation))
- **Note:** The embedding model used here must be recorded in the Z-Bundle's KVP store (`embedding_model_name`, `embedding_model_size_bytes`) and must match the model used at query time.

### B. Graph Ingestion (KuzuDB)

#### LLM Node: Graph Extractor

The **Graph Extractor** node drives `LLMGraphTransformer`. Default: `gemini-2.5-flash-lite` (Google).

- **Extraction Class:** `langchain_experimental.graph_transformers.LLMGraphTransformer`
  - **Method:** `convert_to_graph_documents`
  - **Params:** the list of `Document` objects from Phase 1
  - **Config:** `allowed_nodes` and `allowed_relationships` are specified by the calling process (e.g., World Generation's world-building schema); they are not defined in this general pipeline spec.
- **Storage Class:** `langchain_community.graphs.KuzuGraph`
  - **Method:** `add_graph_documents`
  - **Params:** `graph_documents` (output from transformer), `include_source=True`
  - `include_source=True` causes a `Document` node to be created in Kuzu for each source text chunk, with edges from every extracted graph node back to its source chunk. This enables hybrid lookups: given any graph node you can always retrieve the original passage it was extracted from.

## Parallelization Strategy

To manage concurrency and rate limits:

- Wrap the LanceDB write and KuzuDB extraction/write in `asyncio.gather` for concurrent execution.
- Gate concurrency with a `Semaphore(value=N)`, where N is configurable (e.g. 5–10 for Gemini Flash Lite), to avoid HTTP 429 rate-limit errors.

## Summary of Key LangChain Components

| Component | Class | Primary Method |
|---|---|---|
| Splitter | `RecursiveCharacterTextSplitter` | `split_text` |
| Data Container | `Document` | `__init__(page_content, metadata)` |
| Graph Transformer | `LLMGraphTransformer` | `convert_to_graph_documents` |
| Graph Store | `KuzuGraph` | `add_graph_documents` |
| Vector Store | `LanceDB` | `from_documents` |

## Implementation

- **Process slug:** `document_parsing`
- **Implementation file:** `src/zforge/graphs/document_parsing_graph.py` (new file)
- **LLM nodes** (defined in `process_config.py`):
  - `contextualizer` — Phase 1 breadcrumb generation; default `Google` / `gemini-2.5-flash-lite`
  - `graph_extractor` — Phase 2 graph extraction via `LLMGraphTransformer`; default `Google` / `gemini-2.5-flash-lite`
- **Chunk size defaults:** `parsing_chunk_size = 10000`, `parsing_chunk_overlap = 500`; stored in `ZForgeConfig` and read by the pipeline at runtime. (These are the defaults used at the code level; the chunk size is not yet user-configurable — see [User Experience](User%20Experience.md) for the planned TODO.)
- `allowed_nodes` and `allowed_relationships` for `LLMGraphTransformer` are not defined here; they are specified by the caller (e.g., World Generation).
- **`DocumentParsingState`** (in `src/zforge/graphs/state.py`) — Add a new TypedDict for this process:
  ```python
  class DocumentParsingState(TypedDict):
      input_text: str                   # Raw source text
      z_bundle_root: str                # Z-Bundle root path (target for LanceDB + KuzuDB)
      allowed_nodes: list[str]          # Passed from caller (e.g. World Generation)
      allowed_relationships: list[str]  # Passed from caller
      chunks: list[str]                 # Split text chunks (set by Text Splitter node)
      documents: list                   # LangChain Document objects with breadcrumbs (set by Contextualizer)
      current_chunk_index: Annotated[int, operator.add]  # Phase 1 loop counter
      status: str
      status_message: str
  ```

### Async nodes required — AFC deadlock pitfall

**Pitfall:** All LLM-calling nodes (`contextualizer`, `graph_ingestion`, `fan_out`) **must** be `async def` and use the async model API (`model.ainvoke()`, `transformer.aconvert_to_graph_documents()`). Do **not** call the synchronous equivalents from inside the graph.

**Why it occurs:** The parent graph is consumed via `graph.astream()` (see `ZForgeManager.run_process`). LangGraph runs synchronous nodes in a thread-pool executor to avoid blocking the event loop. The `google-genai` SDK (v1+, underpinning `ChatGoogleGenerativeAI` for Gemini 2.5 models) enables AFC (Automatic Function Calling) and manages async HTTP internally. When `model.invoke()` is called from inside a thread-pool thread, the SDK attempts to schedule async coroutines on an event loop. If the SDK tries to call `asyncio.get_running_loop()` or `asyncio.run()` from within a thread whose loop state is entangled with the parent asyncio event loop, the call hangs indefinitely with no error — the only visible symptom is the log line `AFC is enabled with max remote calls: 10` from `google_genai.models` followed by silence.

**Correct pattern:** Declare nodes as `async def` and use `await model.ainvoke(...)` / `await transformer.aconvert_to_graph_documents(...)`. LangGraph's async runner then awaits them directly on the event loop rather than offloading to a thread, eliminating the deadlock. For nodes that call sync I/O, keep the calls inline inside the async function body — do **not** use `asyncio.to_thread` for any node that loads or runs a local llama.cpp model (see the Metal pitfall below).

### macOS Metal + local embedding models — single-thread executor required

**Pitfall:** Local embedding nodes (those using llama.cpp via `LlamaCppEmbeddingConnector`) cannot safely run either (a) synchronously on the event loop thread, or (b) via `asyncio.to_thread` / a general thread pool:

- **On the event loop thread (async def, no offloading):** llama.cpp model loading and inference are CPU-intensive and block the event loop entirely, freezing the Toga UI for minutes with no feedback.
- **Via `asyncio.to_thread` or a general `ThreadPoolExecutor`:** `ggml_metal` (the GPU backend for llama.cpp on macOS) binds its Metal command queue to the OS thread on which the model is *first loaded*. A general thread pool may dispatch subsequent calls to a different thread, causing Metal to silently hang with no error or timeout.

**Correct pattern:** Use a **module-level `ThreadPoolExecutor(max_workers=1)`** (named `_LLAMA_EXECUTOR`). All embedding computation is dispatched to this executor via `await loop.run_in_executor(_LLAMA_EXECUTOR, fn)`. Because the executor has exactly one worker thread, every call is guaranteed to land on the same OS thread, satisfying Metal's thread-affinity requirement while releasing the event loop so the UI stays responsive. `_LLAMA_EXECUTOR` is defined in `document_parsing_graph.py` and imported by `world_creation_graph.py` for use in `retrieve_vector`.

### `lancedb.connect()` deadlocks in any asyncio context

**Pitfall:** `lancedb.connect()` (the synchronous wrapper) bridges async work onto LanceDB's own internal background event loop via `asyncio.run_coroutine_threadsafe` + `future.result()`. The Rust/PyO3 internals that power the actual connection attempt to attach their futures to `asyncio.get_event_loop()` of the calling thread. When called from *any* thread that has an asyncio event loop reference — either the event loop thread itself, or a thread-pool thread spawned from an asyncio context — the internal future gets attached to a *different* loop than the one running `do_connect`. This raises: `RuntimeError: Task got Future attached to a different loop`.

This affects both the write path (`LanceDBVectorStore.from_documents`) and the read path (`lancedb.connect()` in retriever tools).

**Correct pattern:** Always use `await lancedb.connect_async(path)` from within async functions. Then use the native `AsyncTable` API for reads and writes. Only the embedding computation (the llama.cpp call) goes to `_LLAMA_EXECUTOR`; the LanceDB connection and table operations are awaited directly on the event loop.

### KuzuGraph requires `allow_dangerous_requests=True`

**Pitfall:** Constructing `KuzuGraph(db)` without `allow_dangerous_requests=True` raises an error at runtime.

**Correct pattern:** Always construct as `KuzuGraph(db, allow_dangerous_requests=True)`. This applies wherever `KuzuGraph` is instantiated — both in `graph_ingestion_node` (write path) and `retrieve_graph` (read path in the summarizer tool).

### `KuzuGraph.add_graph_documents` requires `allowed_relationships` as triplets

**Pitfall:** `KuzuGraph.add_graph_documents` has the signature `(graph_documents, allowed_relationships, include_source=False)` — `allowed_relationships` is a **required positional parameter** of type `List[Tuple[str, str, str]]` (source node type, relationship type, target node type). Calling it without this argument, or passing keyword-only, raises a `TypeError`.

**Note:** In the current version of `langchain-community`, this parameter is accepted but not actually executed against — the schema is created dynamically per relationship via `_create_entity_relationship_table`. A full Cartesian product of `allowed_nodes × allowed_relationships × allowed_nodes` satisfies the signature and is future-proof if the implementation starts using it.

### KùzuDB `REL TABLE` single-pair schema violation

Two related pitfalls arise from `KuzuGraph`'s lazy, per-document schema creation when `add_graph_documents` is called across multiple documents:

**Pitfall 1 — Entity relationship tables:** `_create_entity_relationship_table` issues `CREATE REL TABLE IF NOT EXISTS {name} (FROM {src} TO {tgt})` — a **single** FROM-TO pair. When the same relationship type is extracted between different node type pairs across documents, `IF NOT EXISTS` silently skips later DDL. The `MERGE` then raises a Binder exception: *"Query node eN violates schema. Expected labels are X."*

**Pitfall 2 — MENTIONS table:** The `MENTIONS` REL TABLE GROUP is seeded with only the node labels found in the *first* document. For subsequent documents, `CREATE REL TABLE GROUP IF NOT EXISTS MENTIONS (...)` skips re-creation, so new entity types introduced in later chunks are never added. The same Binder exception occurs when merging MENTIONS edges for those new types.

**Correct pattern:** Subclass `KuzuGraph` and (a) add a `_pre_create_schema` method that creates all node tables and the full `MENTIONS` group from the complete `allowed_nodes` list *before* calling `add_graph_documents`, and (b) override `_create_entity_relationship_table` to use `CREATE REL TABLE GROUP` and `ALTER TABLE ADD FROM ... TO ...`:

```python
class _MultiTypeKuzuGraph(KuzuGraph):
    def _pre_create_schema(self, allowed_node_labels: list[str]) -> None:
        for label in allowed_node_labels:
            self.conn.execute(
                f"CREATE NODE TABLE IF NOT EXISTS {label} "
                f"(id STRING, type STRING, PRIMARY KEY (id))"
            )
        self.conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS Chunk "
            "(id STRING, text STRING, type STRING, PRIMARY KEY (id))"
        )
        from_to_pairs = ", ".join(f"FROM Chunk TO {lbl}" for lbl in allowed_node_labels)
        try:
            self.conn.execute(
                f"CREATE REL TABLE GROUP MENTIONS "
                f"({from_to_pairs}, label STRING, triplet_source_id STRING)"
            )
        except Exception:
            for label in allowed_node_labels:
                try:
                    self.conn.execute(f"ALTER TABLE MENTIONS ADD FROM Chunk TO {label}")
                except Exception:
                    pass  # Pair already registered.

    def _create_entity_relationship_table(self, rel) -> None:
        src, rel_type, tgt = rel.source.type, rel.type, rel.target.type
        try:
            self.conn.execute(f"CREATE REL TABLE GROUP {rel_type} (FROM {src} TO {tgt})")
        except Exception:
            try:
                self.conn.execute(f"ALTER TABLE {rel_type} ADD FROM {src} TO {tgt}")
            except Exception:
                pass  # Pair already registered.
```

Call `graph._pre_create_schema(allowed_nodes)` immediately after constructing the instance, before `add_graph_documents`.