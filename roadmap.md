# Z-Forge Roadmap

This document captures UX concerns, priority improvements, and existing TODOs for future development.

## UX Concerns

### Generation Phase User Experience
The biggest UX risk is the experience generation phase. Players may wait several minutes while multiple AI agents iterate (potentially 10-15+ LLM calls). Without excellent progress feedback, this could feel like the app is "stuck."

**Current mitigation**: The `statusMessage` property is displayed during generation, showing progress like "Author submitted outline", "Scripter approves outline", etc.

**Remaining gaps**:
- No animated progress indicator
- No estimated time remaining
- No ability to cancel in-progress generation

### Player Preference Capture
Player preferences are currently set via numeric sliders (1-10 scales). This may not capture nuanced preferences effectively, especially for new users unfamiliar with IF conventions.

## Priority Improvements

| Priority | Issue | Recommendation | Status |
|----------|-------|----------------|--------|
| **HIGH** | Limited feedback during generation | Add animated progress indicator alongside `statusMessage` | Partial (statusMessage exists) |
| **HIGH** | No cancellation of in-progress generation | Add cancel button to GenerateExperienceScreen | TODO |
| **MEDIUM** | Slider-only preferences may miss nuance | Implement "Ultima-style questions" for preference onboarding | TODO |
| **MEDIUM** | No experience preview before playing | Add "Read Synopsis" option generated from Outline artifact | Not started |
| **MEDIUM** | Multiple experience management unclear | Clarify UI for browsing/managing multiple experiences per world | Not started |
| **LOW** | Web storage unspecified | Decide on IndexedDB vs cloud storage for web platform | TODO |
| **LOW** | No undo/rewind during gameplay | Consider adding common IF rewind feature | Not started |

## Existing TODOs (from spec documents)

### Experience Generation.md
- [ ] Pictures and possibly sounds support for multimedia experiences

### Managers, Processes, and MCP Server.md
- [ ] Allow parallel processing for scalability (web app backend scenario)

### User Experience.md
- [ ] Ultima-like questions to gauge player preferences at onboarding
- [ ] Web storage implementation (currently unspecified)
- [ ] Visual flowchart showing process steps with color-coded status
- [ ] User cancellation of in-progress generation

### LLM Abstraction Layer.md
- [ ] Token limit handling strategy (artifact summarization, chunking, or model selection)

### IF Engine Abstraction Layer.md
- [ ] Future interface enhancements (unspecified)

### Testing
- [ ] Unit tests for core services (ZWorldManager, ExperienceManager, config services)
- [ ] Unit tests for process state machines (CreateWorldProcess, ExperienceGenerationProcess)
- [ ] Unit tests for MCP tool handlers
- [ ] Integration tests for LLM orchestration (mocked LlmConnector)
- [ ] Widget tests for key UI screens

## Implementation Readiness

**The specification is implementation-ready.** An implementation agent should be able to build the core system without major clarifications. The items above are enhancements and polish, not blockers.

## Version Planning (Suggested)

### v1.0 - Core Functionality
- World creation from text/file
- Experience generation with progress display
- ink engine support via inkjs
- Basic save/restore
- Slider-based preferences

### v1.1 - UX Polish
- Animated progress during generation
- Cancel button for generation
- Experience synopsis preview

### v1.2 - Enhanced Onboarding
- Ultima-style preference questions
- Improved preference explanations

### v2.0 - Platform Expansion
- Web storage implementation
- Parallel processing support
- Additional IF engines
