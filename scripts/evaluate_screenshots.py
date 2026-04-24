#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from inkscape_copilot.defaults import default_document_context
from inkscape_copilot.openai_bridge import OpenAIPlannerError, _created_plan_bbox, plan_with_openai


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _action_counts(plan_dict: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for action in plan_dict.get("actions", []):
        kind = action.get("kind")
        if isinstance(kind, str):
            counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def evaluate(path: Path, prompt: str) -> dict:
    document = default_document_context()
    try:
        plan = plan_with_openai(prompt, document, image_urls=[_data_url(path)])
        plan_dict = plan.to_dict()
        bbox = _created_plan_bbox(plan)
        fits_page = bool(
            bbox
            and bbox[0] >= 0
            and bbox[1] >= 0
            and bbox[2] <= float(document.width or 0)
            and bbox[3] <= float(document.height or 0)
        )
        return {
            "image": str(path),
            "ok": True,
            "action_count": len(plan.actions),
            "needs_confirmation": plan.needs_confirmation,
            "fits_page": fits_page,
            "bbox": bbox,
            "action_counts": _action_counts(plan_dict),
            "summary": plan.summary,
            "plan": plan_dict,
        }
    except OpenAIPlannerError as exc:
        return {
            "image": str(path),
            "ok": False,
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate screenshot-to-action planning quality.")
    parser.add_argument("images", nargs="+", help="Screenshot image paths")
    parser.add_argument(
        "--prompt",
        default="Recreate this reference image as an editable vector schematic on the current page. Use supported primitives and make it publication clean.",
    )
    parser.add_argument("--out", default="state/evaluation_results.json", help="Output JSON path")
    args = parser.parse_args()

    results = [evaluate(Path(image).expanduser(), args.prompt) for image in args.images]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    summary = [
        {
            "image": result["image"],
            "ok": result.get("ok"),
            "action_count": result.get("action_count"),
            "needs_confirmation": result.get("needs_confirmation"),
            "fits_page": result.get("fits_page"),
            "error": result.get("error"),
        }
        for result in results
    ]
    print(json.dumps({"out": str(out), "summary": summary}, indent=2))
    return 0 if all(result.get("ok") for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
