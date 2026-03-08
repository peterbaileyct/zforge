# Managers, Processes, and MCP Server
The back-end processes of Z-Forge are handled by singleton Manager objects and transitory [Processes](Processes.md).

## Managers
### ZForgeManager
A single `ZForgeManager` is the entry point for UI and external operations. It holds singleton instances of all data managers and is responsible for constructing and running LangGraph process graphs. It does not hold a transitory in-progress process object; process state lives inside the running LangGraph graph.

### ZWorldManager
A single `ZWorldManager` is responsible for CRUD operations on ZWorlds.

### ExperienceManager
A single `ExperienceManager` is responsible for CRUD operations on Experiences, including saving and loading progress within an experience and connecting the IF engine runtime to the UI.
