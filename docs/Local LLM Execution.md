# Local LLM Execution

Z-Forge supports running GGUF-based inference locally as an optional offline path alongside the remote connectors described in [LLM Abstraction Layer](LLM%20Abstraction%20Layer.md). The world generation process defaults to the remote `gpt-5-nano` model, but local connectors remain available when the user explicitly selects an on-device model (for offline, privacy-sensitive, or low-latency scenarios). This document describes those local connectors and their role in chat inference and embedding generation.

## Use Cases

- **Chat inference**: `LlamaCppConnector` can run LangGraph agent nodes whenever the configuration selects an on-device provider; remote connectors described in [LLM Abstraction Layer](LLM%20Abstraction%20Layer.md) are also available when connectivity and policy permit.
- **Embedding generation**: Converting entity text chunks to vector embeddings during Z-Bundle encoding (required by [World Generation](World%20Generation.md) and any future process that encodes a Z-Bundle).

## Connector Abstraction

### Chat: `LlmConnector` and `LlamaCppConnector`

`LlmConnector` is an abstract connector for chat inference. It defines:

- A display name for the connector
- A list of required configuration keys (empty for local GGUF connectors — no credentials needed)
- A validation method that returns true if the connector is fully configured and usable
- A method that returns a LangChain `BaseChatModel` ready for use in a graph agent node

`LlamaCppConnector` implements `LlmConnector` using a local GGUF model file. It has no required API keys; its validation checks that the configured model file exists on disk. It is selected via config in the same way as any other `LlmConnector` implementation.

### Embedding: `EmbeddingConnector` and `LlamaCppEmbeddingConnector`

`EmbeddingConnector` is an abstract connector for embedding generation, parallel in structure to `LlmConnector`. It defines:

- A validation method that returns true if the connector is fully configured and usable
- A method that returns a LangChain `Embeddings` instance

`LlamaCppEmbeddingConnector` is the sole initial implementation, backed by a local GGUF embedding model file.

The `EmbeddingConnector` is injected wherever Z-Bundle encoding occurs, keeping graph and encoding code independent of the backend.

## Model Catalogue

Z-Forge ships with a curated catalogue of supported GGUF models. Each entry records a display name, Hugging Face repo, filename, approximate download size, and role (chat or embedding).

| Role | Display Name | HF Repo | Filename | Size |
|---|---|---|---|---|
| Chat | DeepSeek R1 Distill 1.5B (default) | `bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF` | `DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf` | ~1 GB |
| Chat | DeepSeek R1 Distill 7B | `bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF` | `DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf` | ~4.4 GB |
| Embedding | Nomic Embed Text 1.5 | `nomic-ai/nomic-embed-text-v1.5-GGUF` | `nomic-embed-text-v1.5.Q4_K_M.gguf` | ~90 MB |

The 1.5B chat model is the default selection. The embedding model has no alternative; it is always downloaded automatically alongside whichever chat model is chosen.

Hugging Face CDN download URLs follow the form:
```
https://huggingface.co/{owner}/{repo}/resolve/main/{filename}
```

## Model Configuration

Each model (chat and embedding) is configured separately. The configuration specifies:

- **Model file path** — relative path within sandboxed storage (see [File Storage](File%20Storage.md)); always under `models/`
- **Context window size** — number of tokens
- **GPU layer offload count** — number of transformer layers to offload to GPU/Metal (0 = CPU only)

Default values for context size and GPU offload are defined in config; the user may override them via the LLM configuration screen.

## Model Acquisition

Z-Forge downloads models on first run via the LLM Configuration screen (see [User Experience](User%20Experience.md)). The user selects from the model catalogue; Z-Forge downloads the chosen chat model and the embedding model from Hugging Face and saves both to `models/` in sandboxed storage. No manual file placement is required.

## Model Availability

On startup (and before any operation requiring a local model), Z-Forge checks that the configured GGUF file exists at the specified path. If it does not:

- For **chat**: The UI shows the LLM Configuration screen (model picker + download).
- For **embedding**: World Generation (and any other Z-Bundle encoding process) cannot proceed. The UI surfaces an error directing the user to the LLM Configuration screen.

## Wiring

### EmbeddingConnector injection

`EmbeddingConnector` is a concern of persistence, not of the LangGraph graph. It is injected into `ZWorldManager` at construction time in `app.py`, alongside the other manager dependencies:

```python
embedding_connector = LlamaCppEmbeddingConnector()
# ...configure from config/secure config...
zworld_manager = ZWorldManager(config.bundles_root, embedding_connector)
```

`ZWorldManager.create()` is then responsible for the full Z-Bundle encoding pipeline — embedding each chunk and writing all three stores (KVP, vector, property graph). The graph and tool layer hand structured data to the tool; the tool calls the manager; the manager handles encoding. No embedding-related arguments are added to the graph or tool signatures.

### Availability check

`app.py` calls `embedding_connector.validate()` at startup alongside `llm_connector.validate()`. If either connector is not valid (GGUF file missing or unconfigured), the UI shows the LLM Configuration screen before the home screen is displayed.

`AppState` holds a reference to the `EmbeddingConnector` so that screens can check its validity when deciding whether to enable world creation controls.

### Model identity and mismatch

When a Z-Bundle is encoded, the basename and file size (in bytes) of the GGUF embedding model file are written to the bundle's KVP store (see the Z-Bundle type spec, e.g. [Z-World](Z-World.md)). Together these form the **model identity** for that bundle.

When a Z-Bundle is loaded for use in experience generation, the stored model identity is compared against the currently configured embedding model. If they differ, the application surfaces a **non-blocking warning** — the user may knowingly be on an upgraded model and can choose to proceed. Search quality may be degraded until the bundle is re-encoded.

Re-encoding (running world generation again on the same input to rebuild the Z-Bundle with the current model) is a supported operation and overwrites the existing bundle.

## Implementation

- Chat backend: `llama-cpp-python` via LangChain's `LlamaCpp` chat model class
- Embedding backend: `llama-cpp-python` via LangChain's `LlamaCppEmbeddings` class
- Both require the `llama-cpp-python` package; a single installation covers both use cases
- `LlamaCppConnector` lives in `src/zforge/services/llm/`
- `EmbeddingConnector` (ABC) and `LlamaCppEmbeddingConnector` live in `src/zforge/services/embedding/`
- Model catalogue is a static data structure in `src/zforge/models/model_catalogue.py` — a list of `ModelCatalogueEntry` dataclasses with fields: `role` (chat/embedding), `display_name`, `hf_repo`, `filename`, `size_bytes_approx`, `is_default`
- Download logic lives in `src/zforge/services/model_download_service.py`. It streams the HF CDN URL with `httpx` (async) and writes to `{user_data_dir}/models/{filename}`, reporting byte progress via a callback so the UI can update a progress bar. No auth token is required for these public models.

### Pitfall: `LlamaCppEmbeddings.embed_documents()` batch crash

`LlamaCppEmbeddings.embed_documents(texts)` submits the entire list as a single llama-cpp batch decode. When the number of texts exceeds the context's internal sequence-slot limit, llama-cpp raises:

```
decode: cannot decode batches with this context (calling encode() instead)
init: invalid seq_id[N][0] = 1 >= 1
encode: failed to initialize batch
llama_decode: failed to decode, ret = -1
```

**Correct pattern:** call `embed_query(text)` in a loop — one text at a time. This is safe regardless of entity count:

```python
vectors = [embeddings_model.embed_query(t) for t in texts]
```

Never call `embed_documents(texts)` with a non-trivial list against a local llama-cpp embedding model. The limit is context-slot-count – 1 (often as few as 1 usable slot for embedding contexts), so even small worlds will fail.

### Pitfall: Cloud LLM wrappers block on construction — defer `get_model()` to first invocation

`langchain-google-genai`'s `ChatGoogleGenerativeAI()` (and equivalent LangChain wrappers for other cloud providers) may make a network call during `__init__` to validate the model or fetch endpoint metadata. When a node factory calls `get_model()` eagerly — at LangGraph **graph-build time** — this call blocks the asyncio event loop: no graph nodes ever run and the UI freezes with no further log output.

**Correct pattern:** defer `get_model()` to the first node invocation using a closure cache:

```python
def _make_my_node(connector, model_name):
    _model_cache: list = []
    def node(state):
        if not _model_cache:
            _model_cache.append(connector.get_model(model_name))
        model = _model_cache[0]
        ...
    return node
```

Never call `get_model()` (or any connector method that instantiates a cloud LLM) at node-factory time — only at node-execution time.
