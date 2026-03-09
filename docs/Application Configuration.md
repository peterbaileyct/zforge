# Application Configuration
## LLM Configuration
### Processes
The provider and model used for each LLM node in each [Process](Processes.md) can be configured. The specification for each Process needs to specify a slug for the process and for each node, allowing for consistent identification of the configuration values for each process and each node.
### Connectors
The LLM Connector for each provider identifies what must be configured; typically this is only an API key. This is kept in secure storage, not a plain file.

## Parsing Pipeline

Chunk-splitting parameters for the [Parsing Documents to Z-Bundles](Parsing%20Documents%20to%20Z-Bundles.md) pipeline are stored in `ZForgeConfig` as `parsing_chunk_size` (default 10,000 characters) and `parsing_chunk_overlap` (default 500 characters).

## Implementation
Nearly all application preferences are persisted as JSON in `zforge_config.json` located in `platformdirs.user_config_dir("zforge")` (see `ConfigService`). Values are read at startup and saved when the user changes a setting. Preferences that require secure storage (e.g., API keys) are stored in the host platform’s protected key-value store (macOS Keychain, Windows Credential Locker, etc.) via the BeeWare secure storage helpers. When cross-platform access is required, the helpers expose a `keyring`-style abstraction so each secret feels like an app-scoped key/value pair instead of an ad-hoc file. Keys for LLM connector configuration KVPs are prefixed with `llm.{provider}.` (for example, `llm.anthropic.apikey`).

Process-specific LLM configuration — such as the per-node provider/model pairing used by world generation — is described in the [World Generation](World%20Generation.md#implementation) spec. That document is authoritative for the structure of the `llm_nodes` map stored inside `zforge_config.json`, while this file describes the general storage surface and validation/secure-storage guarantees.

`ZForgeApp.startup` asks `ConfigService.has_llm_config()` to check for a non-empty `llm_nodes` section in the raw JSON (not `exists()` alone); when that check fails the app immediately opens the LLM Configuration screen with an explanatory message ([src/zforge/app.py](src/zforge/app.py#L41-L120)). Process / node default values are defined once in [src/zforge/models/process_config.py](src/zforge/models/process_config.py) and consumed by both `ConfigService._apply_defaults` and `LlmConfigScreen`.
