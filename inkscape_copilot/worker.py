from __future__ import annotations

import sys
import os
import shutil
import subprocess
import time
import traceback
from pathlib import Path

import inkex
from inkex.command import write_svg

PACKAGE_ROOT = Path(__file__).resolve().parent
PACKAGE_PARENT = str(PACKAGE_ROOT.parent)
if PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, PACKAGE_PARENT)

from inkscape_copilot.bridge import (
    DOCUMENT_PNG_SNAPSHOT_FILE,
    DOCUMENT_SVG_SNAPSHOT_FILE,
    SNAPSHOT_DIR,
    append_event,
    clear_planned_step,
    mark_error,
    mark_job_applied,
    pending_jobs,
    read_document_context,
    write_execution_result,
    write_document_context,
)
from inkscape_copilot.executor import apply_action_plan
from inkscape_copilot.planner import DocumentContext, DocumentObject, SelectionItem
from inkscape_copilot.scene_graph import detect_panels, extract_scene_objects
from inkscape_copilot.targeting import style_value, tag_name, bbox_dict, node_text
from inkscape_copilot.verification import verify_plan_execution

SODIPODI_DOCNAME = "{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}docname"
WORKER_DEBUG_LOG = Path(PACKAGE_PARENT) / "inkscape_copilot_runtime" / "state" / "worker_debug.log"


def _debug_log(message: str) -> None:
    try:
        WORKER_DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with WORKER_DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.time():.3f} {message}\n")
    except Exception:
        pass


def _document_name(svg: inkex.SvgDocumentElement) -> str | None:
    for key in (SODIPODI_DOCNAME, "sodipodi:docname", "docname"):
        value = svg.get(key)
        if value:
            return str(value)
    return None


def _document_objects(svg: inkex.SvgDocumentElement, limit: int | None = 500) -> list[DocumentObject]:
    return extract_scene_objects(svg, limit=limit)


def _inkscape_binary() -> str | None:
    explicit = os.environ.get("INKSCAPE_COPILOT_INKSCAPE_BIN")
    candidates = [
        explicit,
        "/Applications/Inkscape.app/Contents/MacOS/inkscape",
        shutil.which("inkscape"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return shutil.which("inkscape")


def _render_visual_snapshot(svg: inkex.SvgDocumentElement) -> dict[str, object]:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, object] = {
        "svg_path": str(DOCUMENT_SVG_SNAPSHOT_FILE),
        "png_path": str(DOCUMENT_PNG_SNAPSHOT_FILE),
        "updated_at": time.time(),
    }
    try:
        if DOCUMENT_SVG_SNAPSHOT_FILE.exists():
            DOCUMENT_SVG_SNAPSHOT_FILE.unlink()
        write_svg(svg, str(DOCUMENT_SVG_SNAPSHOT_FILE))
    except Exception as exc:
        metadata["svg_error"] = str(exc)
        _debug_log(f"visual snapshot SVG write failed error={exc}")
        return metadata

    inkscape_bin = _inkscape_binary()
    if not inkscape_bin:
        metadata["png_error"] = "Could not find Inkscape CLI binary."
        return metadata

    command = [
        inkscape_bin,
        str(DOCUMENT_SVG_SNAPSHOT_FILE),
        "--export-area-page",
        "--export-background=white",
        "--export-background-opacity=1",
        "--export-width=1400",
        f"--export-filename={DOCUMENT_PNG_SNAPSHOT_FILE}",
    ]
    try:
        if DOCUMENT_PNG_SNAPSHOT_FILE.exists():
            DOCUMENT_PNG_SNAPSHOT_FILE.unlink()
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        metadata["png_error"] = "PNG export timed out after 30 seconds."
        _debug_log("visual snapshot PNG export timed out")
        return metadata
    except Exception as exc:
        metadata["png_error"] = str(exc)
        _debug_log(f"visual snapshot PNG export failed error={exc}")
        return metadata

    if result.returncode != 0:
        metadata["png_error"] = (result.stderr or result.stdout or "PNG export failed.").strip()[-2000:]
        _debug_log(f"visual snapshot PNG export failed returncode={result.returncode}")
        return metadata

    if DOCUMENT_PNG_SNAPSHOT_FILE.exists():
        metadata["png_size_bytes"] = DOCUMENT_PNG_SNAPSHOT_FILE.stat().st_size
    return metadata


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


def _nodes_from_snapshot_selection(svg: inkex.SvgDocumentElement) -> list[inkex.BaseElement]:
    payload = read_document_context()
    object_ids = [
        str(item["object_id"])
        for item in payload.get("selection", [])
        if isinstance(item, dict) and item.get("object_id")
    ]
    resolved: list[inkex.BaseElement] = []
    seen_ids: set[str] = set()
    for object_id in object_ids:
        node = _find_node_by_id(svg, object_id)
        if node is None:
            continue
        node_id = node.get("id")
        if node_id and node_id in seen_ids:
            continue
        if node_id:
            seen_ids.add(node_id)
        resolved.append(node)
    return resolved


def _infer_selection_from_prompt(svg: inkex.SvgDocumentElement, prompt: str) -> list[inkex.BaseElement]:
    prompt_lower = prompt.lower()
    desired_tags: tuple[str, ...] = ()
    if "text" in prompt_lower or "label" in prompt_lower or "word" in prompt_lower:
        desired_tags = ("text", "tspan")
    elif "square" in prompt_lower or "rectangle" in prompt_lower or "rect" in prompt_lower:
        desired_tags = ("rect",)
    elif "circle" in prompt_lower:
        desired_tags = ("circle", "ellipse")

    if not desired_tags:
        return []

    candidates: list[inkex.BaseElement] = []
    try:
        for node in svg.iterdescendants():
            if tag_name(node) in desired_tags and node.get("id"):
                candidates.append(node)
    except Exception:
        return []

    if not candidates:
        return []
    return [candidates[-1]]


def resolve_effective_selection(
    svg: inkex.SvgDocumentElement,
    selected: list[inkex.BaseElement],
    prompt: str,
) -> list[inkex.BaseElement]:
    if selected:
        return selected

    snapshot_selection = _nodes_from_snapshot_selection(svg)
    if snapshot_selection:
        _debug_log(f"resolve_effective_selection using snapshot selection count={len(snapshot_selection)}")
        return snapshot_selection

    inferred_selection = _infer_selection_from_prompt(svg, prompt)
    if inferred_selection:
        _debug_log(
            "resolve_effective_selection inferred target "
            f"count={len(inferred_selection)} prompt={prompt!r}"
        )
        return inferred_selection

    return selected


def document_context_from_svg(
    svg: inkex.SvgDocumentElement,
    selected: list[inkex.BaseElement],
    visual_snapshot: dict[str, object] | None = None,
) -> DocumentContext:
    width = None
    height = None
    try:
        width = float(svg.viewport_width)
        height = float(svg.viewport_height)
    except Exception:
        pass

    return DocumentContext(
        document_name=_document_name(svg),
        document_path=None,
        width=width,
        height=height,
        visual_snapshot=visual_snapshot,
        selection=[
            SelectionItem(
                object_id=node.get("id") or f"selected-{index}",
                tag=str(node.tag),
                fill=style_value(node, "fill"),
                stroke=style_value(node, "stroke"),
                bbox=bbox_dict(node),
            )
            for index, node in enumerate(selected, start=1)
        ],
        objects=(objects := _document_objects(svg)),
        panels=detect_panels(objects),
    )


def sync_document_context(svg: inkex.SvgDocumentElement, selected: list[inkex.BaseElement]) -> None:
    _debug_log(f"sync_document_context selection_count={len(selected)}")
    visual_snapshot = _render_visual_snapshot(svg)
    write_document_context(document_context_from_svg(svg, selected, visual_snapshot=visual_snapshot))


def apply_pending_jobs(svg: inkex.SvgDocumentElement, selected: list[inkex.BaseElement]) -> tuple[list[inkex.BaseElement], str]:
    _debug_log(f"apply_pending_jobs entered selection_count={len(selected)}")
    jobs = pending_jobs()
    _debug_log(f"apply_pending_jobs pending_count={len(jobs)}")
    if not jobs:
        sync_document_context(svg, selected)
        write_execution_result(state="idle", summary="No pending copilot changes to apply.")
        _debug_log("apply_pending_jobs no jobs found")
        return selected, "No pending copilot jobs found."

    current_selection = selected
    applied_count = 0
    failed_count = 0
    last_summary = ""

    for job in jobs:
        _debug_log(f"apply_pending_jobs starting job_id={job.job_id}")
        append_event("job_started", {"job_id": job.job_id, "prompt": job.prompt})
        try:
            effective_selection = resolve_effective_selection(svg, current_selection, job.prompt)
            try:
                before_context = document_context_from_svg(svg, effective_selection)
            except Exception as exc:
                _debug_log(f"before verification snapshot failed job_id={job.job_id} error={exc}")
                before_context = DocumentContext(width=None, height=None, selection=[], objects=[])
            current_selection, last_summary = apply_action_plan(svg, effective_selection, job.plan)
            try:
                after_context = document_context_from_svg(svg, current_selection)
                verification = verify_plan_execution(
                    prompt=job.prompt,
                    plan=job.plan,
                    before=before_context,
                    after=after_context,
                )
            except Exception as exc:
                _debug_log(f"post-apply verification failed job_id={job.job_id} error={exc}")
                verification = {
                    "status": "verification_failed",
                    "prompt": job.prompt,
                    "action_count": len(job.plan.actions),
                    "warnings": [f"Verification failed after apply: {exc}"],
                }
            mark_job_applied(job.job_id)
            write_execution_result(
                state="applied",
                job_id=job.job_id,
                summary=last_summary,
                verification=verification,
            )
            clear_planned_step()
            append_event(
                "job_applied",
                {
                    "job_id": job.job_id,
                    "summary": last_summary,
                    "verification": verification,
                },
            )
            applied_count += 1
            _debug_log(
                f"apply_pending_jobs applied job_id={job.job_id} "
                f"summary={last_summary} verification_status={verification.get('status')}"
            )
        except Exception as exc:
            mark_error(job.job_id, str(exc))
            write_execution_result(state="error", job_id=job.job_id, error=str(exc))
            append_event("job_failed", {"job_id": job.job_id, "error": str(exc)})
            failed_count += 1
            _debug_log(f"apply_pending_jobs failed job_id={job.job_id} error={exc}")
            _debug_log(traceback.format_exc())

    sync_document_context(svg, current_selection)
    if applied_count or failed_count:
        return current_selection, (
            f"Applied {applied_count} queued copilot job(s), failed {failed_count}. "
            f"Last summary: {last_summary or 'No successful jobs.'}"
        )
    return current_selection, "No queued copilot jobs were applied."


class ApplyPendingJobsWorker(inkex.EffectExtension):
    def effect(self) -> None:
        _debug_log("ApplyPendingJobsWorker.effect entered")
        append_event("worker_invoked", {"worker": "apply_pending_jobs"})
        selected = list(self.svg.selection.values())
        _selected, summary = apply_pending_jobs(self.svg, selected)
        _debug_log(f"ApplyPendingJobsWorker.effect completed summary={summary}")
        inkex.utils.debug(f"Inkscape Copilot: {summary}")


if __name__ == "__main__":
    _debug_log("worker.py __main__ executing ApplyPendingJobsWorker.run()")
    ApplyPendingJobsWorker().run()
