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
        'rationale': {
          'type': 'string',
          'description':
              'Explain what you did and why. Describe your creative decisions and how they align with the inputs.',
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
      'properties': {
        'rationale': {
          'type': 'string',
          'description':
              'Explain why you approve this outline and what makes it suitable and feasible.',
        },
      },
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
        'rationale': {
          'type': 'string',
          'description':
              'Explain your decision to reject and the key problems you identified.',
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
        'rationale': {
          'type': 'string',
          'description':
              'Explain your approach to implementing the outline and any key decisions you made.',
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
      'properties': {
        'rationale': {
          'type': 'string',
          'description':
              'Explain why the script faithfully implements your vision and outline.',
        },
      },
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
        'rationale': {
          'type': 'string',
          'description':
              'Explain why you reject the script and what key elements diverge from your vision.',
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
      'properties': {
        'rationale': {
          'type': 'string',
          'description':
              'Explain why the script is logically consistent and meets technical standards.',
        },
      },
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
        'rationale': {
          'type': 'string',
          'description':
              'Explain why these logical inconsistencies are problematic and exceed acceptable limits.',
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
      'properties': {
        'rationale': {
          'type': 'string',
          'description':
              'Explain how the script aligns with player preferences and their prompt.',
        },
      },
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
        'rationale': {
          'type': 'string',
          'description':
              'Explain why the script doesn\'t match player preferences and what needs to change.',
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
        return _scripterApproveOutline(args, process);
      case 'experience_scripter_reject_outline':
        return _scripterRejectOutline(args, process);
      case 'experience_scripter_submit_script':
        return await _scripterSubmitScript(args, process, ifEngine);
      case 'experience_author_approve_script':
        return _authorApproveScript(args, process);
      case 'experience_author_reject_script':
        return _authorRejectScript(args, process);
      case 'experience_techeditor_approve':
        return _techeditorApprove(args, process);
      case 'experience_techeditor_reject':
        return _techeditorReject(args, process);
      case 'experience_storyeditor_approve':
        return _storyeditorApprove(args, process);
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
    final rationale = args['rationale'] as String?;
    p.outline = args['outline'] as String?;
    p.techNotes = args['tech_notes'] as String?;
    p.statusMessage = 'Author submitted outline';
    final prevStatus = p.status;
    p.status = ExperienceGenerationStatus.awaitingOutlineReview;
    p.addLogEntry(
      prevStatus.name,
      p.status.name,
      'Author submitted outline',
      rationale,
    );
    return {
      'success': true,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
    };
  }

  Map<String, dynamic> _scripterApproveOutline(
    Map<String, dynamic> args,
    ExperienceGenerationProcess p,
  ) {
    final rationale = args['rationale'] as String?;
    p.statusMessage = 'Scripter approves outline';
    final prevStatus = p.status;
    p.status = ExperienceGenerationStatus.awaitingScript;
    p.addLogEntry(
      prevStatus.name,
      p.status.name,
      'Scripter approved outline',
      rationale,
    );
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
    final rationale = args['rationale'] as String?;
    p.outlineNotes = args['outline_notes'] as String?;
    p.outlineIterations++;
    final prevStatus = p.status;
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
    p.addLogEntry(
      prevStatus.name,
      p.status.name,
      'Scripter rejected outline',
      rationale,
    );
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
    final rationale = args['rationale'] as String?;
    p.script = args['script'] as String?;
    final prevStatus = p.status;
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
      p.addLogEntry(
        prevStatus.name,
        p.status.name,
        'Script submission failed: empty script',
        rationale,
      );
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
      p.addLogEntry(
        prevStatus.name,
        p.status.name,
        'Scripter submitted script - compiled successfully',
        rationale,
      );
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
      p.addLogEntry(
        prevStatus.name,
        p.status.name,
        'Script compilation failed',
        rationale,
      );
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

  Map<String, dynamic> _authorApproveScript(
    Map<String, dynamic> args,
    ExperienceGenerationProcess p,
  ) {
    final rationale = args['rationale'] as String?;
    p.statusMessage = 'Author approves script';
    final prevStatus = p.status;
    p.status = p.preferences.logicalVsMood > 5
        ? ExperienceGenerationStatus.awaitingTechEdit
        : ExperienceGenerationStatus.awaitingStoryEdit;
    p.addLogEntry(
      prevStatus.name,
      p.status.name,
      'Author approved script',
      rationale,
    );
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
    final rationale = args['rationale'] as String?;
    p.scriptNotes = args['script_notes'] as String?;
    p.authorReviewIterations++;
    final prevStatus = p.status;
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
    p.addLogEntry(
      prevStatus.name,
      p.status.name,
      'Author rejected script',
      rationale,
    );
    return {
      'success': p.status != ExperienceGenerationStatus.failed,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
      'iterationsRemaining':
          ExperienceGenerationProcess.maxIterations - p.authorReviewIterations,
    };
  }

  Map<String, dynamic> _techeditorApprove(
    Map<String, dynamic> args,
    ExperienceGenerationProcess p,
  ) {
    final rationale = args['rationale'] as String?;
    p.statusMessage = 'Technical Editor approves';
    final prevStatus = p.status;
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
    p.addLogEntry(
      prevStatus.name,
      p.status.name,
      'Technical Editor approved script',
      rationale,
    );
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
    final rationale = args['rationale'] as String?;
    p.techEditReport = args['tech_edit_report'] as String?;
    p.techEditIterations++;
    final prevStatus = p.status;
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
    p.addLogEntry(
      prevStatus.name,
      p.status.name,
      'Technical Editor rejected script',
      rationale,
    );
    return {
      'success': p.status != ExperienceGenerationStatus.failed,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
      'iterationsRemaining':
          ExperienceGenerationProcess.maxIterations - p.techEditIterations,
    };
  }

  Map<String, dynamic> _storyeditorApprove(
    Map<String, dynamic> args,
    ExperienceGenerationProcess p,
  ) {
    final rationale = args['rationale'] as String?;
    p.statusMessage = 'Story Editor approves';
    final prevStatus = p.status;
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
    p.addLogEntry(
      prevStatus.name,
      p.status.name,
      'Story Editor approved script',
      rationale,
    );
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
    final rationale = args['rationale'] as String?;
    p.storyEditReport = args['story_edit_report'] as String?;
    p.storyEditIterations++;
    final prevStatus = p.status;
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
    p.addLogEntry(
      prevStatus.name,
      p.status.name,
      'Story Editor rejected script',
      rationale,
    );
    return {
      'success': p.status != ExperienceGenerationStatus.failed,
      'statusMessage': p.statusMessage,
      'processStatus': p.status.name,
      'iterationsRemaining':
          ExperienceGenerationProcess.maxIterations - p.storyEditIterations,
    };
  }
}
