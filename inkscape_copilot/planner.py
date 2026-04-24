from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .interpreter import interpret_prompt
from .schema import ActionPlan


@dataclass(frozen=True)
class PanelInfo:
    label: str
    label_object_id: str
    label_bbox: dict[str, float] | None
    bbox: dict[str, float] | None
    object_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "label_object_id": self.label_object_id,
            "label_bbox": self.label_bbox,
            "bbox": self.bbox,
            "object_count": self.object_count,
        }


@dataclass(frozen=True)
class SelectionItem:
    object_id: str
    tag: str
    fill: str | None
    stroke: str | None
    bbox: dict[str, float] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "tag": self.tag,
            "fill": self.fill,
            "stroke": self.stroke,
            "bbox": self.bbox,
        }


@dataclass(frozen=True)
class DocumentObject:
    object_id: str
    tag: str
    text: str | None
    fill: str | None
    stroke: str | None
    bbox: dict[str, float] | None
    object_index: int | None = None
    center: dict[str, float] | None = None
    stroke_width: str | None = None
    font_size: str | None = None
    role: str | None = None
    panel: str | None = None
    axis: str | None = None
    parent_id: str | None = None
    group_id: str | None = None
    descendant_count: int = 0
    panel_root_id: str | None = None
    label_for: str | None = None
    attached_to: str | None = None
    text_group_id: str | None = None
    glyph_for: str | None = None
    line_points: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "tag": self.tag,
            "text": self.text,
            "fill": self.fill,
            "stroke": self.stroke,
            "object_index": self.object_index,
            "center": self.center,
            "stroke_width": self.stroke_width,
            "font_size": self.font_size,
            "bbox": self.bbox,
            "role": self.role,
            "panel": self.panel,
            "axis": self.axis,
            "parent_id": self.parent_id,
            "group_id": self.group_id,
            "descendant_count": self.descendant_count,
            "panel_root_id": self.panel_root_id,
            "label_for": self.label_for,
            "attached_to": self.attached_to,
            "text_group_id": self.text_group_id,
            "glyph_for": self.glyph_for,
            "line_points": self.line_points,
        }


@dataclass(frozen=True)
class DocumentContext:
    width: float | None
    height: float | None
    selection: list[SelectionItem]
    document_name: str | None = None
    document_path: str | None = None
    objects: list[DocumentObject] | None = None
    visual_snapshot: dict[str, Any] | None = None
    panels: list[PanelInfo] | None = None

    def to_dict(self) -> dict[str, Any]:
        objects = self.objects or []
        role_counts: dict[str, int] = {}
        panel_counts: dict[str, int] = {}
        for item in objects:
            if item.role:
                role_counts[item.role] = role_counts.get(item.role, 0) + 1
            if item.panel:
                panel_counts[item.panel] = panel_counts.get(item.panel, 0) + 1
        return {
            "document_name": self.document_name,
            "document_path": self.document_path,
            "width": self.width,
            "height": self.height,
            "selection_count": len(self.selection),
            "selection": [item.to_dict() for item in self.selection],
            "object_count": len(objects),
            "objects": [item.to_dict() for item in objects],
            "visual_snapshot": self.visual_snapshot,
            "panels": [panel.to_dict() for panel in self.panels or []],
            "target_summary": {
                "roles": role_counts,
                "panels": panel_counts,
            },
        }


def build_fallback_plan(prompt: str) -> ActionPlan:
    actions = interpret_prompt(prompt)
    return ActionPlan(
        summary=f"Fallback interpreter plan for: {prompt}",
        actions=actions,
        needs_confirmation=False,
    )
