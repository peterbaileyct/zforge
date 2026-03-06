# LLM Abstraction Layer
To maximize configurability and allow for expansion, an abstraction layer exists between the main Z-Forge engine and any LLMs used for procedural generation. We call this the "LLM Connector". This is implemented as a Python abstract base class (`LlmConnector`) that wraps a [LangChain](https://python.langchain.com/) chat model, allowing a new LLM to be easily swapped in. LangGraph uses this connector to drive all multi-step orchestration.

## Framework: LangChain + LangGraph

Z-Forge uses **LangGraph** for all multi-step LLM orchestration (world creation, experience generation). LangGraph is built on LangChain and provides:
- Stateful agent graphs with typed state (via Python `TypedDict`)
- Native tool calling and `ToolNode` dispatch
- Conditional edges for decision branching (approve/reject loops)
- Checkpointing and state persistence

The `LlmConnector` abstraction wraps a LangChain `BaseChatModel` (e.g., `ChatOpenAI`, `ChatAnthropic`). LangGraph graphs are bound to a connector instance, and tool calling is handled natively by the graph's `ToolNode` — no custom dispatch layer is needed.

## Secure Credential Storage

LLM credentials (e.g., API keys) are stored using the Python [`keyring`](https://pypi.org/project/keyring/) library, which delegates to the platform's native secret store:

| Platform | Backend |
|---|---|
| **macOS** | macOS Keychain |
| **Windows** | Windows Credential Locker |
| **Linux** | Secret Service (libsecret/KWallet) |
| **Web** | In-memory only (credentials re-entered each session); `keyring` not applicable |

Any agent implementing or modifying credential storage must use `keyring.set_password` / `keyring.get_password` with a consistent service name (e.g., `"zforge"`). Do not write credentials to disk in plain text.

## Configuration

The `LlmConnector` defines an arbitrary set of key/value configuration pairs (almost always strings, e.g., an API key). It also specifies the display name of the LLM/connector.

A concrete connector implementation (e.g., `OpenAiConnector`) declares:
- Its required configuration keys and their types
- How to load values from `keyring`
- A `validate()` method that makes a lightweight API call to confirm credentials are valid

## Operations (Python ABC)

```python
from abc import ABC, abstractmethod
from langchain_core.language_models import BaseChatModel

class LlmConnector(ABC):
    @abstractmethod
    def get_name(self) -> str:
        """Display name of this connector (e.g., 'OpenAI')."""

    @abstractmethod
    def get_config_keys(self) -> list[str]:
        """Names of required configuration values (e.g., ['api_key'])."""

    @abstractmethod
    def load_from_keyring(self) -> None:
        """Load credentials from keyring into connector state."""

    @abstractmethod
    def validate(self) -> bool:
        """Return True if credentials are present and valid."""

    @abstractmethod
    def get_model(self) -> BaseChatModel:
        """Return a configured LangChain chat model instance."""
```

The LangGraph orchestration layer calls `get_model()` to obtain a `BaseChatModel` that is then bound to tools via `.bind_tools(tools)` and incorporated into the graph.

### Conversation Model

Each LangGraph node invocation is stateless with respect to history: the graph state carries all relevant artifacts (ZWorld, Outline, Script, etc.) and the node constructs a fresh `SystemMessage` from that state before calling the model. This means:
- Agents are not aware of retry iterations; the graph handles retry logic via conditional edges
- Each invocation includes all context needed for that step via the system message
- Artifacts are passed in their entirety when needed

**TODO**: No specific plan is in place regarding token limits. Large artifacts (e.g., lengthy scripts or detailed ZWorlds) may exceed model context windows. Consider implementing: artifact summarization, chunking strategies, or model selection based on context requirements.

## Tool Invocation via LangGraph

Tools are defined as plain Python functions decorated with `@tool` (from `langchain_core.tools`). They are registered with the LangGraph graph via a `ToolNode`. When the model emits a tool call, LangGraph automatically routes it to the correct tool function and updates the graph state with the result.

See [LLM Orchestration](LLM%20Orchestration.md) and [Managers, Processes, and MCP Server](Managers,%20Processes,%20and%20MCP%20Server.md) for how tools are defined per process.

## ZForgeMcpServer (External Interface)

In addition to the internal LangGraph tool nodes, a `ZForgeMcpServer` is exposed as an external [MCP](https://modelcontextprotocol.io/) server using the Python [`mcp`](https://pypi.org/project/mcp/) library. This allows external agents (e.g., Copilot CLI, other LLM applications) to call Z-Forge operations. Internal orchestration uses LangGraph tools directly; the MCP server re-exposes a subset of these as MCP tools for external access.

ZForgeMcpServer provides the following tools:
- `CreateZWorld`, which creates an instance of a ZWorld given values for all of the properties of a ZWorld as specified in the [specs file](Data%20and%20File%20Specifications.md), and calls the application's singleton `ZWorldManager.create()` method.