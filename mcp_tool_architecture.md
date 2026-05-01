# FigureAgent MCP Tool Architecture

## Direction

FigureAgent should move toward:

```text
Agent client
-> typed FigureAgent tools
-> Inkscape worker
-> live document
-> visual snapshot and QA result
```

The current browser sidecar can remain the main UI, but the core capabilities should be exposed through a tool boundary that can also be served over MCP.

## Why

The existing extension flow works, but it mixes several concerns:

- chat planning
- bridge state
- queue management
- AppleScript menu triggering
- Inkscape worker execution
- visual verification

MCP-style tools separate these concerns. The agent should call clear operations with schemas instead of relying on hidden UI behavior.

## Current First Step

`inkscape_copilot/tools.py` defines a local typed tool registry.

Current tools:

- `get_document_context`
- `get_bridge_status`
- `get_ui_state`
- `sync_live_document_context`
- `get_snapshot_paths`
- `query_scene_graph`
- `get_object_details`
- `rank_edit_targets`
- `validate_action_plan`
- `select_targets`
- `set_target_font_size`
- `set_target_stroke_width`
- `move_targets`
- `create_polygon`
- `resize_plot_width`
- `resize_plot_height`
- `set_tick_length`
- `set_tick_thickness`
- `run_publication_qa`
- `apply_publication_fixes`
- `apply_publication_fix`
- `queue_action_plan`
- `apply_pending_jobs`
- `queue_and_apply_action_plan`
- `dispatch_action_plan`
- `start_always_on_worker`
- `stop_always_on_worker`
- `get_always_on_worker_status`
- `clear_planned_step`
- `reset_bridge_state`

These are served through the stdio MCP server and are intentionally shaped like MCP tools:

- name
- description
- input schema
- JSON result

The browser web app now dispatches action plans through the same `dispatch_action_plan` tool that MCP exposes. This keeps the normal chat workflow and the MCP workflow on the same queue/apply/status boundary.

`Open FigureAgent Chat` also registers the active Inkscape document and starts the always-on worker with that document metadata. When that worker is running, `dispatch_action_plan` queues the plan and waits for the worker to apply it instead of directly requiring the user to open the Inkscape extension dialog.

## MCP Server

FigureAgent now includes a stdio MCP server:

```bash
python3 -m inkscape_copilot.cli mcp
```

When installed as a package, the script entry point is:

```bash
figureagent-inkscape-mcp
```

The server exposes the same tool registry from `inkscape_copilot/tools.py` plus read-only resources from `inkscape_copilot/mcp_resources.py`.

Example client configuration:

```json
{
  "mcpServers": {
    "figureagent-inkscape": {
      "command": "python3",
      "args": [
        "-m",
        "inkscape_copilot.cli",
        "mcp"
      ],
      "cwd": "/path/to/figureagent-inkscape"
    }
  }
}
```

This is intentionally thin: it uses the current bridge and always-on worker flow underneath.

## Current MCP Resources

- `figureagent://document/context`: full structured document context
- `figureagent://document/scene-graph`: addressable objects, panels, selection, and role summary
- `figureagent://document/snapshot.svg`: latest SVG snapshot
- `figureagent://document/snapshot.png`: latest rendered PNG snapshot
- `figureagent://bridge/status`: status, session, execution result
- `figureagent://bridge/events`: recent runtime events
- `figureagent://worker/log`: recent worker debug log lines
- `figureagent://publication/qa`: publication QA findings and safe fix suggestions
- `figureagent://publication/rubric`: human-readable publication rubric
- `figureagent://publication/feedback`: local user feedback log
- `figureagent://publication/examples`: local example notes/metadata index

## Current Granular MCP Tools

These tools preview by default. Pass `apply=true` to dispatch the generated action plan through the worker.

- `select_targets`
- `query_scene_graph`
- `get_object_details`
- `rank_edit_targets`
- `set_target_font_size`
- `set_target_stroke_width`
- `move_targets`
- `resize_plot_width`
- `resize_plot_height`
- `set_tick_length`
- `set_tick_thickness`
- `run_publication_qa`
- `apply_publication_fixes`
- `apply_publication_fix`

`sync_live_document_context` performs a guarded observe step. It asks Inkscape to refresh the current document context and snapshots, but refuses to run while jobs are pending unless `allow_apply_pending=true`.

## Target MCP Server Evolution

The current server should evolve toward richer resources and fewer compatibility triggers.

Suggested next MCP tools/resources:

- export figure
- compare before/after snapshots
- read publication feedback/examples as resources
- direct object-inspection helpers that filter scene graph objects server-side

## Important Constraint

MCP does not remove the need for the Inkscape-side worker.

The live unsaved document still belongs to Inkscape, so the reliable architecture is:

- MCP/tool layer for the agent contract
- Inkscape extension worker for live document access and document registration
- document-scoped always-on local supervisor for no-click queue watching
- bridge/runtime files as compatibility transport until a direct worker server exists

## Migration Plan

1. Keep the existing extension workflow stable.
2. Route internal web actions through `tools.py` where practical. Done for action-plan dispatch.
3. Add an MCP server that wraps `tools.py`. Initial stdio server is in place.
4. Add a long-running worker supervisor. Initial queue-watching worker is in place.
5. Reduce AppleScript to a fallback trigger.
6. Make every agent-visible operation structured, testable, and logged.
