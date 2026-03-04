# LLM Abstraction Layer
To maximize configurability and allow for expansion, an abstraction layer exists between the main Z-Forge engine and any LLMs used for procedural generation. We call this the "LLM Connector". This is implemented via abstract classes and interfaces that allow for a new LLM to be easily dropped in, and, in a later version, to allow selection between different LLM's for different features, with an eye toward adding image generation and runtime LLM invocation for infinite dialog, narration, and even hints. 

## Platform Requirements

LLM credentials are stored in secure storage (`flutter_secure_storage`). Each platform requires specific entitlements or permissions for this to work:

| Platform | Required configuration |
|---|---|
| **macOS** | `com.apple.security.network.client` entitlement in both `DebugProfile.entitlements` and `Release.entitlements` for outgoing API calls; `com.apple.security.files.user-selected.read-only` for file picker. `flutter_secure_storage` is configured with `useDataProtectionKeyChain: false` to use the legacy file-based keychain, avoiding the need for the `keychain-access-groups` entitlement (which requires a signed App Store build). |
| **iOS** | No extra entitlements needed; Keychain access is available by default |
| **Android** | `android.permission.INTERNET` in `AndroidManifest.xml` for API calls |
| **Windows** | No extra configuration needed |
| **Web** | Credentials stored in browser localStorage (less secure); no extra config needed |

Any agent implementing or modifying the secure config storage, LLM connector, or platform build configuration must ensure these entitlements/permissions are present.



## Configuration
The LLM connector defines an arbitrary set of key/value pairs, which in practice are almost always in string format, but specific value types e.g. integer and GUID are allowed. This is often as little as an API Key, which is an unformatted string. The LLM connector also specifies the name of the LLM/connector.

## Operations
- Get LLM connector name
- Get list of configuration keys and types
- Set configuration from secure storage, given a secure storage wrapper
- Validate existing configuration e.g. by connecting to LLM service
- Execute query, with the following parameters:
  - System Message: Gives the LLM's role and ancillary data, e.g. "You are a world-building assistant; you are going to make a ZWorld object from this description of a fictional world: ..."
  - Action Message: Specifies the current desired action, e.g. "Create a ZWorld from your given world description."
  - Tool: Specifies a tool that should be invoked for the given request; Z-Forge will make no requests that allow 0-n of a set of tools to be used, but rather knows exactly when a given tool is needed.

### Conversation Model
The LLM abstraction layer does **not** maintain conversation history. Each call to `execute` is a standalone request:
- System prompts are constructed from the current Process state and relevant artifacts
- A single user/action prompt spurs the desired action
- The LLM responds with a tool call that is processed through the MCP server
- The tool updates Process state, and the orchestration layer determines the next call

This stateless approach means:
- Agents are not aware of retry iterations; the application handles retry logic discretely
- Each call includes all context needed for that step via the system prompt
- Artifacts (Outline, Script, etc.) are passed in their entirety when needed

**TODO**: No specific plan is in place regarding token limits. Large artifacts (e.g., lengthy scripts or detailed ZWorlds) may exceed model context windows. Consider implementing: artifact summarization, chunking strategies, or model selection based on context requirements. 

## MCP Server and Tool Invocation
When an LLM connector has been asked to execute a query with a specified tool, this will be executed via an MCP server set up using flutter_mcp_server. The LLM Connector is responsible for translating any tool calls received into MCP tool calls and then executing that call via the Singleton ZForgeMcpServer.

ZForgeMcpServer provides the following tools:
- CreateZWorld, which creates an instance of a ZWorld given values for all of the properties of a ZWorld as specified in the [specs file]("Data and File Specifications.md"), and calls the application's Singleton ZWorldManager's CreateZWorld method.