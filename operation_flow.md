# Operation Flow

## Goal

Inkscape Copilot should feel like an AI collaborator attached to the document the user is already editing. The user should not need to think about queues, bridge files, worker lifetimes, AppleScript menu triggers, or internal state.

The desired workflow is:

1. Open or create a real Inkscape document.
2. Open `Extensions -> Copilot -> Open Copilot Chat`.
3. Chat naturally about the figure.
4. The copilot observes the current document, reasons about the request, applies supported changes, and reports the result.

## Product Model

There are three layers:

1. `Browser sidecar`
   Owns conversation, user intent, concise assistant replies, and planning.

2. `Inkscape worker`
   Owns document observation and deterministic execution against the real SVG.

3. `Bridge state`
   Carries the latest snapshot, current planned step, running status, and execution result.

The bridge is an implementation detail. The product should feel document-attached, not queue-attached.

## Menu Surface

The user-facing menu should remain simple:

- `Open Copilot Chat`
- `Apply Copilot Changes`

`Open Copilot Chat` starts or refreshes the browser sidecar and captures the active document.

`Apply Copilot Changes` is a worker entry point. During normal chat use, the browser triggers it after a finalized action plan exists. It remains visible as a fallback/debug command.

## Intended Prompt Flow

When the user presses Send:

1. The sidecar marks the command as running.
2. The sidecar reads the latest available document context.
3. The assistant gives a short operational reply.
4. The planner creates a structured action plan using the same context.
5. The plan is stored as the current planned step.
6. Inkscape applies the plan once.
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

Not responsible for:

- directly mutating the SVG
- guessing document state without a sync

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
- `I open Copilot Chat.`
- `I ask for what I want.`
- `The copilot selects the right thing, changes it, verifies it, and keeps going.`

If the user has to reason about hidden queues, stale sessions, manual apply clicks, or internal extension commands, the product model still needs work.

