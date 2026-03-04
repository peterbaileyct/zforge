# Managers, Processes, and MCP Server
The back-end processes of Z-Forge are handled by Singleton Manager objects, transitory Process objects, and a Singleton MCP server, which acts on the Processes via the Managers.

## Managers
### ZForgeManager
A single ZForgeManager is the entry point for UI and MCP operations. It contains a single transitory instance of any given Process in progress. (TODO: Allow for processing in parallel so that we can make this the back-end of a much larger Web app.) It holds a Singleton instance of a Manager for any data that can be saved or loaded.

### ZWorldManager
A single ZWorldManager is responsible for CRUD operations on ZWorlds.

### ExperienceManager
A single ExperienceManager is responsible for CRUD operations on Experiences. This also includes saving and loading progress within an experience and connecting the ink_runtime engine used for playback to the UI.

## Processes
### WorldCreationProcess
A transitory WorldCreationProcess tracks the individual steps of a [world creation]("World Generation.md"), to coordinate that LLM-executed process.

### ExperienceCreationProcess
A transitory ExperienceCreationProcess tracks the individual steps of an [experince creation]("Experience Generation.md"), to coordinate that LLM-executed process.

## MCP Server
A single ZForgeMcpServer is responsible for executing tool calls returned by the configured LLM Connector by executing methods on the ZForgeManager or directly manipulating a nested Manager or Process.

### Tool Implementation Guidelines
MCP tools are derived from the Process specifications. For each Process type (e.g., `ExperienceGenerationProcess`), the implementation agent should:

1. **Analyze the Process specification** (flowcharts, sequence diagrams, and prose) to identify all decision points where an LLM agent completes a step and advances the process.

2. **Create one tool per decision point**: Each tool should:
   - Accept all artifacts produced by that agent at that step (e.g., Script, or Outline + Tech Notes)
   - Store artifacts on the Process object
   - Set `statusMessage` to a human-readable description of what happened (for UI display)
   - Perform any automated validation (e.g., invoke `IfEngineConnector.build()` for script compilation)
   - Advance the process state based on the validation result
   - Increment iteration counters where applicable
   - Return all information needed for the next step, including:
     - Success/failure status
     - Any validation results (e.g., compiler errors)
     - Inputs for the next agent (e.g., the current Outline for the Scripter to review)

3. **Tool naming convention**: `{process}_{agent}_{action}`, e.g.:
   - `experience_author_submit_outline` — Author submits Outline + Tech Notes
   - `experience_scripter_submit_script` — Scripter submits Script; tool compiles and returns result
   - `experience_scripter_reject_outline` — Scripter rejects Outline with Outline Notes
   - `experience_author_approve_script` — Author approves Script
   - `experience_techeditor_submit_report` — Tech Editor submits approval or Tech Edit Report

4. **Process state access**: Tools access the current Process via `ZForgeManager.currentProcess` (cast to the appropriate Process type). All artifacts are stored as named properties on the Process object.

5. **Bundled validation pattern**: When a tool accepts an artifact that requires validation (e.g., Script → compilation), the tool should:
   - Store the artifact on the Process
   - Perform validation internally
   - On success: advance to the next review state and return inputs for the next agent
   - On failure: advance to the fix/retry state and return the errors for the same agent to address

### Tool Schema Standard
Each MCP tool should be defined with:
- **name**: Following the naming convention above
- **description**: What the tool does and when to call it
- **inputSchema**: JSON Schema for parameters—all artifacts produced at this step
- **Returns**: JSON object with:
  - `success`: boolean
  - `statusMessage`: human-readable description of what happened (also stored on Process)
  - `validationErrors`: any errors from automated validation (e.g., compiler errors)
  - `nextAgent`: which agent should act next
  - `nextInputs`: all artifacts/data that agent needs to proceed
  - `processStatus`: the new status of the Process
  - `iterationsRemaining`: how many retry attempts remain for the current loop (if applicable)

