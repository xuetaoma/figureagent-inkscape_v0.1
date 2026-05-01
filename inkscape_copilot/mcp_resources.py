from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import bridge
from .bridge import (
    read_document_context,
    read_events,
    read_execution_result,
    read_session_state,
    read_status,
)
from .planner import DocumentContext, DocumentObject, PanelInfo, SelectionItem
from .publication_fixes import publication_fix_suggestions
from .publication_qa import publication_qa


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLICATION_RUBRIC_FILE = PROJECT_ROOT / "publication_rubric.md"
PUBLICATION_FEEDBACK_FILE = PROJECT_ROOT / "publication_feedback.md"
PUBLICATION_EXAMPLES_DIR = PROJECT_ROOT / "publication_examples"


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class FigureAgentResource:
    uri: str
    name: str
    description: str
    mime_type: str

    def to_descriptor(self) -> JsonDict:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


def _json_text(payload: JsonDict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _document_context_from_payload(payload: JsonDict) -> DocumentContext:
    selection = [
        SelectionItem(
            object_id=str(item.get("object_id") or ""),
            tag=str(item.get("tag") or ""),
            fill=item.get("fill") if isinstance(item.get("fill"), str) else None,
            stroke=item.get("stroke") if isinstance(item.get("stroke"), str) else None,
            bbox=item.get("bbox") if isinstance(item.get("bbox"), dict) else None,
        )
        for item in payload.get("selection", [])
        if isinstance(item, dict)
    ]
    objects = [
        DocumentObject(
            object_id=str(item.get("object_id") or ""),
            tag=str(item.get("tag") or ""),
            text=item.get("text") if isinstance(item.get("text"), str) else None,
            fill=item.get("fill") if isinstance(item.get("fill"), str) else None,
            stroke=item.get("stroke") if isinstance(item.get("stroke"), str) else None,
            bbox=item.get("bbox") if isinstance(item.get("bbox"), dict) else None,
            object_index=item.get("object_index") if isinstance(item.get("object_index"), int) else None,
            center=item.get("center") if isinstance(item.get("center"), dict) else None,
            stroke_width=item.get("stroke_width") if isinstance(item.get("stroke_width"), str) else None,
            font_size=item.get("font_size") if isinstance(item.get("font_size"), str) else None,
            role=item.get("role") if isinstance(item.get("role"), str) else None,
            panel=item.get("panel") if isinstance(item.get("panel"), str) else None,
            axis=item.get("axis") if isinstance(item.get("axis"), str) else None,
            parent_id=item.get("parent_id") if isinstance(item.get("parent_id"), str) else None,
            group_id=item.get("group_id") if isinstance(item.get("group_id"), str) else None,
            descendant_count=int(item.get("descendant_count") or 0),
            panel_root_id=item.get("panel_root_id") if isinstance(item.get("panel_root_id"), str) else None,
            label_for=item.get("label_for") if isinstance(item.get("label_for"), str) else None,
            attached_to=item.get("attached_to") if isinstance(item.get("attached_to"), str) else None,
            text_group_id=item.get("text_group_id") if isinstance(item.get("text_group_id"), str) else None,
            glyph_for=item.get("glyph_for") if isinstance(item.get("glyph_for"), str) else None,
            line_points=item.get("line_points") if isinstance(item.get("line_points"), dict) else None,
        )
        for item in payload.get("objects", [])
        if isinstance(item, dict)
    ]
    panels = [
        PanelInfo(
            label=str(item.get("label") or ""),
            label_object_id=str(item.get("label_object_id") or ""),
            label_bbox=item.get("label_bbox") if isinstance(item.get("label_bbox"), dict) else None,
            bbox=item.get("bbox") if isinstance(item.get("bbox"), dict) else None,
            object_count=int(item.get("object_count") or 0),
        )
        for item in payload.get("panels", [])
        if isinstance(item, dict)
    ]
    return DocumentContext(
        width=payload.get("width") if isinstance(payload.get("width"), (int, float)) else None,
        height=payload.get("height") if isinstance(payload.get("height"), (int, float)) else None,
        document_name=payload.get("document_name") if isinstance(payload.get("document_name"), str) else None,
        document_path=payload.get("document_path") if isinstance(payload.get("document_path"), str) else None,
        selection=selection,
        objects=objects,
        panels=panels,
        visual_snapshot=payload.get("visual_snapshot") if isinstance(payload.get("visual_snapshot"), dict) else None,
    )


def resource_registry() -> dict[str, FigureAgentResource]:
    resources = [
        FigureAgentResource(
            uri="figureagent://document/context",
            name="Current document context",
            description="Latest structured FigureAgent document context, including selection, scene graph, panels, and snapshot metadata.",
            mime_type="application/json",
        ),
        FigureAgentResource(
            uri="figureagent://document/scene-graph",
            name="Current scene graph",
            description="Addressable objects from the latest Inkscape document sync.",
            mime_type="application/json",
        ),
        FigureAgentResource(
            uri="figureagent://document/snapshot.svg",
            name="Current SVG snapshot",
            description="Latest SVG snapshot written by the Inkscape worker.",
            mime_type="image/svg+xml",
        ),
        FigureAgentResource(
            uri="figureagent://document/snapshot.png",
            name="Current rendered PNG snapshot",
            description="Latest rendered page PNG snapshot written by the Inkscape worker.",
            mime_type="image/png",
        ),
        FigureAgentResource(
            uri="figureagent://bridge/status",
            name="Bridge status",
            description="Queue, session, execution, and worker status.",
            mime_type="application/json",
        ),
        FigureAgentResource(
            uri="figureagent://bridge/events",
            name="Recent bridge events",
            description="Recent FigureAgent runtime events.",
            mime_type="application/json",
        ),
        FigureAgentResource(
            uri="figureagent://worker/log",
            name="Worker debug log",
            description="Recent Inkscape worker debug log lines.",
            mime_type="text/plain",
        ),
        FigureAgentResource(
            uri="figureagent://publication/qa",
            name="Publication QA",
            description="Publication quality findings and safe fix suggestions for the latest document context.",
            mime_type="application/json",
        ),
        FigureAgentResource(
            uri="figureagent://publication/rubric",
            name="Publication rubric",
            description="Human-readable publication quality rules used by FigureAgent.",
            mime_type="text/markdown",
        ),
        FigureAgentResource(
            uri="figureagent://publication/feedback",
            name="Publication feedback",
            description="User feedback log for prior FigureAgent publication-editing attempts.",
            mime_type="text/markdown",
        ),
        FigureAgentResource(
            uri="figureagent://publication/examples",
            name="Publication examples index",
            description="Index of local publication example notes and metadata files.",
            mime_type="application/json",
        ),
    ]
    return {resource.uri: resource for resource in resources}


def list_resources() -> list[JsonDict]:
    return [resource.to_descriptor() for resource in resource_registry().values()]


def _read_text_file(path: Path, *, missing_message: str) -> str:
    if not path.exists():
        return missing_message
    return path.read_text(encoding="utf-8", errors="replace")


def _worker_debug_log() -> Path:
    return bridge.STATE_DIR / "worker_debug.log"


def read_resource(uri: str) -> JsonDict:
    registry = resource_registry()
    if uri not in registry:
        raise ValueError(f"Unknown FigureAgent resource: {uri}")
    resource = registry[uri]

    if uri == "figureagent://document/context":
        text = _json_text(read_document_context())
        return {"uri": uri, "mimeType": resource.mime_type, "text": text}

    if uri == "figureagent://document/scene-graph":
        context = read_document_context()
        text = _json_text(
            {
                "document_name": context.get("document_name"),
                "updated_at": context.get("updated_at"),
                "object_count": context.get("object_count"),
                "target_summary": context.get("target_summary"),
                "panels": context.get("panels") or [],
                "selection": context.get("selection") or [],
                "objects": context.get("objects") or [],
            }
        )
        return {"uri": uri, "mimeType": resource.mime_type, "text": text}

    if uri == "figureagent://document/snapshot.svg":
        text = _read_text_file(bridge.DOCUMENT_SVG_SNAPSHOT_FILE, missing_message="No SVG snapshot has been written yet.")
        return {"uri": uri, "mimeType": resource.mime_type, "text": text}

    if uri == "figureagent://document/snapshot.png":
        png_path = bridge.DOCUMENT_PNG_SNAPSHOT_FILE
        if not png_path.exists():
            return {
                "uri": uri,
                "mimeType": "text/plain",
                "text": "No PNG snapshot has been written yet.",
            }
        return {
            "uri": uri,
            "mimeType": resource.mime_type,
            "blob": base64.b64encode(png_path.read_bytes()).decode("ascii"),
        }

    if uri == "figureagent://bridge/status":
        text = _json_text(
            {
                "status": read_status(),
                "session": read_session_state(),
                "execution_result": read_execution_result(),
            }
        )
        return {"uri": uri, "mimeType": resource.mime_type, "text": text}

    if uri == "figureagent://bridge/events":
        return {"uri": uri, "mimeType": resource.mime_type, "text": _json_text({"events": read_events(limit=100)})}

    if uri == "figureagent://worker/log":
        text = _read_text_file(_worker_debug_log(), missing_message="No worker debug log has been written yet.")
        lines = text.splitlines()[-200:]
        return {"uri": uri, "mimeType": resource.mime_type, "text": "\n".join(lines)}

    if uri == "figureagent://publication/qa":
        context = _document_context_from_payload(read_document_context())
        qa = publication_qa(context)
        text = _json_text(
            {
                "qa": qa,
                "publication_fix_suggestions": publication_fix_suggestions(context, qa),
            }
        )
        return {"uri": uri, "mimeType": resource.mime_type, "text": text}

    if uri == "figureagent://publication/rubric":
        return {
            "uri": uri,
            "mimeType": resource.mime_type,
            "text": _read_text_file(PUBLICATION_RUBRIC_FILE, missing_message="publication_rubric.md is missing."),
        }

    if uri == "figureagent://publication/feedback":
        return {
            "uri": uri,
            "mimeType": resource.mime_type,
            "text": _read_text_file(PUBLICATION_FEEDBACK_FILE, missing_message="publication_feedback.md is missing."),
        }

    if uri == "figureagent://publication/examples":
        examples: list[JsonDict] = []
        if PUBLICATION_EXAMPLES_DIR.exists():
            for path in sorted(PUBLICATION_EXAMPLES_DIR.rglob("*")):
                if path.is_dir():
                    continue
                if path.suffix.lower() not in {".md", ".json", ".txt"}:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    text = ""
                examples.append(
                    {
                        "path": str(path),
                        "relative_path": str(path.relative_to(PUBLICATION_EXAMPLES_DIR)),
                        "size_bytes": path.stat().st_size,
                        "preview": text[:2000],
                    }
                )
        return {"uri": uri, "mimeType": resource.mime_type, "text": _json_text({"examples": examples})}

    raise ValueError(f"Unhandled FigureAgent resource: {uri}")
