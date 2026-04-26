from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


MAX_FEEDBACK_CHARS = 3000
MAX_EXAMPLE_CHARS = 4000


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    env_root = os.environ.get("INKSCAPE_COPILOT_PROJECT_ROOT")
    if env_root:
        roots.append(Path(env_root).expanduser())
    roots.append(Path(__file__).resolve().parents[1])
    roots.append(Path.home() / "Desktop" / "inkscape-copilot")

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _project_root() -> Path | None:
    for root in _candidate_roots():
        if (root / "publication_rubric.md").exists():
            return root
    return None


def _read_text(path: Path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except OSError:
        return ""


def _latest_feedback(root: Path) -> list[dict[str, str]]:
    text = _read_text(root / "publication_feedback.md", MAX_FEEDBACK_CHARS * 2)
    if not text:
        return []
    entries = re.split(r"\n(?=##\s+\d{4}-\d{2}-\d{2}\s+-\s+)", text)
    recent = [entry.strip() for entry in entries if entry.strip().startswith("## ")]
    output: list[dict[str, str]] = []
    for entry in recent[-3:]:
        title = entry.splitlines()[0].removeprefix("## ").strip()
        body = "\n".join(entry.splitlines()[1:]).strip()
        output.append({"title": title, "notes": body[:1000]})
    return output


def _example_summaries(root: Path) -> list[dict[str, Any]]:
    examples_dir = root / "publication_examples"
    if not examples_dir.exists():
        return []
    examples: list[dict[str, Any]] = []
    for folder in sorted(item for item in examples_dir.iterdir() if item.is_dir()):
        metadata: dict[str, Any] = {}
        metadata_path = folder / "metadata.json"
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                metadata = {}
        notes = _read_text(folder / "notes.md", 1200)
        if metadata or notes:
            examples.append(
                {
                    "id": metadata.get("id") or folder.name,
                    "category": metadata.get("category"),
                    "quality": metadata.get("quality"),
                    "rubric_tags": metadata.get("rubric_tags") or [],
                    "notes": notes,
                }
            )
    return examples[-5:]


def publication_memory_summary() -> dict[str, Any]:
    root = _project_root()
    if not root:
        return {"feedback": [], "examples": []}
    summary = {
        "feedback": _latest_feedback(root),
        "examples": _example_summaries(root),
    }
    encoded = json.dumps(summary, ensure_ascii=True)
    if len(encoded) <= MAX_FEEDBACK_CHARS + MAX_EXAMPLE_CHARS:
        return summary
    return {
        "feedback": summary["feedback"][-2:],
        "examples": summary["examples"][-3:],
    }
