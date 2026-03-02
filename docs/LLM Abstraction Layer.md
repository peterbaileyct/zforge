# LLM Abstraction Layer
To maximize configurability and allow for expansion, an abstraction layer exists between the main Z-Forge engine and any LLMs used for procedural generation. We call this the "LLM Connector". This is implemented via abstract classes and interfaces that allow for a new LLM to be easily dropped in, and, in a later version, to allow selection between different LLM's for different features, with an eye toward adding image generation and runtime LLM invocation for infinite dialog, narration, and even hints. 

## Requirements
Any LLM leveraged by Z-Forge must support MCP, to connect the LLM to functions like Inform interpretation.

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
  - Tool: Specifies a tool that should be invoked for the given request; Z-Forge will make no requests that allow 0-n of a set of tools to be used, but rather knows exactly when a given tool is needed. E.g. 

## MCP Server and Tool Invocation
When an LLM connector has been asked to execute a query with a specified tool, this will be executed via an MCP server set up using flutter_mcp_server. The LLM Connector is responsible for translating any tool calls received into MCP tool calls and then executing that call via the Singleton ZForgeMcpServer.

ZForgeMcpServer provides the following tools:
- CreateZWorld, which creates an instance of a ZWorld given values for all of the properties of a ZWorld as specified in the [specs file]("Data and File Specifications.md"), and calls the application's Singleton ZWorldManager's CreateZWorld method.