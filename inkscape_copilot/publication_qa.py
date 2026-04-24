from __future__ import annotations

from collections import Counter
from typing import Any

from .planner import DocumentContext, DocumentObject


def _finding(
    *,
    rule_id: str,
    severity: str,
    message: str,
    target_selector: dict[str, Any] | None = None,
    suggested_fix: str | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "target_selector": target_selector or {},
        "suggested_fix": suggested_fix,
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


def _spread(values: list[float]) -> float:
    return max(values) - min(values) if values else 0.0


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


def publication_qa(document: DocumentContext) -> dict[str, Any]:
    objects = document.objects or []
    findings: list[dict[str, Any]] = []
    findings.extend(_panel_label_findings(document))

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

    warnings = [str(item.get("message")) for item in findings if item.get("severity") in {"warning", "error"}]

    return {
        "status": "needs_review" if findings else "ok",
        "rubric_version": "2026-04-24",
        "panel_count": len(document.panels or []),
        "panels": [panel.to_dict() for panel in document.panels or []],
        "role_font_spreads": role_font_spreads,
        "findings": findings,
        "warnings": warnings,
    }
