# Managers, Processes, and MCP Server
The back-end processes of Z-Forge are handled by singleton Manager objects, LangGraph state graphs (replacing the former transitory Process objects), and a singleton MCP server which exposes Z-Forge operations to external agents.

## Managers
### ZForgeManager
A single `ZForgeManager` is the entry point for UI and external operations. It holds singleton instances of all data managers and is responsible for constructing and running LangGraph process graphs. It does not hold a transitory in-progress process object; process state lives inside the running LangGraph graph.

### ZWorldManager
A single `ZWorldManager` is responsible for CRUD operations on ZWorlds.

### ExperienceManager
A single `ExperienceManager` is responsible for CRUD operations on Experiences, including saving and loading progress within an experience and connecting the IF engine runtime to the UI.

## Processes (LangGraph State Graphs)

What were formerly transitory Process objects are now **LangGraph `StateGraph` instances** with typed `TypedDict` state. Each process graph:
- Defines a `TypedDict` class holding all inputs, artifacts, counters, and status
- Is constructed by a factory function (e.g., `build_create_world_graph()`)
- Is invoked by `ZForgeManager.run_process()` and streams state updates to the UI

### WorldCreationState
A `TypedDict` holding the state for a [world creation](World%20Generation.md) graph run.

### ExperienceGenerationState
A `TypedDict` holding the state for an [experience creation](Experience%20Generation.md) graph run.

See [LLM Orchestration](LLM%20Orchestration.md) for full graph structure.

## External MCP Server
A singleton `ZForgeMcpServer` exposes a subset of Z-Forge operations as [MCP](https://modelcontextprotocol.io/) tools using the Python [`mcp`](https://pypi.org/project/mcp/) library. This allows external agents (e.g., Copilot CLI) to invoke Z-Forge functionality. Internal orchestration uses LangGraph `@tool` functions directly.

### Tool Implementation Guidelines
Internal LangGraph tools are derived from the Process specifications. For each process graph, the implementation agent should:

1. **Analyze the Process specification** (flowcharts, sequence diagrams, and prose) to identify all decision points where an LLM agent completes a step and advances the process.

2. **Create one `@tool` per decision point**: Each tool should:
   - Accept all artifacts produced by that agent at that step (e.g., Script, or Outline + Tech Notes)
   - Include those artifacts in the returned state update dict
   - Set `status_message` to a human-readable description (for UI display)
   - Perform any automated validation (e.g., invoke `IfEngineConnector.build()` for script compilation)
   - Set `status` in the returned dict to advance the graph
   - Increment iteration counters where applicable

3. **Tool naming convention**: `{process}_{agent}_{action}`, e.g.:
   - `experience_author_submit_outline` — Author submits Outline + Tech Notes
   - `experience_scripter_submit_script` — Scripter submits Script; tool compiles and returns result
   - `experience_scripter_reject_outline` — Scripter rejects Outline with Outline Notes
   - `experience_author_approve_script` — Author approves Script
   - `experience_techeditor_submit_report` — Tech Editor submits approval or Tech Edit Report

4. **State access**: Tools receive all required inputs as function parameters (from the LLM's tool call). They return a dict of state updates to be merged into the LangGraph state by `ToolNode`.

5. **Bundled validation pattern**: When a tool accepts an artifact that requires validation (e.g., Script → compilation), the tool should:
   - Perform validation internally
   - On success: set `status` to the next review state in the returned dict
   - On failure: set `status` to the fix/retry state and include errors

### Tool Schema Standard
Each `@tool` function should:
- Have a clear docstring describing what it does and when to call it
- Use typed parameters matching the artifacts produced at that step
- Return a `dict` containing:
  - `status`: new process status string
  - `status_message`: human-readable description of what just happened
  - Any artifact fields to update
  - `validation_errors`: any errors from automated validation
  - Iteration counter fields to increment

Example:

```python
from langchain_core.tools import tool

@tool
def experience_scripter_submit_script(script: str) -> dict:
    """
    Scripter submits a complete ink script. Triggers compilation validation.
    Call when the Scripter has written a complete script.
    """
    build_result = if_engine_connector.build(script)
    if build_result.errors:
        return {
            "script": script,
            "compiler_errors": build_result.errors,
            "script_compile_iterations": 1,  # +1 via operator.add reducer
            "status": "awaiting_script_fix",
            "status_message": f"Compilation failed with {len(build_result.errors)} error(s)",
        }
    return {
        "script": script,
        "compiled_output": build_result.output,
        "compiler_errors": [],
        "script_compile_iterations": 0,  # add 0 to leave counter unchanged
        "status": "awaiting_author_review",
        "status_message": "Script compiled successfully",
    }
```
