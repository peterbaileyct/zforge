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
| **MEDIUM** | Story Editor uses generic lore rules; produces false positives that trigger unnecessary Arbiter invocations | Implement world lore briefings: LLM-generated, world-specific constraint checklists injected into the Story Editor's system prompt. Per-world briefings are cached and invalidated on world update; per-world-combination briefings are generated lazily for crossover stories. A thin per-story resolution layer appends how the player's premise navigates any cross-world conflicts. See [Experience Generation § Story Editor Briefings](docs/Experience%20Generation.md) | Not started |
| **MEDIUM** | No experience preview before playing | Add "Read Synopsis" option generated from Outline artifact | Not started |
| **MEDIUM** | Multiple experience management unclear | Clarify UI for browsing/managing multiple experiences per world | Not started |
| **MEDIUM** | World generation cannot run on mobile | Hide "Generate World" on iOS/Android (JVM and heavy LLM stack not available on-device); note that a server-side world generation path may be added later | Not started |
| **MEDIUM** | No way to share Z-Worlds across devices | Define `.zworld` archive format (zip of the Z-Bundle directory tree) and implement export/import so desktop-generated worlds can be transferred to mobile for experience creation | Not started |
| **LOW** | Web storage unspecified | Decide on IndexedDB vs cloud storage for web platform | TODO |
| **LOW** | No undo/rewind during gameplay | Consider adding common IF rewind feature | Not started |
| **LOW** | "Create Your Universe" supports only Z-Worlds | Extend the data source selector on the Create Experience screen to support additional knowledge source types: user-supplied character rosters (structured character sheets outside a full Z-World), and real-world knowledge bases sourced from publicly editable encyclopaedias (useful for educational games that teach real-world facts through interactive narrative). Requires defining ingestion pipelines and retrieval tool variants for each new source type. | Not started |
| **MEDIUM** | Entity dedup misses title/honorific variants (`"Glory"` vs `"Queen Glory"`) | Add a second merge pass to Phase 4: for each pair of entities of the same type, if one id is a whole-word substring of the other, flag as duplicates regardless of embedding distance. Cheap, no new dependencies. See [Parsing § Phase 4](docs/Parsing%20Documents%20to%20Z-Bundles.md#phase-4-entity-deduplication) | Not started |
| **LOW** | Entity dedup cannot resolve semantic coreference (`"the DragonWing Queen"` / `"Glory"`) | Implement Phase 4b: an LLM-assisted coreference pass that, given entity names and sample passages, identifies aliases that are semantically unrelated at the string level. More expensive; should run only when `entity_coreference_enabled` is true. | Not started |
| **LOW** | `RecursiveCharacterTextSplitter` for retrieval pass produces fixed-size, topic-agnostic chunks | Replace with `SemanticChunker` (topic-shift-aware, no LLM cost) per [Parsing § Chunking Strategy](docs/Parsing%20Documents%20to%20Z-Bundles.md#chunking-strategy) | TODO |
| **LOW** | Propositional chunking not implemented | Implement propositional chunking as an optional retrieval-pass mode for high-value worlds; delivers highest per-fact retrieval precision (see [Parsing § Future: Propositional Chunking](docs/Parsing%20Documents%20to%20Z-Bundles.md#future-propositional-chunking)) | Not started |
| **LOW** | No static type checking for UI breakage | Implement static type checking (Mypy / Pyright) to catch third-party library API/enum changes at compile time | Not started |


## Existing TODOs (from spec documents)

### Experience Generation.md
- [ ] Pictures and possibly sounds support for multimedia experiences
- [ ] World lore briefings: cached per-world (and lazily per-world-combination) LLM-generated Story Editor constraint checklists, plus a per-story resolution layer referencing the player prompt (reduces false-positive lore violations and Arbiter invocations)

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

### Mobile Platform
- [ ] Guard "Generate World" behind a desktop-only platform check (iOS/Android show a disabled state or hide the option entirely); leave an extension point for a future server-side world generation path on mobile
- [ ] Define `.zworld` archive format — zip of the Z-Bundle directory tree (`source.txt`, `chunks/` LanceDB table, `propertygraph` KuzuDB file, KVP store) with a top-level manifest (`manifest.json`) recording the bundle slug, UUID, title, and the Z-Forge version that produced it
- [ ] Implement "Export World" action on desktop (writes `.zworld` to a user-chosen path)
- [ ] Implement "Import World" action on all platforms (extracts `.zworld` into the platform's `bundles/` directory, validating the manifest)

### Parsing Documents to Z-Bundles.md
- [ ] Replace `RecursiveCharacterTextSplitter` retrieval pass with `SemanticChunker` (topic-shift-aware splitting; no LLM cost; see [Chunking Strategy](docs/Parsing%20Documents%20to%20Z-Bundles.md#chunking-strategy))
- [ ] Implement structure-aware context-pass splitting (`MarkdownTextSplitter` + header detection before size-cap fallback)
- [ ] Add `parent_chunk_id` metadata field to retrieval chunks (parent-child tagging)
- [ ] Propositional chunking as an opt-in retrieval-pass mode for high-value worlds
- [ ] PROPN-density pre-filter: skip graph extraction on chunks with fewer than N proper nouns per 100 tokens (spaCy POS tagger; language-agnostic entity-type-independent cost saving; implement only after co-reference and dedup are stable)
- [ ] Phase 4 substring-containment merge pass: flag entity pairs of the same type as duplicates when one id is a whole-word substring of the other (catches honorific/title prepends such as `"Glory"` → `"Queen Glory"`; no LLM cost)
- [ ] Phase 4b LLM coreference pass: optional (`entity_coreference_enabled`), bounded LLM call that identifies semantically coreferent entities whose string forms share no obvious substring relationship

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
- World lore briefings for Story Editor (per-world cached; per-world-combination lazy; per-story resolution layer)

### v1.2 - Enhanced Onboarding
- Ultima-style preference questions
- Improved preference explanations

### v1.3 - Mobile & Sharing
- Hide / disable "Generate World" on iOS and Android
- `.zworld` archive format (zip of Z-Bundle tree + `manifest.json`)
- Export World action (desktop)
- Import World action (all platforms, including mobile)

### v2.0 - Platform Expansion
- Web storage implementation
- Parallel processing support
- Additional IF engines
- Server-side world generation path for mobile (optional, replaces on-device restriction)
- Propositional chunking mode for high-value world sources (maximum retrieval precision)
