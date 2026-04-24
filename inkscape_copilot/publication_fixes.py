from __future__ import annotations

from typing import Any

from .planner import DocumentContext
from .publication_qa import publication_qa
from .schema import Action


PT_TO_CSS_PX = 4.0 / 3.0


PUBLICATION_RUBRIC_SUMMARY = {
    "typography": {
        "panel_label_pt": 12,
        "axis_label_pt": 10,
        "tick_label_pt": 9,
        "legend_annotation_pt": "7-9",
        "rule": "Use a clear visual hierarchy and keep comparable text sizes consistent.",
    },
    "panels": {
        "rule": "Panel labels should be ordered, unique, consistently placed, and not hard-coded to a-d only.",
    },
    "axes": {
        "rule": "Comparable axes should share tick length, tick thickness, tick-label size, and axis-label size.",
    },
    "math_glyphs": {
        "rule": "Path-based rho/Omega/subscript/superscript glyphs should move and scale with their text label using text_group_id/glyph_for.",
    },
    "page": {
        "rule": "Do not resize the page unless the user explicitly asks; keep important artwork visible on the page.",
    },
}


def pt_to_css_px(points: float) -> float:
    return points * PT_TO_CSS_PX


def _action_dict(action: Action) -> dict[str, Any]:
    return {"kind": action.kind, "params": action.params}


def _safe_action_for_finding(finding: dict[str, Any]) -> Action | None:
    rule_id = str(finding.get("rule_id") or "")
    message = str(finding.get("message") or "").lower()
    selector = finding.get("target_selector")
    if not isinstance(selector, dict):
        selector = {}
    role = str(selector.get("role") or "")

    if rule_id == "TEXT-001" and role == "panel_label":
        return Action(kind="set_object_font_size", params={"role": "panel_label", "font_size_px": pt_to_css_px(12)})
    if rule_id == "TEXT-001" and role == "axis_label":
        return Action(kind="set_object_font_size", params={"role": "axis_label", "font_size_px": pt_to_css_px(10)})
    if rule_id == "AXIS-001" and role == "tick_label":
        return Action(kind="set_tick_label_size", params={"role": "tick_label", "font_size_px": pt_to_css_px(9)})
    if rule_id == "TEXT-001" and "oversized text" in message:
        object_id = selector.get("object_id")
        if isinstance(object_id, str) and object_id.strip():
            return Action(
                kind="set_object_font_size",
                params={"object_id": object_id.strip(), "font_size_px": pt_to_css_px(10)},
            )
    return None


def publication_fix_suggestions(
    document: DocumentContext,
    qa: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    qa = qa if isinstance(qa, dict) else publication_qa(document)
    findings = qa.get("findings") if isinstance(qa, dict) else None
    if not isinstance(findings, list):
        return []

    suggestions: list[dict[str, Any]] = []
    seen_actions: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        action = _safe_action_for_finding(finding)
        action_payload = _action_dict(action) if action else None
        key = repr(action_payload)
        if action_payload and key in seen_actions:
            continue
        if action_payload:
            seen_actions.add(key)
        suggestions.append(
            {
                "rule_id": finding.get("rule_id"),
                "severity": finding.get("severity"),
                "message": finding.get("message"),
                "target_selector": finding.get("target_selector") or {},
                "suggested_fix": finding.get("suggested_fix"),
                "safe_action": action_payload,
                "auto_apply_safe": bool(action_payload),
            }
        )
    return suggestions


def safe_publication_actions(document: DocumentContext, qa: dict[str, Any] | None = None) -> list[Action]:
    actions: list[Action] = []
    seen: set[str] = set()
    for suggestion in publication_fix_suggestions(document, qa):
        payload = suggestion.get("safe_action")
        if not isinstance(payload, dict):
            continue
        try:
            action = Action.from_dict(payload)
        except ValueError:
            continue
        key = repr(action.to_dict())
        if key in seen:
            continue
        seen.add(key)
        actions.append(action)
    return actions

