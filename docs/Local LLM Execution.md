# Local LLM Execution

Z-Forge runs **all LLM inference on-device** using local GGUF models. There is no cloud LLM path — no OpenAI, Anthropic, or other hosted provider is used or supported. Local execution covers both **chat inference** (graph agent nodes) and **embedding generation** (Z-Bundle encoding).

## Use Cases

- **Chat inference**: The sole LLM inference path for all LangGraph agent nodes. `LlamaCppConnector` is the only supported `LlmConnector` implementation.
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
