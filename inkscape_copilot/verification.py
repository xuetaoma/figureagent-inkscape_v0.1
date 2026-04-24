from __future__ import annotations

from typing import Any

from .planner import DocumentContext, DocumentObject
from .publication_qa import publication_qa
from .schema import ActionPlan


MUTATING_ACTION_PREFIXES = (
    "create_",
    "delete_",
    "move_",
    "replace_",
    "set_",
    "resize_",
    "scale_",
    "rotate_",
    "duplicate_",
    "align_",
    "distribute_",
    "rename_",
)


def _object_map(document: DocumentContext) -> dict[str, DocumentObject]:
    return {item.object_id: item for item in document.objects or []}


def _comparable_object(item: DocumentObject) -> dict[str, Any]:
    return {
        "tag": item.tag,
        "text": item.text,
        "fill": item.fill,
        "stroke": item.stroke,
        "stroke_width": item.stroke_width,
        "font_size": item.font_size,
        "bbox": item.bbox,
        "center": item.center,
        "role": item.role,
        "panel": item.panel,
        "axis": item.axis,
        "parent_id": item.parent_id,
        "group_id": item.group_id,
        "panel_root_id": item.panel_root_id,
        "label_for": item.label_for,
        "attached_to": item.attached_to,
        "text_group_id": item.text_group_id,
        "glyph_for": item.glyph_for,
        "line_points": item.line_points,
    }


def _selected_ids(document: DocumentContext) -> list[str]:
    return [item.object_id for item in document.selection if item.object_id]


def _target_selector(params: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "object_id",
        "object_index",
        "text",
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
        "include_descendants",
    )
    return {key: params.get(key) for key in keys if params.get(key) not in (None, "", False)}


def _planned_target_selectors(plan: ActionPlan) -> list[dict[str, Any]]:
    selectors: list[dict[str, Any]] = []
    for action in plan.actions:
        selector = _target_selector(action.params)
        if selector:
            selectors.append({"kind": action.kind, "selector": selector})
    return selectors


def _mutating_action_count(plan: ActionPlan) -> int:
    return sum(1 for action in plan.actions if action.kind.startswith(MUTATING_ACTION_PREFIXES))


def _target_only_action_count(plan: ActionPlan) -> int:
    return sum(1 for action in plan.actions if action.kind in {"select_object", "select_targets"})


def verify_plan_execution(
    *,
    prompt: str,
    plan: ActionPlan,
    before: DocumentContext,
    after: DocumentContext,
) -> dict[str, Any]:
    before_objects = _object_map(before)
    after_objects = _object_map(after)
    before_ids = set(before_objects)
    after_ids = set(after_objects)

    created_ids = sorted(after_ids - before_ids)
    deleted_ids = sorted(before_ids - after_ids)
    changed_ids = sorted(
        object_id
        for object_id in before_ids & after_ids
        if _comparable_object(before_objects[object_id]) != _comparable_object(after_objects[object_id])
    )

    mutating_count = _mutating_action_count(plan)
    target_only_count = _target_only_action_count(plan)
    warnings: list[str] = []
    if mutating_count and not (created_ids or deleted_ids or changed_ids):
        warnings.append("The plan contained mutating actions, but the document snapshot did not show any object changes.")
    if target_only_count and not _selected_ids(after):
        warnings.append("The plan selected targets, but the post-apply snapshot has no active selection.")

    qa = publication_qa(after)
    qa_warnings = qa.get("warnings") if isinstance(qa, dict) else None
    if isinstance(qa_warnings, list):
        warnings.extend(str(item) for item in qa_warnings)

    status = "verified"
    if warnings:
        status = "needs_review"
    if not plan.actions:
        status = "no_actions"

    return {
        "status": status,
        "prompt": prompt,
        "action_count": len(plan.actions),
        "mutating_action_count": mutating_count,
        "planned_target_selectors": _planned_target_selectors(plan),
        "before_object_count": len(before_objects),
        "after_object_count": len(after_objects),
        "created_object_ids": created_ids,
        "deleted_object_ids": deleted_ids,
        "changed_object_ids": changed_ids,
        "selected_object_ids": _selected_ids(after),
        "publication_qa": qa,
        "warnings": warnings,
    }
