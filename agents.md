Human-readable documentation is rooted in readme.md. This file links to deeper documentation in Markdown format in the docs folder. All documentation is in Markdown format with embedded Mermaid diagrams.

Documentation should reference, where appropriate, which code file(s) implement the described functionality.

Where helpful, documentation should illustrate functions and use cases in which control flow varies significantly via Mermaid flow chart diagrams. Where helpful, documentation should illustrate functions that involve significant communication between the user, AI actors, and/or separate subsystems via Mermaid sequence diagrams. Both flow chart and sequence diagrams may be appropriate for the same functions, and both should be rendered in this case.

Any code changes should be mirrored in changes to/creation of Mermaid ER diagrams in the docs folder.

## LLM Prompts
LLM prompts appear in two places and MUST be kept in sync:
1. **Spec files** (in docs/): The authoritative documentation of what each prompt should contain. Changes to prompt content, structure, or intent should be made here first.
2. **Code files** (in lib/): The implementation that delivers prompts to the LLM. These must match the spec files.

When modifying LLM prompts:
- Update BOTH the spec file and the code file in the same change.
- The spec file serves as the source of truth for prompt design decisions.
- Code implementations (e.g., `getScriptPrompt()` in IfEngineConnector, system prompts in ExperienceGenerationProcess) must reflect the spec.

Key prompt locations:
- **Experience Generation prompts** (Author, Scripter, Technical Editor, Story Editor): Spec in `docs/Experience Generation.md`, code in `lib/processes/experience_generation_process.dart`
- **IF Engine script prompts** (ink syntax guidance): Spec in `docs/Ink Engine Connector.md`, code in `lib/services/if_engine/ink_engine_connector.dart`
