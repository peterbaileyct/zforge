# File Storage

## Specification
When reading or writing of a file is mentioned, a path must be specified. It will not be an absolute path, and will be assumed to be relative to platform-specific sandboxed storage for Z-Forge.

## Directory Layout

| Path | Contents |
|---|---|
| `models/` | Downloaded GGUF model files (chat and embedding). Managed by Z-Forge; populated via [model download](Local%20LLM%20Execution.md#model-acquisition). |
| `bundles/` | Z-Bundle directories (one per ZWorld). |
| `experiences/` | Generated ink experience files, organised by ZWorld ID. |
| `experiences-generation/` | Debug artifacts from experience generation runs (see [Experience Generation](Experience%20Generation.md#debug-artifacts)). Organised as `{experience_slug}/debug/*.txt`. Cleaned up on app startup per the configured retention period. |
| `config.json` | `ZForgeConfig` persisted via `platformdirs.user_config_dir`. |

## Implementation
TODO: What part of this does BeeWare handle? And how will it change if/when we pivot to Flet?
