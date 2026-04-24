from __future__ import annotations

from typing import Any

from .planner import DocumentObject, PanelInfo
from .targeting import node_snapshot_payload, panel_labels


def _bbox_center(bbox: dict[str, float] | None) -> tuple[float, float] | None:
    if not bbox:
        return None
    return (bbox["left"] + (bbox["width"] / 2.0), bbox["top"] + (bbox["height"] / 2.0))


def _distance(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
    if a is None or b is None:
        return float("inf")
    return ((a[0] - b[0]) ** 2) + ((a[1] - b[1]) ** 2)


def _contains(outer: dict[str, float] | None, inner: dict[str, float] | None, pad: float = 0.0) -> bool:
    if not outer or not inner:
        return False
    return (
        inner["left"] >= outer["left"] - pad
        and inner["top"] >= outer["top"] - pad
        and (inner["left"] + inner["width"]) <= (outer["left"] + outer["width"] + pad)
        and (inner["top"] + inner["height"]) <= (outer["top"] + outer["height"] + pad)
    )


def _bbox_union(boxes: list[dict[str, float]]) -> dict[str, float] | None:
    if not boxes:
        return None
    left = min(box["left"] for box in boxes)
    top = min(box["top"] for box in boxes)
    right = max(box["left"] + box["width"] for box in boxes)
    bottom = max(box["top"] + box["height"] for box in boxes)
    return {
        "left": left,
        "top": top,
        "width": right - left,
        "height": bottom - top,
    }


def _reasonable_panel_member_bbox(bbox: dict[str, float] | None) -> bool:
    if not bbox:
        return False
    if bbox["width"] < 0 or bbox["height"] < 0:
        return False
    # Imported bitmaps/clip artifacts can occasionally report enormous EMF-like
    # coordinates. They are real SVG nodes, but not useful for panel bounds.
    if bbox["width"] > 10000 or bbox["height"] > 10000:
        return False
    return True


def _contains_point(outer: dict[str, float] | None, point: tuple[float, float] | None, pad: float = 0.0) -> bool:
    if not outer or not point:
        return False
    x, y = point
    return (
        outer["left"] - pad <= x <= outer["left"] + outer["width"] + pad
        and outer["top"] - pad <= y <= outer["top"] + outer["height"] + pad
    )


def _point_to_bbox_distance(point: tuple[float, float], bbox: dict[str, float] | None) -> float:
    if not bbox:
        return float("inf")
    x, y = point
    left = bbox["left"]
    right = bbox["left"] + bbox["width"]
    top = bbox["top"]
    bottom = bbox["top"] + bbox["height"]
    dx = max(left - x, 0.0, x - right)
    dy = max(top - y, 0.0, y - bottom)
    return (dx * dx) + (dy * dy)


def _line_orientation(bbox: dict[str, float] | None) -> str | None:
    if not bbox:
        return None
    if bbox["width"] >= bbox["height"]:
        return "horizontal"
    return "vertical"


def _line_endpoints(item: DocumentObject) -> tuple[tuple[float, float], tuple[float, float]] | None:
    points = item.line_points or {}
    try:
        return (
            (float(points["x1"]), float(points["y1"])),
            (float(points["x2"]), float(points["y2"])),
        )
    except (KeyError, TypeError, ValueError):
        pass

    if not item.bbox:
        return None
    left = item.bbox["left"]
    right = item.bbox["left"] + item.bbox["width"]
    top = item.bbox["top"]
    bottom = item.bbox["top"] + item.bbox["height"]
    center_x = left + (item.bbox["width"] / 2.0)
    center_y = top + (item.bbox["height"] / 2.0)
    if _line_orientation(item.bbox) == "horizontal":
        return (left, center_y), (right, center_y)
    return (center_x, top), (center_x, bottom)


def _connector_bar_score(connector: DocumentObject, bar: DocumentObject) -> float:
    endpoints = _line_endpoints(connector)
    if not endpoints:
        return float("inf")
    endpoint_distance = min(_point_to_bbox_distance(point, bar.bbox) for point in endpoints)
    center_distance = _distance(_bbox_center(connector.bbox), _bbox_center(bar.bbox))
    return endpoint_distance * 1000.0 + center_distance * 0.001


def _panel_root_map(objects: list[DocumentObject]) -> dict[str, str]:
    panel_roots = [item for item in objects if item.role == "panel_root"]
    mapping: dict[str, str] = {}
    for item in objects:
        if item.object_id in mapping:
            continue
        best_root: tuple[float, str] | None = None
        item_center = _bbox_center(item.bbox)
        for root in panel_roots:
            if item.panel and root.panel and item.panel != root.panel:
                continue
            if not _contains(root.bbox, item.bbox, pad=2.0) and not _contains_point(
                root.bbox, item_center, pad=10.0
            ):
                continue
            score = _distance(item_center, _bbox_center(root.bbox))
            if best_root is None or score < best_root[0]:
                best_root = (score, root.object_id)
        if best_root:
            mapping[item.object_id] = best_root[1]
    return mapping


def _label_targets(objects: list[DocumentObject]) -> dict[str, str]:
    targets: dict[str, str] = {}
    bars = [item for item in objects if item.role == "layer_bar"]
    labels = [item for item in objects if item.role in {"layer_label", "label"} and item.text]
    for label in labels:
        label_center = _bbox_center(label.bbox)
        best: tuple[float, str] | None = None
        for bar in bars:
            if label.panel and bar.panel and label.panel != bar.panel:
                continue
            if not _contains(bar.bbox, label.bbox, pad=10.0):
                continue
            score = _distance(label_center, _bbox_center(bar.bbox))
            if best is None or score < best[0]:
                best = (score, bar.object_id)
        if best:
            targets[label.object_id] = best[1]
    return targets


def _connector_targets(objects: list[DocumentObject]) -> dict[str, str]:
    targets: dict[str, str] = {}
    bars = [item for item in objects if item.role == "layer_bar"]
    connectors = [item for item in objects if item.role in {"connector", "electrode"}]
    for connector in connectors:
        if _line_endpoints(connector) is None:
            continue
        best: tuple[float, str] | None = None
        for bar in bars:
            if connector.panel and bar.panel and connector.panel != bar.panel:
                continue
            score = _connector_bar_score(connector, bar)
            if best is None or score < best[0]:
                best = (score, bar.object_id)
        if best:
            targets[connector.object_id] = best[1]
    return targets


def _has_visible_fill(item: DocumentObject) -> bool:
    fill = (item.fill or "").strip().lower()
    return bool(fill) and fill != "none" and not fill.startswith("url(")


def _is_text_glyph_candidate(item: DocumentObject) -> bool:
    if item.tag not in {"path", "polygon", "polyline", "use"} or not item.bbox:
        return False
    if not _has_visible_fill(item):
        return False
    width = item.bbox["width"]
    height = item.bbox["height"]
    if width <= 0 or height <= 0:
        return False
    if width > 30 or height > 30:
        return False
    if item.role in {"axis_line", "axis_tick", "connector", "electrode", "layer_bar", "frame"}:
        return False
    return True


def _is_text_group_anchor(item: DocumentObject) -> bool:
    if item.tag not in {"text", "tspan"} or not item.bbox:
        return False
    return item.role in {"axis_label", "label", "layer_label", "tick_label"}


def _text_glyph_targets(objects: list[DocumentObject]) -> dict[str, str]:
    targets: dict[str, str] = {}
    anchors = [item for item in objects if _is_text_group_anchor(item)]
    glyphs = [item for item in objects if _is_text_glyph_candidate(item)]
    for glyph in glyphs:
        glyph_center = _bbox_center(glyph.bbox)
        best: tuple[float, str] | None = None
        for anchor in anchors:
            if glyph.panel and anchor.panel and glyph.panel != anchor.panel:
                continue
            if glyph.group_id and anchor.group_id and glyph.group_id != anchor.group_id:
                # Imported math labels usually keep their glyph paths in the
                # same group. Allow cross-group fallback below only when close.
                group_penalty = 900.0
            else:
                group_penalty = 0.0
            distance = _point_to_bbox_distance(glyph_center, anchor.bbox)
            if distance > 2500 and group_penalty:
                continue
            if distance > 900 and not group_penalty:
                continue
            score = distance + group_penalty
            if best is None or score < best[0]:
                best = (score, anchor.object_id)
        if best:
            targets[glyph.object_id] = best[1]
    return targets


def _with_relationships(objects: list[DocumentObject]) -> list[DocumentObject]:
    panel_root_map = _panel_root_map(objects)
    label_targets = _label_targets(objects)
    connector_targets = _connector_targets(objects)
    text_glyph_targets = _text_glyph_targets(objects)
    enriched: list[DocumentObject] = []
    for item in objects:
        glyph_for = text_glyph_targets.get(item.object_id)
        text_group_id = glyph_for
        if _is_text_group_anchor(item):
            text_group_id = item.object_id
        enriched.append(
            DocumentObject(
                object_id=item.object_id,
                tag=item.tag,
                text=item.text,
                fill=item.fill,
                stroke=item.stroke,
                bbox=item.bbox,
                object_index=item.object_index,
                center=item.center,
                stroke_width=item.stroke_width,
                font_size=item.font_size,
                role="text_glyph" if glyph_for else item.role,
                panel=item.panel,
                axis=item.axis,
                parent_id=item.parent_id,
                group_id=item.group_id,
                descendant_count=item.descendant_count,
                panel_root_id=panel_root_map.get(item.object_id),
                label_for=label_targets.get(item.object_id),
                attached_to=connector_targets.get(item.object_id),
                text_group_id=text_group_id,
                glyph_for=glyph_for,
                line_points=item.line_points,
            )
        )
    return enriched


def _scene_priority(item: DocumentObject) -> tuple[int, str]:
    role_priority = {
        "panel_root": 0,
        "panel_label": 1,
        "frame": 2,
        "layer_bar": 3,
        "layer_label": 4,
        "connector": 5,
        "electrode": 5,
        "axis_line": 6,
        "axis_tick": 7,
        "axis_label": 8,
        "tick_label": 9,
        "label": 10,
    }
    return (role_priority.get(item.role or "", 20), item.object_id)


def detect_panels(objects: list[DocumentObject]) -> list[PanelInfo]:
    labels = sorted(
        [item for item in objects if item.role == "panel_label" and item.text and len(item.text.strip()) == 1],
        key=lambda item: (item.text or "", item.object_index or 0),
    )
    panels: list[PanelInfo] = []
    for label in labels:
        panel_name = (label.text or "").strip()
        members = [
            item
            for item in objects
            if item.panel == panel_name
            and item.object_id != label.object_id
            and item.bbox
            and _reasonable_panel_member_bbox(item.bbox)
            and item.role not in {"panel_label", "panel_root"}
        ]
        member_boxes = [item.bbox for item in members if item.bbox]
        if label.bbox:
            member_boxes.append(label.bbox)
        panels.append(
            PanelInfo(
                label=panel_name,
                label_object_id=label.object_id,
                label_bbox=label.bbox,
                bbox=_bbox_union(member_boxes),
                object_count=len(members),
            )
        )
    return panels


def extract_scene_objects(svg: Any, limit: int | None = 500) -> list[DocumentObject]:
    objects: list[DocumentObject] = []
    try:
        nodes = list(svg.iterdescendants())
    except Exception:
        return objects

    labels = panel_labels(nodes)
    object_index = 0
    for node in nodes:
        payload = node_snapshot_payload(node, labels)
        if not payload:
            continue
        object_index += 1
        objects.append(
            DocumentObject(
                object_id=str(payload["object_id"]),
                tag=str(payload["tag"]),
                text=payload.get("text"),
                fill=payload.get("fill"),
                stroke=payload.get("stroke"),
                bbox=payload.get("bbox"),
                object_index=object_index,
                center=payload.get("center"),
                stroke_width=payload.get("stroke_width"),
                font_size=payload.get("font_size"),
                role=payload.get("role"),
                panel=payload.get("panel"),
                axis=payload.get("axis"),
                parent_id=payload.get("parent_id"),
                group_id=payload.get("group_id"),
                descendant_count=int(payload.get("descendant_count") or 0),
                line_points=payload.get("line_points"),
            )
        )
    enriched = _with_relationships(objects)
    if limit is None or len(enriched) <= limit:
        return enriched
    return sorted(enriched, key=_scene_priority)[:limit]
