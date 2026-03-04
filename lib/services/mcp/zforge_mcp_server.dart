import '../../models/zworld.dart';
import '../../models/zforge_config.dart';
import '../managers/zworld_manager.dart';
import '../llm/llm_connector.dart';
import '../if_engine/if_engine_connector.dart';
import '../../processes/experience_generation_process.dart';

/// In-process MCP tool dispatcher for Z-Forge.
///
/// ZForgeMcpServer acts as the bridge between LLM tool calls and application
/// singletons. When an [LlmConnector] receives a tool call response from the
/// LLM, it invokes [ZForgeMcpServer.instance.dispatch] with the tool name and
/// arguments.
///
/// Registered tools:
/// - [createZWorldTool]: Creates a ZWorld and saves it via [ZWorldManager].
/// - Experience generation tools (10): See docs/Experience Generation.md.
///
/// See docs/LLM Abstraction Layer.md and docs/Managers, Processes, and MCP Server.md.
/// Implemented in: lib/services/mcp/zforge_mcp_server.dart
class ZForgeMcpServer {
  ZForgeMcpServer._();
  static final ZForgeMcpServer instance = ZForgeMcpServer._();

  /// The [LlmTool] definition for CreateZWorld, to be passed in [LlmQuery.tool].
  static final LlmTool createZWorldTool = LlmTool(
    name: 'create_zworld',
    description:
        'Creates a structured ZWorld object from the described fictional world '
        'and saves it to storage. Call this exactly once with all fields populated.',
    parametersSchema: {
      'type': 'object',
      'required': ['id', 'name', 'locations', 'characters', 'relationships', 'events'],
      'properties': {
        'id': {'type': 'string', 'description': 'Unique text identifier for the world (e.g. "discworld"). Used for cross-referencing and file organization. Lowercase, hyphen-separated.'},
        'name': {'type': 'string', 'description': 'The name of the world.'},
        'locations': {
          'type': 'array',
          'description': 'Top-level locations in the world.',
          'items': {
            'type': 'object',
            'required': ['id', 'name', 'description'],
            'properties': {
              'id': {'type': 'string'},
              'name': {'type': 'string'},
              'description': {'type': 'string'},
              'sublocations': {
                'type': 'array',
                'items': {'\$ref': '#/properties/locations/items'},
              },
            },
          },
        },
        'characters': {
          'type': 'array',
          'items': {
            'type': 'object',
            'required': ['id', 'names', 'history'],
            'properties': {
              'id': {'type': 'string'},
              'names': {
                'type': 'array',
                'items': {
                  'type': 'object',
                  'required': ['name'],
                  'properties': {
                    'name': {'type': 'string'},
                    'context': {'type': 'string'},
                  },
                },
              },
              'history': {'type': 'string'},
            },
          },
        },
        'relationships': {
          'type': 'array',
          'items': {
            'type': 'object',
            'required': ['character_a_id', 'character_b_id', 'description'],
            'properties': {
              'character_a_id': {'type': 'string'},
              'character_b_id': {'type': 'string'},
              'description': {'type': 'string'},
            },
          },
        },
        'events': {
          'type': 'array',
          'items': {
            'type': 'object',
            'required': ['description', 'date'],
            'properties': {
              'description': {'type': 'string'},
              'date': {'type': 'string'},
            },
          },
        },
      },
    },
  );

  /// Dispatches an LLM tool call by name. Returns the created [ZWorld] if the
  /// tool was create_zworld, otherwise throws [ArgumentError].
  Future<ZWorld> dispatch(
    String toolName,
    Map<String, dynamic> args,
    ZForgeConfig config, {
    bool suppressEvent = false,
  }) async {
    if (toolName == createZWorldTool.name) {
      final world = ZWorld.fromJson(args);
      await ZWorldManager.instance.create(world, config,
          suppressEvent: suppressEvent);
      return world;
    }
    throw ArgumentError('Unknown MCP tool: $toolName');
  }

  // =========================================================================
  // Experience Generation Tools
  // =========================================================================

  /// All experience generation tools (for inclusion in multi-tool LLM calls).
  static List<LlmTool> get experienceTools => [
        experienceAuthorSubmitOutlineTool,
        experienceScripterApproveOutlineTool,
        experienceScripterRejectOutlineTool,
        experienceScripterSubmitScriptTool,
        experienceAuthorApproveScriptTool,
        experienceAuthorRejectScriptTool,
        experienceTecheditorApproveTool,
        experienceTecheditorRejectTool,
        experienceStoryeditorApproveTool,
        experienceStoryeditorRejectTool,
      ];

  static final LlmTool experienceAuthorSubmitOutlineTool = LlmTool(
    name: 'experience_author_submit_outline',
    description:
        'Author submits their Story Outline and Tech Notes for Scripter review.',
    parametersSchema: {
      'type': 'object',
      'required': ['outline', 'tech_notes'],
      'properties': {
        'outline': {
          'type': 'string',
          'description': 'The detailed Story Outline.',
        },
        'tech_notes': {
          'type': 'string',
          'description':
              'Tech Notes documenting intentional logical exceptions, '
              'or "No special technical exceptions".',
        },
      },
    },
  );

  static final LlmTool experienceScripterApproveOutlineTool = LlmTool(
    name: 'experience_scripter_approve_outline',
    description:
        'Scripter approves the Outline as suitable and feasible. '
        'Call this when the Outline is acceptable.',
    parametersSchema: {
      'type': 'object',
      'properties': {},
    },
  );

  static final LlmTool experienceScripterRejectOutlineTool = LlmTool(
    name: 'experience_scripter_reject_outline',
    description:
        'Scripter rejects the Outline with feedback. '
        'Call this when the Outline has issues that must be addressed.',
    parametersSchema: {
      'type': 'object',
      'required': ['outline_notes'],
      'properties': {
        'outline_notes': {
          'type': 'string',
          'description': 'Feedback on why the Outline is not suitable.',
        },
      },
    },
  );

  static final LlmTool experienceScripterSubmitScriptTool = LlmTool(
    name: 'experience_scripter_submit_script',
    description:
        'Scripter submits a complete script for compilation and review. '
        'The script will be automatically compiled via the IF engine.',
    parametersSchema: {
      'type': 'object',
      'required': ['script'],
      'properties': {
        'script': {
          'type': 'string',
          'description': 'The complete script in the IF engine\'s language.',
        },
      },
    },
  );

  static final LlmTool experienceAuthorApproveScriptTool = LlmTool(
    name: 'experience_author_approve_script',
    description:
        'Author approves the Script as faithfully implementing the Outline.',
    parametersSchema: {
      'type': 'object',
      'properties': {},
    },
  );

  static final LlmTool experienceAuthorRejectScriptTool = LlmTool(
    name: 'experience_author_reject_script',
    description:
        'Author rejects the Script with feedback (Script Notes) '
        'about what must change.',
    parametersSchema: {
      'type': 'object',
      'required': ['script_notes'],
      'properties': {
        'script_notes': {
          'type': 'string',
          'description': 'Specific feedback on how the Script diverges from the Outline.',
        },
      },
    },
  );

  static final LlmTool experienceTecheditorApproveTool = LlmTool(
    name: 'experience_techeditor_approve',
    description:
        'Technical Editor approves the Script as logically consistent.',
    parametersSchema: {
      'type': 'object',
      'properties': {},
    },
  );

  static final LlmTool experienceTecheditorRejectTool = LlmTool(
    name: 'experience_techeditor_reject',
    description:
        'Technical Editor rejects the Script due to logical inconsistencies.',
    parametersSchema: {
      'type': 'object',
      'required': ['tech_edit_report'],
      'properties': {
        'tech_edit_report': {
          'type': 'string',
          'description': 'Report detailing logical inconsistencies found.',
        },
      },
    },
  );

  static final LlmTool experienceStoryeditorApproveTool = LlmTool(
    name: 'experience_storyeditor_approve',
    description:
        'Story Editor approves the Script as aligned with player preferences.',
    parametersSchema: {
      'type': 'object',
      'properties': {},
    },
  );

  static final LlmTool experienceStoryeditorRejectTool = LlmTool(
    name: 'experience_storyeditor_reject',
    description:
        'Story Editor rejects the Script due to preference misalignment.',
    parametersSchema: {
      'type': 'object',
      'required': ['story_edit_report'],
      'properties': {
        'story_edit_report': {
          'type': 'string',
          'description': 'Report describing preference alignment issues.',
        },
      },
    },
  );

  /// Dispatches an experience-generation tool call, modifying [process] state.
  ///
  /// Returns a JSON-encodable map with the tool result per the MCP Tool Schema
  /// Standard (see docs/Managers, Processes, and MCP Server.md).
  Future<Map<String, dynamic>> dispatchExperience(
    String toolName,
    Map<String, dynamic> args,
    ExperienceGenerationProcess process,
    IfEngineConnector ifEngine,
  ) async {
    switch (toolName) {
      case 'experience_author_submit_outline':
        return _authorSubmitOutline(args, process);
      case 'experience_scripter_approve_outline':
        return _scripterApproveOutline(process);
      case 'experience_scripter_reject_outline':
        return _scripterRejectOutline(args, process);
      case 'experience_scripter_submit_script':
        return await _scripterSubmitScript(args, process, ifEngine);
      case 'experience_author_approve_script':
        return _authorApproveScript(process);
      case 'experience_author_reject_script':
        return _authorRejectScript(args, process);
      case 'experience_techeditor_approve':
        return _techeditorApprove(process);
      case 'experience_techeditor_reject':
        return _techeditorReject(args, process);
      case 'experience_storyeditor_approve':
        return _storyeditorApprove(process);
      case 'experience_storyeditor_reject':
        return _storyeditorReject(args, process);
      default:
        throw ArgumentError('Unknown experience tool: $toolName');
    }
  }

  // --- Tool implementations ---

  Map<String, dynamic> _authorSubmitOutline(
    Map<String, dynamic> args,
    ExperienceGenerationProcess p,
  ) {
    p.outline = args['outline'] as String?;
    p.techNotes = args['tech_notes'] as String?;
    p.statusMessage = 'Author submitted outline';
    p.status = ExperienceGenerationStatus.awaitingOutlineReview;
    return {
      'success': true,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
    };
  }

  Map<String, dynamic> _scripterApproveOutline(ExperienceGenerationProcess p) {
    p.statusMessage = 'Scripter approves outline';
    p.status = ExperienceGenerationStatus.awaitingScript;
    return {
      'success': true,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
    };
  }

  Map<String, dynamic> _scripterRejectOutline(
    Map<String, dynamic> args,
    ExperienceGenerationProcess p,
  ) {
    p.outlineNotes = args['outline_notes'] as String?;
    p.outlineIterations++;
    if (p.outlineIterations >= ExperienceGenerationProcess.maxIterations) {
      p.failureReason =
          'Failed to produce an acceptable outline after '
          '${ExperienceGenerationProcess.maxIterations} attempts.';
      p.statusMessage = p.failureReason!;
      p.status = ExperienceGenerationStatus.failed;
    } else {
      p.statusMessage = 'Scripter requests outline revision '
          '(attempt ${p.outlineIterations}/${ExperienceGenerationProcess.maxIterations})';
      p.status = ExperienceGenerationStatus.awaitingOutlineRevision;
    }
    return {
      'success': p.status != ExperienceGenerationStatus.failed,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
      'iterationsRemaining':
          ExperienceGenerationProcess.maxIterations - p.outlineIterations,
    };
  }

  Future<Map<String, dynamic>> _scripterSubmitScript(
    Map<String, dynamic> args,
    ExperienceGenerationProcess p,
    IfEngineConnector ifEngine,
  ) async {
    p.script = args['script'] as String?;
    p.statusMessage = 'Compiling script…';
    p.status = p.status; // trigger notifyListeners via setter

    if (p.script == null || p.script!.isEmpty) {
      p.compilerErrors = ['No script provided.'];
      p.scriptCompileIterations++;
      if (p.scriptCompileIterations >=
          ExperienceGenerationProcess.maxIterations) {
        p.failureReason =
            'Failed to generate a compileable script after '
            '${ExperienceGenerationProcess.maxIterations} tries. Giving up.';
        p.statusMessage = p.failureReason!;
        p.status = ExperienceGenerationStatus.failed;
      } else {
        p.statusMessage = 'Script is empty — Scripter must retry';
        p.status = ExperienceGenerationStatus.awaitingScriptFix;
      }
      return {
        'success': false,
        'statusMessage': p.statusMessage,
        'validationErrors': p.compilerErrors,
        'processStatus': p.status.name,
      };
    }

    final buildResult = await ifEngine.build(p.script!);
    if (buildResult.success) {
      p.compiledOutput = buildResult.output;
      p.compilerErrors = null;
      p.scriptCompileIterations = 0; // reset on success
      p.statusMessage = 'Script compiled successfully';

      // Determine next state depending on where we came from.
      if (p.status == ExperienceGenerationStatus.awaitingScriptFix ||
          p.status == ExperienceGenerationStatus.awaitingScript) {
        p.status = ExperienceGenerationStatus.awaitingAuthorReview;
      } else if (p.status == ExperienceGenerationStatus.awaitingScriptRevision) {
        p.status = ExperienceGenerationStatus.awaitingAuthorReview;
      } else if (p.status == ExperienceGenerationStatus.awaitingTechFix ||
          p.status == ExperienceGenerationStatus.awaitingStoryFix) {
        // After editor-requested fix, return to first editor per preferences.
        p.status = p.preferences.logicalVsMood > 5
            ? ExperienceGenerationStatus.awaitingTechEdit
            : ExperienceGenerationStatus.awaitingStoryEdit;
      } else {
        p.status = ExperienceGenerationStatus.awaitingAuthorReview;
      }
      return {
        'success': true,
        'statusMessage': p.statusMessage,
        'processStatus': p.status.name,
      };
    } else {
      p.compilerErrors = buildResult.errors;
      p.compiledOutput = null;
      p.scriptCompileIterations++;
      if (p.scriptCompileIterations >=
          ExperienceGenerationProcess.maxIterations) {
        p.failureReason =
            'Failed to generate a compileable script after '
            '${ExperienceGenerationProcess.maxIterations} tries. Giving up.';
        p.statusMessage = p.failureReason!;
        p.status = ExperienceGenerationStatus.failed;
      } else {
        p.statusMessage = 'Compilation failed '
            '(attempt ${p.scriptCompileIterations}/${ExperienceGenerationProcess.maxIterations})';
        p.status = ExperienceGenerationStatus.awaitingScriptFix;
      }
      return {
        'success': false,
        'statusMessage': p.statusMessage,
        'validationErrors': p.compilerErrors,
        'processStatus': p.status.name,
        'iterationsRemaining':
            ExperienceGenerationProcess.maxIterations -
                p.scriptCompileIterations,
      };
    }
  }

  Map<String, dynamic> _authorApproveScript(ExperienceGenerationProcess p) {
    p.statusMessage = 'Author approves script';
    p.status = p.preferences.logicalVsMood > 5
        ? ExperienceGenerationStatus.awaitingTechEdit
        : ExperienceGenerationStatus.awaitingStoryEdit;
    return {
      'success': true,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
    };
  }

  Map<String, dynamic> _authorRejectScript(
    Map<String, dynamic> args,
    ExperienceGenerationProcess p,
  ) {
    p.scriptNotes = args['script_notes'] as String?;
    p.authorReviewIterations++;
    if (p.authorReviewIterations >=
        ExperienceGenerationProcess.maxIterations) {
      p.failureReason =
          'Author rejected the script ${ExperienceGenerationProcess.maxIterations} times. Giving up.';
      p.statusMessage = p.failureReason!;
      p.status = ExperienceGenerationStatus.failed;
    } else {
      p.statusMessage = 'Author requests script revision '
          '(attempt ${p.authorReviewIterations}/${ExperienceGenerationProcess.maxIterations})';
      p.status = ExperienceGenerationStatus.awaitingScriptRevision;
    }
    return {
      'success': p.status != ExperienceGenerationStatus.failed,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
      'iterationsRemaining':
          ExperienceGenerationProcess.maxIterations - p.authorReviewIterations,
    };
  }

  Map<String, dynamic> _techeditorApprove(ExperienceGenerationProcess p) {
    p.statusMessage = 'Technical Editor approves';
    // If story editing hasn't passed yet (or we're tech-first and haven't done story yet)
    if (p.storyEditIterations == 0 && p.status == ExperienceGenerationStatus.awaitingTechEdit) {
      // If tech was first, proceed to story
      if (p.preferences.logicalVsMood > 5) {
        p.status = ExperienceGenerationStatus.awaitingStoryEdit;
      } else {
        // Story was first and already passed; we're done.
        p.status = ExperienceGenerationStatus.complete;
      }
    } else {
      p.status = ExperienceGenerationStatus.complete;
    }
    return {
      'success': true,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
    };
  }

  Map<String, dynamic> _techeditorReject(
    Map<String, dynamic> args,
    ExperienceGenerationProcess p,
  ) {
    p.techEditReport = args['tech_edit_report'] as String?;
    p.techEditIterations++;
    if (p.techEditIterations >= ExperienceGenerationProcess.maxIterations) {
      p.failureReason =
          'Technical Editor rejected the script '
          '${ExperienceGenerationProcess.maxIterations} times. Giving up.';
      p.statusMessage = p.failureReason!;
      p.status = ExperienceGenerationStatus.failed;
    } else {
      p.statusMessage = 'Technical Editor found issues '
          '(attempt ${p.techEditIterations}/${ExperienceGenerationProcess.maxIterations})';
      p.status = ExperienceGenerationStatus.awaitingTechFix;
    }
    return {
      'success': p.status != ExperienceGenerationStatus.failed,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
      'iterationsRemaining':
          ExperienceGenerationProcess.maxIterations - p.techEditIterations,
    };
  }

  Map<String, dynamic> _storyeditorApprove(ExperienceGenerationProcess p) {
    p.statusMessage = 'Story Editor approves';
    // If tech editing hasn't passed yet
    if (p.techEditIterations == 0 && p.status == ExperienceGenerationStatus.awaitingStoryEdit) {
      if (p.preferences.logicalVsMood <= 5) {
        // Story was first; proceed to tech
        p.status = ExperienceGenerationStatus.awaitingTechEdit;
      } else {
        // Tech was first and already passed; done.
        p.status = ExperienceGenerationStatus.complete;
      }
    } else {
      p.status = ExperienceGenerationStatus.complete;
    }
    return {
      'success': true,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
    };
  }

  Map<String, dynamic> _storyeditorReject(
    Map<String, dynamic> args,
    ExperienceGenerationProcess p,
  ) {
    p.storyEditReport = args['story_edit_report'] as String?;
    p.storyEditIterations++;
    if (p.storyEditIterations >= ExperienceGenerationProcess.maxIterations) {
      p.failureReason =
          'Story Editor rejected the script '
          '${ExperienceGenerationProcess.maxIterations} times. Giving up.';
      p.statusMessage = p.failureReason!;
      p.status = ExperienceGenerationStatus.failed;
    } else {
      p.statusMessage = 'Story Editor requests changes '
          '(attempt ${p.storyEditIterations}/${ExperienceGenerationProcess.maxIterations})';
      p.status = ExperienceGenerationStatus.awaitingStoryFix;
    }
    return {
      'success': p.status != ExperienceGenerationStatus.failed,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
      'iterationsRemaining':
          ExperienceGenerationProcess.maxIterations - p.storyEditIterations,
    };
  }
}
