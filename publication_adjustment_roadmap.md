# Publication Adjustment Roadmap

## Goal

Move Inkscape Copilot from "can create/edit figures" to "can refine publication figures reliably".

Publication-level editing means precision, consistency, and verification:

- exact size
- exact position
- alignment
- distribution
- consistent text styling
- consistent stroke styling
- correct panel structure
- visually verified output

The baseline judgment rules live in `publication_rubric.md`. User evaluations should be recorded in `publication_feedback.md`, and strong or failed examples should be collected under `publication_examples/`.

## High-Value Feature Groups

### 1. Precision Layout

- exact object position
- exact object size
- exact selection position
- selection alignment:
  - left
  - center
  - right
  - top
  - middle
  - bottom
- selection distribution:
  - horizontal
  - vertical
- panel grid layout
- margin and padding normalization

### 2. Typography

- font family
- font size in visual points
- bold
- italic
- text alignment
- line spacing
- letter spacing
- superscript/subscript helpers
- panel label standardization
- axis label standardization
- tick label standardization

### 3. Math Glyph Companions

Imported figures often store Greek/math symbols as paths, not text. The agent needs to edit them with their logical labels.

Needed behavior:

- detect path-based text glyphs such as rho, Omega, superscripts, and math fragments
- mark them as `role=text_glyph`
- link them to text anchors through `glyph_for`
- group full logical labels through `text_group_id`
- include companion glyphs when selecting axis labels or general labels
- scale companion glyph paths when font size changes

This is required for commands like:

- `make rho_xx labels 10 pt`
- `make Omega symbols match the axis label size`
- `standardize all y-axis labels`

### 4. Paint And Stroke

- fill color
- no fill
- stroke color
- no stroke
- stroke width
- dash pattern
- opacity
- stroke cap
- stroke join
- marker/arrowhead style

### 5. Axis And Tick Controls

- tick length
- tick thickness
- tick direction
- tick label size
- tick label offset
- axis label size
- axis label offset
- axis line thickness
- consistent axes across panels

Example target command:

```text
make ticks in figure a longer
```

This requires:

- detecting panel `a`
- detecting axis lines
- detecting tick objects
- resolving which ticks belong to which axis
- editing only those tick objects

### 6. Panel And Figure Assembly

- panel labels (`a`, `b`, `c`, ...), not hard-coded to `a-d`
- arbitrary panel ranges such as `a-e` or `a-g`
- panel bounding boxes
- panel object counts
- panel alignment
- equal panel sizing
- consistent panel spacing
- multi-panel grid layout
- crop/fit figure to page when explicitly requested

### 7. Structural Editing

- group
- ungroup
- stable object targeting by ID/index
- selection by visible text
- z-order edits
- connector rerouting
- layer management
- reusable figure templates

### 8. Visual QA Loop

- render the current SVG page to a PNG snapshot after sync/apply
- compare structured SVG state against rendered appearance
- detect publication issues:
  - inconsistent panel label sizing
  - inconsistent axis/tick label sizing
  - missing or duplicate panel labels
  - panel sequence gaps such as missing `e`
  - oversized text after a font-size command
  - missing rendered snapshot
  - possible off-page objects
- expose QA findings in `execution_result.json`
- feed QA findings back into corrective planning

QA findings should be structured, not only free-text warnings:

- `rule_id`
- `severity`
- `message`
- `target_selector`
- `suggested_fix`

### 9. Export Readiness

- page size only when explicitly requested
- crop to artwork when explicitly requested
- export presets:
  - SVG
  - PDF
  - PNG
- font/path safety checks
- publication DPI checks for raster images

## Implementation Order

### Batch 1: Precision Primitives

- `set_object_position`
- `set_object_size`
- `set_selection_position`
- `align_selection`
- `distribute_selection`

### Batch 2: Semantic Targeting

- panel detection for arbitrary labels (`a`, `b`, `c`, ...)
- panel bounding boxes and panel object counts
- role detection
- axis detection
- tick detection
- relationship fields:
  - `panel_root_id`
  - `label_for`
  - `attached_to`
  - `text_group_id`
  - `glyph_for`

### Batch 3: Typography And Stroke

- font family
- bold
- italic
- text alignment
- stroke cap
- stroke join
- marker/arrowhead controls

### Batch 4: Publication Operations

- panel-label helpers
- equal-size helpers
- label-centering helpers
- axis/tick standardization helpers
- connector rerouting helpers
- export presets

## Current Batch Status

In progress:

- semantic selection via `role`, `panel`, and `axis`
- figure-aware targeting for ticks, panel labels, and axis labels
- arbitrary panel detection and panel bounding boxes
- rendered snapshot generation for visual QA
- math glyph companion targeting for Greek/path-based labels
- tick controls:
  - `set_tick_length`
  - `set_tick_thickness`
  - `set_tick_label_size`

Recently added:

- panel detection ignores one-letter `tspan` fragments such as axis `n` or `x`
- detected panels are stored in `document_context.json` under `panels`
- post-apply verification includes structured publication QA findings and warnings
- scene graph marks path-based math symbols as `text_glyph` companions through `text_group_id` / `glyph_for`
- font-size conversion accounts for document units and parent transforms
- planner/chat context includes `publication_rubric`, `publication_qa`, and `publication_fix_suggestions`
- safe QA-to-action suggestions are generated for obvious typography normalization fixes

Next:

- improve panel bounding boxes for dense imported figures
- add typography controls:
  - bold
  - italic
  - font family
  - text alignment
- add stroke controls:
  - cap
  - join
  - arrowhead/marker style
- feed QA warnings into corrective planning
- expand QA-to-action suggestions beyond typography into tick length, stroke consistency, and panel alignment
