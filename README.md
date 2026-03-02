# Z-Forge

Z-Forge is an AI-powered tool for creating and running short Interactive Fiction (IF) experiences. It leverages large language models (LLMs) to generate fictional worlds, characters, and scenarios, compiling them into playable Glulx-format games coded in Inform.

## Features
- **AI-assisted World Building:** Generate structured world files (.zworld) from plain-text descriptions.
- **Personalized Scenarios:** Cross-reference player preferences and prompts to create unique IF experiences.
- **Zart Engine Integration:** Compile and play games in .gblorb format with a streamlined, typewriter-style interface.
- **Flexible Preferences:** Set preferences directly or via a quiz inspired by classic IF games.
- **Save/Load Support:** Save and resume progress across platforms.

## Quickstart
1. **Select or Create a World:** Use a plain-text description or build manually.
2. **Set Preferences:** Take the quiz or set preferences directly.
3. **Describe Your Scenario:** Provide a prompt for the kind of story or situation you want.
4. **Generate & Play:** Z-Forge creates a playable IF experience, which you can play immediately.

## Framework
Z-Forge uses Flutter for a cross-platform UI (iOS, Android, PC, MacOS, Web) and the Zart library (from pub.dev) for running Glulx experiences.

## Documentation
- [Specification & Format Details]("docs/Data and File Specifications.md")
- [World Generation Process]("docs/World Generation.md")
- [Experience Generation Process]("docs/Experience Generation.md")
- [User Experience]("docs/User Experience.md")

---

© 2026 Z-Forge Contributors. All rights reserved.
