# LLM Abstraction Layer
To maximize configurability and allow for expansion, an abstraction layer exists between the main Z-Forge engine and any LLM invocation, to allow selection between different LLM's for different features, and with an eye toward adding (in a future version) image generation and runtime LLM invocation for infinite dialog, narration, and even hints.

## Configurability
No LLM call is hard-coded; instead, LLMs are always invoked through [Processes](Processes.md). To allow for this abstraction and configuration, the state machine implementing a Process must be built with reference to the application configuration, with default values specified in the spec file for that process and in the code at compile time. Each LLM call node uses a specific provider and a specific model. Providers may be [local](Local%20LLM%20Execution.md) or online.

World Generation targets the remote gpt-5 nano model by default, deferring to user-specified provider/model pairs whenever they are explicitly set.

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
- Execute query, with the following parameters:
  - System Messages: Gives the LLM's role and ancillary data, e.g. "You are a world-building assistant; you are going to make a ZWorld object from this description of a fictional world: ..."
  - User Messages: Specifies the current desired action, e.g. "Create a ZWorld from your given world description."
  - Tools: Specifies tools that can be invoked by the LLM. The choice of tool determines the state change and movement within the state machine. At least one tool must therefore be provided.


  ## Implementation
  ### APIs
  Connectors are provided for the following API's:
  - OpenAI
  - Google
  - Anthropic
  Each one only needs an API key specified for that vendor, which must be stored in platform-specific secure storage.
  Each should be implemented with a package, if possible, rather than direct HTTP requests.
  Each one, if the provider allows for it, should call an API to get a list of model names the first time that this list is requested on each run of the application. For vendors that do not provide such an API, the list should be hard-coded based on available models at compile time (when the connector is created or updated).

  ### Local Execution
  Local connectors provide an offline option (chat inference and embeddings) when a GGUF model is configured. The list of models is based on the GGUF files that have been downloaded.
