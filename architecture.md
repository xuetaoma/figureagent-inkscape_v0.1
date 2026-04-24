# Inkscape Copilot Architecture

## Purpose

Build an AI-assisted publication figure editor, not a prompt-to-SVG macro tool.

The system should reliably:

- observe the current Inkscape document
- build a useful model of the figure
- resolve the correct target objects
- plan semantic figure edits
- execute deterministic SVG changes
- resync and verify the result

## Core Principle

The executor should not guess.

Reasoning belongs in the browser/planner layer. Execution belongs in the Inkscape worker. Target selection should be explicit, inspectable, and based on a scene graph snapshot.

## Pipeline

```text
Inkscape document
-> scene graph extraction
-> semantic annotation
-> rendered visual snapshot
-> target resolution
-> structured action plan
-> deterministic execution
-> post-apply snapshot
-> verification / QA
```

## Main Layers

### 1. Browser Sidecar

Owns:

- chat conversation
- concise assistant reply
- reasoning over document context
- action-plan generation
- running indicator and session UI

The browser should trigger Inkscape only after a finalized action plan exists.

### 2. Bridge State

Owns shared files:

- latest document context
- current planned step
- execution result
- session/status data
- rendered snapshots

The bridge should model state, not raw prompt queues.

### 3. Inkscape Worker

Owns:

- document observation
- scene graph extraction
- SVG/PNG snapshot generation
- deterministic action execution
- post-apply verification

The worker treats Inkscape as the source of truth.

### 4. Scene Graph

The scene graph is the main observed model of the document.

Each object should include:

- `object_id`
- `object_index`
- `tag`
- `text`
- `fill`
- `stroke`
- `stroke_width`
- `font_size`
- `bbox`
- `center`
- `role`
- `panel`
- `axis`
- `parent_id`
- `group_id`
- `descendant_count`
- relationship hints

Important relationship hints:

- `panel_root_id`: object belongs to a stable figure/panel root
- `label_for`: text label names a nearby shape/layer
- `attached_to`: connector/electrode attaches to a target object
- `text_group_id`: text and path glyphs belong to one logical label
- `glyph_for`: path glyph belongs to a text anchor

Examples of semantic roles:

- `panel_root`
- `panel_label`
- `frame`
- `layer_bar`
- `layer_label`
- `connector`
- `electrode`
- `axis_line`
- `axis_tick`
- `tick_label`
- `axis_label`
- `text_glyph`
- `legend`
- `scale_bar`
- `lattice_dot`

### 5. Target Resolver

The resolver turns semantic selectors into concrete object IDs.

Selectors include:

- `object_id`
- `object_index`
- `text`
- `role`
- `panel`
- `axis`
- `tag`
- `parent_id`
- `group_id`
- `panel_root_id`
- `label_for`
- `attached_to`
- `text_group_id`
- `glyph_for`
- `include_descendants`

Examples:

- `select_targets(panel="a", include_descendants=true)`
- `select_targets(role="axis_tick", panel="b", axis="x")`
- `select_targets(role="axis_label", panel="c", axis="y")`
- `select_targets(text_group_id="text123")`

When selecting text-like objects, companion `text_glyph` paths should be included so imported rho/Omega/superscript glyphs move and scale with their logical label.

### 6. Figure Planner

The planner should reason semantically before geometrically.

It should:

1. inspect document context and visual snapshot
2. resolve targets first
3. decide whether the operation is a direct object edit, multi-object transform, or semantic figure operation
4. produce a compact executable action plan

Examples of semantic operations:

- move figure a to the top-left
- connect electrodes to graphite
- make x ticks longer
- standardize panel labels
- set axis labels to 10 pt and tick labels to 9 pt

### 7. Executor

The executor is intentionally narrow.

It should:

1. resolve targets from explicit selectors
2. apply supported edits
3. update selection when needed
4. write execution results
5. trigger/respect post-apply resync

The executor should not infer intent from the raw prompt.

## Current Module Map

- `bridge.py`: runtime paths and bridge-state helpers
- `webapp.py`: browser sidecar and status UI
- `openai_bridge.py`: chat/planner calls and prompt contract
- `worker.py`: Inkscape extension worker, sync, apply, snapshot
- `executor.py`: deterministic action execution
- `scene_graph.py`: semantic relationships and panel detection
- `targeting.py`: shared role inference and selector resolution
- `schema.py`: structured action contract
- `verification.py`: before/after execution comparison
- `publication_qa.py`: publication-oriented QA checks
- `publication_fixes.py`: maps safe QA findings into candidate action-plan fixes
- `templates.py`: fallback/template plans for common diagram builds
- `publication_rubric.md`: human-readable publication quality rules
- `publication_feedback.md`: user evaluation log for edited results
- `publication_examples/`: reference/evaluated example library

## Development Direction

Short term:

- turn rubric rules into structured QA findings
- feed rubric, QA, and safe fix suggestions into chat/planner context
- record user evaluation after generated/edited figures
- improve panel boundaries for dense multi-panel figures
- make axis/legend detection more robust
- improve math-glyph companion grouping
- add font family, bold, italic, text alignment, stroke cap, and stroke join

Medium term:

- add semantic figure operations in a dedicated operation layer
- support group/ungroup and connector rerouting
- preview resolved target sets in the UI
- feed verification warnings back into corrective planning

Long term:

- publication presets
- export readiness checks
- reusable figure templates
- richer visual QA
- agentic multi-step repair loops
