# Z-Forge Data Model ER Diagram

All persistent data models used by Z-Forge. Implemented across `src/zforge/models/`.

```mermaid
erDiagram
    ZWorld {
        string title
        string slug
        string uuid
        string summary
        string setting_era "optional"
        stringList source_canon "optional"
        stringList content_advisories "optional"
    }
    ZBundleKVP {
        string title
        string slug
        string uuid
        string summary
        string setting_era "optional"
        stringList source_canon "optional"
        stringList content_advisories "optional"
        string embedding_model_name
        int embedding_model_size_bytes
    }
    ZForgeConfig {
        string bundlesRoot "optional; desktop only"
        string experienceFolderPath "optional; desktop only"
        string chatModelPath "relative to sandboxed storage"
        int chatContextSize "default 512"
        int chatGpuLayers "default 0"
        string embeddingModelPath "relative to sandboxed storage"
        int embeddingContextSize "default 512"
        int embeddingGpuLayers "default 0"
        int parsingChunkSize "default 10000"
        int parsingChunkOverlap "default 500"
    }
    PlayerPreferences {
        int    characterToPlot      "1-10; 1=character, 10=plot; default 5"
        int    narrativeToDialog    "1-10; 1=narrative, 10=dialog; default 5"
        int    puzzleComplexity     "1-10; default 5"
        int    levity               "1-10; 1=somber, 10=comedic; default 5"
        string generalPreferences   "optional free text"
        int    logicalVsMood        "1-10; 1=mood priority, 10=logic priority; default 5"
    }
    ModelCatalogueEntry {
        string role "chat or embedding"
        string displayName
        string hfRepo "Hugging Face repo"
        string filename "GGUF filename"
        int sizeBytesApprox
        bool isDefault
    }
    LlmNodeConfig {
        string processSlug
        string nodeSlug
        string provider
        string model
    }

    ZForgeConfig ||--|| PlayerPreferences       : "contains"
    ZForgeConfig ||--o{ LlmNodeConfig           : "maps per-node settings"
    ZWorld       ||--|| ZBundleKVP              : "persisted as"
```

## Z-Bundle Storage

Z-Worlds are persisted as Z-Bundles at `bundles/world/{slug}/`:
- `kvp.json` — key-value metadata (title, slug, UUID, summary, setting_era, source_canon, content_advisories, embedding model identity)
- `raw.txt` — original raw input text
- `vector/` — LanceDB vector store (document chunk embeddings; table name `chunks`)
- `propertygraph` — KùzuDB property graph file (schema-less entity nodes and relationship edges, managed by `KuzuGraph.add_graph_documents`)

Entity types (Character, Location, Event, Faction, Artifact, Era, Culture, Deity, Prophecy, Concept, Mechanic, Trope, Species, Occupation) are no longer Python dataclasses — they exist as schema-less nodes in KuzuDB, created dynamically by `LLMGraphTransformer`.

```mermaid
erDiagram
    ZBundle {
        string type_slug "e.g. world"
        string slug "e.g. discworld"
    }
    KVPStore {
        string path "kvp.json"
    }
    SourceText {
        string path "raw.txt"
    }
    VectorStore {
        string path "vector/"
        string backend "LanceDB"
        string table_name "chunks"
    }
    PropertyGraph {
        string path "propertygraph"
        string backend "KuzuDB"
    }

    ZBundle      ||--|| KVPStore         : "contains"
    ZBundle      ||--|| SourceText       : "contains"
    ZBundle      ||--|| VectorStore      : "contains"
    ZBundle      ||--|| PropertyGraph    : "contains"
```

## Runtime / Service Models

These models are created and managed by services at runtime. See the corresponding source files for details.

```mermaid
erDiagram
    Experience {
        string zworldSlug
        string name
        string engineExtension
        string filePath
    }
    ExperienceManager ||--o{ Experience : "manages"
```

## UI Runtime

The Flet `Page` object is the root of the UI. It holds a reference to `AppState`
and navigates between screens by replacing `page.controls`.

```mermaid
erDiagram
    FletPage {
        string title "Z-Forge"
    }
    AppState {
        ref zforgeManager
        ref configService
        ref llmConnector
        ref connectorRegistry
        ref ifEngineConnector
        ref embeddingConnector
    }
    Screen {
        string kind "home, llm_config, create_world, preferences, world_details, gameplay, generate_experience"
    }

    FletPage ||--|| AppState : "initializes and holds"
    FletPage ||--o| Screen  : "displays one at a time"
    Screen   }o--|| AppState : "reads / writes"
```

## Transitory Process Models

Process objects are not persisted but track multi-step LLM workflows. See [Managers, Processes, and MCP Server](Managers,%20Processes,%20and%20MCP%20Server.md) for tool implementation guidelines.

```mermaid
erDiagram
    ExperienceGenerationProcess {
        string status "outlining, reviewing_outline, writing_prose, reviewing_prose, scripting, compiling, debugging, qa, auditing, complete, failed"
        string statusMessage "current step description for UI"
        string failureReason "optional"
        dict zworldKvp "input"
        string worldSlug "input"
        string zBundleRoot "input"
        dict preferences "input"
        string playerPrompt "optional input"
        string outline "optional"
        string researchNotes "optional"
        string experienceTitle "optional"
        string experienceSlug "optional"
        string proseDraft "optional"
        string inkScript "optional"
        bytes compiledOutput "optional"
        stringArray compilerErrors
        string outlineFeedback "optional"
        string proseFeedback "optional"
        string qaFeedback "optional"
        string auditFeedback "optional"
        int outlineReviewCount
        int proseReviewCount
        int compileFixCount
        int scriptRewriteCount
        list messages
    }
    CreateWorldProcess {
        string status "parsing, summarizing, finalizing, complete, failed"
        string statusMessage "current step description for UI"
        string failureReason "optional"
        string inputText
        string zBundleRoot "optional"
        dict zworldKvp "optional"
    }
    AskAboutWorldProcess {
        string zBundleRoot
        dict zworldKvp
        string userQuestion
        string answer "optional"
        list messages
    }
    DocumentParsingProcess {
        string status "contextualizing, complete"
        string statusMessage "current step description for UI"
        string inputText
        string zBundleRoot
        listStr allowedNodes
        listStr allowedRelationships
        listStr chunks
        list documents
        int currentChunkIndex
    }

    ExperienceGenerationProcess ||--|| ZWorld : "references via slug"
    ExperienceGenerationProcess ||--|| PlayerPreferences : "optional input"
    AskAboutWorldProcess ||--|| ZWorld : "input"
```

## Notes
- Z-Worlds are stored as Z-Bundles under `bundles/world/{slug}/` by `ZWorldManager` (`src/zforge/managers/zworld_manager.py`).
- `Experience` objects are managed by `ExperienceManager` (`src/zforge/managers/experience_manager.py`), stored as compiled `.ink.json` files under the experience folder.
- `ZForgeConfig` is persisted via `ConfigService` (`src/zforge/services/config_service.py`) using `platformdirs` JSON file storage.
- `ModelCatalogueEntry` entries are defined in `src/zforge/models/model_catalogue.py` (static catalogue, not persisted).
- `ModelDownloadService` (`src/zforge/services/model_download_service.py`) streams GGUF files from Hugging Face CDN.
- `ExperienceGenerationState` (`src/zforge/graphs/state.py`) is the LangGraph TypedDict that drives the multi-agent LLM workflow for experience creation.
- `CreateWorldState` (`src/zforge/graphs/state.py`) is the LangGraph TypedDict that drives the world creation pipeline.
- `AskAboutWorldState` (`src/zforge/graphs/state.py`) is the LangGraph TypedDict for the Ask About World agentic RAG process.
- `DocumentParsingState` (`src/zforge/graphs/state.py`) is the LangGraph TypedDict for the document parsing sub-graph.
- IF engine abstraction: `IfEngineConnector` (`src/zforge/services/if_engine/if_engine_connector.py`) with ink implementation (`src/zforge/services/if_engine/ink_engine_connector.py`).
- Embedding abstraction: `EmbeddingConnector` (`src/zforge/services/embedding/embedding_connector.py`) with llama.cpp implementation (`src/zforge/services/embedding/llama_cpp_embedding_connector.py`).
- LLM abstraction: `LlmConnector` (`src/zforge/services/llm/llm_connector.py`) with local llama.cpp implementation (`src/zforge/services/llm/llama_cpp_connector.py`).
