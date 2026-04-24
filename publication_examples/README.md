# Publication Examples

This folder is for reference figures and user-evaluated examples.

The near-term goal is not fine-tuning. The goal is example-based guidance:

1. collect strong publication figures
2. collect failed/copilot-edited examples
3. write short critiques using `publication_rubric.md`
4. retrieve relevant examples during planning

## Suggested Structure

Use one folder per example:

```text
publication_examples/
  example_001_transport_multipanel/
    reference.png
    notes.md
    metadata.json
```

## Example Metadata

```json
{
  "id": "example_001_transport_multipanel",
  "category": "multi-panel transport figure",
  "quality": "reference",
  "rubric_tags": ["PANEL-001", "TEXT-001", "AXIS-001"],
  "notes": "Good panel label hierarchy, clean axis typography, consistent plot spacing."
}
```

## Notes Template

```markdown
# Example Notes

## Why This Is Good

- ...

## Relevant Rubric Rules

- `TEXT-001`: ...

## Style Values

- panel labels: ...
- axis labels: ...
- tick labels: ...
- stroke widths: ...

## Reusable Guidance

- ...
```

