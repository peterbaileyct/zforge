# Z-Forge Data Model ER Diagram

All persistent data models used by Z-Forge. Implemented across `lib/models/`.

```mermaid
erDiagram
    ZWorld {
        string id
        string name
    }
    Location {
        string id
        string name
        string description
    }
    Character {
        string id
        string history
    }
    CharacterName {
        string name
        string context "optional"
    }
    Relationship {
        string character_a_id
        string character_b_id
        string description
    }
    WorldEvent {
        string description
        string date
    }
    ZForgeConfig {
        string zWorldFolderPath "optional; desktop only"
        string experienceFolderPath "optional; desktop only"
    }
    PlayerPreferences {
        int    characterToPlot      "1-10; 1=character, 10=plot; default 5"
        int    narrativeToDialog    "1-10; 1=narrative, 10=dialog; default 5"
        int    puzzleComplexity     "1-10; default 5"
        int    levity               "1-10; 1=somber, 10=comedic; default 5"
        string generalPreferences   "optional free text"
        int    logicalVsMood        "1-10; 1=mood priority, 10=logic priority; default 5"
    }
    ZForgeSecureConfig {
    }
    LlmConnectorConfiguration {
        string connectorName
        map    values         "key/value credential pairs"
    }

    ZWorld       ||--o{ Location                : "has"
    ZWorld       ||--o{ Character               : "has"
    ZWorld       ||--o{ Relationship            : "has"
    ZWorld       ||--o{ WorldEvent              : "has"
    Location     ||--o{ Location                : "sublocations"
    Character    ||--o{ CharacterName           : "has"
    ZForgeConfig ||--|| PlayerPreferences       : "contains"
    ZForgeSecureConfig ||--o{ LlmConnectorConfiguration : "keyed by connectorName"
```

## Runtime / Service Models

These models are created and managed by services at runtime. See the corresponding source files for details.

```mermaid
erDiagram
    Experience {
        string zworldId
        string name
        string engineExtension
        string filePath
    }
    ExperienceManager ||--o{ Experience : "manages"
```

## Transitory Process Models

Process objects are not persisted but track multi-step LLM workflows. See [Managers, Processes, and MCP Server](Managers,%20Processes,%20and%20MCP%20Server.md) for tool implementation guidelines.

```mermaid
erDiagram
    ExperienceGenerationProcess {
        ExperienceGenerationStatus status
        string statusMessage "current step description for UI"
        string failureReason "optional"
        string playerPrompt "optional input"
        string outline "optional"
        string techNotes "optional"
        string outlineNotes "optional"
        string script "optional"
        string scriptNotes "optional"
        string techEditReport "optional"
        string storyEditReport "optional"
        bytes compiledOutput "optional"
        stringArray compilerErrors "optional"
        int outlineIterations
        int scriptCompileIterations
        int authorReviewIterations
        int techEditIterations
        int storyEditIterations
    }
    CreateWorldProcess {
        CreateWorldStatus status
        string statusMessage "current step description for UI"
        string failureReason "optional"
        string inputText
        bool inputValid "optional"
        int validationIterations
    }

    ExperienceGenerationProcess ||--|| ZWorld : "input"
    ExperienceGenerationProcess ||--|| PlayerPreferences : "input"
```

## Notes
- `.zworld` files are JSON representations of `ZWorld`, stored locally by `ZWorldManager` (`lib/services/managers/zworld_manager.dart`).
- `Experience` objects are managed by `ExperienceManager` (`lib/services/managers/experience_manager.dart`), stored as compiled `.ink.json` files under the experience folder.
- `ZForgeConfig` is persisted via `ConfigService` (`lib/services/config_service.dart`) using `shared_preferences`.
- `ZForgeSecureConfig` is persisted via `SecureConfigService` (`lib/services/secure_config_service.dart`) using `flutter_secure_storage`.
- `ExperienceGenerationProcess` (`lib/processes/experience_generation_process.dart`) drives the multi-agent LLM workflow for experience creation.
- `CreateWorldProcess` (`lib/processes/create_world_process.dart`) drives the LLM workflow for world creation.
- IF engine abstraction: `IfEngineConnector` (`lib/services/if_engine/if_engine_connector.dart`) with ink implementation (`lib/services/if_engine/ink_engine_connector.dart`).
