# LLM Abstraction Layer
To maximize configurability and allow for expansion, an abstraction layer exists between the main Z-Forge engine and any LLM invocation, to allow selection between different LLM's for different features, and with an eye toward adding (in a future version) image generation and runtime LLM invocation for infinite dialog, narration, and even hints.

## Configurability
No LLM call is hard-coded; instead, LLMs are always invoked through [Processes](Processes.md). To allow for this abstraction and configuration, the state machine implementing a Process must be built with reference to the application configuration, with default values specified in the spec file for that process and in the code at compile time. Each LLM call node uses a specific provider and a specific model. Providers may be [local](Local%20LLM%20Execution.md) or online.

World Generation targets the remote `gpt-5-nano` model by default, deferring to user-specified provider/model pairs whenever they are explicitly set.

## Configuration
The LLM connector defines an arbitrary set of key/value pairs, which in practice are almost always in string format, but specific value types e.g. integer and GUID are allowed. This is often as little as an API Key, which is an unformatted string. The LLM connector also specifies the name of the LLM/connector.

## Abstraction
Each LLM connector, corresponding to a specific LLM provider, defines the following operations:

## Operations
- Get LLM connector name
- Get list of configuration keys and types
- Get list of available models
- Set configuration from secure storage, given a secure storage wrapper
- Validate existing configuration e.g. by connecting to LLM service
- `get_model(model_name: str | None) -> BaseChatModel` — returns a configured LangChain `BaseChatModel` instance for the given model (or the connector's default when `None`). Graph nodes are responsible for constructing messages and invoking the model directly. Two patterns are used:
  - **Plain-text routing** (e.g. World Creation): the node calls `model.invoke([SystemMessage(...), HumanMessage(...)])` and parses the text response; routing decisions are made by conditional edge functions that inspect graph state.
  - **Tool-call routing** (e.g. Experience Generation): the node calls `model.bind_tools(tools).invoke(messages)`; a `ToolNode` executes the selected tool and its return value drives graph state transitions. This pattern is used when the LLM should select among named actions.


  ## Implementation

  ### Integration with LangGraph
  Connectors integrate with LangGraph by returning a LangChain `BaseChatModel` via `get_model()`. Graph nodes hold a reference to the connector and call `get_model()` lazily (on first invocation) so that graph construction does not trigger network calls.

  - For plain-text routing nodes, the node calls `model.invoke(messages)` and a conditional edge function reads graph state to decide the next node.
  - For tool-call routing nodes (agentic RAG), the node calls `model.bind_tools(tools).invoke(messages)` and iterates `response.tool_calls` directly via the Processes.md self-loop pattern (e.g. World Generation Summarizer). Tool functions are invoked inline and `ToolMessage`s are appended manually — no `ToolNode` is used.
  - Chunk parallelism in World Creation is currently implemented with `ThreadPoolExecutor` inside a single graph node. The LangGraph-native alternative is the [Send API](https://langchain-ai.github.io/langgraph/concepts/low_level/#send) (fan-out / map-reduce), which would make parallelism visible to the LangGraph runtime. This is a candidate future refactor.

  ### APIs
  Connectors are provided for the following API's:
  - OpenAI
  - Google
  - Anthropic
  Each one only needs an API key specified for that vendor, which must be stored in platform-specific secure storage.
  Each should be implemented with a package, if possible, rather than direct HTTP requests.
  Each one, if the provider allows for it, should call an API to get a list of model names the first time that this list is requested on each run of the application. For vendors that do not provide such an API, the list should be hard-coded based on available models at compile time (when the connector is created or updated).

  **OpenAI model list (implementation note):** The `openai` Python SDK exposes `openai.OpenAI(api_key=...).models.list()`, which returns _all_ models including non-chat types (image, audio, TTS, realtime, moderation, embeddings, Codex, Sora, etc.). The connector must filter this list to text-chat-completion models only. The current filter rule: include model IDs that start with `gpt-` or with `o` followed by a digit, and exclude any ID containing: `tts`, `transcribe`, `audio`, `realtime`, `image`, `search`, `moderation`, `embedding`, `dall-e`, `whisper`, `sora`, `babbage`, `davinci`, `codex`, `deep-research`, `computer-use`, `oss`, `chat-latest`. This fetch is performed synchronously and cached per process run; if the key is absent or the call fails, the hardcoded fallback list is used. The cached list is invalidated when the API key changes (e.g. via `set_api_key()`). Fallback list (as of March 2026): `gpt-5.4`, `gpt-5.4-pro`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5`, `gpt-4.1`, `gpt-4o`, `gpt-4o-mini`.

  ### Local Execution
  Local connectors provide an offline option (chat inference and embeddings) when a GGUF model is configured. The list of models is based on the GGUF files that have been downloaded.
