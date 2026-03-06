# User Experience

## Main UI
The user interface for ZForge is built with [BeeWare](https://beeware.org/) (Toga widget toolkit). On PC and Mac, a main application menu takes the user to basic functions like opening an experience or creating a world. On mobile/web, the same menu is accessible by a "hamburger" menu icon to the left of the main text input at the bottom of the main window.

## Gameplay Interface
When an ink experience has been started, the UI looks as follows:
- **Input:** One-line at bottom
- **Output:** Scrolling text above
- **Display:**
  - Game output: left-justified
  - Player input: right-justified (like chat, no bubbles)
  - Font: Veteran Typewriter or similar (monospace, typewriter aesthetic)
- **Main menu:** A main menu appears in the header on Mac/PC and is triggered by a "hamburger" menu icon to the left of the input area while an experience is on progress on mobile/Web. Options include:
  - Create
    - World
    - Experience (only available if at least one World has been created)
  - Save/Restore
    - Save (only available while an experience is in progress)
    - Restore (only available if at least one progress has been saved)
- **Input Submission:**
  - "Return" key submits
  - Button with return/line feed icon also submits (right of input)
- **Accessibility:**
  - All controls keyboard-accessible
  - High-contrast and large-text modes recommended

### Gameplay Flow and IF Engine Integration

The gameplay interface interacts with the [IF Engine Abstraction Layer](IF%20Engine%20Abstraction%20Layer.md) as follows:

#### Starting an Experience
When the user selects an experience to play:
1. The `ExperienceManager` loads the compiled experience file (e.g., `.ink.json`)
2. Calls `IfEngineConnector.start_experience(compiled_data)`
3. The returned opening text is displayed in the output area
4. Available choices (if any) are displayed as numbered options or tappable buttons below the output

#### Player Input (Choice-Based)
For choice-based engines like ink:
1. Choices are displayed as a numbered list (e.g., "1. Go north", "2. Examine the door")
2. Player can either:
   - Tap/click a choice directly (on touch/mouse devices)
   - Type the choice number and press Enter/Return or tap the submit button
3. The selected choice index is passed to `IfEngineConnector.take_action(choice_index)`
4. The returned `ActionResult` contains:
   - `text`: New narrative text, appended to the output
   - `choices`: Next set of choices (or `None` if story ended)
   - `is_complete`: Whether the experience has ended
5. If `is_complete` is true, display an "Experience Complete" message and offer to return to home

#### Choice Display
Choices are rendered below the main output area:
- Each choice is a tappable button with the choice text
- Choices are also numbered (1, 2, 3...) so players can type the number
- When a choice is selected, it appears in the output as player input (right-justified)
- The input field shows a placeholder like "Enter choice number or tap above"

#### Saving Progress
When the user selects "Save" from the menu:
1. Calls `IfEngineConnector.save_state()` to get the current state as bytes
2. Saves the state bytes to `{experienceFolderPath}/{zworld.id}/{experience-name}.save`
3. Shows confirmation: "Progress saved"

#### Restoring Progress
When the user selects "Restore" or "Resume Experience":
1. Loads the saved state bytes from the `.save` file
2. Calls `IfEngineConnector.restore_state(saved_state)`
3. The returned `ActionResult` contains both the current narrative text and available choices
4. Displays the restored text and choices

#### Gameplay Sequence Diagram

```mermaid
sequenceDiagram
    participant U as User
    participant UI as GameplayScreen
    participant EM as ExperienceManager
    participant IFC as IfEngineConnector

    U->>UI: Select experience to play
    UI->>EM: loadExperience(experienceId)
    EM->>IFC: start_experience(compiled_data)
    IFC-->>EM: openingText
    EM-->>UI: openingText + choices
    UI-->>U: Display text and choice buttons

    loop Gameplay
        U->>UI: Tap choice or type number + Enter
        UI->>IFC: take_action(choice_index)
        IFC-->>UI: ActionResult(text, choices, is_complete)
        UI-->>U: Append text, show new choices
        
        alt is_complete
            UI-->>U: "Experience Complete" + return to home
        end
    end

    opt Save
        U->>UI: Menu > Save
        UI->>IFC: save_state()
        IFC-->>UI: stateBytes
        UI->>EM: saveProgress(experienceId, stateBytes)
        UI-->>U: "Progress saved"
    end

    opt Restore
        U->>UI: Menu > Restore
        UI->>EM: loadProgress(experienceId)
        EM-->>UI: stateBytes
        UI->>IFC: restore_state(savedState)
        IFC-->>UI: ActionResult(text, choices)
        UI-->>U: Display restored position and choices
    end
```

## Pre-Gameplay interface
If no experience is in progress:
 If progress within an experience has been saved, but that experience was not successfully completed before the last time Z-Forge was closed, the user will be asked if they want to continue {name of experience} at application start.
 In addition to their usual places in the main menu, buttons will appear offering the options to "Create World" and, if there is at least one ZWorld available, "Create Experience", and, if there is at least one experience available, "Start Experience" and, if there is at least one saved progress available within an experience, "Resume Experience".

## Application Start
### LLM Configuration
When the user opens the application, the implemented [LLM abstraction layer]("LLM Abstraction Layer.md") will be checked to confirm that its required configuration details are both available and valid. If either fails, the user will be prompted for each required credential, with the existing credentials pre-populated if available, and the name of the LLM/engine used will be shown for clariy. For example, the implemented and selected LLM may be ChatGPT, which requires only a simple API key, so the user would then be prompted "ChatGPT configuration has not been provided. Please enter API Key:". As the LLM abstraction layer allows for arbitrary key/value pairs for configuration, the user will be prompted for as many as the selected implementation requires. When the user submits the new configuration values, they will be tested for validity; if not valid, the user will be told so and to double-check and update them. If valid, they will be stored to secure local storage.

### Player Preferences
Player preferences, if not already specified, default to 5/10 complexity and 5/10 plot-to-character-development ratio. TODO: In a future version of Z-Forge, the user will be prompted with a series of Ultima-like questions to gauge their preferences.

## Back-End and Front-End Elements
### ZForgeConfig
A single `ZForgeConfig` is either loaded from insecure storage at application start or created with defaults if unavailable. This includes player preferences as defined in the [spec file](Data%20and%20File%20Specifications.md). On Mac and PC it also includes the path to the user's ZWorld and ink experience storage folders, both of which default to `~/zforge/`. On mobile these are stored in application data; on web, TODO.

`ZForgeConfig` is persisted as a JSON file in the user's config directory, accessed via the Python [`platformdirs`](https://pypi.org/project/platformdirs/) library (e.g., `user_config_dir("zforge")`).

### ZForgeSecureConfig
A single `ZForgeSecureConfig` is either loaded from secure storage at application start or created empty if unavailable. It holds a dict of `LlmConnectorConfiguration` objects keyed on connector names. Each `LlmConnectorConfiguration` holds whatever key/value pairs that connector requires.

`ZForgeSecureConfig` is persisted using the Python [`keyring`](https://pypi.org/project/keyring/) library, which delegates to the platform native keychain/keystore (see [LLM Abstraction Layer](LLM%20Abstraction%20Layer.md) for platform details). No platform-specific entitlements or manifest changes are required beyond standard BeeWare app configuration.

### ZWorldManager
A singleton ZWorldManager object handles CRUD operations on ZWorlds. Create can be invoked with an optional flag (default false) to suppress an event that is normally used to prompt the user to create an experience in the new ZWorld. ZWorld are written in JSON format to the user's ZWorld storage, which is local application storage on mobile or a configured folder on Mac or PC. (On web, TODO.)

### ExperienceManager
A singleton ExperienceManager object handles CRUD operations on experiences. Create can be invoked with an optional flag (default false) to suppress an event that is normally used to begin playing the experience.

#### Experience Storage
Experiences are organized by the ZWorld they were generated from:
- **Storage location**: `{experienceFolderPath}/{zworld.id}/` on Mac/PC; application storage on mobile
- **File naming**: `{experience-name}.{engine-extension}`, e.g., `bank-heist.ink.json`
- **File extension**: Determined by the IF engine (see [IF Engine Abstraction Layer](IF%20Engine%20Abstraction%20Layer.md)); identifies which engine can play the experience
- **Saved progress**: Stored alongside experiences as `{experience-name}.save`

Experiences are enumerated by reading the contents of world subfolders. Given the expected small number of experiences (hundreds at most for personal use), no database or index is maintained.

## Application Startup Flow

```mermaid
flowchart TD
    A[App Launch] --> B[Load ZForgeConfig\nfrom platformdirs JSON file]
    B --> C[Load ZForgeSecureConfig\nfrom keyring]
    C --> D{LLM connector\nconfigured?}
    D -- No --> E[Show LlmConfigScreen\nPrompt for credentials]
    E --> F{Credentials valid?}
    F -- No --> E
    F -- Yes --> G[Store to keyring]
    G --> H[Show HomeScreen]
    D -- Yes --> H
    H --> I{Worlds exist?}
    I -- No --> J[Show Create World button only]
    I -- Yes --> K[Show world list\n+ all available buttons]
```

## World Creation Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant H as HomeScreen
    participant C as CreateWorldScreen
    participant G as LangGraph (world_creation_graph)
    participant LLM as LLM (LangChain model)
    participant WM as ZWorldManager

    U->>H: Tap "Create World"
    H->>C: Navigate to CreateWorldScreen
    U->>C: Enter description / load file
    U->>C: Tap "Create World"
    C->>G: astream(initial_state)
    loop Validate (up to 5x)
        G->>LLM: validate_input tool call
        LLM-->>G: valid=true/false
    end
    alt Valid
        G->>LLM: create_zworld tool call
        LLM-->>G: ZWorld args
        G->>WM: create(ZWorld)
        WM-->>G: saved
        G-->>C: status=complete
        C-->>H: navigate back + show confirmation
        H-->>U: World list updated
    else Invalid
        G-->>C: status=failed, failure_reason
        C-->>U: Show error message
    end
```

## Implementation Files
- `src/zforge/__main__.py` — entry point
- `src/zforge/app.py` — `ZForgeApp` (Toga `App` subclass)
- `src/zforge/app_state.py` — `AppState`
- `src/zforge/ui/screens/home_screen.py` — `HomeScreen`
- `src/zforge/ui/screens/llm_config_screen.py` — `LlmConfigScreen`
- `src/zforge/ui/screens/create_world_screen.py` — `CreateWorldScreen`
- `src/zforge/ui/screens/preferences_screen.py` — `PreferencesScreen`
- `src/zforge/ui/screens/generate_experience_screen.py` — `GenerateExperienceScreen`

## Experience Generation UI

### Flow
1. User selects a ZWorld from the home screen and taps "Generate Experience"
2. User is presented with `GenerateExperienceScreen`, which shows:
   - The selected world's name
   - An optional text input for a player prompt (specific experience request)
   - A "Generate" button
3. Upon tapping "Generate", the `experience_generation_graph` LangGraph run begins
4. During generation, progress is displayed (see below)
5. On success, the user is prompted to play the new experience
6. On failure, the `failure_reason` is displayed (e.g., "Failed to generate a compileable script after five tries. Giving up.")

### Progress Display
During generation, the UI displays the `status_message` field streamed from the running LangGraph graph (e.g., "Author submitted outline", "Scripter approves outline", "Compiling script...").

On failure, the `failure_reason` is displayed instead.

**TODO**: Visual flowchart showing process steps with color-coded status (requires Peanut Gallery workflow model).

**TODO**: Allow user cancellation of in-progress generation.

### Experience Generation Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant H as HomeScreen
    participant GE as GenerateExperienceScreen
    participant G as LangGraph (experience_generation_graph)
    participant LLM as LLM Connector
    participant EM as ExperienceManager

    U->>H: Select ZWorld, tap "Generate Experience"
    H->>GE: Navigate with selected ZWorld
    U->>GE: Optionally enter prompt
    U->>GE: Tap "Generate"
    GE->>G: astream(initial_state)
    
    loop Generation Process
        G-->>GE: status_message update (via astream chunk)
        GE-->>U: Display progress
        G->>LLM: Agent node calls (Author, Scripter, Editors)
        LLM-->>G: Tool calls update graph state
    end
    
    alt Success
        G-->>GE: status=complete, compiled_output
        GE->>EM: save(experience)
        GE-->>U: "Experience created! Play now?"
    else Failure
        G-->>GE: status=failed, failure_reason
        GE-->>U: Display error message
    end
```
