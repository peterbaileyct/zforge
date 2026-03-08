# Processes
Multiple key functions of Z-Forge, such as [parsing unstructured world bibles into Z-Worlds](World%20Generation.md) and [generating experiences from Z-Worlds](Experience%20Generation.md), operate using a state machine-based Process, frequently aided by [RAG](Rag%20and%20GRAG%20implementation.md).

## Overview
Any procedural generation process in Z-Forge takes the form of a state machine, with discrete steps that may correspond to LLM calls or, for example, local file operations.

## Specifications
A procedural generation process is defined in a single Markdown file. The definition begins with a title, a brief textual description of intent (but not process), and then a Mermaid flowchart defining the elements of the state machine. No implementation is to take place without this canonical visual representation. It must have five subgraphs:
- Agents: Contains nodes for any LLM interactions.
- State: Contains a node for each property of the machine's state. Each node is rendered as a document.
- Repositories: Contains a node for each RAG repo available. Each node is rendered as a database store. 
- Tools: Contains nodes for non-LLM functionality.
- Process: Contains nodes corresponding to the nodes of the state machine. 
  - Entry is defined by a "start" node rendered as an empty circle, with one arrow leading to the initial state.
  - Exit is defined by a "stop" node rendered as an empty circle, with no arrows leading out of it.
  - Dotted, undirected lines between a process node and a state property node indicate that the information from the state is used in that node. If the node connects to an agent node, the state properties are almost always used to generate system prompts to the agent.
  - Dotted, undirected lines between a process node and a repository node indicate **deterministic RAG**: a lookup is always performed as part of that node's execution and the results are stuffed into the agent's context. Almost always paired with a dotted line to an Agent node.
  - A labeled directed self-loop on an agent's process node (e.g., `node -->|retrieves: ZWorld| node`) indicates **agentic RAG**: the agent may call the named retriever tool zero or more times before calling an advancement tool. Each iteration the retrieved content is appended to a state list and included in the next invocation of the agent. The routing condition after the ToolNode must distinguish retriever tool calls (loop back to agent) from advancement tool calls (proceed forward). The corresponding retriever `@tool` appears in the **Tools** subgraph, identified by a `retrieve_[topic]` name, with a directed arrow to the relevant **Repositories** node indicating the vector store queried.
  - If retrieved documents may fail a relevance grading check, the agentic RAG self-loop may instead route through an explicit `grade_[topic]` diamond (conditional edge) and optionally a `rewrite_[topic]` process node before looping back to the agent, forming an explicit retrieve → grade → (rewrite →) agent cycle.
  - Dotted, undirected lines between a process node and an Agent node indicate that a query is made of the Agent.

### Implementation
Each state machine is defined in LangGraph. Each LLM call in the state machine has a specified default service and model, which may be changed the application config. Each RAG step is either a direct lookup against a vector store or a hybrid lookup of both a vector store and a property graph where each node links to a text chunk in the vector store. See [Storage%20for%20RAG.md] for details.

#### LangGraph tool call pattern
**Do not use `ToolNode` for tools that update graph state.** In LangGraph 1.x, `ToolNode` stores tool return values as `ToolMessage` content appended to `messages` — it does **not** merge plain-dict returns into other state fields. This causes state mutations (e.g., `status`, `validation_iterations`) to be silently dropped, leaving the graph stuck in a loop.

The correct pattern for every agent node that drives state transitions:

1. Call `model.bind_tools(tools).invoke(...)` to get the LLM response.
2. Iterate over `response.tool_calls` and call each tool function directly via `tool_fn.invoke(args)`.
3. Merge each tool's dict return value into the node's own return dict.
4. Append a `ToolMessage(content=..., tool_call_id=tc["id"], name=tc["name"])` to `messages` for each call, so the message history remains well-formed for the next LLM invocation.
5. Return all state updates and messages in a single dict from the node — no separate `tools` node or `ToolNode` is needed.

Routing conditional edges are placed directly after agent nodes (not after a shared `tools` node), because the state is now fully updated by the time the node returns.