# Experience Generation Process

```mermaid
flowchart TD
    %% Subgraph: State & Artifacts
    subgraph State [State / Artifacts]
        direction LR
        S1[(Z-World KV Store)]
        S2[(Player Profile)]
        S3[(Outline - WIP)]
        S3a[(Research Notes - Ref)]
        S4[(Polish Draft - WIP)]
        S5[(Ink Script - WIP)]
        S6[(Validation Report)]
    end

    %% Subgraph: Agents
    subgraph Agents [Agent Roles]
        A1[Outliner]
        A2[Technical Editor]
        A3[Story Editor]
        A4[Staff Writer]
        A5[Junior Scripter]
        A6[Senior Scripter]
        A7[QA Analyst]
        A8[Final Technical Reviewer]
        A9[Arbiter]
    end

    %% Subgraph: External Tools
    subgraph Tools [External Tools & Services]
        T1_qw{{query_world}}
        T1_rs{{retrieve_source}}
        T2{{Ink Compiler}}
    end

    %% Workflow Logic
    Start((Player Prompt)) --> Node_Outline

    %% Step 1: Outlining (Shift-Left)
    Node_Outline[outline_author]
    A1 -.-> Node_Outline
    S1 & S2 --> Node_Outline
    T1_qw & T1_rs --- Node_Outline
    Node_Outline --> S3
    Node_Outline --> S3a

    Node_Review_Outline{outline_reviewer}
    A2 & A3 -.-> Node_Review_Outline
    S3 & S1 --> Node_Review_Outline
    T1_qw & T1_rs --- Node_Review_Outline

    Node_Review_Outline -- "Logic Error (Tech Only)" --> Node_Outline
    Node_Review_Outline -- "Story Editor Rejected" --> Node_Arbiter_Outline{arbiter_outline}
    A9 -.-> Node_Arbiter_Outline
    Node_Arbiter_Outline -- "Overruled" --> Node_Prose
    Node_Arbiter_Outline -- "Upheld / Tech Also Fails" --> Node_Outline
    Node_Review_Outline -- "Approved" --> Node_Prose

    %% Step 2: Prose Polishing
    Node_Prose[prose_writer]
    A4 -.-> Node_Prose
    S3 & S3a --> Node_Prose
    T1_qw & T1_rs --- Node_Prose
    Node_Prose --> S4

    Node_Review_Prose{prose_reviewer}
    A2 & A3 -.-> Node_Review_Prose
    S4 & S1 --> Node_Review_Prose
    T1_qw & T1_rs --- Node_Review_Prose

    Node_Review_Prose -- "Tone/Lore/Logic Fix" --> Node_Prose
    Node_Review_Prose -- "Story Editor Rejected" --> Node_Arbiter_Prose{arbiter_prose}
    A9 -.-> Node_Arbiter_Prose
    Node_Arbiter_Prose -- "Overruled" --> Node_Script
    Node_Arbiter_Prose -- "Upheld / Tech Also Fails" --> Node_Prose
    Node_Review_Prose -- "Approved" --> Node_Script

    %% Step 3: Scripting & Technical Loops
    Node_Script[ink_scripter]
    A5 -.-> Node_Script
    S4 --> Node_Script
    Node_Script --> S5

    Node_Compile{Node: Ink_Compile_Check}
    S5 --> Node_Compile
    T2 --- Node_Compile

    Node_Compile -- "Syntax Errors" --> Node_Debug[ink_debugger]
    A6 -.-> Node_Debug
    Node_Debug -- "Retry" --> Node_Compile
    Node_Debug -- "Critical Fail" --> Fail((Exit))

    %% Step 4: Functional QA & Final Review
    Node_Compile -- "Success" --> Node_QA[ink_qa]
    A7 -.-> Node_QA
    S5 --> Node_QA

    Node_QA -- "Pathing Error" --> Node_Script
    Node_QA -- "Passed" --> Node_Final_Rev[ink_auditor]
    
    A8 -.-> Node_Final_Rev
    S5 --> Node_Final_Rev

    Node_Final_Rev -- "Structural Error" --> Node_Script
    Node_Final_Rev -- "Approved" --> End((Output .Ink))

    %% Styling
    style Node_Outline fill:#f9f,stroke:#333
    style Node_Prose fill:#bbf,stroke:#333
    style Node_Script fill:#dfd,stroke:#333
```

## Input

The following are provided as inputs to the graph at entry:

- **World KVP** (required): The [ZWorld](../src/zforge/models/zworld.py) KVP metadata for the target world.
- **World slug** (required): The kebab-case slug identifying the target world. Used to locate the Z-World hybrid data store and to construct the output path.
- **Player preferences** (required): The player's preference profile, including tone, complexity, and content advisory tolerances.
- **Player prompt** (optional): A free-text request from the player describing the experience they want (e.g. "a tense diplomatic negotiation with the High Council").

## Agent Role & Prompt Specifications

> **Note:** LLM prompts for each agent role are forthcoming and will be added here before implementation.

* **Outliner (Narrative Designer)** — node: `outline_author`, default: `Google` / `gemini-2.5-flash`
    * Generates the structural beat sheet and extracts factual reference data from the Z-World hybrid data store. Also defines the **experience title**, which is stored in state; the graph derives a kebab-case slug from this title (e.g. `"The Heist at Ironhaven"` → `the-heist-at-ironhaven`) for use in output file naming. Has access to `query_world` and `retrieve_source` tools (see [Retrieval Patterns](RAG%20and%20GRAG%20Implementation.md#retrieval-patterns)).
        * Prompt:
        ```
        You are a Lead Narrative Designer. Convert world data and player intent into a structural "beat sheet."
        1.	Query the Z-World hybrid data store using query_world to gather entities and relationships relevant to the prompt.
        2.	Create Outline (S3): Structured Markdown of scenes and branching points (using === knot_names ===).
        3.	Create Research Notes (S3a): A bulleted list of factual data retrieved from the Z-World store (e.g., location name, notable traits, key relationships). Keep these distinct from the outline.
        4.	Adhere to the Player Preference scale (1-10).        
* **Technical Editor (Internal Consistency)** — nodes: `outline_reviewer`, `prose_reviewer`, default: `Anthropic` / `claude-haiku-4-5`
    * Acts as the "Logic Police." Monitors internal plot consistency, pacing, and ensuring branching choices have actual narrative value. Does not use retrieval tools (structural review only). **The player prompt's premise is accepted as given — do not penalise relationships or scenarios that follow directly from it.**
        * Prompt:
        ```
        You are the Logic Police. Your focus is the internal consistency of the story being built.
        CRITICAL RULE: The player prompt establishes the founding premise of this experience. Do NOT penalise character relationships, motivations, or scenarios that follow directly from the player's stated premise, even if they seem unusual or contrary to established canon. Accept the premise as given and evaluate consistency within it.
        1.	Plot Holes: Ensure actions have clear motivations and that the player can't bypass critical story beats.
        2.	Branching Value: Ensure choices are meaningful and don't immediately "fold" back to the same result.
        3.	Pacing: Check if the sequence of events feels earned.
        4.	Output: {"status": "PASS/FAIL", "feedback": "Notes on plot logic"}.
* **Story Editor (World Consistency)** — nodes: `outline_reviewer`, `prose_reviewer`, default: `Anthropic` / `claude-haiku-4-5`
    * Acts as the "Lore Police." Enforces external consistency by cross-referencing all content against the Z-World store. Has access to `query_world` and `retrieve_source` tools to verify entity traits, relationships, and verbatim lore details. **The player prompt's premise is accepted as given — an AU or crossover scenario that diverges from canon is not itself a violation.**
        * Prompt:
        ```
        You are the Lore Police. Your focus is the external consistency between the draft and the Z-World KV Store (S1).
        CRITICAL RULE: The player prompt establishes the creative premise of this experience and may intentionally diverge from established world canon (e.g., an alternate-universe scenario where normally hostile factions are friendly, or a playful crossover). Do NOT flag the player's stated premise itself as a lore violation. Treat it as an accepted given. Your job is to ensure that the Z-World details referenced within the draft (entity names, traits, locations, world mechanics) are accurately represented once the premise is in play.
        1.	Lore Adherence: Ensure world facts are used accurately (e.g., if world.tech_level: medieval, flag any mention of steam engines unrelated to the premise).
        2.	Fact-Checking: Cross-reference mentions of NPCs, artifacts, or locations against the specific key-value pairs provided.
        3.	Tone: Ensure the draft matches the "voice" established in the world metadata.
        4.	Output: {"status": "PASS/FAIL", "feedback": "Notes on Z-World violations"}.
* **Staff Writer (Author)** — node: `prose_writer`, default: `Anthropic` / `claude-sonnet-4-5`
    * High-fidelity creative writing. Expands the approved outline into vivid prose and dialogue while adhering to the editors' stylistic and lore-based feedback. Has access to `query_world` and `retrieve_source` tools for on-demand character detail, sensory description, and verbatim lore.
        * Prompt:
        ``` 
        You are a Professional Fiction Author. Expand the Outline (S3) into vivid narrative text.
        1.	Use Research Notes (S3a) and query_world to retrieve additional sensory details, character traits, and relationships as needed.
        2.	Write dialogue and descriptions. Mark choices with [Choice Text].
        3.	Focus on quality of prose while respecting the "World Consistency" notes.
* **Junior Scripter (Implementation)** — node: `ink_scripter`, default: `Google` / `gemini-2.5-flash`
    * Technical implementation. Translates prose drafts into valid Ink syntax, mapping narrative choices to state variables and diverts.
        * Prompt:
        ```
        You are a Narrative Implementation Engineer. Translate the Polish Draft into valid Ink syntax.
        1.	Use === knots ===, + choices, and -> diverts.
        2.	Implement state variables as requested in the draft.
        3.	Ensure all paths lead to a valid -> END.
        
* **Senior Scripter (Debugger)** — node: `ink_debugger`, default: `OpenAI` / `gpt-4.1`
    * Advanced troubleshooting. Resolves complex syntax errors, compiler warnings, and infinite loop recursion that the Junior Scripter fails to fix.
        * Prompt:
        ```
        You are a Senior Game Developer. Fix a broken Ink script based on compiler error logs.
        1.	Fix syntax errors and break infinite loops.
        2.	Return the functional script without altering the author's prose style.
        
* **QA Analyst (Functional Playtester)** — node: `ink_qa`, default: `Google` / `gemini-2.5-flash`
    * Playability validation. Uses high-context reasoning to ensure path reachability, terminality, and logical story flow in the final script.
        * Prompt:
        ```
        You are a Game QA Lead. Perform a "Virtual Playtest" of the final Ink script.
        1.	Pathing: Ensure all knots are reachable.
        2.	Dead Ends: Flag any path that terminates without a proper -> END.
        3.	Flow: Identify areas where the player might get "stuck" in a choice cycle.
* **Final Technical Reviewer (Auditor)** — node: `ink_auditor`, default: `Anthropic` / `claude-sonnet-4-5`
    * Final script verification. Audits for advanced Ink traps like variable scope leaks, improper state-setting, and complex nested logic errors.
        * Prompt:
        ```
        You are the Lead Script Auditor. Perform a final high-level technical check on the Ink Script (S5).
        1.	Variable Integrity: Ensure variables are initialized before being checked.
        2.	State Logic: Verify that flag-setting is placed logically relative to diverts.
        3.	Structural Polish: Check for "sticky" choices or nested logic traps specific to Ink.
* **Arbiter (Premise Defender)** — nodes: `arbiter_outline`, `arbiter_prose`, default: `Google` / `gemini-2.5-flash-lite`
    * Dispute resolution. Activated only when the Story Editor rejects a draft. Receives exclusively the **player's premise** and the **Story Editor's rejection reason** (no outline, no prose). Determines whether the rejection targets a lore divergence the player deliberately introduced (OVERRULE) or a genuine world-fact error in the draft (UPHOLD).
    * If OVERRULE and the Tech Editor had also failed, the revision loop continues with only the Tech Editor's feedback.
    * If OVERRULE and the Tech Editor had passed, generation proceeds to the next stage.
        * Prompt:
        ```
        You are a Senior Creative Director arbitrating a dispute between the Story Editor (Lore Police) and the player.
        The player has submitted a premise for their interactive experience. The Story Editor reviewed the draft and rejected it with a lore concern. Your task is to determine whether the Story Editor's rejection is primarily targeting the player's stated premise itself — i.e., the editor is penalising a creative divergence the player deliberately introduced — rather than a genuine error in the draft's execution of world facts.
        Rules:
        - If the Story Editor's rejection is caused by, or flows directly from, the player's premise (e.g., the editor flags a faction alignment, relationship, or scenario that the player explicitly set up), choose OVERRULE.
        - If the rejection is caused by the writer misrepresenting world facts that are not covered or implied by the player's premise, choose UPHOLD.
        Output: {"verdict": "OVERRULE/UPHOLD", "reason": "one-sentence explanation"}

## Output

On successful completion, the graph writes the compiled Ink JSON to "{world_slug}/{experience_slug}.ink.json"

where `world_slug` is the input world slug, and `experience_slug` is the kebab-case slug derived from the Outliner-defined title.

## Implementation

- **Process slug:** `experience_generation`
- **LLM nodes:** `outline_author`, `outline_reviewer`, `arbiter_outline`, `prose_writer`, `prose_reviewer`, `arbiter_prose`, `ink_scripter`, `ink_debugger`, `ink_qa`, `ink_auditor`

### Observability State Fields

Two additional fields in `ExperienceGenerationState` drive live UI feedback during generation:

- **`last_step_rationale: str | None`** — Set by each review/QA/audit/arbiter node (`outline_reviewer`, `arbiter_outline`, `prose_reviewer`, `arbiter_prose`, `ink_qa`, `ink_auditor`) to a 1–2 sentence summary of the decision. Displayed in the UI below the status label and appended to the action log.

- **`action_log: list[dict[str, Any]]`** — Set by agentic RAG nodes (`outline_author`, `prose_writer`, and the Story Editor sub-loop inside reviewer nodes) to record each tool call made during that node's execution. Entries have `type: "tool_call"` and carry `node`, `role`, `tool`, and `args` keys. The `run_process` runner fires `on_rationale_update` for each entry immediately when the node completes. These appear in the UI action log as `> [role] tool_name(arg_preview)` lines so it is visible which world-store queries the reviewers relied on.

- **`story_editor_feedback: str | None`** — Set by `outline_reviewer`/`prose_reviewer` when the Story Editor fails; consumed by `arbiter_outline`/`arbiter_prose`. Cleared to `None` by the arbiter after use.

- **`tech_editor_feedback: str | None`** — Set by `outline_reviewer`/`prose_reviewer` when the Tech Editor also fails (alongside a Story Editor rejection). Used by the arbiter to reconstruct tech-only feedback if it overrules the Story Editor but the Tech Editor rejection stands.

  These fields are **not accumulated** across nodes — each node replaces them with its own output. Nodes that emit neither (e.g. `ink_scripter`, `ink_debugger`) simply omit both keys from their return dict.

### Pitfalls

- **`ZWorld` is a plain dataclass, not a Pydantic model.** When serialising the input `ZWorld` to a dict for the graph's initial state, use `dataclasses.asdict(zworld)`. Do **not** use `dict(zworld)` — `dict()` on a dataclass attempts to iterate it as key-value pairs and raises `TypeError: 'ZWorld' object is not iterable`. Also do not rely on `hasattr(zworld, "model_dump")` as the primary check; the correct portable pattern is `dataclasses.asdict()` for all dataclass models in this project.

- **Embedding model load must not occur on the async event loop.** `LlamaCppEmbeddingConnector.get_embeddings()` lazily constructs a `LlamaCppEmbeddings` instance on first call, which loads the GGUF file synchronously. If this is called directly inside an `async` graph node (even before `await`), it blocks the entire event loop — in BeeWare/Toga this causes the UI to freeze with no error and no log output. The correct pattern is to fold `get_embeddings()` into the same `run_in_executor` call as `embed_query()`, so the first-call model load also occurs on the thread pool:
  ```python
  query_vec = await loop.run_in_executor(
      _LLAMA_EXECUTOR,
      lambda: embedding_connector.get_embeddings().embed_query(query),
  )
  ```
  Do **not** separate the two calls as `embedder = embedding_connector.get_embeddings()` followed by `run_in_executor(..., lambda: embedder.embed_query(query))` — the first line is the blocking operation.
