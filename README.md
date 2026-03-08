# Z-Forge

Z-Forge is an AI-powered tool for creating and running short Interactive Fiction (IF) experiences. It leverages large language models (LLMs) to generate fictional worlds, characters, and scenarios, compiling them into playable ink-format games.

## Features
- **AI-assisted World Building:** Generate structured world files (.zworld) from plain-text descriptions.
- **Personalized Scenarios:** Cross-reference player preferences and prompts to create unique IF experiences.
- **ink Engine Integration:** Compile and play games using inkjs (via a JavaScript bridge) with a streamlined, typewriter-style interface.
- **Flexible Preferences:** Set preferences directly or via a quiz inspired by classic IF games.
- **Save/Load Support:** Save and resume progress across platforms.

## Quickstart
1. **Select or Create a World:** Use a plain-text description or build manually.
2. **Set Preferences:** Take the quiz or set preferences directly.
3. **Describe Your Scenario:** Provide a prompt for the kind of story or situation you want.
4. **Generate & Play:** Z-Forge creates a playable IF experience, which you can play immediately.

## Prerequisites

Z-Forge requires Python 3.11+ and the BeeWare `toga` package for the desktop UI. If the `pip` command is not available on your system, use `python3 -m pip` which is always available when Python is installed.

Install steps (recommended):

```bash
# Ensure Python 3.11+ is available
python3 --version

# If pip is missing, bootstrap it and upgrade packaging tools
python3 -m ensurepip --upgrade
python3 -m pip install --upgrade pip setuptools wheel

# Install Toga only (fast) or install the project editable (installs all deps)
# Fast (just Toga):
python3 -m pip install toga
# Full editable install (recommended for development):
python3 -m pip install -e .
```

If you prefer managing Python versions, consider installing via Homebrew (`brew install python@3.11`), `pyenv`, or the official Python installer from python.org.

## Framework
Z-Forge uses [BeeWare](https://beeware.org/) (Toga widget toolkit) for a cross-platform UI (iOS, Android, PC, macOS, Web), Python for all application logic, [LangGraph](https://langchain-ai.github.io/langgraph/) for LLM orchestration, and inkjs (via a Python JS bridge) for compiling and running ink experiences. Project configuration is managed via `pyproject.toml`.

## Implementation Status

| Feature | Status |
|---|---|
| BeeWare/Toga project scaffold (all platforms) | 🔲 Phase 1 |
| ZWorld data model & file storage | 🔲 Phase 1 |
| LLM Abstraction Layer (LangGraph + OpenAI) | 🔲 Phase 1 |
| LangGraph orchestration graphs | 🔲 Phase 1 |
| World Creation workflow | 🔲 Phase 1 |
| Player Preferences | 🔲 Phase 1 |
| Home / LLM Config / Preferences screens | 🔲 Phase 1 |
| ink experience generation | 🔲 Phase 2 |
| ink gameplay interface | 🔲 Phase 2 |
| Save/Load progress | 🔲 Phase 2 |

## Documentation
- [Data Models ER Diagram](docs/ER%20Diagram.md)
- [Specification & Format Details](docs/Data%20and%20File%20Specifications.md)
- [World Generation Process](docs/World%20Generation.md)
- [Experience Generation Process](docs/Experience%20Generation.md)
- [IF Engine Abstraction Layer](docs/IF%20Engine%20Abstraction%20Layer.md)
- [Ink Engine Connector](docs/Ink%20Engine%20Connector.md)
- [Managers, Processes, and MCP Server](docs/Managers,%20Processes,%20and%20MCP%20Server.md)
- [Player Preferences](docs/Player%20Preferences.md)
- [User Experience](docs/User%20Experience.md)
- [LLM Abstraction Layer](docs/LLM%20Abstraction%20Layer.md)
- [LLM Orchestration](docs/LLM%20Orchestration.md)
- [Local LLM Execution](docs/Local%20LLM%20Execution.md)
- [ZWorld Format](docs/ZWorld.md)

---

© 2026 Z-Forge Contributors. All rights reserved.
