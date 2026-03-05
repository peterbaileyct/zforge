# Rationale Logging Implementation

## Summary
Enhanced the experience generation feedback system to capture and display LLM decision rationale and maintain an action log.

## Changes Made

### 1. Data Model (`lib/processes/experience_generation_process.dart`)
- **Added `LogEntry` class**: Captures timestamp, state transitions, actions, and rationale
- **Added fields to `ExperienceGenerationProcess`**:
  - `currentRationale`: Current step's reasoning from LLM
  - `actionLog`: Historical list of all actions and rationales
  - `addLogEntry()`: Method to add entries to the log

### 2. MCP Tool Schemas (`lib/services/mcp/zforge_mcp_server.dart`)
- **Updated all 10 experience generation tools** to include a `rationale` parameter:
  - `experience_author_submit_outline`
  - `experience_scripter_approve_outline`
  - `experience_scripter_reject_outline`
  - `experience_scripter_submit_script`
  - `experience_author_approve_script`
  - `experience_author_reject_script`
  - `experience_techeditor_approve`
  - `experience_techeditor_reject`
  - `experience_storyeditor_approve`
  - `experience_storyeditor_reject`

### 3. MCP Tool Implementations (`lib/services/mcp/zforge_mcp_server.dart`)
- **Updated all tool handler methods** to:
  - Extract `rationale` from tool arguments
  - Capture previous status before state change
  - Call `addLogEntry()` with state transition and rationale
  - Store rationale in process for UI display

### 4. UI Updates (`lib/ui/screens/generate_experience_screen.dart`)
- **Current Rationale Display**: Shows the latest LLM reasoning below status message
- **Action Log Panel**: Scrollable list showing full history with:
  - Timestamps (HH:MM:SS format)
  - State transitions (fromState → toState)
  - Action descriptions
  - Rationale text (indented)

## UI Layout Example

```
Status: Story Editor requests changes
Rationale: The player requested a silly story, but the generated content 
           was overly sad and didn't match the requested mood.

[Action Log - scrollable]
10:23:45 | awaitingOutline → awaitingOutlineReview
  Author submitted outline
  Created an engaging mystery with branching paths...

10:24:12 | awaitingOutlineReview → awaitingScript
  Scripter approved outline
  The outline is feasible and aligns well with player preferences...
```

## Benefits

1. **Transparency**: Users can see why the LLM made each decision
2. **Debugging**: Complete log helps diagnose generation issues
3. **Learning**: Users understand the multi-agent collaboration process
4. **Session-only**: Log is not persisted (as specified)

## Future Enhancements (Not Implemented)

- Log persistence for debugging
- Export log feature
- Filtering/search in action log
- Color-coding by agent type
