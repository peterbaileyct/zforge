# Z-Forge

Z-Forge is an AI-powered tool for creating and running short Interactive Fiction (IF) experiences. It leverages large language models (LLMs) to generate fictional worlds, characters, and scenarios, compiling them into playable ink-format games.

## Features
- **AI-assisted World Building:** Generate structured world bundles (Z-Bundles) from plain-text descriptions.
- **Personalized Scenarios:** Cross-reference player preferences and prompts to create unique IF experiences.
- **ink Engine Integration:** Compile and play games using inkjs (via a JavaScript bridge) with a streamlined, typewriter-style interface.
- **Flexible Preferences:** Set preferences directly or via a quiz inspired by classic IF games.
- **Save/Load Support:** Save and resume progress across platforms.

## Quickstart

> **Requires [uv](https://docs.astral.sh/uv/).** See [Prerequisites](#prerequisites) for install instructions, then run `uv sync --all-extras` before anything else.

1. **Select or Create a World:** Use a plain-text description or build manually.
2. **Set Preferences:** Take the quiz or set preferences directly.
3. **Describe Your Scenario:** Provide a prompt for the kind of story or situation you want.
4. **Generate & Play:** Z-Forge creates a playable IF experience, which you can play immediately.

## Prerequisites

Z-Forge uses [uv](https://docs.astral.sh/uv/) to manage Python, dependencies, and the virtual environment. `uv` replaces manual `pip`/`venv` workflows and guarantees the environment exactly matches `pyproject.toml` (via `uv.lock`) every time you run the project.

### Install uv

```bash
# macOS / Linux (official installer)
curl -LsSf https://astral.sh/uv/install.sh | sh

# macOS via Homebrew
brew install uv
```

For other platforms see the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/).

### Set up the project

```bash
# Clone and enter the repo
git clone <repo-url> && cd zforge

# Install all dependencies and sync the virtual environment
# (uv will download the correct Python version if needed)
uv sync --all-extras
```

### Run the app

```bash
# uv auto-syncs the environment before launching — no manual pip steps needed
uv run python -m zforge
```

### Keeping dependencies in sync

Whenever `pyproject.toml` changes (e.g. after a `git pull` or adding a new package):

```bash
uv sync --all-extras
```

To add a new dependency:

```bash
uv add <package>          # runtime dependency
uv add --dev <package>    # dev-only dependency
```

Both commands update `pyproject.toml` and `uv.lock` atomically.

## Framework
Z-Forge uses [BeeWare](https://beeware.org/) (Toga widget toolkit) for a cross-platform UI (iOS, Android, PC, macOS, Web), Python for all application logic, [LangGraph](https://langchain-ai.github.io/langgraph/) for LLM orchestration, and inkjs (via a Python JS bridge) for compiling and running ink experiences. Project dependencies are declared in `pyproject.toml` and locked in `uv.lock`, managed by [uv](https://docs.astral.sh/uv/).

> **Local LLMs only.** Z-Forge runs all inference on-device using local GGUF models (e.g. DeepSeek). No cloud LLM providers (OpenAI, Anthropic, etc.) are supported or required. See [Local LLM Execution](docs/Local%20LLM%20Execution.md) for setup.

## Implementation Status

| Feature | Status |
|---|---|
| BeeWare/Toga project scaffold (all platforms) | 🔲 Phase 1 |
| ZWorld data model & file storage | 🔲 Phase 1 |
| LLM Abstraction Layer (LangGraph + local GGUF / DeepSeek) | 🔲 Phase 1 |
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
