# Selection Architecture

## Goal

Make object selection explicit and reliable. FigureAgent should not depend on stale UI selection or fragile prompt guessing when it can inspect the document directly.

## Model

```text
SVG document
-> scene graph snapshot
-> semantic relationships
-> target resolver
-> structured action plan
-> deterministic executor
```

## Scene Graph Snapshot

Each object snapshot should include:

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

Relationship hints include:

- `panel_root_id`
- `label_for`
- `attached_to`
- `text_group_id`
- `glyph_for`

## Target Resolver

Resolvers accept semantic queries such as:

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

This allows prompts like:

- `move figure a to the top left`
- `make the connectors thicker`
- `connect the electrodes to the graphite layer`
- `make ticks in figure a longer`
- `make the rho axis label smaller`

## Text And Math Glyphs

Imported scientific figures often convert symbols like rho, Omega, subscripts, superscripts, and other math fragments into SVG paths. Those paths do not expose editable text properties.

The selection layer handles this by:

- marking nearby filled path glyphs as `role=text_glyph`
- linking them to their text anchor through `glyph_for`
- assigning a shared `text_group_id`
- expanding text-label selections to include companion glyph paths

This means a command such as `set y-axis labels to 10 pt` can affect both normal text and path-based math glyphs.

## Planning Rule

The planner should:

1. resolve targets first
2. build a selection if the edit is multi-object
3. apply transforms or style edits after target resolution
4. use `include_descendants=true` for panel-wide operations
5. prefer relationship selectors when available

## Executor Rule

The executor should never guess intent from the prompt. It should only:

1. resolve targets from explicit selectors
2. merge selection if requested
3. apply the requested edit
4. report what changed

## Current Direction

- shared targeting logic lives in `inkscape_copilot/targeting.py`
- scene relationship logic lives in `inkscape_copilot/scene_graph.py`
- worker and executor use the same semantic inference rules
- `select_targets` is the preferred explicit multi-object target action
- panel-wide edits use panel selectors plus `include_descendants=true`
- text-label edits should include companion `text_glyph` paths when present
