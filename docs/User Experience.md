# User Experience

## Main UI
The user interface for ZForge is built in Flutter. On PC and Mac, a main application menu takes the user to basic functions like opening an experience or creating a world. On mobile/web, the same menu is accessible by a "hamburger" menu icon to the left of the main text input at the bottom of the main window.

## Gameplay Interface
- **Input:** One-line at bottom
- **Output:** Scrolling text above
- **Display:**
  - Game output: left-justified
  - Player input: right-justified (like chat, no bubbles)
  - Font: Veteran Typewriter or similar (monospace, typewriter aesthetic)
- **Save/Load:**
  - PC/Mac: main menu bar
  - Mobile/Web: hamburger menu left of input
  - User specifies save file name
- **Input Submission:**
  - "Return" key submits
  - Button with return/line feed icon also submits (right of input)
- **Accessibility:**
  - All controls keyboard-accessible
  - High-contrast and large-text modes recommended

## Application Start
### LLM Configuration
When the user opens the application, the implemented [LLM abstraction layer]("LLM Abstraction Layer.md") will be checked to confirm that its required configuration details are both available and valid. If either fails, the user will be prompted for each required credential, with the existing credentials pre-populated if available, and the name of the LLM/engine used will be shown for clariy. For example, the implemented and selected LLM may be ChatGPT, which requires only a simple API key, so the user would then be prompted "ChatGPT configuration has not been provided. Please enter API Key:". As the LLM abstraction layer allows for arbitrary key/value pairs for configuration, the user will be prompted for as many as the selected implementation requires. When the user submits the new configuration values, they will be tested for validity; if not valid, the user will be told so and to double-check and update them. If valid, they will be stored to secure local storage.

### Player Preferences