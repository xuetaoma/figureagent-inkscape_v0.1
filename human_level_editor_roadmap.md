# Human-Level FigureAgent for Inkscape Roadmap

## Product Goal

The goal is a real editor agent, not an assistant that only gives advice.

For publication figures, FigureAgent should be able to do the same classes of work a skilled human does in Inkscape:

- inspect the current figure
- identify the correct object or region
- select the right targets
- make precise changes
- check the visual result
- correct mistakes
- continue across multiple steps

## Core Principle

FigureAgent should not require the user to manually select the correct object. Manual selection can be a useful hint, but the agent needs its own editable model of the document.

## Required Capabilities

### 1. Full Object Addressability

- Every visible SVG element gets a stable handle in `document_context.objects`.
- Objects include ID, index, tag, text, style, bounds, center, parent/group IDs, and relationships.
- Objects with weak semantic roles must still be selectable by ID/index/bounds.
- Dense imported figures should not disappear from context because of overly aggressive truncation.

### 2. Scene Understanding

Infer roles such as:

- panel
- frame
- layer bar
- label
- connector
- electrode
- axis
- tick
- legend
- image
- text glyph
- generic shape

Infer relationships such as:

- label names object
- connector attaches to target
- object belongs to panel
- path glyph belongs to text label
- object belongs to group/root

Semantic guesses should never replace raw addressability. If a role guess is wrong, the object must remain editable.

### 3. Target Resolution

Convert language like:

- `the right electrode`
- `the graphite layer`
- `figure a`
- `axis labels`
- `rho_xx label`
- `ticks in panel c`

into concrete object IDs.

Resolution order should prefer:

1. direct object IDs from the scene graph
2. relationship selectors
3. semantic selectors
4. spatial selectors
5. current manual selection

### 4. Editor Primitives

Implemented or partially implemented:

- create basic shapes/text
- create common schematic primitives
- set fill/stroke/font
- move/resize/scale/rotate
- align/distribute
- tick length/thickness/label-size adjustment
- object-targeted edits
- panel-aware targeting
- path-glyph companion scaling for text-like labels

Still needed:

- group/ungroup
- font family/bold/italic/text alignment
- stroke cap/join/marker controls
- connector rerouting
- path node edits
- layer management
- clone/use handling
- boolean path operations
- snapping and guide-aware layout
- export checks

### 5. Verification Loop

After applying a step, the worker should:

- resync the SVG
- render a PNG snapshot
- compare before/after object state
- report created/deleted/changed/selected object IDs
- run publication QA checks
- expose warnings to the planner

The next step is corrective autonomy: if verification shows the wrong thing changed or nothing changed, FigureAgent should plan a small corrective follow-up.

## Human Evaluation Layer

FigureAgent should learn from user judgment before we attempt true model training.

Near-term loop:

1. FigureAgent edits or creates a figure.
2. User accepts, partially accepts, or rejects the result.
3. User records what worked and what failed in `publication_feedback.md`.
4. The failure is mapped to `publication_rubric.md` rule IDs.
5. Good and bad examples are saved under `publication_examples/`.
6. The planner later retrieves similar examples and rubric guidance.

This gives us a practical learning loop without requiring fine-tuning yet.

## Current Agency Layer

The first agency layer is in place:

- document snapshots before/after apply
- structured scene graph context
- rendered visual snapshot
- execution result with changed-object reporting
- publication QA warnings
- running status in the side panel

This is not yet full autonomous repair, but it gives the planner factual feedback.

## Near-Term Focus

The immediate focus is target reliability:

- improve panel detection for `a-g` and beyond
- improve axis and legend detection
- improve connector-to-target relationships
- improve text/math glyph grouping
- make visual QA more useful to the planner

Once targeting is reliable, higher-level publication commands become much easier.

## End State

The desired end state is:

```text
human-level figure editing agent inside Inkscape
```

not:

```text
chatbot that occasionally edits SVG
```
