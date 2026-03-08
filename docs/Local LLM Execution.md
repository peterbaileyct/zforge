# Local LLM Execution

Z-Forge supports local (on-device) LLM execution for both **chat inference** and **embedding generation**. Local chat is used as an alternative to cloud LLM providers for graph agent nodes. Local embedding is used during Z-Bundle encoding and is always local — there is no cloud embedding path.

## Use Cases

- **Chat inference**: Drop-in alternative to cloud providers (e.g., OpenAI) for any LangGraph agent node. Selected via config in the same way as any other `LlmConnector`.
- **Embedding generation**: Converting entity text chunks to vector embeddings during Z-Bundle encoding (required by [World Generation](World%20Generation.md) and any future process that encodes a Z-Bundle).

## Connector Abstraction

### Chat: `LlmConnector` and `LlamaCppConnector`

`LlmConnector` is an abstract connector for chat inference. It defines:

- A display name for the connector
- A list of required configuration keys (e.g., API key for cloud providers; empty for local)
- A validation method that returns true if the connector is fully configured and usable
- A method that returns a LangChain `BaseChatModel` ready for use in a graph agent node

`LlamaCppConnector` implements `LlmConnector` using a local GGUF model file. It has no required API keys; its validation checks that the configured model file exists on disk. It is selected via config in the same way as any other `LlmConnector` implementation.

### Embedding: `EmbeddingConnector` and `LlamaCppEmbeddingConnector`

`EmbeddingConnector` is an abstract connector for embedding generation, parallel in structure to `LlmConnector`. It defines:

- A validation method that returns true if the connector is fully configured and usable
- A method that returns a LangChain `Embeddings` instance

`LlamaCppEmbeddingConnector` is the sole initial implementation, backed by a local GGUF embedding model file.

The `EmbeddingConnector` is injected wherever Z-Bundle encoding occurs, keeping graph and encoding code independent of the backend.

## Model Configuration

Each model (chat and embedding) is configured separately. The configuration specifies:

- **Model file path** — path to the GGUF file, relative to platform-specific sandboxed storage (see [File Storage](File%20Storage.md))
- **Context window size** — number of tokens
- **GPU layer offload count** — number of transformer layers to offload to GPU/Metal (0 = CPU only)

Default values for context size and GPU offload are defined in config; the user may override them.

## Model Availability

On startup (and before any operation requiring a local model), Z-Forge checks that the configured GGUF file exists at the specified path. If it does not:

- For **chat**: The local connector is treated as unconfigured, the same as a cloud connector with a missing API key. The UI surfaces a configuration prompt.
- For **embedding**: World Generation (and any other Z-Bundle encoding process) cannot proceed. The UI surfaces an error with guidance to configure a model path.

Z-Forge does not download models. The user is responsible for obtaining GGUF files and placing them at the configured path.

## Wiring

### EmbeddingConnector injection

`EmbeddingConnector` is a concern of persistence, not of the LangGraph graph. It is injected into `ZWorldManager` at construction time in `app.py`, alongside the other manager dependencies:

```python
embedding_connector = LlamaCppEmbeddingConnector()
# ...configure from config/secure config...
zworld_manager = ZWorldManager(config.zworld_folder, embedding_connector)
```

`ZWorldManager.create()` is then responsible for the full Z-Bundle encoding pipeline — embedding each chunk and writing all three stores (KVP, vector, property graph). The graph and tool layer hand structured data to the tool; the tool calls the manager; the manager handles encoding. No embedding-related arguments are added to the graph or tool signatures.

### Availability check

`app.py` calls `embedding_connector.validate()` at startup alongside `llm_connector.validate()`. If the embedding connector is not valid (GGUF file missing or unconfigured), the world creation entry point in the UI is disabled with a message directing the user to configure an embedding model path. This mirrors the way a missing LLM API key disables generation features.

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
- `EmbeddingConnector` (ABC) and `LlamaCppEmbeddingConnector` live in a new `src/zforge/services/embedding/` module
