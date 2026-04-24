from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

try:
    import inkex
except ModuleNotFoundError:  # pragma: no cover
    inkex = None


SCENE_SKIP_TAGS = {"defs", "metadata", "namedview", "style", "script", "svg"}
DRAWABLE_TAGS = {
    "circle",
    "ellipse",
    "g",
    "image",
    "line",
    "path",
    "polygon",
    "polyline",
    "rect",
    "text",
    "tspan",
    "use",
}


@dataclass(frozen=True)
class TargetQuery:
    object_id: str | None = None
    object_index: int | None = None
    text: str | None = None
    role: str | None = None
    panel: str | None = None
    axis: str | None = None
    tag: str | None = None
    parent_id: str | None = None
    group_id: str | None = None
    panel_root_id: str | None = None
    label_for: str | None = None
    attached_to: str | None = None
    text_group_id: str | None = None
    glyph_for: str | None = None
    include_descendants: bool = False

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> "TargetQuery":
        def _clean(key: str) -> str | None:
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            return None

        object_index = params.get("object_index")
        include_descendants = params.get("include_descendants")
        return cls(
            object_id=_clean("object_id"),
            object_index=int(object_index) if isinstance(object_index, (int, float)) else None,
            text=_clean("text"),
            role=_clean("role"),
            panel=_clean("panel"),
            axis=_clean("axis"),
            tag=_clean("tag"),
            parent_id=_clean("parent_id"),
            group_id=_clean("group_id"),
            panel_root_id=_clean("panel_root_id"),
            label_for=_clean("label_for"),
            attached_to=_clean("attached_to"),
            text_group_id=_clean("text_group_id"),
            glyph_for=_clean("glyph_for"),
            include_descendants=bool(include_descendants),
        )

    def has_selector(self) -> bool:
        return any(
            value
            for value in (
                self.object_id,
                self.object_index,
                self.text,
                self.role,
                self.panel,
                self.axis,
                self.tag,
                self.parent_id,
                self.group_id,
                self.panel_root_id,
                self.label_for,
                self.attached_to,
                self.text_group_id,
                self.glyph_for,
            )
        )


def tag_name(node: Any) -> str:
    return str(getattr(node, "tag", "")).split("}")[-1].lower()


def node_text(node: Any) -> str | None:
    parts: list[str] = []
    try:
        if getattr(node, "text", None):
            parts.append(str(node.text))
        for descendant in node.iterdescendants():
            if descendant.text:
                parts.append(str(descendant.text))
    except Exception:
        return None
    text = " ".join(" ".join(parts).split())
    return text or None


def bbox_dict(node: Any) -> dict[str, float] | None:
    try:
        bbox = node.bounding_box()
    except Exception:
        return None
    if bbox is None:
        return None
    return {
        "left": float(bbox.left),
        "top": float(bbox.top),
        "width": float(bbox.width),
        "height": float(bbox.height),
    }


def bbox_center(bbox: dict[str, float] | None) -> dict[str, float] | None:
    if not bbox:
        return None
    return {
        "x": bbox["left"] + (bbox["width"] / 2.0),
        "y": bbox["top"] + (bbox["height"] / 2.0),
    }


def style_value(node: Any, key: str) -> str | None:
    try:
        value = dict(node.style).get(key)
    except Exception:
        return None
    return str(value) if value is not None else None


def parent_id(node: Any) -> str | None:
    try:
        parent = node.getparent()
    except Exception:
        return None
    if parent is None:
        return None
    value = parent.get("id")
    return str(value) if value else None


def group_id(node: Any) -> str | None:
    try:
        current = node.getparent()
    except Exception:
        return None
    while current is not None:
        if tag_name(current) == "g":
            value = current.get("id")
            if value:
                return str(value)
        current = current.getparent()
    return None


def line_points(node: Any) -> dict[str, float] | None:
    if tag_name(node) != "line":
        return None
    try:
        return {
            "x1": float(node.get("x1")),
            "y1": float(node.get("y1")),
            "x2": float(node.get("x2")),
            "y2": float(node.get("y2")),
        }
    except (TypeError, ValueError):
        return None


def panel_labels(nodes: list[Any]) -> list[tuple[str, dict[str, float], str]]:
    labels: list[tuple[str, dict[str, float], str]] = []
    seen: set[tuple[str, str]] = set()
    for node in nodes:
        if tag_name(node) != "text":
            continue
        text = node_text(node)
        bbox = bbox_dict(node)
        if not text or not bbox:
            continue
        cleaned = text.strip()
        if len(cleaned) == 1 and cleaned in "abcdefghijklmnopqrstuvwxyz" and node.get("id"):
            key = (cleaned, str(node.get("id")))
            if key in seen:
                continue
            seen.add(key)
            labels.append((cleaned, bbox, str(node.get("id"))))
    return labels


def nearest_panel(bbox: dict[str, float] | None, labels: list[tuple[str, dict[str, float], str]]) -> str | None:
    if not bbox or not labels:
        return None
    cx = bbox["left"] + (bbox["width"] / 2.0)
    cy = bbox["top"] + (bbox["height"] / 2.0)
    best: tuple[float, str] | None = None
    for label, label_bbox, _object_id in labels:
        lx = label_bbox["left"] + (label_bbox["width"] / 2.0)
        ly = label_bbox["top"] + (label_bbox["height"] / 2.0)
        score = ((cx - lx) ** 2) + ((cy - ly) ** 2)
        if best is None or score < best[0]:
            best = (score, label)
    return best[1] if best else None


def infer_role(tag: str, text: str | None, bbox: dict[str, float] | None, fill: str | None, stroke: str | None) -> tuple[str | None, str | None]:
    if text:
        cleaned = text.strip()
        lowered = cleaned.lower()
        if tag == "text" and len(cleaned) == 1 and cleaned in "abcdefghijklmnopqrstuvwxyz":
            return "panel_label", None
        if re.fullmatch(r"[\d\s\.\,\-\+\(\)\[\]/%]+", lowered):
            return "tick_label", None
        if "axis" in lowered:
            if lowered.startswith("x") or " x" in lowered:
                return "axis_label", "x"
            if lowered.startswith("y") or " y" in lowered:
                return "axis_label", "y"
            return "axis_label", None
        if lowered in {"graphite", "hbn", "graphene", "wse2", "sio2/si", "sio2", "au"}:
            return "layer_label", None
        return "label", None

    if not bbox:
        return None, None

    width = bbox["width"]
    height = bbox["height"]
    if tag == "g":
        return "panel_root", None
    if tag == "rect":
        if width >= 60 and 8 <= height <= 24:
            return "layer_bar", None
        if width >= 100 and height >= 60:
            return "frame", None
    if tag == "circle" and 2 <= width <= 12 and 2 <= height <= 12:
        return "lattice_dot", None
    if tag in {"line", "path", "polyline"}:
        stroke_lower = (stroke or "").lower()
        if stroke_lower in {"#dc2626", "#2563eb", "#d7191c", "#2c7bb6"} and width >= 20:
            if height <= 8:
                return "electrode", None
            return "connector", None
        if width <= 4 and 4 <= height <= 18:
            return "axis_tick", "x"
        if height <= 4 and 4 <= width <= 18:
            return "axis_tick", "y"
        if width >= 40 and height <= 3:
            return "axis_line", "x"
        if height >= 40 and width <= 3:
            return "axis_line", "y"
        if stroke and stroke.lower() != "none":
            return "line_art", None
    if tag in {"circle", "ellipse"}:
        return "ellipse", None
    if tag in {"path", "polygon", "polyline"}:
        return "shape", None
    return None, None


def has_graphic_children(node: Any) -> bool:
    try:
        for child in node:
            if tag_name(child) not in SCENE_SKIP_TAGS:
                return True
    except Exception:
        return False
    return False


def graphic_descendant_count(node: Any) -> int:
    count = 0
    try:
        for descendant in node.iterdescendants():
            if tag_name(descendant) not in SCENE_SKIP_TAGS:
                count += 1
    except Exception:
        return count
    return count


def group_contains_panel_label(node: Any) -> bool:
    try:
        for descendant in node.iterdescendants():
            text = node_text(descendant)
            if not text:
                continue
            cleaned = text.strip()
            if len(cleaned) == 1 and cleaned in "abcdefghijklmnopqrstuvwxyz":
                return True
    except Exception:
        return False
    return False


def include_in_snapshot(node: Any, tag: str, bbox: dict[str, float] | None, text: str | None) -> bool:
    if tag in SCENE_SKIP_TAGS:
        return False
    if tag not in DRAWABLE_TAGS:
        return False
    if tag == "g":
        if not has_graphic_children(node):
            return False
        if group_contains_panel_label(node) or graphic_descendant_count(node) >= 5:
            return True
        return False
    if bbox is None and not text:
        return False
    if bbox is not None and bbox["width"] == 0 and bbox["height"] == 0 and not text:
        return False
    return True


def node_snapshot_payload(node: Any, labels: list[tuple[str, dict[str, float]]]) -> dict[str, Any] | None:
    object_id = node.get("id")
    if not object_id:
        return None
    tag = tag_name(node)
    bbox = bbox_dict(node)
    text = node_text(node)
    if not include_in_snapshot(node, tag, bbox, text):
        return None
    fill = style_value(node, "fill")
    stroke = style_value(node, "stroke")
    role, axis = infer_role(tag, text, bbox, fill, stroke)
    return {
        "object_id": str(object_id),
        "tag": tag,
        "text": text,
        "fill": fill,
        "stroke": stroke,
        "stroke_width": style_value(node, "stroke-width"),
        "font_size": style_value(node, "font-size"),
        "bbox": bbox,
        "center": bbox_center(bbox),
        "role": role,
        "panel": nearest_panel(bbox, labels),
        "axis": axis,
        "parent_id": parent_id(node),
        "group_id": group_id(node),
        "line_points": line_points(node),
        "descendant_count": graphic_descendant_count(node) if tag == "g" else 0,
    }


def matches_query(payload: dict[str, Any], query: TargetQuery) -> bool:
    if query.object_id and str(payload.get("object_id") or "") != query.object_id:
        return False
    if query.object_index is not None:
        try:
            if int(payload.get("object_index")) != query.object_index:
                return False
        except (TypeError, ValueError):
            return False
    if query.text:
        haystack = str(payload.get("text") or "").lower()
        if query.text.lower() not in haystack:
            return False
    for key in (
        "role",
        "panel",
        "axis",
        "tag",
        "parent_id",
        "group_id",
        "panel_root_id",
        "label_for",
        "attached_to",
        "text_group_id",
        "glyph_for",
    ):
        value = getattr(query, key)
        if value and str(payload.get(key) or "").lower() != value.lower():
            return False
    return True


def expand_descendants(objects: list[dict[str, Any]], object_ids: list[str]) -> list[str]:
    wanted = set(object_ids)
    changed = True
    while changed:
        changed = False
        for item in objects:
            item_id = str(item.get("object_id") or "")
            if not item_id or item_id in wanted:
                continue
            if (
                str(item.get("parent_id") or "") in wanted
                or str(item.get("group_id") or "") in wanted
                or str(item.get("panel_root_id") or "") in wanted
                or str(item.get("text_group_id") or "") in wanted
                or str(item.get("glyph_for") or "") in wanted
            ):
                wanted.add(item_id)
                changed = True
    ordered: list[str] = []
    for item in objects:
        item_id = str(item.get("object_id") or "")
        if item_id in wanted:
            ordered.append(item_id)
    return ordered


def resolve_ids_from_snapshot(objects: list[dict[str, Any]], query: TargetQuery) -> list[str]:
    matched: list[str] = []
    matched_groups: set[str] = set()
    for item in objects:
        if matches_query(item, query):
            object_id = item.get("object_id")
            if isinstance(object_id, str) and object_id.strip():
                clean_id = object_id.strip()
                matched.append(clean_id)
                text_group_id = str(item.get("text_group_id") or "").strip()
                if text_group_id:
                    matched_groups.add(text_group_id)
                if item.get("role") in {"axis_label", "label", "layer_label", "tick_label"}:
                    matched_groups.add(clean_id)
    if matched_groups:
        seen = set(matched)
        for item in objects:
            item_id = str(item.get("object_id") or "").strip()
            if not item_id or item_id in seen:
                continue
            if (
                str(item.get("text_group_id") or "").strip() in matched_groups
                or str(item.get("glyph_for") or "").strip() in matched_groups
            ):
                matched.append(item_id)
                seen.add(item_id)
    if query.include_descendants and matched:
        return expand_descendants(objects, matched)
    return matched
