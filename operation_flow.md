# Operation Flow

## Goal

FigureAgent for Inkscape should feel like an AI collaborator attached to the document the user is already editing. The user should not need to think about queues, bridge files, worker lifetimes, AppleScript menu triggers, or internal state.

The desired workflow is:

1. Open or create a real Inkscape document.
2. Open `Extensions -> FigureAgent -> Open FigureAgent Chat`.
3. Chat naturally about the figure.
4. FigureAgent observes the current document, reasons about the request, applies supported changes, and reports the result.

## Product Model

There are four layers:

1. `Agent client`
   Owns conversation, user intent, concise assistant replies, and planning. Today this is the browser sidecar; later it can be an MCP-capable client.

2. `FigureAgent tool boundary`
   Owns typed operations such as reading document context, validating action plans, queueing plans, starting/stopping the worker, dispatching finalized plans, and reading results.

3. `Inkscape worker`
   Owns document observation and deterministic execution against the real SVG. A local always-on supervisor watches for queued work and invokes this worker automatically.

4. `Bridge state`
   Carries the latest snapshot, current planned step, running status, and execution result.

The bridge is an implementation detail. The tool boundary is the product-facing API and future MCP surface.

## Menu Surface

The user-facing menu should remain simple:

- `Open FigureAgent Chat`
- `Apply FigureAgent Changes`

`Open FigureAgent Chat` starts or refreshes the browser sidecar, captures the active document, registers a document/session fingerprint from inside Inkscape, and starts the always-on worker attached to that document.

`Apply FigureAgent Changes` is a worker entry point. During normal chat use, the always-on worker triggers it after a finalized action plan exists. It remains visible as a fallback/debug command.

## Intended Prompt Flow

When the user presses Send:

1. The sidecar marks the command as running.
2. The sidecar reads the latest available document context.
3. The assistant gives a short operational reply.
4. The planner creates a structured action plan using the same context.
5. The plan is stored as the current planned step.
6. The document-scoped always-on worker asks Inkscape to apply the plan once.
7. The worker writes a post-apply snapshot and execution result.
8. The sidecar clears the running indicator and updates session status.

Important constraints:

- Do not trigger apply just because the user typed a message.
- Trigger apply only after action generation is complete.
- Do not show raw action JSON in the chat by default.
- Do not resize the page unless the user explicitly asks.

## Document Awareness

The current document context should include:

- document name/path when available
- page size
- current selection summary
- scene graph objects
- semantic roles
- panels and panel bounding boxes
- relationship hints
- rendered SVG/PNG snapshots
- recent execution result and QA findings

The scene graph is the main working model. Manual Inkscape selection is useful, but it should not be the only way the agent can decide what to edit.

## Scene Graph And Targeting

Every visible/editable SVG object should be addressable by:

- `object_id`
- `object_index`
- `tag`
- `text`
- `bbox`
- `center`
- `style`
- `parent_id`
- `group_id`

Semantic targeting adds:

- `role`
- `panel`
- `axis`
- `panel_root_id`
- `label_for`
- `attached_to`
- `text_group_id`
- `glyph_for`

This lets the planner handle prompts like:

- `make ticks in figure a longer`
- `set panel labels a-g to 12 pt`
- `connect electrodes to the graphite layer`
- `make the rho/Omega axis label smaller`

## Visual Snapshot Loop

Structured SVG data is necessary but not sufficient. Publication figures often contain imported plots, text converted to paths, clipping artifacts, and transformed groups.

The worker should write:

- current SVG snapshot
- current rendered PNG snapshot
- structured document context
- verification and QA results

The model can then compare what the SVG says with what the figure visually looks like.

## Responsibilities

### Browser Sidecar

Responsible for:

- conversation
- brief assistant replies
- current-step planning
- showing running/session state
- sending finalized plans to Inkscape
- calling the FigureAgent tool boundary

Not responsible for:

- directly mutating the SVG
- guessing document state without a sync

### FigureAgent Tool Boundary

Responsible for:

- typed tool schemas
- validating action plans
- reading context/status/results
- queueing finalized plans
- triggering Inkscape apply through the always-on worker path
- providing the MCP-compatible surface

Not responsible for:

- mutating the live SVG directly
- replacing the Inkscape worker as source of truth

### Always-On Worker Supervisor

Responsible for:

- watching for queued finalized plans
- invoking the Inkscape apply entry point without requiring a user click
- writing heartbeat/session state
- preserving attached document metadata from the Inkscape registration step
- exposing start/stop/status through CLI and MCP tools

Not responsible for:

- planning edits
- directly mutating the live SVG outside Inkscape

### Inkscape Worker

Responsible for:

- reading the real current SVG
- extracting scene graph snapshots
- rendering visual snapshots
- applying supported actions deterministically
- writing execution results

Not responsible for:

- open-ended conversation
- inferring user intent from raw prompts during execution

### Bridge State

Responsible for:

- `document_context.json`
- `planned_step.json`
- `execution_result.json`
- status/session metadata
- visual snapshots

Not responsible for:

- becoming the visible product model

## Definition Of Success

The project is succeeding when the workflow feels like:

- `I open my SVG.`
- `I open FigureAgent Chat.`
- `I ask for what I want.`
- `FigureAgent selects the right thing, changes it, verifies it, and keeps going.`

If the user has to reason about hidden queues, stale sessions, manual apply clicks, or internal extension commands, the product model still needs work.
