import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show rootBundle;
import '../models/zworld.dart';
import '../models/zforge_config.dart';
import '../services/llm/llm_connector.dart';
import '../services/mcp/zforge_mcp_server.dart';
import '../services/if_engine/if_engine_connector.dart';

/// State machine status for experience generation.
/// See docs/Experience Generation.md — State Machine.
enum ExperienceGenerationStatus {
  awaitingOutline,
  awaitingOutlineReview,
  awaitingOutlineRevision,
  awaitingScript,
  awaitingScriptFix,
  awaitingAuthorReview,
  awaitingScriptRevision,
  awaitingTechEdit,
  awaitingTechFix,
  awaitingStoryEdit,
  awaitingStoryFix,
  complete,
  failed,
}

/// Drives the multi-agent LLM workflow that generates a playable interactive
/// fiction experience from a [ZWorld], [PlayerPreferences], and optional prompt.
///
/// Each step dispatches a tool call through [ZForgeMcpServer], which modifies
/// this process's state and advances the status. The process continues until
/// [status] is [ExperienceGenerationStatus.complete] or
/// [ExperienceGenerationStatus.failed].
///
/// See docs/Experience Generation.md for the full specification.
/// Implemented in: lib/processes/experience_generation_process.dart
class ExperienceGenerationProcess extends ChangeNotifier {
  static const int maxIterations = 5;

  final LlmConnector _connector;
  final IfEngineConnector _ifEngine;

  ExperienceGenerationProcess({
    required LlmConnector connector,
    required IfEngineConnector ifEngine,
  })  : _connector = connector,
        _ifEngine = ifEngine;

  // --- Inputs ---
  late ZWorld zWorld;
  late PlayerPreferences preferences;
  String? playerPrompt;

  // --- Artifacts ---
  String? outline;
  String? techNotes;
  String? outlineNotes;
  String? script;
  String? scriptNotes;
  String? techEditReport;
  String? storyEditReport;
  Uint8List? compiledOutput;
  List<String>? compilerErrors;

  // --- Iteration counters ---
  int outlineIterations = 0;
  int scriptCompileIterations = 0;
  int authorReviewIterations = 0;
  int techEditIterations = 0;
  int storyEditIterations = 0;

  // --- Status ---
  ExperienceGenerationStatus _status = ExperienceGenerationStatus.awaitingOutline;
  ExperienceGenerationStatus get status => _status;
  set status(ExperienceGenerationStatus s) {
    _status = s;
    notifyListeners();
  }

  String _statusMessage = 'Initializing…';
  String get statusMessage => _statusMessage;
  set statusMessage(String m) {
    _statusMessage = m;
    notifyListeners();
  }

  String? failureReason;

  bool get isTerminal =>
      _status == ExperienceGenerationStatus.complete ||
      _status == ExperienceGenerationStatus.failed;

  /// Whether tech editing should happen before story editing.
  bool get _techFirst => preferences.logicalVsMood > 5;

  /// Cached ZWorld spec text (loaded once from assets).
  String? _zworldSpecText;

  /// Launches the full generation pipeline.
  Future<void> run(
    ZWorld world,
    PlayerPreferences prefs,
    String? prompt,
  ) async {
    zWorld = world;
    preferences = prefs;
    playerPrompt = prompt;
    _status = ExperienceGenerationStatus.awaitingOutline;
    _statusMessage = 'Author is creating outline…';
    notifyListeners();

    try {
      _zworldSpecText = await rootBundle.loadString('assets/zworld_spec.md').catchError((_) => '');
    } catch (_) {
      _zworldSpecText = '';
    }

    try {
      while (!isTerminal) {
        await _step();
      }
    } catch (e) {
      failureReason = e.toString();
      status = ExperienceGenerationStatus.failed;
      statusMessage = 'Process failed: $failureReason';
    }
  }

  /// Executes one step of the state machine.
  Future<void> _step() async {
    switch (_status) {
      case ExperienceGenerationStatus.awaitingOutline:
        await _authorCreateOutline();
      case ExperienceGenerationStatus.awaitingOutlineReview:
        await _scripterReviewOutline();
      case ExperienceGenerationStatus.awaitingOutlineRevision:
        await _authorReviseOutline();
      case ExperienceGenerationStatus.awaitingScript:
        await _scripterWriteScript();
      case ExperienceGenerationStatus.awaitingScriptFix:
        await _scripterFixScript();
      case ExperienceGenerationStatus.awaitingAuthorReview:
        await _authorReviewScript();
      case ExperienceGenerationStatus.awaitingScriptRevision:
        await _scripterReviseScript();
      case ExperienceGenerationStatus.awaitingTechEdit:
        await _techEditorReview();
      case ExperienceGenerationStatus.awaitingTechFix:
        await _scripterFixTechIssues();
      case ExperienceGenerationStatus.awaitingStoryEdit:
        await _storyEditorReview();
      case ExperienceGenerationStatus.awaitingStoryFix:
        await _scripterFixStoryIssues();
      case ExperienceGenerationStatus.complete:
      case ExperienceGenerationStatus.failed:
        break;
    }
  }

  // -----------------------------------------------------------------------
  // Agent actions
  // -----------------------------------------------------------------------

  Future<void> _authorCreateOutline() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _authorSystemPrompt(),
      actionMessage: _authorCreateOutlineAction(),
      tool: ZForgeMcpServer.experienceAuthorSubmitOutlineTool,
    ));
    await _dispatchToolResult(result, 'experience_author_submit_outline');
  }

  Future<void> _authorReviseOutline() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _authorSystemPrompt(),
      actionMessage:
          'The Scripter has provided the following feedback on your Outline:\n\n'
          '--- Outline Notes ---\n${outlineNotes ?? "(none)"}\n---\n\n'
          'Your previous Outline:\n${outline ?? "(none)"}\n\n'
          'Your previous Tech Notes:\n${techNotes ?? "(none)"}\n\n'
          'Please revise the Outline and Tech Notes to address the Scripter\'s '
          'feedback while maintaining your creative vision, then call '
          'experience_author_submit_outline with the revised Outline and Tech Notes.',
      tool: ZForgeMcpServer.experienceAuthorSubmitOutlineTool,
    ));
    await _dispatchToolResult(result, 'experience_author_submit_outline');
  }

  Future<void> _scripterReviewOutline() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _scripterSystemPrompt(),
      actionMessage:
          'Review the following Outline for feasibility and alignment with '
          'Player Preferences.\n\n'
          '--- Outline ---\n${outline ?? "(none)"}\n---\n\n'
          '--- Tech Notes ---\n${techNotes ?? "(none)"}\n---\n\n'
          '--- Player Preferences ---\n${_preferencesText()}\n---\n\n'
          'If the Outline is acceptable, call experience_scripter_approve_outline.\n'
          'If not, call experience_scripter_reject_outline with your Outline Notes '
          'explaining what needs to change.',
      availableTools: [
        ZForgeMcpServer.experienceScripterApproveOutlineTool,
        ZForgeMcpServer.experienceScripterRejectOutlineTool,
      ],
    ));
    if (result.hasToolCall) {
      await _dispatchToolResult(result, result.toolName!);
    } else {
      statusMessage = 'Scripter approves outline';
      status = ExperienceGenerationStatus.awaitingScript;
    }
  }

  Future<void> _scripterWriteScript() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _scripterSystemPrompt(),
      actionMessage:
          'Write a complete script in the ${_ifEngine.getEngineName()} engine\'s '
          'language based on the following Outline and Tech Notes.\n\n'
          '--- Outline ---\n${outline ?? "(none)"}\n---\n\n'
          '--- Tech Notes ---\n${techNotes ?? "(none)"}\n---\n\n'
          '--- Player Preferences ---\n${_preferencesText()}\n---\n\n'
          'Provide the complete script by calling experience_scripter_submit_script.',
      tool: ZForgeMcpServer.experienceScripterSubmitScriptTool,
    ));
    await _dispatchToolResult(result, 'experience_scripter_submit_script');
  }

  Future<void> _scripterFixScript() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _scripterSystemPrompt(),
      actionMessage:
          'The following script failed to compile. Fix the errors and resubmit.\n\n'
          '--- Script ---\n${script ?? "(none)"}\n---\n\n'
          '--- Compiler Errors ---\n${compilerErrors?.join('\n') ?? "(none)"}\n---\n\n'
          'Submit the corrected script by calling experience_scripter_submit_script.',
      tool: ZForgeMcpServer.experienceScripterSubmitScriptTool,
    ));
    await _dispatchToolResult(result, 'experience_scripter_submit_script');
  }

  Future<void> _authorReviewScript() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _authorSystemPrompt(),
      actionMessage:
          'Review the following Script against your Outline.\n\n'
          '--- Your Outline ---\n${outline ?? "(none)"}\n---\n\n'
          '--- Script ---\n${script ?? "(none)"}\n---\n\n'
          'If the Script faithfully implements your Outline, call '
          'experience_author_approve_script.\n'
          'If not, call experience_author_reject_script with specific Script '
          'Notes describing what must change.',
      availableTools: [
        ZForgeMcpServer.experienceAuthorApproveScriptTool,
        ZForgeMcpServer.experienceAuthorRejectScriptTool,
      ],
    ));
    if (result.hasToolCall) {
      await _dispatchToolResult(result, result.toolName!);
    } else {
      statusMessage = 'Author approves script';
      status = _techFirst
          ? ExperienceGenerationStatus.awaitingTechEdit
          : ExperienceGenerationStatus.awaitingStoryEdit;
    }
  }

  Future<void> _scripterReviseScript() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _scripterSystemPrompt(),
      actionMessage:
          'The Author has requested changes to the Script.\n\n'
          '--- Author\'s Script Notes ---\n${scriptNotes ?? "(none)"}\n---\n\n'
          '--- Current Script ---\n${script ?? "(none)"}\n---\n\n'
          '--- Outline ---\n${outline ?? "(none)"}\n---\n\n'
          'Revise the Script to address the Author\'s feedback and call '
          'experience_scripter_submit_script with the updated script.',
      tool: ZForgeMcpServer.experienceScripterSubmitScriptTool,
    ));
    await _dispatchToolResult(result, 'experience_scripter_submit_script');
  }

  Future<void> _techEditorReview() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _techEditorSystemPrompt(),
      actionMessage:
          'Review the following Script for logical consistency.\n\n'
          '--- Script ---\n${script ?? "(none)"}\n---\n\n'
          '--- Tech Notes ---\n${techNotes ?? "(none)"}\n---\n\n'
          '--- Player\'s Logical vs. Mood preference ---\n'
          '${preferences.logicalVsMood}/10 (1=mood priority, 10=logic priority)\n---\n\n'
          'If the Script is logically consistent (or issues are within the '
          'player\'s tolerance), call experience_techeditor_approve.\n'
          'If not, call experience_techeditor_reject with your Tech Edit Report.',
      availableTools: [
        ZForgeMcpServer.experienceTecheditorApproveTool,
        ZForgeMcpServer.experienceTecheditorRejectTool,
      ],
    ));
    if (result.hasToolCall) {
      await _dispatchToolResult(result, result.toolName!);
    } else {
      statusMessage = 'Technical Editor approves';
      // Tech editor done—move to story edit or complete
      if (storyEditIterations > 0 || !_techFirst) {
        status = ExperienceGenerationStatus.complete;
      } else {
        status = ExperienceGenerationStatus.awaitingStoryEdit;
      }
    }
  }

  Future<void> _scripterFixTechIssues() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _scripterSystemPrompt(),
      actionMessage:
          'The Technical Editor found logical inconsistencies.\n\n'
          '--- Tech Edit Report ---\n${techEditReport ?? "(none)"}\n---\n\n'
          '--- Current Script ---\n${script ?? "(none)"}\n---\n\n'
          '--- Tech Notes ---\n${techNotes ?? "(none)"}\n---\n\n'
          'Fix the logical inconsistencies and call '
          'experience_scripter_submit_script with the corrected script.',
      tool: ZForgeMcpServer.experienceScripterSubmitScriptTool,
    ));
    await _dispatchToolResult(result, 'experience_scripter_submit_script');
  }

  Future<void> _storyEditorReview() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _storyEditorSystemPrompt(),
      actionMessage:
          'Review the following Script for alignment with player preferences.\n\n'
          '--- Script ---\n${script ?? "(none)"}\n---\n\n'
          '--- Player Preferences ---\n${_preferencesText()}\n---\n\n'
          '--- Player Prompt ---\n${playerPrompt ?? "(none)"}\n---\n\n'
          'If the Script aligns well with the player\'s preferences, call '
          'experience_storyeditor_approve.\n'
          'If not, call experience_storyeditor_reject with your Story Edit Report.',
      availableTools: [
        ZForgeMcpServer.experienceStoryeditorApproveTool,
        ZForgeMcpServer.experienceStoryeditorRejectTool,
      ],
    ));
    if (result.hasToolCall) {
      await _dispatchToolResult(result, result.toolName!);
    } else {
      statusMessage = 'Story Editor approves';
      if (techEditIterations > 0 || _techFirst) {
        status = ExperienceGenerationStatus.complete;
      } else {
        status = ExperienceGenerationStatus.awaitingTechEdit;
      }
    }
  }

  Future<void> _scripterFixStoryIssues() async {
    final result = await _connector.execute(LlmQuery(
      systemMessage: _scripterSystemPrompt(),
      actionMessage:
          'The Story Editor believes the Script does not match player preferences.\n\n'
          '--- Story Edit Report ---\n${storyEditReport ?? "(none)"}\n---\n\n'
          '--- Current Script ---\n${script ?? "(none)"}\n---\n\n'
          '--- Outline ---\n${outline ?? "(none)"}\n---\n\n'
          '--- Player Preferences ---\n${_preferencesText()}\n---\n\n'
          'Modify the Script to better match player preferences and call '
          'experience_scripter_submit_script with the updated script.',
      tool: ZForgeMcpServer.experienceScripterSubmitScriptTool,
    ));
    await _dispatchToolResult(result, 'experience_scripter_submit_script');
  }

  // -----------------------------------------------------------------------
  // Tool dispatch helper
  // -----------------------------------------------------------------------

  Future<void> _dispatchToolResult(LlmResult result, String expectedTool) async {
    if (!result.hasToolCall) {
      throw Exception('LLM did not return a tool call (expected $expectedTool)');
    }
    final toolName = result.toolName ?? expectedTool;
    await ZForgeMcpServer.instance.dispatchExperience(
      toolName,
      result.toolCallArguments!,
      this,
      _ifEngine,
    );
  }

  // -----------------------------------------------------------------------
  // System prompts (from spec)
  // -----------------------------------------------------------------------

  String _authorSystemPrompt() => '''
Role: You are an expert interactive fiction Author, equivalent to a story writer and director with final creative authority. You work as part of a collaborative team to create engaging interactive fiction experiences tailored to individual players.

Team Context: You collaborate with a Scripter (who translates your vision into ink script), a Technical Editor (who ensures logical consistency), and a Story Editor (who validates alignment with player preferences). You have final edit rights over the creative direction.

Your Responsibilities:
1. Receive and synthesize inputs: ZWorld (setting/characters/events), Player Preferences (narrative style, complexity, tone), and optional Player Prompt (specific experience request).
2. Produce a detailed Story Outline that serves as a blueprint for the Scripter.
3. Produce Tech Notes that document any intentional logical exceptions (e.g., "time flows differently in the dream sequences" or "rooms may not connect consistently while aboard the chaos ship").

Outline Requirements:
- Opening: Establish the initial situation, setting, and protagonist's goal or conflict.
- Key Scenes: List 5-15 major story beats, each with: location, characters involved, core conflict or revelation, and branching possibilities.
- Branching Structure: Identify 2-4 major decision points that significantly alter the story's direction, and note how branches may reconverge.
- Endings: Describe 2-5 possible conclusions based on player choices, ensuring each feels earned.
- Tone and Pacing: Note the intended emotional arc and how it aligns with player preferences.
- Character Arcs: For key characters, describe how they may develop based on player interactions.

When Receiving Feedback:
- From Scripter (Outline Notes): Carefully consider whether the outline is implementable and aligns with player preferences. Revise to address legitimate concerns while maintaining creative vision.
- When reviewing completed Scripts: Compare against your Outline. Produce Script Notes if the script diverges unacceptably from your vision, being specific about what must change and why.

Output Format: Provide the Outline as structured prose with clear section headers. Provide Tech Notes as a bulleted list of exceptions, or state "No special technical exceptions" if standard logic applies throughout.
''';

  String _scripterSystemPrompt() => '''
Role: You are an expert interactive fiction scripter and the technical implementer of the creative team. You translate the Author's vision into playable interactive fiction using the scripting language of the configured IF engine.

Team Context: You collaborate with an Author (provides story outlines, has final creative authority), a Technical Editor (validates logical consistency), and a Story Editor (ensures player preference alignment). You are the bridge between creative vision and playable experience.

IF Engine: ${_ifEngine.getEngineName()}

${_ifEngine.getScriptPrompt()}

Your Responsibilities:
1. Evaluate incoming Outlines for feasibility and preference alignment before writing.
2. Transform approved Outlines into complete, valid scripts in the configured engine's language.
3. Incorporate feedback from the Author (Script Notes), Technical Editor (Tech Edit Report), and Story Editor (Story Edit Report).
4. Ensure scripts compile successfully when validated through the IfEngineConnector.

When Evaluating Outlines:
- Consider whether the Outline can be effectively implemented in the target engine's format.
- Check alignment with Player Preferences—flag concerns in Outline Notes if you see mismatches the Author may have missed.
- If you have concerns, produce Outline Notes explaining the issues and suggesting alternatives.
- If the Outline is acceptable, proceed to scripting.

Script Quality Standards:
- Every choice should feel meaningful—avoid false choices where all options lead to identical outcomes.
- Maintain clear narrative flow; players should understand where they are and what's happening.
- Balance branch complexity with convergence—too many permanent branches become unmanageable.
- Use the engine's state tracking features to track state that affects future choices and text variations.
- Include appropriate pacing: moments of tension, relief, discovery, and reflection.
- Follow all syntax requirements specified in the engine's script prompt.

Output Format: Provide the complete script in a single code block. Include a brief summary of the script structure (major sections and branches) before the code block.

When Incorporating Feedback:
- Author Script Notes: These have highest priority—the Author has final creative authority.
- Tech Edit Report: Fix logical inconsistencies while preserving creative intent.
- Story Edit Report: Adjust tone, pacing, or content balance to better match player preferences.
- Compiler Errors: Fix syntax issues while maintaining the intended narrative. Refer to the engine's script prompt for syntax guidance.
''';

  String _techEditorSystemPrompt() => '''
Role: You are a meticulous Technical Editor specializing in interactive fiction. Your focus is ensuring logical and spatial consistency within the narrative, respecting any intentional exceptions documented by the Author.

Team Context: You work alongside an Author (creative lead), a Scripter (implements the story in the configured IF engine's language), and a Story Editor (validates player preference alignment). Your domain is internal consistency, not creative direction or player preference matching.

Your Responsibilities:
1. Review scripts for logical inconsistencies that would break immersion or confuse players.
2. Respect the Author's Tech Notes—documented exceptions are intentional and should not be flagged.
3. Produce a Tech Edit Report when issues exceed the player's indicated tolerance (per their "Logical vs. mood scale" preference).

Categories of Issues to Check:
- Spatial Consistency: If location A is described as north of location B, then B should be south of A (unless Tech Notes indicate otherwise). Check for impossible geography.
- Temporal Consistency: Events should occur in a logical sequence. Characters cannot reference events that haven't happened yet in the current branch.
- Character Consistency: Names, descriptions, relationships, and knowledge should remain consistent unless explicitly changed by story events.
- Object/State Tracking: Items obtained, lost, or transformed should be tracked correctly. A character cannot use an item they don't have.
- Dialogue Consistency: Information conveyed in dialogue should not contradict established facts (unless the character is intentionally lying or mistaken, which should be clear from context).
- World Rule Consistency: If the world establishes rules (magic systems, technology limits, social structures), the script should adhere to them.

Evaluation Threshold:
- The player's "Logical vs. mood scale" preference (1-10) determines your strictness.
- Low scores (1-3): Only flag issues that would make the story incomprehensible or unplayable.
- Medium scores (4-6): Flag issues that noticeably break immersion for attentive players.
- High scores (7-10): Flag any inconsistency, however minor, that a detail-oriented player might notice.

Output Format - Tech Edit Report:
- If no issues: State "No logical inconsistencies found that exceed player tolerance."
- If issues found: List each issue with:
  - Location in script (knot/stitch name or approximate location)
  - Description of the inconsistency
  - Severity (Minor/Moderate/Major)
  - Suggested fix (brief)
''';

  String _storyEditorSystemPrompt() => '''
Role: You are a discerning Story Editor specializing in interactive fiction. Your focus is ensuring the completed script delivers an experience aligned with the player's stated preferences and any specific prompt they provided.

Team Context: You work alongside an Author (creative lead), a Scripter (implements the story in the configured IF engine's language), and a Technical Editor (ensures logical consistency). Your domain is player satisfaction and preference alignment, not technical correctness.

Your Responsibilities:
1. Review scripts against Player Preferences and the optional Player Prompt.
2. Evaluate whether the experience will satisfy this specific player based on their stated preferences.
3. Produce a Story Edit Report when the script meaningfully deviates from what the player requested or prefers.

Preference Dimensions to Evaluate:
- Character vs. Plot (1=character, 10=plot): Does the script emphasize what the player prefers? A character-focused player should see deep character development and meaningful relationships. A plot-focused player should experience exciting events and narrative momentum.
- Narrative vs. Dialog (1=narrative, 10=dialog): Does the script's balance match? High narrative preference means rich descriptions; high dialog preference means character voices carry the story.
- Puzzle Complexity (1=minimal, 10=challenging): Are puzzles present and appropriately difficult? A low score means puzzles should be simple or absent; a high score means meaningful obstacles requiring thought.
- Levity (1=somber, 10=comedic): Does the tone match? Check humor frequency, dark themes, and overall emotional register.
- General Preferences: Does the script honor any specific requests in the player's free-text preferences?
- Player Prompt: If provided, does the script deliver the specific experience requested?

Evaluation Approach:
- Consider the script holistically—individual moments may vary from the overall preference balance.
- Weight the Player Prompt heavily if provided; it represents what they want right now.
- Be pragmatic: perfect alignment is impossible. Flag issues only when the mismatch would noticeably disappoint the player.

Output Format - Story Edit Report:
- If aligned: State "Script aligns well with player preferences. No significant adjustments needed."
- If misaligned: List each concern with:
  - Preference dimension affected
  - Current state in script
  - Player's preference/expectation
  - Specific examples from the script
  - Suggested direction for revision (not specific rewrites—that's the Scripter's job)
''';

  // -----------------------------------------------------------------------
  // Action-message helpers
  // -----------------------------------------------------------------------

  String _authorCreateOutlineAction() {
    final zworldJson = jsonEncode(zWorld.toJson());
    final specNote = (_zworldSpecText != null && _zworldSpecText!.isNotEmpty)
        ? '\n\nThe following describes the ZWorld format:\n$_zworldSpecText\n'
        : '';

    return 'Create a Story Outline and Tech Notes for an interactive fiction '
        'experience based on the following inputs.\n\n'
        '--- ZWorld ---\n$zworldJson\n---$specNote\n\n'
        '--- Player Preferences ---\n${_preferencesText()}\n---\n\n'
        '${playerPrompt != null ? '--- Player Prompt ---\n$playerPrompt\n---\n\n' : ''}'
        'Call experience_author_submit_outline with your Outline and Tech Notes.';
  }

  String _preferencesText() {
    final p = preferences;
    return 'Character to Plot: ${p.characterToPlot}/10 (1=character, 10=plot)\n'
        'Narrative to Dialog: ${p.narrativeToDialog}/10 (1=narrative, 10=dialog)\n'
        'Puzzle Complexity: ${p.puzzleComplexity}/10 (1=minimal, 10=challenging)\n'
        'Levity: ${p.levity}/10 (1=somber, 10=comedic)\n'
        'Logical vs. Mood: ${p.logicalVsMood}/10 (1=mood priority, 10=logic priority)\n'
        '${p.generalPreferences != null ? 'General Preferences: ${p.generalPreferences}\n' : ''}';
  }
}
