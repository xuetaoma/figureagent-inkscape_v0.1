from __future__ import annotations

import re
import time
from dataclasses import dataclass
from math import atan2, cos, pi, sin, sqrt

import inkex
from inkex import Circle, PathElement, Rectangle, Transform
from lxml import etree

from .bridge import STATE_DIR, read_document_context
from .schema import ActionPlan
from .scene_graph import extract_scene_objects
from .targeting import (
    TargetQuery,
    bbox_dict as shared_bbox_dict,
    infer_role,
    nearest_panel,
    node_text,
    panel_labels,
    resolve_ids_from_snapshot,
    style_value,
    tag_name,
)


def _set_style_value(node: inkex.BaseElement, key: str, value: str) -> None:
    style = node.style
    style[key] = value
    node.set("style", str(style))
    if key == "font-size":
        node.set("font-size", value)


def _font_debug_log(message: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "font_size_debug.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{time.time():.3f} {message}\n")
    except Exception:
        pass


def _clean_text(value: str) -> str:
    cleaned = "".join(char if char >= " " or char in "\n\t" else "" for char in value)
    return cleaned.replace("SiO/Si", "SiO2/Si")


def _tag_name(node: inkex.BaseElement) -> str:
    return tag_name(node)


def _node_text(node: inkex.BaseElement) -> str:
    return node_text(node) or ""


def _find_node_by_id(svg: inkex.SvgDocumentElement, object_id: str) -> inkex.BaseElement | None:
    try:
        matches = svg.xpath(f'//*[@id="{object_id}"]')
        if matches:
            return matches[0]
    except Exception:
        pass
    try:
        for node in svg.iterdescendants():
            if node.get("id") == object_id:
                return node
    except Exception:
        return None
    return None


def _find_node_by_text(svg: inkex.SvgDocumentElement, text: str) -> inkex.BaseElement | None:
    needle = " ".join(text.lower().split())
    if not needle:
        return None
    matches: list[inkex.BaseElement] = []
    try:
        for node in svg.iterdescendants():
            if _tag_name(node) not in {"text", "tspan", "g"}:
                continue
            haystack = _node_text(node).lower()
            if needle and needle in haystack:
                matches.append(node)
    except Exception:
        return None
    return matches[-1] if matches else None


def _bbox_dict(node: inkex.BaseElement) -> dict[str, float] | None:
    return shared_bbox_dict(node)


def _snapshot_target_ids(params: dict) -> list[str]:
    payload = read_document_context()
    objects = payload.get("objects", [])
    if not isinstance(objects, list):
        return []
    return resolve_ids_from_snapshot(
        [item for item in objects if isinstance(item, dict)],
        TargetQuery.from_params(params),
    )


def _live_semantic_target_ids(svg: inkex.SvgDocumentElement, params: dict) -> list[str]:
    query = TargetQuery.from_params(params)
    try:
        objects = [item.to_dict() for item in extract_scene_objects(svg, limit=None)]
    except Exception:
        return []
    return resolve_ids_from_snapshot(objects, query)


def _line_endpoints(node: inkex.BaseElement) -> tuple[float, float, float, float] | None:
    try:
        return (
            float(node.get("x1")),
            float(node.get("y1")),
            float(node.get("x2")),
            float(node.get("y2")),
        )
    except (TypeError, ValueError):
        return None


def _nearest_axis_anchor(svg: inkex.SvgDocumentElement, bbox: dict[str, float], axis: str, panel: str | None) -> float | None:
    axis_line_ids = _snapshot_target_ids({"role": "axis_line", "axis": axis, "panel": panel})
    candidates: list[float] = []
    for object_id in axis_line_ids:
        node = _find_node_by_id(svg, object_id)
        if node is None:
            continue
        line_bbox = _bbox_dict(node)
        if not line_bbox:
            continue
        if axis == "x":
            candidates.append(line_bbox["top"] + (line_bbox["height"] / 2.0))
        else:
            candidates.append(line_bbox["left"] + (line_bbox["width"] / 2.0))
    if not candidates:
        return None
    center = bbox["top"] + (bbox["height"] / 2.0) if axis == "x" else bbox["left"] + (bbox["width"] / 2.0)
    return min(candidates, key=lambda value: abs(value - center))


def _node_semantics(svg: inkex.SvgDocumentElement, node: inkex.BaseElement) -> tuple[str | None, str | None, str | None]:
    bbox = _bbox_dict(node)
    text = _node_text(node)
    role, axis = infer_role(_tag_name(node), text, bbox, style_value(node, "fill"), style_value(node, "stroke"))
    panel = nearest_panel(bbox, panel_labels(list(svg.iterdescendants())))
    return role, panel, axis


def _set_tick_length(svg: inkex.SvgDocumentElement, nodes: list[inkex.BaseElement], length_px: float) -> None:
    if length_px <= 0:
        raise inkex.AbortExtension("Tick length must be greater than zero.")
    for node in nodes:
        if _tag_name(node) != "line":
            continue
        endpoints = _line_endpoints(node)
        if endpoints is None:
            continue
        x1, y1, x2, y2 = endpoints
        bbox = _bbox_dict(node)
        if not bbox:
            continue
        role, panel, axis = _node_semantics(svg, node)
        if role != "axis_tick":
            continue
        anchor = _nearest_axis_anchor(svg, bbox, axis or "x", panel)
        if axis == "x":
            if anchor is None:
                anchor = y1
            if abs(y1 - anchor) <= abs(y2 - anchor):
                node.set("y1", str(anchor))
                node.set("y2", str(anchor + length_px if y2 >= y1 else anchor - length_px))
            else:
                node.set("y2", str(anchor))
                node.set("y1", str(anchor + length_px if y1 >= y2 else anchor - length_px))
        elif axis == "y":
            if anchor is None:
                anchor = x1
            if abs(x1 - anchor) <= abs(x2 - anchor):
                node.set("x1", str(anchor))
                node.set("x2", str(anchor + length_px if x2 >= x1 else anchor - length_px))
            else:
                node.set("x2", str(anchor))
                node.set("x1", str(anchor + length_px if x1 >= x2 else anchor - length_px))


def _target_nodes(svg: inkex.SvgDocumentElement, params: dict) -> list[inkex.BaseElement]:
    query = TargetQuery.from_params(params)
    if query.object_id and not query.include_descendants:
        node = _find_node_by_id(svg, query.object_id)
        if node is None:
            raise inkex.AbortExtension("Could not find the requested existing object.")
        return [node]

    semantic_ids = _snapshot_target_ids(params)
    if not semantic_ids and query.has_selector():
        semantic_ids = _live_semantic_target_ids(svg, params)

    resolved: list[inkex.BaseElement] = []
    seen_ids: set[str] = set()
    for candidate_id in semantic_ids:
        node = _find_node_by_id(svg, candidate_id)
        if node is None:
            continue
        node_id = node.get("id")
        if node_id and node_id in seen_ids:
            continue
        if node_id:
            seen_ids.add(node_id)
        resolved.append(node)

    if resolved:
        return resolved

    if query.text and not any(
        (
            query.role,
            query.object_index,
            query.panel,
            query.axis,
            query.tag,
            query.parent_id,
            query.group_id,
            query.panel_root_id,
            query.label_for,
            query.attached_to,
            query.text_group_id,
            query.glyph_for,
        )
    ):
        node = _find_node_by_text(svg, query.text)
        if node is not None:
            return [node]

    if query.has_selector():
        raise inkex.AbortExtension("Could not find the requested existing object.")
    raise inkex.AbortExtension("Could not find the requested existing object.")


def _merge_selection(current: list[inkex.BaseElement], incoming: list[inkex.BaseElement]) -> list[inkex.BaseElement]:
    merged: list[inkex.BaseElement] = list(current)
    seen = {node.get("id") or str(id(node)) for node in current}
    for node in incoming:
        key = node.get("id") or str(id(node))
        if key in seen:
            continue
        merged.append(node)
        seen.add(key)
    return merged


def _replace_text(nodes: list[inkex.BaseElement], new_text: str) -> None:
    for node in nodes:
        if _tag_name(node) == "text":
            node.text = _clean_text(new_text)
            for descendant in node.iterdescendants():
                descendant.text = None
            continue
        for descendant in node.iterdescendants():
            if _tag_name(descendant) in {"text", "tspan"}:
                descendant.text = _clean_text(new_text)
                return
        raise inkex.AbortExtension("Target object does not contain editable text.")


def _delete_nodes(nodes: list[inkex.BaseElement]) -> None:
    for node in nodes:
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)


def _set_document_size(svg: inkex.SvgDocumentElement, width: float, height: float) -> None:
    if width <= 0 or height <= 0:
        raise inkex.AbortExtension("Document size must be greater than zero.")
    svg.set("width", f"{width}px")
    svg.set("height", f"{height}px")
    svg.set("viewBox", f"0 0 {width} {height}")


def _apply_stroke_style(
    node: inkex.BaseElement,
    *,
    stroke_hex: str | None,
    stroke_width_px: float | None,
    dash_pattern: str | None = None,
) -> None:
    node.style["stroke"] = stroke_hex or "none"
    if stroke_width_px is not None:
        node.style["stroke-width"] = str(max(0.0, stroke_width_px))
    if dash_pattern:
        node.style["stroke-dasharray"] = dash_pattern


def _rename_selected(nodes: list[inkex.BaseElement], prefix: str) -> None:
    for index, node in enumerate(nodes, start=1):
        node.set("id", f"{prefix}-{index}")


def _move_selected(nodes: list[inkex.BaseElement], delta_x: float, delta_y: float) -> None:
    for node in nodes:
        node.transform = Transform(f"translate({delta_x}, {delta_y})") @ node.transform


def _scale_selected(nodes: list[inkex.BaseElement], percent: float) -> None:
    factor = percent / 100.0
    for node in nodes:
        bbox = node.bounding_box()
        center_x = bbox.left + (bbox.width / 2.0)
        center_y = bbox.top + (bbox.height / 2.0)
        transform = Transform(
            f"translate({center_x}, {center_y}) scale({factor}) translate({-center_x}, {-center_y})"
        )
        node.transform = transform @ node.transform


def _resize_selected(nodes: list[inkex.BaseElement], width: float | None, height: float | None) -> None:
    for node in nodes:
        bbox = node.bounding_box()
        current_width = float(bbox.width)
        current_height = float(bbox.height)
        if current_width <= 0 or current_height <= 0:
            raise inkex.AbortExtension("Cannot resize an object with zero width or height.")

        target_width = float(width) if width is not None else None
        target_height = float(height) if height is not None else None

        if target_width is None and target_height is None:
            raise inkex.AbortExtension("Resize requires a target width or height.")
        if target_width is not None and target_width <= 0:
            raise inkex.AbortExtension("Resize width must be greater than zero.")
        if target_height is not None and target_height <= 0:
            raise inkex.AbortExtension("Resize height must be greater than zero.")

        scale_x = (target_width / current_width) if target_width is not None else None
        scale_y = (target_height / current_height) if target_height is not None else None

        if scale_x is None:
            scale_x = scale_y
        if scale_y is None:
            scale_y = scale_x

        center_x = bbox.left + (bbox.width / 2.0)
        center_y = bbox.top + (bbox.height / 2.0)
        transform = Transform(
            f"translate({center_x}, {center_y}) scale({scale_x}, {scale_y}) translate({-center_x}, {-center_y})"
        )
        node.transform = transform @ node.transform


def _rotate_selected(nodes: list[inkex.BaseElement], degrees: float) -> None:
    for node in nodes:
        bbox = node.bounding_box()
        center_x = bbox.left + (bbox.width / 2.0)
        center_y = bbox.top + (bbox.height / 2.0)
        transform = Transform().add_rotate(degrees, center_x, center_y)
        node.transform = transform @ node.transform


def _set_opacity(nodes: list[inkex.BaseElement], opacity_percent: float) -> None:
    clamped = max(0.0, min(100.0, opacity_percent)) / 100.0
    for node in nodes:
        _set_style_value(node, "opacity", str(clamped))


def _set_stroke_width(nodes: list[inkex.BaseElement], stroke_width_px: float) -> None:
    for node in nodes:
        _set_style_value(node, "stroke-width", str(max(0.0, stroke_width_px)))


def _parse_css_length_px(value: object) -> float | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)\s*", str(value))
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "px").lower()
    if unit == "px":
        return number
    if unit == "pt":
        return number * 96.0 / 72.0
    if unit == "in":
        return number * 96.0
    if unit == "cm":
        return number * 96.0 / 2.54
    if unit == "mm":
        return number * 96.0 / 25.4
    return None


def _root_user_units_per_css_px(node: inkex.BaseElement) -> float:
    try:
        root = node.getroottree().getroot()
    except Exception:
        return 1.0
    raw_viewbox = root.get("viewBox") or root.get("viewbox")
    if not raw_viewbox:
        return 1.0
    parts = [part for part in re.split(r"[\s,]+", raw_viewbox.strip()) if part]
    if len(parts) != 4:
        return 1.0
    try:
        _min_x, _min_y, viewbox_width, viewbox_height = (float(part) for part in parts)
    except ValueError:
        return 1.0
    viewport_width_px = _parse_css_length_px(root.get("width"))
    viewport_height_px = _parse_css_length_px(root.get("height"))
    scales: list[float] = []
    if viewport_width_px and viewport_width_px > 0 and viewbox_width > 0:
        scales.append(viewbox_width / viewport_width_px)
    if viewport_height_px and viewport_height_px > 0 and viewbox_height > 0:
        scales.append(viewbox_height / viewport_height_px)
    return sum(scales) / len(scales) if scales else 1.0


def _hexad_scale(hexad: tuple[float, float, float, float, float, float]) -> float:
    a, b, c, d, _e, _f = hexad
    scale_x = sqrt((a * a) + (b * b))
    scale_y = sqrt((c * c) + (d * d))
    scales = [scale for scale in (scale_x, scale_y) if scale > 0]
    return sum(scales) / len(scales) if scales else 1.0


def _raw_transform_chain_scale(node: inkex.BaseElement) -> float:
    scale = 1.0
    try:
        chain = list(node.iterancestors()) + [node]
    except Exception:
        chain = [node]
    for item in chain:
        raw_transform = item.get("transform")
        if not raw_transform:
            continue
        try:
            scale *= _hexad_scale(Transform(str(raw_transform)).to_hexad())
        except Exception:
            continue
    return scale


def _node_visual_scale(node: inkex.BaseElement) -> float:
    raw_scale = _raw_transform_chain_scale(node)
    return raw_scale if raw_scale > 0 else 1.0


def _local_font_size_for_visual_css_px(node: inkex.BaseElement, font_size_px: float) -> float:
    transform_scale = _node_visual_scale(node)
    if transform_scale <= 0:
        transform_scale = 1.0
    return font_size_px * _root_user_units_per_css_px(node) / transform_scale


def _text_size_targets(node: inkex.BaseElement) -> list[inkex.BaseElement]:
    targets: list[inkex.BaseElement] = []
    if _tag_name(node) in {"text", "tspan"}:
        targets.append(node)
    try:
        for descendant in node.iterdescendants():
            if _tag_name(descendant) in {"text", "tspan"}:
                targets.append(descendant)
    except Exception:
        pass
    return targets or [node]


def _scale_path_glyph_to_font_size(node: inkex.BaseElement, font_size_px: float) -> None:
    tag = _tag_name(node)
    if tag not in {"path", "polygon", "polyline", "use"}:
        return
    try:
        bbox = node.bounding_box()
    except Exception:
        return
    current_height = float(getattr(bbox, "height", 0.0) or 0.0)
    if current_height <= 0:
        return
    target_height = _local_font_size_for_visual_css_px(node, font_size_px) * 0.85
    if target_height <= 0:
        return
    factor = max(0.05, min(20.0, target_height / current_height))
    _font_debug_log(
        "scale_text_glyph "
        f"id={node.get('id')} tag={tag} requested_px={font_size_px:g} "
        f"current_h={current_height:g} target_h={target_height:g} factor={factor:g}"
    )
    _scale_selected([node], factor * 100.0)


def _set_font_size(nodes: list[inkex.BaseElement], font_size_px: float) -> None:
    if font_size_px <= 0:
        raise inkex.AbortExtension("Font size must be greater than zero.")
    for node in nodes:
        for target in _text_size_targets(node):
            if _tag_name(target) not in {"text", "tspan"}:
                _scale_path_glyph_to_font_size(target, font_size_px)
                continue
            # Action params use CSS pixels (pt * 4/3). The SVG document may use
            # mm-like user units, and imported groups may already scale px to
            # document units, so convert the requested visual size into the
            # target's local font-size value.
            visual_scale = _node_visual_scale(target)
            unit_scale = _root_user_units_per_css_px(target)
            local_font_size_px = _local_font_size_for_visual_css_px(target, font_size_px)
            _font_debug_log(
                "set_font_size "
                f"id={target.get('id')} tag={_tag_name(target)} requested_px={font_size_px:g} "
                f"unit_scale={unit_scale:g} visual_scale={visual_scale:g} local_px={local_font_size_px:g}"
            )
            _set_style_value(target, "font-size", f"{local_font_size_px}px")


def _set_text_style(nodes: list[inkex.BaseElement], key: str, value: str) -> None:
    for node in nodes:
        for target in _text_size_targets(node):
            if _tag_name(target) in {"text", "tspan"}:
                _set_style_value(target, key, value)
                if key in {"font-family", "font-weight", "font-style", "text-anchor"}:
                    target.set(key, value)


def _set_line_style(nodes: list[inkex.BaseElement], key: str, value: str) -> None:
    for node in nodes:
        _set_style_value(node, key, value)


def _svg_defs(svg: inkex.SvgDocumentElement) -> inkex.BaseElement:
    try:
        for child in svg:
            if _tag_name(child) == "defs":
                return child
    except Exception:
        pass
    return etree.SubElement(svg, inkex.addNS("defs", "svg"))


def _ensure_arrowhead_marker(svg: inkex.SvgDocumentElement) -> str:
    marker_id = "figureagent-arrowhead"
    existing = _find_node_by_id(svg, marker_id)
    if existing is not None:
        return marker_id
    defs = _svg_defs(svg)
    marker = etree.SubElement(defs, inkex.addNS("marker", "svg"))
    marker.set("id", marker_id)
    marker.set("markerWidth", "8")
    marker.set("markerHeight", "8")
    marker.set("refX", "7")
    marker.set("refY", "4")
    marker.set("orient", "auto")
    marker.set("markerUnits", "strokeWidth")
    path = etree.SubElement(marker, inkex.addNS("path", "svg"))
    path.set("d", "M 0,0 L 8,4 L 0,8 z")
    path.set("style", "fill:context-stroke;stroke:none")
    return marker_id


def _set_arrowhead(svg: inkex.SvgDocumentElement, nodes: list[inkex.BaseElement], marker: str) -> None:
    if marker == "none":
        for node in nodes:
            _set_style_value(node, "marker-start", "none")
            _set_style_value(node, "marker-end", "none")
        return
    marker_id = _ensure_arrowhead_marker(svg)
    marker_url = f"url(#{marker_id})"
    for node in nodes:
        if marker in {"start", "both"}:
            _set_style_value(node, "marker-start", marker_url)
        else:
            _set_style_value(node, "marker-start", "none")
        if marker in {"end", "both"}:
            _set_style_value(node, "marker-end", marker_url)
        else:
            _set_style_value(node, "marker-end", "none")


def _set_corner_radius(nodes: list[inkex.BaseElement], corner_radius: float) -> None:
    radius = max(0.0, corner_radius)
    for node in nodes:
        node.set("rx", str(radius))
        node.set("ry", str(radius))


def _set_dash_pattern(nodes: list[inkex.BaseElement], dash_pattern: str) -> None:
    for node in nodes:
        _set_style_value(node, "stroke-dasharray", dash_pattern)


def _selection_bbox(nodes: list[inkex.BaseElement]) -> tuple[float, float, float, float]:
    if not nodes:
        raise inkex.AbortExtension("This action requires at least one selected object.")
    lefts: list[float] = []
    tops: list[float] = []
    rights: list[float] = []
    bottoms: list[float] = []
    for node in nodes:
        bbox = node.bounding_box()
        lefts.append(float(bbox.left))
        tops.append(float(bbox.top))
        rights.append(float(bbox.left + bbox.width))
        bottoms.append(float(bbox.top + bbox.height))
    return min(lefts), min(tops), max(rights), max(bottoms)


def _set_selection_position(nodes: list[inkex.BaseElement], x: float, y: float) -> None:
    left, top, _, _ = _selection_bbox(nodes)
    _move_selected(nodes, x - left, y - top)


def _align_selection(nodes: list[inkex.BaseElement], mode: str) -> None:
    if len(nodes) < 2:
        raise inkex.AbortExtension("Align requires at least two selected objects.")
    left, top, right, bottom = _selection_bbox(nodes)
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    for node in nodes:
        bbox = node.bounding_box()
        node_left = float(bbox.left)
        node_top = float(bbox.top)
        node_right = float(bbox.left + bbox.width)
        node_bottom = float(bbox.top + bbox.height)
        node_center_x = (node_left + node_right) / 2.0
        node_center_y = (node_top + node_bottom) / 2.0
        delta_x = 0.0
        delta_y = 0.0
        if mode == "left":
            delta_x = left - node_left
        elif mode == "center":
            delta_x = center_x - node_center_x
        elif mode == "right":
            delta_x = right - node_right
        elif mode == "top":
            delta_y = top - node_top
        elif mode == "middle":
            delta_y = center_y - node_center_y
        elif mode == "bottom":
            delta_y = bottom - node_bottom
        _move_selected([node], delta_x, delta_y)


def _distribute_selection(nodes: list[inkex.BaseElement], mode: str) -> None:
    if len(nodes) < 3:
        raise inkex.AbortExtension("Distribute requires at least three selected objects.")
    if mode == "horizontal":
        ordered = sorted(nodes, key=lambda node: float(node.bounding_box().left))
        first = ordered[0].bounding_box()
        last = ordered[-1].bounding_box()
        start = float(first.left)
        end = float(last.left)
        step = (end - start) / (len(ordered) - 1)
        for index, node in enumerate(ordered):
            bbox = node.bounding_box()
            _move_selected([node], (start + (step * index)) - float(bbox.left), 0.0)
        return
    ordered = sorted(nodes, key=lambda node: float(node.bounding_box().top))
    first = ordered[0].bounding_box()
    last = ordered[-1].bounding_box()
    start = float(first.top)
    end = float(last.top)
    step = (end - start) / (len(ordered) - 1)
    for index, node in enumerate(ordered):
        bbox = node.bounding_box()
        _move_selected([node], 0.0, (start + (step * index)) - float(bbox.top))


RESIZABLE_PLOT_TAGS = {"circle", "ellipse", "image", "line", "path", "polygon", "polyline", "rect", "text", "tspan", "use"}


@dataclass(frozen=True)
class PlotResizeGeometry:
    left: float
    top: float
    right: float
    bottom: float
    source: str

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


def _plot_resize_targets(nodes: list[inkex.BaseElement]) -> list[inkex.BaseElement]:
    targets: list[inkex.BaseElement] = []
    seen: set[str] = set()
    for node in nodes:
        descendants: list[inkex.BaseElement] = []
        try:
            descendants = [item for item in node.iterdescendants() if _tag_name(item) in RESIZABLE_PLOT_TAGS]
        except Exception:
            descendants = []
        candidates = descendants if descendants else ([node] if _tag_name(node) in RESIZABLE_PLOT_TAGS else [])
        for candidate in candidates:
            key = candidate.get("id") or str(id(candidate))
            if key in seen:
                continue
            seen.add(key)
            targets.append(candidate)
    return targets


def _line_role(node: inkex.BaseElement) -> tuple[str | None, str | None]:
    try:
        svg = node.getroottree().getroot()
    except Exception:
        svg = node
    role, _panel, axis = _node_semantics(svg, node)
    return role, axis


def _node_bbox_tuple(node: inkex.BaseElement) -> tuple[float, float, float, float] | None:
    try:
        bbox = node.bounding_box()
    except Exception:
        return None
    return (
        float(bbox.left),
        float(bbox.top),
        float(bbox.left + bbox.width),
        float(bbox.top + bbox.height),
    )


def _bbox_center_tuple(bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    left, top, right, bottom = bounds
    return (left + (right - left) / 2.0, top + (bottom - top) / 2.0)


def _line_bounds_for_role(targets: list[inkex.BaseElement], role: str, semantic_axis: str) -> list[tuple[float, float, float, float]]:
    bounds: list[tuple[float, float, float, float]] = []
    for node in targets:
        if _tag_name(node) != "line":
            continue
        node_role, node_axis = _line_role(node)
        if node_role != role or node_axis != semantic_axis:
            continue
        endpoints = _line_endpoints(node)
        if endpoints is not None:
            x1, y1, x2, y2 = endpoints
            bounds.append((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
            continue
        bbox = _node_bbox_tuple(node)
        if bbox:
            bounds.append(bbox)
    return bounds


def _plot_geometry_from_axes(nodes: list[inkex.BaseElement], targets: list[inkex.BaseElement]) -> PlotResizeGeometry:
    selection_left, selection_top, selection_right, selection_bottom = _selection_bbox(nodes)
    fallback = PlotResizeGeometry(selection_left, selection_top, selection_right, selection_bottom, "selection")

    x_axis_bounds = _line_bounds_for_role(targets, "axis_line", "x")
    y_axis_bounds = _line_bounds_for_role(targets, "axis_line", "y")
    if not x_axis_bounds and not y_axis_bounds:
        return fallback

    left = min((item[0] for item in x_axis_bounds), default=selection_left)
    right = max((item[2] for item in x_axis_bounds), default=selection_right)
    top = min((item[1] for item in y_axis_bounds), default=selection_top)
    bottom = max((item[3] for item in y_axis_bounds), default=selection_bottom)

    if x_axis_bounds and not y_axis_bounds:
        top = selection_top
        bottom = selection_bottom
    if y_axis_bounds and not x_axis_bounds:
        left = selection_left
        right = selection_right

    if right <= left or bottom <= top:
        return fallback
    return PlotResizeGeometry(left, top, right, bottom, "axes")


def _number_attr(node: inkex.BaseElement, name: str) -> float | None:
    value = node.get(name)
    if value is None:
        return None
    try:
        return float(str(value).replace("px", "").strip())
    except ValueError:
        return None


def _set_number_attr(node: inkex.BaseElement, name: str, value: float) -> None:
    node.set(name, f"{value:g}")


def _remap(value: float, origin: float, scale: float) -> float:
    return origin + ((value - origin) * scale)


def _plot_resize_origin(geometry: PlotResizeGeometry, axis: str) -> float:
    return geometry.left if axis == "x" else geometry.top


def _plot_resize_length(geometry: PlotResizeGeometry, axis: str) -> float:
    return geometry.width if axis == "x" else geometry.height


def _center_position_policy(
    node: inkex.BaseElement,
    *,
    axis: str,
    geometry: PlotResizeGeometry,
) -> str:
    role, semantic_axis = _line_role(node)
    if role == "panel_label":
        return "skip"
    bounds = _node_bbox_tuple(node)
    if bounds is None:
        return "remap"
    center_x, center_y = _bbox_center_tuple(bounds)
    pad_x = max(6.0, geometry.width * 0.08)
    pad_y = max(6.0, geometry.height * 0.08)
    inside_x = geometry.left - pad_x <= center_x <= geometry.right + pad_x
    inside_y = geometry.top - pad_y <= center_y <= geometry.bottom + pad_y

    if role in {"tick_label", "axis_label"}:
        if semantic_axis == axis:
            return "remap"
        if semantic_axis and semantic_axis != axis:
            return "skip"
        if axis == "x":
            return "remap" if inside_x and not (inside_y and center_x < geometry.left + pad_x) else "skip"
        return "remap" if inside_y and not (inside_x and center_y > geometry.bottom - pad_y) else "skip"

    if axis == "x":
        return "remap" if center_x >= geometry.left - pad_x else "skip"
    return "remap" if geometry.top - pad_y <= center_y <= geometry.bottom + (pad_y * 3.0) else "skip"


def _semantic_translate(node: inkex.BaseElement, delta_x: float, delta_y: float) -> None:
    if abs(delta_x) < 1e-9 and abs(delta_y) < 1e-9:
        return
    node.transform = Transform(f"translate({delta_x}, {delta_y})") @ node.transform


def _resize_line_for_plot(node: inkex.BaseElement, *, axis: str, origin: float, scale: float) -> bool:
    endpoints = _line_endpoints(node)
    if endpoints is None:
        return False
    x1, y1, x2, y2 = endpoints
    role, semantic_axis = _line_role(node)

    if role == "axis_tick":
        if axis == "x":
            center = (x1 + x2) / 2.0
            new_center = _remap(center, origin, scale)
            _set_number_attr(node, "x1", new_center + (x1 - center))
            _set_number_attr(node, "x2", new_center + (x2 - center))
            _set_number_attr(node, "y1", y1)
            _set_number_attr(node, "y2", y2)
        else:
            center = (y1 + y2) / 2.0
            new_center = _remap(center, origin, scale)
            _set_number_attr(node, "y1", new_center + (y1 - center))
            _set_number_attr(node, "y2", new_center + (y2 - center))
            _set_number_attr(node, "x1", x1)
            _set_number_attr(node, "x2", x2)
        return True

    if axis == "x":
        _set_number_attr(node, "x1", _remap(x1, origin, scale))
        _set_number_attr(node, "x2", _remap(x2, origin, scale))
        _set_number_attr(node, "y1", y1)
        _set_number_attr(node, "y2", y2)
    else:
        _set_number_attr(node, "y1", _remap(y1, origin, scale))
        _set_number_attr(node, "y2", _remap(y2, origin, scale))
        _set_number_attr(node, "x1", x1)
        _set_number_attr(node, "x2", x2)
    if role in {"axis_line", "plot_curve"} or semantic_axis:
        _set_style_value(node, "vector-effect", "non-scaling-stroke")
    return True


def _resize_rect_for_plot(node: inkex.BaseElement, *, axis: str, origin: float, scale: float) -> bool:
    x = _number_attr(node, "x")
    y = _number_attr(node, "y")
    width = _number_attr(node, "width")
    height = _number_attr(node, "height")
    if x is None or y is None:
        return False
    if axis == "x":
        if width is None:
            return False
        new_left = _remap(x, origin, scale)
        new_right = _remap(x + width, origin, scale)
        _set_number_attr(node, "x", min(new_left, new_right))
        _set_number_attr(node, "width", abs(new_right - new_left))
    else:
        if height is None:
            return False
        new_top = _remap(y, origin, scale)
        new_bottom = _remap(y + height, origin, scale)
        _set_number_attr(node, "y", min(new_top, new_bottom))
        _set_number_attr(node, "height", abs(new_bottom - new_top))
    _set_style_value(node, "vector-effect", "non-scaling-stroke")
    return True


def _move_node_center_for_plot(node: inkex.BaseElement, *, axis: str, origin: float, scale: float) -> bool:
    try:
        bbox = node.bounding_box()
    except Exception:
        return False
    if axis == "x":
        center = float(bbox.left + bbox.width / 2.0)
        new_center = _remap(center, origin, scale)
        _semantic_translate(node, new_center - center, 0.0)
    else:
        center = float(bbox.top + bbox.height / 2.0)
        new_center = _remap(center, origin, scale)
        _semantic_translate(node, 0.0, new_center - center)
    return True


def _resize_path_like_for_plot(node: inkex.BaseElement, *, axis: str, origin: float, scale: float) -> None:
    if axis == "x":
        transform = Transform(f"translate({origin}, 0) scale({scale}, 1) translate({-origin}, 0)")
    else:
        transform = Transform(f"translate(0, {origin}) scale(1, {scale}) translate(0, {-origin})")
    node.transform = transform @ node.transform
    _set_style_value(node, "vector-effect", "non-scaling-stroke")


def _path_like_should_scale(node: inkex.BaseElement, *, axis: str, geometry: PlotResizeGeometry) -> bool:
    role, semantic_axis = _line_role(node)
    if role in {"axis_label", "tick_label", "label", "panel_label", "layer_label"}:
        return False
    if role in {"axis_line", "axis_tick", "plot_curve"} or semantic_axis:
        return True
    bounds = _node_bbox_tuple(node)
    if bounds is None:
        return True
    center_x, center_y = _bbox_center_tuple(bounds)
    if axis == "x":
        return geometry.left <= center_x <= geometry.right and geometry.top <= center_y <= geometry.bottom
    return geometry.left <= center_x <= geometry.right and geometry.top <= center_y <= geometry.bottom


def _resize_plot_dimension(nodes: list[inkex.BaseElement], *, axis: str, percent: float | None, target_length: float | None) -> None:
    if not nodes:
        raise inkex.AbortExtension("Semantic plot resize requires a selected plot or target objects.")
    if percent is not None and percent <= 0:
        raise inkex.AbortExtension("Semantic plot resize percent must be greater than zero.")
    if target_length is not None and target_length <= 0:
        raise inkex.AbortExtension("Semantic plot resize target length must be greater than zero.")

    targets = _plot_resize_targets(nodes)
    geometry = _plot_geometry_from_axes(nodes, targets)
    current_length = _plot_resize_length(geometry, axis)
    if current_length <= 0:
        raise inkex.AbortExtension("Cannot semantically resize a plot with zero width or height.")
    scale = (percent / 100.0) if percent is not None else (float(target_length) / current_length)
    if scale <= 0:
        raise inkex.AbortExtension("Semantic plot resize scale must be greater than zero.")
    origin = _plot_resize_origin(geometry, axis)

    for node in targets:
        tag = _tag_name(node)
        handled = False
        if tag == "line":
            handled = _resize_line_for_plot(node, axis=axis, origin=origin, scale=scale)
        elif tag == "rect" or tag == "image":
            handled = _resize_rect_for_plot(node, axis=axis, origin=origin, scale=scale)
        elif tag in {"circle", "ellipse", "text", "tspan", "use"}:
            policy = _center_position_policy(node, axis=axis, geometry=geometry)
            handled = True if policy == "skip" else _move_node_center_for_plot(node, axis=axis, origin=origin, scale=scale)
        elif tag in {"path", "polygon", "polyline"}:
            if _path_like_should_scale(node, axis=axis, geometry=geometry):
                _resize_path_like_for_plot(node, axis=axis, origin=origin, scale=scale)
            else:
                policy = _center_position_policy(node, axis=axis, geometry=geometry)
                if policy != "skip":
                    _move_node_center_for_plot(node, axis=axis, origin=origin, scale=scale)
            handled = True
        if not handled:
            policy = _center_position_policy(node, axis=axis, geometry=geometry)
            if policy != "skip":
                _move_node_center_for_plot(node, axis=axis, origin=origin, scale=scale)


def _set_z_order(nodes: list[inkex.BaseElement], order: str) -> list[inkex.BaseElement]:
    for node in nodes:
        parent = node.getparent()
        if parent is None:
            continue
        if order == "front":
            parent.remove(node)
            parent.append(node)
        elif order == "back":
            parent.remove(node)
            parent.insert(0, node)
        elif order == "raise":
            next_node = node.getnext()
            if next_node is not None:
                next_node.addnext(node)
        elif order == "lower":
            previous_node = node.getprevious()
            if previous_node is not None:
                previous_node.addprevious(node)
    return nodes


def _duplicate_selected(
    nodes: list[inkex.BaseElement],
    count: int,
    delta_x: float,
    delta_y: float,
) -> list[inkex.BaseElement]:
    duplicates: list[inkex.BaseElement] = []
    for copy_index in range(max(1, count)):
        multiplier = copy_index + 1
        for node in nodes:
            duplicate = node.copy()
            node.addnext(duplicate)
            duplicate.transform = Transform(
                f"translate({delta_x * multiplier}, {delta_y * multiplier})"
            ) @ duplicate.transform
            duplicates.append(duplicate)
    return duplicates


def _create_rectangle(
    layer: inkex.BaseElement,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    fill_hex: str | None,
    stroke_hex: str | None,
    stroke_width_px: float | None,
    dash_pattern: str | None = None,
) -> inkex.BaseElement:
    rect = layer.add(Rectangle.new(x, y, width, height))
    rect.style["fill"] = fill_hex or "#2563eb"
    _apply_stroke_style(rect, stroke_hex=stroke_hex, stroke_width_px=stroke_width_px, dash_pattern=dash_pattern)
    return rect


def _create_rounded_rectangle(
    layer: inkex.BaseElement,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    corner_radius: float,
    fill_hex: str | None,
    stroke_hex: str | None,
    stroke_width_px: float | None,
    dash_pattern: str | None,
) -> inkex.BaseElement:
    rect = _create_rectangle(
        layer,
        x=x,
        y=y,
        width=width,
        height=height,
        fill_hex=fill_hex,
        stroke_hex=stroke_hex,
        stroke_width_px=stroke_width_px,
        dash_pattern=dash_pattern,
    )
    rect.set("rx", str(max(0.0, corner_radius)))
    rect.set("ry", str(max(0.0, corner_radius)))
    return rect


def _create_circle(
    layer: inkex.BaseElement,
    *,
    cx: float,
    cy: float,
    radius: float,
    fill_hex: str | None,
    stroke_hex: str | None,
    stroke_width_px: float | None,
) -> inkex.BaseElement:
    circle = layer.add(Circle.new((cx, cy), radius))
    circle.style["fill"] = fill_hex or "#2563eb"
    circle.style["stroke"] = stroke_hex or "none"
    if stroke_width_px is not None:
        circle.style["stroke-width"] = str(max(0.0, stroke_width_px))
    return circle


def _create_ellipse(
    layer: inkex.BaseElement,
    *,
    cx: float,
    cy: float,
    width: float,
    height: float,
    fill_hex: str | None,
    stroke_hex: str | None,
    stroke_width_px: float | None,
) -> inkex.BaseElement:
    rx = width / 2.0
    ry = height / 2.0
    ellipse = layer.add(PathElement())
    ellipse.set("d", f"M {cx - rx},{cy} A {rx},{ry} 0 1 0 {cx + rx},{cy} A {rx},{ry} 0 1 0 {cx - rx},{cy} Z")
    ellipse.style["fill"] = fill_hex or "#2563eb"
    ellipse.style["stroke"] = stroke_hex or "none"
    if stroke_width_px is not None:
        ellipse.style["stroke-width"] = str(max(0.0, stroke_width_px))
    return ellipse


def _create_repeated_circles(
    layer: inkex.BaseElement,
    *,
    x: float,
    y: float,
    radius: float,
    count: int,
    spacing_x: float,
    spacing_y: float | None,
    fill_hex: str | None,
    stroke_hex: str | None,
    stroke_width_px: float | None,
) -> list[inkex.BaseElement]:
    circles: list[inkex.BaseElement] = []
    for index in range(max(0, count)):
        circle = _create_circle(
            layer,
            cx=x + (index * spacing_x),
            cy=y + (index * (spacing_y or 0.0)),
            radius=radius,
            fill_hex=fill_hex,
            stroke_hex=stroke_hex,
            stroke_width_px=stroke_width_px,
        )
        circles.append(circle)
    return circles


def _regular_polygon_points(cx: float, cy: float, radius: float, count: int, degrees: float) -> list[tuple[float, float]]:
    start = (degrees * pi) / 180.0 - (pi / 2.0)
    step = (2.0 * pi) / count
    return [
        (cx + cos(start + (step * index)) * radius, cy + sin(start + (step * index)) * radius)
        for index in range(count)
    ]


def _create_polygon(
    layer: inkex.BaseElement,
    *,
    cx: float | None,
    cy: float | None,
    radius: float | None,
    count: int | None,
    degrees: float,
    points: list[dict[str, float]] | None = None,
    fill_hex: str | None,
    stroke_hex: str | None,
    stroke_width_px: float | None,
) -> inkex.BaseElement:
    if points:
        if len(points) < 3:
            raise inkex.AbortExtension("Polygon requires at least 3 points.")
        path_points = [(float(point["x"]), float(point["y"])) for point in points]
    else:
        if cx is None or cy is None or radius is None or count is None:
            raise inkex.AbortExtension("Polygon requires either points or center/radius/count.")
        if count < 3:
            raise inkex.AbortExtension("Polygon requires at least 3 sides.")
        path_points = _regular_polygon_points(cx, cy, radius, count, degrees)
    polygon = layer.add(PathElement())
    polygon.set("d", "M " + " L ".join(f"{x},{y}" for x, y in path_points) + " Z")
    polygon.style["fill"] = fill_hex or "#2563eb"
    polygon.style["stroke"] = stroke_hex or "none"
    if stroke_width_px is not None:
        polygon.style["stroke-width"] = str(max(0.0, stroke_width_px))
    return polygon


def _create_star(
    layer: inkex.BaseElement,
    *,
    cx: float,
    cy: float,
    radius: float,
    inner_radius: float,
    count: int,
    degrees: float,
    fill_hex: str | None,
    stroke_hex: str | None,
    stroke_width_px: float | None,
) -> inkex.BaseElement:
    if count < 3:
        raise inkex.AbortExtension("Star requires at least 3 points.")
    if inner_radius <= 0 or inner_radius >= radius:
        raise inkex.AbortExtension("Star inner_radius must be greater than zero and smaller than radius.")
    start = (degrees * pi) / 180.0 - (pi / 2.0)
    step = pi / count
    points: list[tuple[float, float]] = []
    for index in range(count * 2):
        current_radius = radius if index % 2 == 0 else inner_radius
        angle = start + (step * index)
        points.append((cx + cos(angle) * current_radius, cy + sin(angle) * current_radius))
    star = layer.add(PathElement())
    star.set("d", "M " + " L ".join(f"{x},{y}" for x, y in points) + " Z")
    star.style["fill"] = fill_hex or "#2563eb"
    star.style["stroke"] = stroke_hex or "none"
    if stroke_width_px is not None:
        star.style["stroke-width"] = str(max(0.0, stroke_width_px))
    return star


def _create_line(
    layer: inkex.BaseElement,
    *,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    stroke_hex: str | None,
    stroke_width_px: float | None,
    dash_pattern: str | None = None,
) -> inkex.BaseElement:
    line = layer.add(inkex.Line.new((x1, y1), (x2, y2)))
    line.style["fill"] = "none"
    _apply_stroke_style(
        line,
        stroke_hex=stroke_hex or "#111827",
        stroke_width_px=stroke_width_px if stroke_width_px is not None else 2.0,
        dash_pattern=dash_pattern,
    )
    return line


def _create_arrow(
    layer: inkex.BaseElement,
    *,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    stroke_hex: str | None,
    stroke_width_px: float | None,
) -> list[inkex.BaseElement]:
    stroke = stroke_hex or "#111827"
    width = stroke_width_px if stroke_width_px is not None else 2.0
    line = _create_line(layer, x1=x1, y1=y1, x2=x2, y2=y2, stroke_hex=stroke, stroke_width_px=width)

    angle = atan2(y2 - y1, x2 - x1)
    head_length = max(6.0, width * 4.0)
    spread = pi / 7.0
    left_x = x2 - head_length * cos(angle - spread)
    left_y = y2 - head_length * sin(angle - spread)
    right_x = x2 - head_length * cos(angle + spread)
    right_y = y2 - head_length * sin(angle + spread)

    left = _create_line(layer, x1=x2, y1=y2, x2=left_x, y2=left_y, stroke_hex=stroke, stroke_width_px=width)
    right = _create_line(layer, x1=x2, y1=y2, x2=right_x, y2=right_y, stroke_hex=stroke, stroke_width_px=width)
    return [line, left, right]


def _create_bracket(
    layer: inkex.BaseElement,
    *,
    x: float,
    y1: float,
    y2: float,
    width: float,
    stroke_hex: str | None,
    stroke_width_px: float | None,
) -> list[inkex.BaseElement]:
    stroke = stroke_hex or "#111827"
    line_width = stroke_width_px if stroke_width_px is not None else 1.5
    return [
        _create_line(layer, x1=x, y1=y1, x2=x, y2=y2, stroke_hex=stroke, stroke_width_px=line_width),
        _create_line(layer, x1=x, y1=y1, x2=x + width, y2=y1, stroke_hex=stroke, stroke_width_px=line_width),
        _create_line(layer, x1=x, y1=y2, x2=x + width, y2=y2, stroke_hex=stroke, stroke_width_px=line_width),
    ]


def _create_text(
    layer: inkex.BaseElement,
    *,
    x: float,
    y: float,
    text: str,
    font_size_px: float,
    fill_hex: str | None,
) -> inkex.BaseElement:
    if font_size_px <= 0:
        raise inkex.AbortExtension("Text font size must be greater than zero.")

    text_node = layer.add(inkex.TextElement())
    text_node.set("x", str(x))
    text_node.set("y", str(y))
    text_node.text = _clean_text(text)
    text_node.style["fill"] = fill_hex or "#111827"
    text_node.style["stroke"] = "none"
    text_node.style["font-size"] = f"{font_size_px}px"
    return text_node


def _create_layer_bar(
    layer: inkex.BaseElement,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    corner_radius: float,
    text: str,
    font_size_px: float,
    fill_hex: str | None,
    stroke_hex: str | None,
    stroke_width_px: float | None,
    text_hex: str | None,
) -> list[inkex.BaseElement]:
    bar = _create_rounded_rectangle(
        layer,
        x=x,
        y=y,
        width=width,
        height=height,
        corner_radius=corner_radius,
        fill_hex=fill_hex or "#9ca3af",
        stroke_hex=stroke_hex,
        stroke_width_px=stroke_width_px,
        dash_pattern=None,
    )
    label = _create_text(
        layer,
        x=x + width / 2.0,
        y=y + height / 2.0 + font_size_px / 3.0,
        text=text,
        font_size_px=font_size_px,
        fill_hex=text_hex or "#111827",
    )
    label.style["text-anchor"] = "middle"
    return [bar, label]


SELECTION_REQUIRED_ACTIONS = {
    "align_selection",
    "distribute_selection",
    "set_selection_position",
    "set_fill_none",
    "set_fill_color",
    "set_font_size",
    "set_corner_radius",
    "set_dash_pattern",
    "set_z_order",
    "set_stroke_none",
    "set_stroke_color",
    "set_stroke_width",
    "set_opacity",
    "move_selection",
    "duplicate_selection",
    "resize_selection",
    "scale_selection",
    "rotate_selection",
    "rename_selection",
}


def apply_action_plan(
    svg: inkex.SvgDocumentElement,
    selected: list[inkex.BaseElement],
    plan: ActionPlan,
) -> tuple[list[inkex.BaseElement], str]:
    layer = svg.get_current_layer()

    for action in plan.actions:
        if action.kind == "set_document_size":
            _set_document_size(svg, float(action.params["width"]), float(action.params["height"]))
            continue

        if action.kind in SELECTION_REQUIRED_ACTIONS and not selected:
            raise inkex.AbortExtension(f"Action '{action.kind}' requires at least one selected object.")

        if action.kind == "set_fill_color":
            for node in selected:
                _set_style_value(node, "fill", str(action.params["hex"]))
            continue

        if action.kind == "set_fill_none":
            for node in selected:
                _set_style_value(node, "fill", "none")
            continue

        if action.kind == "set_font_size":
            _set_font_size(selected, float(action.params["font_size_px"]))
            continue

        if action.kind == "set_corner_radius":
            _set_corner_radius(selected, float(action.params["corner_radius"]))
            continue

        if action.kind == "set_dash_pattern":
            _set_dash_pattern(selected, str(action.params["dash_pattern"]))
            continue

        if action.kind == "set_z_order":
            selected = _set_z_order(selected, str(action.params["text"]))
            continue

        if action.kind == "set_stroke_color":
            for node in selected:
                _set_style_value(node, "stroke", str(action.params["hex"]))
            continue

        if action.kind == "set_stroke_none":
            for node in selected:
                _set_style_value(node, "stroke", "none")
            continue

        if action.kind == "set_stroke_width":
            _set_stroke_width(selected, float(action.params["stroke_width_px"]))
            continue

        if action.kind == "set_opacity":
            _set_opacity(selected, float(action.params["opacity_percent"]))
            continue

        if action.kind == "set_tick_length":
            selected = _target_nodes(svg, action.params)
            _set_tick_length(svg, selected, float(action.params["length_px"]))
            continue

        if action.kind == "set_tick_thickness":
            selected = _target_nodes(svg, action.params)
            _set_stroke_width(selected, float(action.params["stroke_width_px"]))
            continue

        if action.kind == "set_tick_label_size":
            selected = _target_nodes(svg, action.params)
            _set_font_size(selected, float(action.params["font_size_px"]))
            continue

        if action.kind == "move_selection":
            _move_selected(
                selected,
                float(action.params["delta_x_px"]),
                float(action.params["delta_y_px"]),
            )
            continue

        if action.kind == "set_selection_position":
            _set_selection_position(selected, float(action.params["x"]), float(action.params["y"]))
            continue

        if action.kind == "duplicate_selection":
            selected = _duplicate_selected(
                selected,
                int(action.params["count"]),
                float(action.params["delta_x_px"]),
                float(action.params["delta_y_px"]),
            )
            continue

        if action.kind == "resize_selection":
            width = action.params.get("width")
            height = action.params.get("height")
            _resize_selected(
                selected,
                float(width) if width is not None else None,
                float(height) if height is not None else None,
            )
            continue

        if action.kind == "resize_plot_width":
            targets = _target_nodes(svg, action.params) if TargetQuery.from_params(action.params).has_selector() else selected
            _resize_plot_dimension(
                targets,
                axis="x",
                percent=float(action.params["percent"]) if action.params.get("percent") is not None else None,
                target_length=float(action.params["width"]) if action.params.get("width") is not None else None,
            )
            selected = targets
            continue

        if action.kind == "resize_plot_height":
            targets = _target_nodes(svg, action.params) if TargetQuery.from_params(action.params).has_selector() else selected
            _resize_plot_dimension(
                targets,
                axis="y",
                percent=float(action.params["percent"]) if action.params.get("percent") is not None else None,
                target_length=float(action.params["height"]) if action.params.get("height") is not None else None,
            )
            selected = targets
            continue

        if action.kind == "scale_selection":
            _scale_selected(selected, float(action.params["percent"]))
            continue

        if action.kind == "rotate_selection":
            _rotate_selected(selected, float(action.params["degrees"]))
            continue

        if action.kind == "align_selection":
            _align_selection(selected, str(action.params["text"]))
            continue

        if action.kind == "distribute_selection":
            _distribute_selection(selected, str(action.params["text"]))
            continue

        if action.kind == "rename_selection":
            prefix = str(action.params["prefix"])
            if not re.fullmatch(r"[a-z0-9_-]+", prefix):
                raise inkex.AbortExtension("Rename prefix may only contain lowercase letters, digits, _ or -.")
            _rename_selected(selected, prefix)
            continue

        if action.kind in {"select_object", "select_targets"}:
            selected = _target_nodes(svg, action.params)
            continue

        if action.kind == "delete_object":
            targets = _target_nodes(svg, action.params)
            _delete_nodes(targets)
            selected = []
            continue

        if action.kind == "move_object":
            selected = _target_nodes(svg, action.params)
            _move_selected(
                selected,
                float(action.params["delta_x_px"]),
                float(action.params["delta_y_px"]),
            )
            continue

        if action.kind == "set_object_position":
            selected = _target_nodes(svg, action.params)
            _set_selection_position(selected, float(action.params["x"]), float(action.params["y"]))
            continue

        if action.kind == "set_object_size":
            selected = _target_nodes(svg, action.params)
            width = action.params.get("width")
            height = action.params.get("height")
            _resize_selected(
                selected,
                float(width) if width is not None else None,
                float(height) if height is not None else None,
            )
            continue

        if action.kind == "set_object_fill_color":
            selected = _target_nodes(svg, action.params)
            for node in selected:
                _set_style_value(node, "fill", str(action.params["hex"]))
            continue

        if action.kind == "set_object_fill_none":
            selected = _target_nodes(svg, action.params)
            for node in selected:
                _set_style_value(node, "fill", "none")
            continue

        if action.kind == "set_object_stroke_color":
            selected = _target_nodes(svg, action.params)
            for node in selected:
                _set_style_value(node, "stroke", str(action.params["hex"]))
            continue

        if action.kind == "set_object_stroke_none":
            selected = _target_nodes(svg, action.params)
            for node in selected:
                _set_style_value(node, "stroke", "none")
            continue

        if action.kind == "set_object_stroke_width":
            selected = _target_nodes(svg, action.params)
            _set_stroke_width(selected, float(action.params["stroke_width_px"]))
            continue

        if action.kind == "set_object_dash_pattern":
            selected = _target_nodes(svg, action.params)
            _set_dash_pattern(selected, str(action.params["dash_pattern"]))
            continue

        if action.kind == "set_object_font_size":
            selected = _target_nodes(svg, action.params)
            _set_font_size(selected, float(action.params["font_size_px"]))
            continue

        if action.kind == "set_object_font_family":
            selected = _target_nodes(svg, action.params)
            _set_text_style(selected, "font-family", str(action.params["font_family"]))
            continue

        if action.kind == "set_object_font_weight":
            selected = _target_nodes(svg, action.params)
            _set_text_style(selected, "font-weight", str(action.params["font_weight"]))
            continue

        if action.kind == "set_object_font_style":
            selected = _target_nodes(svg, action.params)
            _set_text_style(selected, "font-style", str(action.params["font_style"]))
            continue

        if action.kind == "set_object_text_anchor":
            selected = _target_nodes(svg, action.params)
            _set_text_style(selected, "text-anchor", str(action.params["text_anchor"]))
            continue

        if action.kind == "replace_text":
            selected = _target_nodes(svg, action.params)
            _replace_text(selected, str(action.params["new_text"]))
            continue

        if action.kind == "set_object_stroke_linecap":
            selected = _target_nodes(svg, action.params)
            _set_line_style(selected, "stroke-linecap", str(action.params["stroke_linecap"]))
            continue

        if action.kind == "set_object_stroke_linejoin":
            selected = _target_nodes(svg, action.params)
            _set_line_style(selected, "stroke-linejoin", str(action.params["stroke_linejoin"]))
            continue

        if action.kind == "set_object_arrowhead":
            selected = _target_nodes(svg, action.params)
            _set_arrowhead(svg, selected, str(action.params["marker"]))
            continue

        if action.kind == "create_rectangle":
            selected = [
                _create_rectangle(
                    layer,
                    x=float(action.params["x"]),
                    y=float(action.params["y"]),
                    width=float(action.params["width"]),
                    height=float(action.params["height"]),
                    fill_hex=action.params.get("fill_hex"),
                    stroke_hex=action.params.get("stroke_hex"),
                    stroke_width_px=action.params.get("stroke_width_px"),
                    dash_pattern=action.params.get("dash_pattern"),
                )
            ]
            continue

        if action.kind == "create_rounded_rectangle":
            selected = [
                _create_rounded_rectangle(
                    layer,
                    x=float(action.params["x"]),
                    y=float(action.params["y"]),
                    width=float(action.params["width"]),
                    height=float(action.params["height"]),
                    corner_radius=float(action.params.get("corner_radius") or 4.0),
                    fill_hex=action.params.get("fill_hex"),
                    stroke_hex=action.params.get("stroke_hex"),
                    stroke_width_px=action.params.get("stroke_width_px"),
                    dash_pattern=action.params.get("dash_pattern"),
                )
            ]
            continue

        if action.kind == "create_circle":
            selected = [
                _create_circle(
                    layer,
                    cx=float(action.params["cx"]),
                    cy=float(action.params["cy"]),
                    radius=float(action.params["radius"]),
                    fill_hex=action.params.get("fill_hex"),
                    stroke_hex=action.params.get("stroke_hex"),
                    stroke_width_px=action.params.get("stroke_width_px"),
                )
            ]
            continue

        if action.kind == "create_ellipse":
            selected = [
                _create_ellipse(
                    layer,
                    cx=float(action.params["cx"]),
                    cy=float(action.params["cy"]),
                    width=float(action.params["width"]),
                    height=float(action.params["height"]),
                    fill_hex=action.params.get("fill_hex"),
                    stroke_hex=action.params.get("stroke_hex"),
                    stroke_width_px=action.params.get("stroke_width_px"),
                )
            ]
            continue

        if action.kind == "create_repeated_circles":
            selected = _create_repeated_circles(
                layer,
                x=float(action.params["x"]),
                y=float(action.params["y"]),
                radius=float(action.params["radius"]),
                count=int(action.params["count"]),
                spacing_x=float(action.params["spacing_x"]),
                spacing_y=float(action.params["spacing_y"]) if action.params.get("spacing_y") is not None else None,
                fill_hex=action.params.get("fill_hex"),
                stroke_hex=action.params.get("stroke_hex"),
                stroke_width_px=action.params.get("stroke_width_px"),
            )
            continue

        if action.kind == "create_polygon":
            selected = [
                _create_polygon(
                    layer,
                    cx=float(action.params["cx"]) if isinstance(action.params.get("cx"), (int, float)) else None,
                    cy=float(action.params["cy"]) if isinstance(action.params.get("cy"), (int, float)) else None,
                    radius=float(action.params["radius"]) if isinstance(action.params.get("radius"), (int, float)) else None,
                    count=int(action.params["count"]) if isinstance(action.params.get("count"), (int, float)) else None,
                    degrees=float(action.params.get("degrees") or 0.0),
                    points=action.params.get("points") if isinstance(action.params.get("points"), list) else None,
                    fill_hex=action.params.get("fill_hex"),
                    stroke_hex=action.params.get("stroke_hex"),
                    stroke_width_px=action.params.get("stroke_width_px"),
                )
            ]
            continue

        if action.kind == "create_star":
            selected = [
                _create_star(
                    layer,
                    cx=float(action.params["cx"]),
                    cy=float(action.params["cy"]),
                    radius=float(action.params["radius"]),
                    inner_radius=float(action.params["inner_radius"]),
                    count=int(action.params["count"]),
                    degrees=float(action.params.get("degrees") or 0.0),
                    fill_hex=action.params.get("fill_hex"),
                    stroke_hex=action.params.get("stroke_hex"),
                    stroke_width_px=action.params.get("stroke_width_px"),
                )
            ]
            continue

        if action.kind == "create_line":
            selected = [
                _create_line(
                    layer,
                    x1=float(action.params["x1"]),
                    y1=float(action.params["y1"]),
                    x2=float(action.params["x2"]),
                    y2=float(action.params["y2"]),
                    stroke_hex=action.params.get("stroke_hex"),
                    stroke_width_px=action.params.get("stroke_width_px"),
                    dash_pattern=action.params.get("dash_pattern"),
                )
            ]
            continue

        if action.kind == "create_arrow":
            selected = _create_arrow(
                layer,
                x1=float(action.params["x1"]),
                y1=float(action.params["y1"]),
                x2=float(action.params["x2"]),
                y2=float(action.params["y2"]),
                stroke_hex=action.params.get("stroke_hex"),
                stroke_width_px=action.params.get("stroke_width_px"),
            )
            continue

        if action.kind == "create_bracket":
            selected = _create_bracket(
                layer,
                x=float(action.params["x"]),
                y1=float(action.params["y1"]),
                y2=float(action.params["y2"]),
                width=float(action.params["width"]),
                stroke_hex=action.params.get("stroke_hex"),
                stroke_width_px=action.params.get("stroke_width_px"),
            )
            continue

        if action.kind == "create_text":
            selected = [
                _create_text(
                    layer,
                    x=float(action.params["x"]),
                    y=float(action.params["y"]),
                    text=str(action.params["text"]),
                    font_size_px=float(action.params["font_size_px"]),
                    fill_hex=action.params.get("fill_hex"),
                )
            ]
            continue

        if action.kind == "create_layer_bar":
            selected = _create_layer_bar(
                layer,
                x=float(action.params["x"]),
                y=float(action.params["y"]),
                width=float(action.params["width"]),
                height=float(action.params["height"]),
                corner_radius=float(action.params.get("corner_radius") or 3.0),
                text=str(action.params["text"]),
                font_size_px=float(action.params["font_size_px"]),
                fill_hex=action.params.get("fill_hex"),
                stroke_hex=action.params.get("stroke_hex"),
                stroke_width_px=action.params.get("stroke_width_px"),
                text_hex=action.params.get("text_hex"),
            )
            continue

        raise inkex.AbortExtension(f"Unsupported action: {action.kind}")

    return selected, plan.summary
