from __future__ import annotations

from collections import Counter
from math import hypot
from statistics import median
from typing import Any

from .planner import DocumentContext, DocumentObject


def _finding(
    *,
    rule_id: str,
    severity: str,
    message: str,
    target_selector: dict[str, Any] | None = None,
    suggested_fix: str | None = None,
    suggested_value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "target_selector": target_selector or {},
        "suggested_fix": suggested_fix,
        "suggested_value": suggested_value or {},
    }


def _numeric_px(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(str(value).replace("px", "").strip())
    except ValueError:
        return None


def _font_values(objects: list[DocumentObject], role: str) -> list[float]:
    values: list[float] = []
    for item in objects:
        if item.role != role:
            continue
        value = _numeric_px(item.font_size)
        if value is not None:
            values.append(value)
    return values


def _role_objects(objects: list[DocumentObject], role: str) -> list[DocumentObject]:
    return [item for item in objects if item.role == role]


def _stroke_values(objects: list[DocumentObject], role: str) -> list[float]:
    values: list[float] = []
    for item in _role_objects(objects, role):
        value = _numeric_px(item.stroke_width)
        if value is not None:
            values.append(value)
    return values


def _line_length(item: DocumentObject) -> float | None:
    points = item.line_points or {}
    try:
        x1 = float(points["x1"])
        y1 = float(points["y1"])
        x2 = float(points["x2"])
        y2 = float(points["y2"])
        return hypot(x2 - x1, y2 - y1)
    except (KeyError, TypeError, ValueError):
        pass
    if not item.bbox:
        return None
    width = float(item.bbox.get("width") or 0.0)
    height = float(item.bbox.get("height") or 0.0)
    length = max(width, height)
    return length if length > 0 else None


def _tick_lengths(objects: list[DocumentObject], axis: str | None = None) -> list[float]:
    values: list[float] = []
    for item in _role_objects(objects, "axis_tick"):
        if axis and item.axis != axis:
            continue
        length = _line_length(item)
        if length is not None:
            values.append(length)
    return values


def _spread(values: list[float]) -> float:
    return max(values) - min(values) if values else 0.0


def _median(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def _rounded(value: float) -> float:
    return round(value, 3)


def _cluster_by_position(
    items: list[tuple[float, Any]],
    *,
    tolerance: float,
) -> list[list[Any]]:
    clusters: list[dict[str, Any]] = []
    for position, item in sorted(items, key=lambda pair: pair[0]):
        for cluster in clusters:
            if abs(position - cluster["center"]) <= tolerance:
                cluster["items"].append(item)
                cluster["positions"].append(position)
                cluster["center"] = sum(cluster["positions"]) / len(cluster["positions"])
                break
        else:
            clusters.append({"center": position, "positions": [position], "items": [item]})
    return [cluster["items"] for cluster in clusters]


def _expected_sequence(labels: list[str]) -> list[str]:
    if not labels:
        return []
    start = min(ord(label) for label in labels)
    end = max(ord(label) for label in labels)
    return [chr(code) for code in range(start, end + 1)]


def _panel_label_findings(document: DocumentContext) -> list[dict[str, Any]]:
    panels = document.panels or []
    labels = [panel.label for panel in panels]
    findings: list[dict[str, Any]] = []
    if not labels:
        findings.append(
            _finding(
                rule_id="PANEL-001",
                severity="warning",
                message="No figure panel labels were detected.",
                target_selector={"role": "panel_label"},
                suggested_fix="Add lowercase panel labels if this is a multi-panel figure.",
            )
        )
        return findings
    duplicates = [label for label, count in Counter(labels).items() if count > 1]
    if duplicates:
        findings.append(
            _finding(
                rule_id="PANEL-001",
                severity="warning",
                message=f"Duplicate panel labels detected: {', '.join(sorted(duplicates))}.",
                target_selector={"role": "panel_label"},
                suggested_fix="Rename duplicate panel labels so the panel sequence is unique.",
            )
        )
    expected = _expected_sequence(labels)
    missing = [label for label in expected if label not in labels]
    if missing:
        findings.append(
            _finding(
                rule_id="PANEL-001",
                severity="info",
                message=f"Panel sequence has gaps: missing {', '.join(missing)}.",
                target_selector={"role": "panel_label"},
                suggested_fix="Confirm whether the skipped panel labels are intentional; otherwise add or rename labels.",
            )
        )
    zero_object_panels = [panel.label for panel in panels if panel.object_count == 0]
    if zero_object_panels:
        findings.append(
            _finding(
                rule_id="PANEL-002",
                severity="warning",
                message=f"Some detected panels have no associated objects: {', '.join(zero_object_panels)}.",
                target_selector={"role": "panel_label"},
                suggested_fix="Review panel detection and panel bounding boxes; this may indicate a bad panel association.",
            )
        )
    return findings


def _axis_style_findings(objects: list[DocumentObject]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {"tick_length_spreads": {}, "role_stroke_spreads": {}}

    tick_objects = _role_objects(objects, "axis_tick")
    has_axis_metadata = any(item.axis in {"x", "y"} for item in tick_objects)
    axes_to_check: tuple[str | None, ...] = ("x", "y") if has_axis_metadata else (None,)
    for axis in axes_to_check:
        values = _tick_lengths(objects, axis=axis)
        if len(values) < 3:
            continue
        spread = _spread(values)
        key = axis or "all"
        metrics["tick_length_spreads"][key] = _rounded(spread)
        target = _median(values)
        if target is None or spread <= max(0.8, target * 0.25):
            continue
        selector = {"role": "axis_tick"}
        if axis:
            selector["axis"] = axis
        findings.append(
            _finding(
                rule_id="AXIS-002",
                severity="warning",
                message=f"{key.upper()} tick lengths are inconsistent.",
                target_selector=selector,
                suggested_fix=f"Normalize comparable tick lengths to about {_rounded(target)} px.",
                suggested_value={"length_px": _rounded(target)},
            )
        )

    for role in ("axis_tick", "axis_line", "plot_curve", "connector", "electrode", "line_art"):
        values = _stroke_values(objects, role)
        if len(values) < 2:
            continue
        spread = _spread(values)
        metrics["role_stroke_spreads"][role] = _rounded(spread)
        target = _median(values)
        if target is None or spread <= max(0.12, target * 0.25):
            continue
        rule_id = "AXIS-003" if role == "axis_tick" else "STROKE-001"
        findings.append(
            _finding(
                rule_id=rule_id,
                severity="warning",
                message=f"{role.replace('_', ' ')} strokes are inconsistent.",
                target_selector={"role": role},
                suggested_fix=f"Normalize comparable {role.replace('_', ' ')} stroke widths to about {_rounded(target)} px.",
                suggested_value={"stroke_width_px": _rounded(target)},
            )
        )

    return findings, metrics


def _panel_alignment_findings(document: DocumentContext) -> list[dict[str, Any]]:
    panels = [panel for panel in document.panels or [] if panel.bbox]
    if len(panels) < 3:
        return []

    findings: list[dict[str, Any]] = []
    widths = [float(panel.bbox.get("width") or 0.0) for panel in panels if panel.bbox]
    heights = [float(panel.bbox.get("height") or 0.0) for panel in panels if panel.bbox]
    median_width = _median([value for value in widths if value > 0]) or 0.0
    median_height = _median([value for value in heights if value > 0]) or 0.0
    page_width = float(document.width or 0.0)
    page_height = float(document.height or 0.0)

    if page_width > 0 and page_height > 0:
        oversized = [
            panel.label
            for panel in panels
            if panel.bbox
            and (
                float(panel.bbox.get("width") or 0.0) > page_width * 0.95
                or float(panel.bbox.get("height") or 0.0) > page_height * 0.95
            )
        ]
        if oversized:
            findings.append(
                _finding(
                    rule_id="PANEL-003",
                    severity="warning",
                    message=f"Panel bounding boxes may be too broad: {', '.join(oversized)}.",
                    target_selector={"role": "panel_root"},
                    suggested_fix="Re-detect panel bounds using local panel content before applying panel-level layout fixes.",
                )
            )

    if median_width > 0 and median_height > 0 and len(panels) >= 4:
        row_clusters = _cluster_by_position(
            [
                (float(panel.bbox.get("top") or 0.0) + float(panel.bbox.get("height") or 0.0) / 2.0, panel)
                for panel in panels
                if panel.bbox
            ],
            tolerance=max(2.0, median_height * 0.35),
        )
        column_clusters = _cluster_by_position(
            [
                (float(panel.bbox.get("left") or 0.0) + float(panel.bbox.get("width") or 0.0) / 2.0, panel)
                for panel in panels
                if panel.bbox
            ],
            tolerance=max(2.0, median_width * 0.35),
        )
        row_top_spreads = [
            _spread([float(panel.bbox.get("top") or 0.0) for panel in cluster if panel.bbox])
            for cluster in row_clusters
            if len(cluster) >= 2
        ]
        column_left_spreads = [
            _spread([float(panel.bbox.get("left") or 0.0) for panel in cluster if panel.bbox])
            for cluster in column_clusters
            if len(cluster) >= 2
        ]
        row_misaligned = any(spread > max(1.0, median_height * 0.08) for spread in row_top_spreads)
        column_misaligned = any(spread > max(1.0, median_width * 0.08) for spread in column_left_spreads)
        if row_misaligned or column_misaligned:
            findings.append(
                _finding(
                    rule_id="PANEL-004",
                    severity="info",
                    message="Detected panels do not appear aligned to a clean row/column grid.",
                    target_selector={"role": "panel_root"},
                    suggested_fix="Align panel roots by rows and columns after confirming panel bounds.",
                )
            )

    return findings


def publication_qa(document: DocumentContext) -> dict[str, Any]:
    objects = document.objects or []
    findings: list[dict[str, Any]] = []
    findings.extend(_panel_label_findings(document))
    findings.extend(_panel_alignment_findings(document))

    visual_snapshot = document.visual_snapshot or {}
    if not visual_snapshot.get("png_path"):
        findings.append(
            _finding(
                rule_id="PAGE-001",
                severity="warning",
                message="No rendered page snapshot is available for visual QA.",
                suggested_fix="Render the current SVG page to PNG before evaluating visual layout.",
            )
        )
    elif visual_snapshot.get("png_error"):
        findings.append(
            _finding(
                rule_id="PAGE-001",
                severity="warning",
                message=f"Rendered page snapshot failed: {visual_snapshot.get('png_error')}",
                suggested_fix="Fix the render/snapshot path before relying on visual QA.",
            )
        )

    role_font_spreads: dict[str, float] = {}
    for role in ("panel_label", "axis_label", "tick_label", "label"):
        values = _font_values(objects, role)
        if len(values) >= 2:
            role_font_spreads[role] = _spread(values)

    if role_font_spreads.get("tick_label", 0.0) > 0.2:
        findings.append(
            _finding(
                rule_id="AXIS-001",
                severity="warning",
                message="Tick labels are not using a consistent font size.",
                target_selector={"role": "tick_label"},
                suggested_fix="Set tick labels in comparable panels to a consistent visual size, usually 8-9 pt.",
            )
        )
    if role_font_spreads.get("axis_label", 0.0) > 0.2:
        findings.append(
            _finding(
                rule_id="TEXT-001",
                severity="warning",
                message="Axis labels are not using a consistent font size.",
                target_selector={"role": "axis_label"},
                suggested_fix="Set axis labels in comparable panels to a consistent visual size, usually 10 pt.",
            )
        )
    if role_font_spreads.get("panel_label", 0.0) > 0.2:
        findings.append(
            _finding(
                rule_id="TEXT-001",
                severity="warning",
                message="Panel labels are not using a consistent font size.",
                target_selector={"role": "panel_label"},
                suggested_fix="Set panel labels to a consistent visual size, usually 12 pt.",
            )
        )

    text_objects = [item for item in objects if item.tag in {"text", "tspan"} and item.font_size]
    oversized = []
    for item in text_objects:
        value = _numeric_px(item.font_size)
        if value is not None and value > 24.0:
            oversized.append(item.object_id)
    if oversized:
        findings.append(
            _finding(
                rule_id="TEXT-001",
                severity="warning",
                message=f"Potentially oversized text objects detected: {', '.join(oversized[:12])}.",
                target_selector={"object_id": oversized[0]} if oversized else {},
                suggested_fix="Review these text objects visually and reduce to the intended hierarchy if they appear oversized.",
            )
        )

    axis_findings, axis_metrics = _axis_style_findings(objects)
    findings.extend(axis_findings)

    warnings = [str(item.get("message")) for item in findings if item.get("severity") in {"warning", "error"}]

    return {
        "status": "needs_review" if findings else "ok",
        "rubric_version": "2026-04-24",
        "panel_count": len(document.panels or []),
        "panels": [panel.to_dict() for panel in document.panels or []],
        "role_font_spreads": role_font_spreads,
        **axis_metrics,
        "findings": findings,
        "warnings": warnings,
    }
