# Publication Figure Rubric

## Purpose

This rubric defines what FigureAgent for Inkscape should look for when judging whether a figure is publication-ready. It is intentionally practical: every rule should eventually map to a detectable issue, a target selector, and a corrective action.

The rubric is not a single journal style. It is a baseline for clean scientific figures that can be adapted later with journal-specific presets.

## Core Standard

A publication-level figure should be:

- readable at final printed size
- internally consistent
- spatially aligned
- visually balanced
- minimally cluttered
- semantically clear
- reproducible as editable vector graphics when possible

## Rubric Rules

### PANEL-001: Panel Labels Exist And Are Ordered

Panel labels should be present when the figure has multiple panels.

Expected:

- labels use lowercase letters: `a`, `b`, `c`, ...
- labels follow a continuous sequence unless the user intentionally skips one
- labels are not duplicated
- labels are placed consistently near each panel

Typical correction:

- create missing panel labels
- rename duplicate labels
- align labels to a shared offset
- standardize panel label font size and weight

### PANEL-002: Panel Layout Is Balanced

Panels should be aligned and spaced consistently.

Expected:

- panels in the same row share top/bottom alignment
- panels in the same column share left/right alignment
- gutters are consistent
- panel sizes are not accidentally distorted

Typical correction:

- align panel groups
- distribute panel groups horizontally or vertically
- resize panel groups to a consistent width/height when appropriate

### TEXT-001: Typography Hierarchy Is Consistent

Text should follow a clear hierarchy.

Recommended baseline:

- panel labels: `12 pt`, bold when possible
- axis labels: `10 pt`
- tick labels: `8-9 pt`
- legends/annotations: `7-9 pt`, depending on density

Typical correction:

- set panel labels to 12 pt
- set axis labels to 10 pt
- set tick labels to 9 pt
- reduce oversized imported text

### TEXT-002: Text Remains Readable And Non-Overlapping

Text should not collide with axes, data, panels, or other labels.

Expected:

- tick labels do not overlap each other
- axis labels do not overlap tick labels
- legends do not obscure important data
- annotations are inside the intended panel

Typical correction:

- move label by a small offset
- reduce font size
- increase panel margin
- reposition legend/annotation

### TEXT-003: Math Glyphs Stay With Their Labels

Imported symbols such as rho, Omega, superscripts, and subscripts may appear as paths rather than editable text. They should still be treated as part of the logical label.

Expected:

- path-based glyphs are linked to nearby text through `text_group_id` / `glyph_for`
- resizing a label also resizes companion glyph paths
- moving a label also moves companion glyph paths

Typical correction:

- group text and glyph companions
- scale path glyphs to match nearby text
- move glyphs with their text anchor

### AXIS-001: Axes And Ticks Are Consistent

Axes in comparable panels should use consistent styling.

Expected:

- axis stroke widths match across comparable plots
- tick lengths match across comparable plots
- tick labels use consistent font size
- axis labels use consistent font size
- ticks are not excessively long or short

Typical correction:

- set tick length
- set tick thickness
- set tick label size
- set axis line stroke width

Related automated checks:

- `AXIS-001`: tick label size consistency
- `AXIS-002`: tick length consistency
- `AXIS-003`: tick stroke/thickness consistency

### STROKE-001: Strokes Are Clean And Consistent

Stroke styling should be intentional and consistent.

Expected:

- similar object types share stroke width
- connector/electrode lines are visibly connected
- dashed lines use consistent dash patterns
- arrowheads are consistent
- strokes are not too thin for print

Typical correction:

- set stroke width
- set dash pattern
- set stroke cap/join
- reroute or reconnect lines
- standardize arrowheads

### COLOR-001: Color Has Sufficient Contrast

Color should be clear in print and screen contexts.

Expected:

- foreground text has strong contrast
- data colors are distinguishable
- schematic colors support meaning
- unnecessary colors are removed

Typical correction:

- darken low-contrast text/strokes
- standardize palette
- reduce decorative colors
- use colorblind-aware pairs where possible

### PAGE-001: Artwork Fits The Page

Objects should not unintentionally sit outside the page or be clipped.

Expected:

- important figure content is on page
- margins are intentional
- page size is only changed when explicitly requested

Typical correction:

- move artwork onto page
- scale/fit figure to page when explicitly requested
- crop page to artwork when explicitly requested

### VECTOR-001: Figure Remains Editable

The figure should preserve editable vector structure when possible.

Expected:

- text remains text unless conversion is necessary
- imported path glyphs are grouped with labels
- schematic elements remain separate editable objects
- generated objects use semantic IDs when possible

Typical correction:

- avoid flattening objects unnecessarily
- name/group related objects
- keep templates editable

## User Evaluation Loop

After FigureAgent edits a figure, the user evaluates the result.

The user feedback should capture:

- prompt
- screenshot before/after if available
- what worked
- what failed
- which rubric rule was violated
- desired correction

This feedback becomes the training signal for future rubric refinement and example retrieval.
