# FigureAgent for Inkscape

FigureAgent for Inkscape is an early AI figure-editing agent for Inkscape. The goal is not just to generate simple SVG shapes from prompts. The goal is to help edit real publication figures: inspect the current document, identify the right objects, plan a precise edit, apply it in Inkscape, and verify what changed.

The current product surface is intentionally small:

1. Open an SVG in Inkscape.
2. Use `Extensions -> FigureAgent -> Open FigureAgent Chat`.
3. Talk to FigureAgent in the browser window.
4. FigureAgent syncs the document, plans the next step, and applies supported changes back into Inkscape.

## Current Status

This is a working prototype, not a finished editor. It can already make useful edits, but the main engineering direction is reliable document understanding and target selection.

The current architecture is:

- Inkscape observes and executes.
- The browser chat owns conversation and planning.
- Shared bridge files carry the latest snapshot, planned step, and execution result.
- The scene graph gives every visible object an addressable ID plus semantic hints.
- The planner should target objects through explicit selectors instead of relying on stale manual selection.

## Inkscape Menu

The extension exposes only two menu items:

- `Open FigureAgent Chat`
- `Apply FigureAgent Changes`

`Open FigureAgent Chat` starts or refreshes the sidecar chat and captures the active document state.

`Apply FigureAgent Changes` is the Inkscape-side execution entry point. In normal chat use, `Open FigureAgent Chat` snapshots and registers the active Inkscape document, then starts a document-scoped always-on worker. That worker watches for finalized action plans and asks Inkscape to apply them automatically, so users should rarely need to click this manually.

## What It Can Do Now

Supported capabilities include:

- create basic shapes and diagram primitives
- create regular and custom-point polygons
- create and edit text
- change fill, stroke paint, stroke width, dash pattern, opacity, font size, font family, bold/italic, text anchoring, stroke cap/join, and arrowheads
- move, resize, scale, rotate, align, and distribute objects
- semantically resize plot width/height while preserving tick length, stroke width, and text size
- target existing objects by `object_id`, visible text, role, panel, axis, group, parent, and relationship hints
- detect arbitrary panel labels such as `a`, `b`, `c`, ..., not just `a-d`
- adjust axis tick length, tick thickness, and tick label sizes
- use rendered page snapshots so the model can compare SVG state with visual appearance
- associate path-based math glyphs such as rho/Omega with nearby text labels through `text_group_id` and `glyph_for`
- include publication rubric, QA findings, safe fix suggestions, feedback notes, and local publication examples in the planning context
- use attached reference images when running with an image-capable OpenAI model

FigureAgent is conservative about page resizing:

- it will not change the page/canvas size unless you explicitly ask for it

## Product Behavior

When you send a chat message:

1. the sidecar uses the latest document snapshot, including structured SVG state and a rendered PNG snapshot
2. the model replies briefly about the intended operation
3. the model generates a structured action plan
4. the plan is written to bridge state
5. the document-scoped always-on worker asks Inkscape to apply the finalized plan once
6. the worker resyncs and writes execution/verification results

The chat UI is intentionally concise:

- assistant replies are short and operational
- raw JSON action plans are hidden
- the message area scrolls independently from the session panel
- the session panel shows whether work is currently running

## Project Layout

- `inkscape_copilot/`: bridge, planner, executor, worker, web UI, scene graph, targeting, verification, and API bridge
- `inkscape_extension/`: Inkscape manifest files for the two menu entries
- `scripts/`: setup and evaluation helpers
- `operation_flow.md`: product workflow and bridge responsibilities
- `architecture.md`: system architecture and module responsibilities
- `selection_architecture.md`: target-resolution model
- `human_level_editor_roadmap.md`: long-term agent roadmap
- `publication_adjustment_roadmap.md`: publication figure editing roadmap
- `publication_rubric.md`: baseline rules for publication-quality figure evaluation
- `publication_examples/`: reference and evaluated example figures
- `publication_feedback.md`: user evaluation log for FigureAgent results

Compatibility note: the user-facing project name is **FigureAgent for Inkscape**, but the Python package and some environment variables still use `inkscape_copilot` / `INKSCAPE_COPILOT_*` to avoid breaking existing extension installs.

## Local Setup

Before starting, you need:

- an API key for the provider you want to use
- a model that can read images if you want screenshot/reference-image support

Recommended starting point:

- OpenAI API key
- `MAIN_MODEL=gpt-5.4`

Create one local `.env` file in the project root:

```bash
cp .env.example .env
```

Recommended config:

```bash
INKSCAPE_COPILOT_PROVIDER=openai
MAIN_MODEL=gpt-5.4
OPENAI_MODEL=gpt-5.4
OPENAI_API_KEY=your_openai_key_here
```

DeepSeek V4 Pro config:

```bash
INKSCAPE_COPILOT_PROVIDER=deepseek
MAIN_MODEL=deepseek-v4-pro
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_API_KEY=your_deepseek_key_here
```

Optional variables:

- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `DEEPSEEK_MODEL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `INKSCAPE_COPILOT_ENV_FILE`
- `INKSCAPE_COPILOT_IMAGE_DETAIL`: defaults to `low` for faster image planning
- `INKSCAPE_COPILOT_API_TIMEOUT_SECONDS`: defaults to `180`

The installed Inkscape extension is configured to read one root `.env` file. On this development machine the expected path is:

```bash
/Users/xuetao.ma/Desktop/inkscape-copilot/.env
```

If you move the project somewhere else, point the extension at the correct file:

```bash
launchctl setenv INKSCAPE_COPILOT_ENV_FILE "/path/to/inkscape-copilot/.env"
```

On Windows 11, use PowerShell:

```powershell
setx INKSCAPE_COPILOT_ENV_FILE "C:\path\to\inkscape-copilot\.env"
```

## Python Environment

Create and install a local virtual environment:

```bash
cd /path/to/inkscape-copilot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

Or use the included setup script:

```bash
cd /path/to/inkscape-copilot
bash scripts/setup_venv.sh
source .venv/bin/activate
```

Notes:

- `requirements.txt` installs the local package with `pip install -e .`
- the browser-side agent does not need third-party API SDKs
- the Inkscape extension runtime uses Inkscape's bundled Python environment for `inkex`

## Run The Web UI Manually

From the project root:

```bash
source .venv/bin/activate
python3 -m inkscape_copilot.cli serve --port 8767
```

Then open:

```bash
http://127.0.0.1:8767
```

## Run The MCP Server

FigureAgent includes a stdio MCP server that exposes the same typed tool boundary used by the local CLI and browser app:

```bash
source .venv/bin/activate
python3 -m inkscape_copilot.cli mcp
```

If installed as a package, you can also use:

```bash
figureagent-inkscape-mcp
```

Example MCP client config:

```json
{
  "mcpServers": {
    "figureagent-inkscape": {
      "command": "python3",
      "args": ["-m", "inkscape_copilot.cli", "mcp"],
      "cwd": "/path/to/figureagent-inkscape"
    }
  }
}
```

Useful MCP/local tools include:

- `get_document_context`: read the latest structured document state and visual snapshot metadata
- `get_ui_state`: read the aggregate dashboard state used by thin clients such as the browser UI
- `sync_live_document_context`: ask Inkscape to refresh the live document context and rendered snapshots
- `get_snapshot_paths`: return local SVG/PNG snapshot paths and existence metadata
- `query_scene_graph`: filter the latest scene graph by role, panel, axis, object ID, text, or relationship selectors
- `get_object_details`: inspect one object and its related/grouped/attached objects
- `rank_edit_targets`: rank likely edit targets for an intent such as `top right plot in panel c`
- `validate_action_plan`: validate a structured action plan
- `dispatch_action_plan`: queue a plan and wait for it to apply
- `select_targets`: preview/apply semantic target selection
- `set_target_font_size`: preview/apply font-size edits by object ID, role, panel, text, or relationship selector
- `set_target_stroke_width`: preview/apply stroke-width edits by selector
- `move_targets`: preview/apply relative moves by selector
- `create_polygon`: preview/apply regular or custom-point polygon creation
- `resize_plot_width` / `resize_plot_height`: preview/apply semantic plot resizing while preserving tick/text styling
- `set_tick_length` / `set_tick_thickness`: preview/apply axis tick edits
- `run_publication_qa`: evaluate the latest document context and return safe fix suggestions
- `apply_publication_fixes`: preview/apply safe publication QA fixes
- `apply_publication_fix`: preview/apply one safe publication QA fix by `finding_index` or `rule_id`
- `start_always_on_worker`: start the queue-watching Inkscape worker
- `stop_always_on_worker`: stop the queue-watching worker
- `get_always_on_worker_status`: check whether the worker is running

MCP resources include:

- `figureagent://document/context`
- `figureagent://document/scene-graph`
- `figureagent://document/snapshot.svg`
- `figureagent://document/snapshot.png`
- `figureagent://bridge/status`
- `figureagent://bridge/events`
- `figureagent://worker/log`
- `figureagent://publication/qa`
- `figureagent://publication/rubric`
- `figureagent://publication/feedback`
- `figureagent://publication/examples`

Recommended MCP agent loop:

1. read `figureagent://document/context` and `figureagent://document/snapshot.png`
2. inspect targets using `query_scene_graph`, `rank_edit_targets`, or `figureagent://document/scene-graph`
3. if the context might be stale, call `sync_live_document_context`
4. call a focused edit tool with `apply=false` to preview the action plan
5. call the same tool with `apply=true` or call `dispatch_action_plan`
6. read `figureagent://publication/qa` and the updated snapshot to verify

You can manage the same worker from the CLI:

```bash
python3 -m inkscape_copilot.cli worker start
python3 -m inkscape_copilot.cli worker status
python3 -m inkscape_copilot.cli worker stop
```

The worker status includes the attached Inkscape document metadata:

```bash
python3 -m inkscape_copilot.cli worker status
```

Design note: standard Inkscape effect extensions are still one-shot. A permanently running effect process would block the Inkscape UI and would not commit SVG changes until it exits. FigureAgent therefore uses an Inkscape-registered, document-scoped supervisor as the reliable no-click worker model.

## Install Inkscape Extension

Copy into your Inkscape user extensions directory:

- the `inkscape_copilot/` package
- `inkscape_extension/inkscape_copilot_open_window.inx`
- `inkscape_extension/inkscape_copilot_apply_queue.inx`

On macOS this is typically:

```bash
~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions
```

On Windows 11 this is typically:

```powershell
$env:APPDATA\inkscape\extensions
```

After copying, restart Inkscape. The `Extensions -> FigureAgent` submenu should contain exactly:

- `Open FigureAgent Chat`
- `Apply FigureAgent Changes`

## Windows 11 Compatibility

The core Python package, MCP server, browser UI, harness, OpenAI/DeepSeek API calls, and Inkscape CLI snapshot export are designed to run on Windows 11.

Current limitation:

- automatic menu triggering for `Apply FigureAgent Changes` is still macOS-only because it uses AppleScript/System Events
- on Windows, the chat can open and plan through the same MCP/tool layer, but applying queued changes may still require manually choosing `Extensions -> FigureAgent -> Apply FigureAgent Changes`

Recommended Windows setup:

```powershell
cd C:\path\to\inkscape-copilot
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
setx INKSCAPE_COPILOT_ENV_FILE "C:\path\to\inkscape-copilot\.env"
```

If PNG snapshots do not render, set the Inkscape CLI path explicitly:

```powershell
setx INKSCAPE_COPILOT_INKSCAPE_BIN "C:\Program Files\Inkscape\bin\inkscape.com"
```

## Evaluation Harness

FigureAgent has two evaluation paths.

To test the deterministic tool/MCP contract against fixture document contexts:

```bash
python3 scripts/run_harness.py --mcp-smoke --out state/harness_report.json
```

Or through the package CLI:

```bash
python3 -m inkscape_copilot.cli harness --mcp-smoke --out state/harness_report.json
```

This loads `tests/fixtures/contexts/multi_panel_publication.json`, runs semantic scenarios from `tests/fixtures/harness_scenarios.json`, checks target ranking and preview actions, and smoke-tests the MCP server against the same isolated runtime.

To test screenshot-to-action planning without manually using the chat UI:

```bash
python3 scripts/evaluate_screenshots.py "/path/to/reference.png"
```

The screenshot harness writes JSON results under `state/` and reports whether the plan produced actions, avoided confirmation stalls, and fit newly-created geometry inside the current page.

## Development Direction

The next major work is making FigureAgent more agentic:

- rubric-based publication evaluation
- user-reviewed examples and feedback
- richer scene graph extraction
- stronger panel/axis/legend detection
- better grouping of imported path glyphs with text labels
- more deterministic connector and electrode routing
- visual QA after every action
- corrective follow-up when verification detects a failed or incomplete edit
