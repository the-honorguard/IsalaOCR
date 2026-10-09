"""/test-pipeline routes, split out of webui.create_web_app.

The proefpagina retests an existing input image (never a fresh upload) so a
retest is always reproducible from what Inputselectie already knows about.
Two screens:

- ``/test-pipeline`` -- a list of every Inputselectie-visible image with its
  current proefpagina-retest status ("Testen" starts a worker run; a finished
  retest links to the compare screen) and whether the training pipeline has
  ever produced a datablok for it ("Getraind" vs "Nog niet getraind") -- only
  a "Getraind" image's retest has a real trainingspipeline result to compare
  against; retesting an untrained one still runs, but the compare screen's
  right-hand column stays "Nog niet beschikbaar" throughout.
- ``/test-pipeline/vergelijk/<source_id>`` -- the retest laid out stage by
  stage next to the training pipeline's own result for the same image (see
  ``test_pipeline_compare()``'s docstring).

``workspace_root``, ``project_manager``, ``safe_workspace_file``,
``job_statuses``, ``database`` and ``enqueue_job`` are all reused by other
route groups in webui.py and are passed in explicitly.
``active_table_cell_model`` and the per-stage data builders in
``routes_documents.py`` are pure functions imported directly from their own
modules (not from webui.py). A rerun's target file is passed straight to job
61 via its own ``options`` (see ``_start_rerun()``'s docstring) -- it is
never written to the shared ``input_selection.json`` Inputselectie itself
uses, since multiple reruns queued close together would race on that single
mutable file.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import cv2
from flask import Flask, abort, flash, redirect, render_template, request, url_for

from ..image_io import load_input
from .input_selection import input_file_source_id, input_files
from .json_store import read_json, write_json_atomic
from .projects import ProjectManager
from .routes_documents import (
    _cells_stage_data, _datablok_stage_data, _identification_stage_data, _mapping_scope_stage_data,
    _measurement_diff_rows, _rasterized_cells_stage_data, _readout_diff_rows, _recognition_readout_stage_data,
    _tables_stage_data,
)
from .table_cell_training import active_table_cell_model
from .test_pipeline_rerun import duplicate_dicom_with_fresh_identity, find_input_file_by_source_id
from .test_pipeline_sources import (
    forget_test_pipeline_source, is_test_pipeline_source_reviewed, job_of_test_pipeline_source,
    latest_rerun_of_source, mark_test_pipeline_reviewed, origin_of_test_pipeline_source,
    record_test_pipeline_source, test_pipeline_source_ids, test_pipeline_sources_snapshot,
)

RERUN_ERROR_MESSAGES = {
    "not_found": "Het originele DICOM-bestand voor deze afbeelding is niet gevonden in de inputmap.",
    "invalid_path": "Ongeldig doelpad voor de rerun-kopie.",
    "copy_failed": "Kon geen rerun-kopie maken van het originele DICOM-bestand.",
}

RUNNING_JOB_STATUSES = {"pending", "running"}
FAILED_JOB_STATUSES = {"failed", "error"}
DISPLAY_TIMEZONE = ZoneInfo("Europe/Amsterdam")


def _processed_at_label(value: object, fallback_mtime_ns: int) -> tuple[str, str]:
    """Return an ISO timestamp and its Amsterdam wall-clock label."""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
        if moment is None:
            raise ValueError("missing timestamp")
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        if not fallback_mtime_ns:
            return "", ""
        moment = datetime.fromtimestamp(fallback_mtime_ns / 1_000_000_000, tz=timezone.utc)
    return moment.isoformat(), moment.astimezone(DISPLAY_TIMEZONE).strftime("%d-%m-%Y %H:%M")


def _table_mapping_summary(localization: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    """Count final mapped values per detected table using their image coordinates."""
    tables = [table for table in (localization.get("tables") or []) if isinstance(table, dict)]
    tables.sort(key=lambda table: (float(table.get("x1") or 0), float(table.get("y1") or 0)))
    counts = [0] * len(tables)
    unassigned = 0
    for measurement in (output.get("measurements") or {}).values():
        if not isinstance(measurement, dict) or not measurement.get("mapping_id") or not measurement.get("raw_text"):
            continue
        roi = measurement.get("roi")
        if not isinstance(roi, (list, tuple)) or len(roi) != 4:
            unassigned += 1
            continue
        try:
            x1, y1, x2, y2 = (float(value) for value in roi)
            overlaps = [
                max(0, min(x2, float(table["x2"])) - max(x1, float(table["x1"])))
                * max(0, min(y2, float(table["y2"])) - max(y1, float(table["y1"])))
                for table in tables
            ]
        except (KeyError, TypeError, ValueError):
            unassigned += 1
            continue
        if overlaps and max(overlaps) > 0:
            counts[overlaps.index(max(overlaps))] += 1
        else:
            unassigned += 1
    return {"table_count": len(tables), "mapped_per_table": counts, "unassigned": unassigned}


def _test_upload_destination(project_manager: ProjectManager, filename: str) -> Path:
    """Resolve a safe ``/input``-scoped destination for a new proefpagina rerun copy."""
    input_root = Path(project_manager.active().input_path).resolve()
    allowed_root = Path("/input").resolve()
    if allowed_root != input_root and allowed_root not in input_root.parents:
        raise ValueError("Het actieve project-inputpad valt buiten /input.")
    input_root.mkdir(parents=True, exist_ok=True)
    stored_name = f"test_{uuid.uuid4().hex[:12]}_{filename}"
    destination = (input_root / stored_name).resolve()
    if input_root not in destination.parents:
        raise ValueError("Ongeldig uploadpad.")
    return destination


def register_test_pipeline_routes(
    app: Flask,
    *,
    workspace_root: Callable[[], Path],
    project_manager: ProjectManager,
    safe_workspace_file: Callable[[str | Path], Path],
    job_statuses: Callable[..., list[dict[str, Any]]],
    database: Any,
    enqueue_job: Callable[..., dict[str, Any]],
    source_rows: Callable[[], list[dict[str, Any]]],
    loaded_config: Any | None,
) -> None:
    # (rerun_source_id, origin_source_id) -> (fingerprint, differing_count). The
    # fingerprint is each side's own extracted_output file (mtime_ns, size), so a
    # rerun's result (written once and never touched again) is cached forever,
    # while an origin whose datablok gets regenerated later (e.g. a Mapping
    # Studio correction) still invalidates correctly. See
    # _cached_differing_count()'s own docstring for why this exists.
    _differing_count_cache: dict[tuple[str, str], tuple[tuple[tuple[int, int], tuple[int, int]], int]] = {}
    _differing_count_cache_lock = threading.Lock()
    _table_summary_cache: dict[str, tuple[tuple[tuple[int, int], tuple[int, int]], dict[str, Any]]] = {}
    _table_summary_cache_lock = threading.Lock()

    def _cached_table_summary(source_id: str) -> dict[str, Any]:
        """Read one rerun's table counts and completion time only when files change."""
        localization_path = workspace_root() / "localization_detections" / f"{source_id}.json"
        output_path = workspace_root() / "extracted_output" / f"{source_id}.json"

        def _fingerprint(path: Path) -> tuple[int, int]:
            try:
                stat = path.stat()
            except OSError:
                return (0, 0)
            return (stat.st_mtime_ns, stat.st_size)

        fingerprint = (_fingerprint(localization_path), _fingerprint(output_path))
        with _table_summary_cache_lock:
            cached = _table_summary_cache.get(source_id)
            if cached is not None and cached[0] == fingerprint:
                return cached[1]
        result: dict[str, Any] = {"table_summary": None, "processed_at_iso": "", "processed_at_label": ""}
        output: Any = None
        if fingerprint[1] != (0, 0):
            output = read_json(safe_workspace_file(Path("extracted_output") / f"{source_id}.json"), {})
            if isinstance(output, dict):
                result["processed_at_iso"], result["processed_at_label"] = _processed_at_label(
                    output.get("generated_at"), fingerprint[1][0],
                )
        if fingerprint[0] != (0, 0) and isinstance(output, dict):
            localization = read_json(safe_workspace_file(Path("localization_detections") / f"{source_id}.json"), {})
            if isinstance(localization, dict):
                result["table_summary"] = _table_mapping_summary(localization, output)
        with _table_summary_cache_lock:
            _table_summary_cache[source_id] = (fingerprint, result)
        return result

    def _cached_differing_count(rerun_source_id: str, origin_source_id: str) -> int:
        """Field-by-field deviation count between a rerun and its origin, cached by file mtime.

        _datablok_stage_data() reads and parses a JSON file and resolves
        several paths per call; recomputing it for both sides of every
        "getest" row on every proefpagina list view (dozens to low hundreds
        of rows) measurably slowed the page down -- profiling a real project
        showed ~5s of a ~24s page load going into this alone. Neither side's
        file content needs re-reading if neither has changed since the last
        time this exact pair was computed, so this mirrors
        input_file_source_id()'s own (mtime, size) cache in input_selection.py.
        """
        def _fingerprint(source_id: str) -> tuple[int, int]:
            # Deliberately not safe_workspace_file(): that resolves the full
            # real path (symlink-safe, for paths built from a request) on
            # every call, which this function also pays on a cache *hit* --
            # profiling showed it as the single biggest remaining cost once
            # the rest of this page was fixed. source_id here always comes
            # from this project's own tracked ids (never straight from a
            # request), and _datablok_stage_data() below still reads the
            # file through safe_workspace_file() itself when there's an
            # actual cache miss to serve.
            try:
                stat = (workspace_root() / "extracted_output" / f"{source_id}.json").stat()
            except OSError:
                return (0, 0)
            return (stat.st_mtime_ns, stat.st_size)

        fingerprint = (_fingerprint(rerun_source_id), _fingerprint(origin_source_id))
        cache_key = (rerun_source_id, origin_source_id)
        with _differing_count_cache_lock:
            cached = _differing_count_cache.get(cache_key)
            if cached is not None and cached[0] == fingerprint:
                return cached[1]
        new_datablok = _datablok_stage_data(
            rerun_source_id, workspace_root=workspace_root(), safe_workspace_file=safe_workspace_file,
            database=database,
        )
        old_datablok = _datablok_stage_data(
            origin_source_id, workspace_root=workspace_root(), safe_workspace_file=safe_workspace_file,
            database=database,
        )
        diff_rows = _measurement_diff_rows(new_datablok, old_datablok)
        differing_count = sum(1 for item in diff_rows if item["differs"])
        with _differing_count_cache_lock:
            _differing_count_cache[cache_key] = (fingerprint, differing_count)
        return differing_count

    def _extracted_output_ids() -> set[str]:
        """Every source_id with an ``extracted_output/<id>.json`` file, in one directory scan.

        ``_all_input_rows()``/``test_pipeline()`` used to check this per row
        with an individual ``Path.is_file()`` stat call -- harmless locally,
        but each one is its own round trip across the project's Docker bind
        mount, and with ~200 rows that alone was over 10,000 stat calls
        (~11s) on a real project. One directory listing plus in-memory set
        membership checks replaces all of them.
        """
        root = workspace_root() / "extracted_output"
        if not root.is_dir():
            return set()
        return {path.stem for path in root.glob("*.json")}

    def _render_ids() -> set[str]:
        """Every source_id with a ``source_renders/<id>.png`` file, in one directory scan."""
        root = workspace_root() / "source_renders"
        if not root.is_dir():
            return set()
        return {path.stem for path in root.glob("*.png")}

    def _prepare_rerun(source_id: str) -> dict[str, Any]:
        """Create one byte-distinct DICOM copy for a new proefrun."""
        previous_rerun_source_id = latest_rerun_of_source(workspace_root(), source_id)
        if previous_rerun_source_id:
            forget_test_pipeline_source(workspace_root(), previous_rerun_source_id)
        input_root = Path(project_manager.active().input_path).resolve()
        original = find_input_file_by_source_id(input_root, source_id)
        if original is None:
            return {"error": "not_found"}
        try:
            destination = _test_upload_destination(project_manager, original.name)
        except ValueError:
            return {"error": "invalid_path"}
        try:
            duplicate_dicom_with_fresh_identity(original, destination)
        except (OSError, ValueError, RuntimeError):
            return {"error": "copy_failed"}
        relative_key = destination.relative_to(Path("/input").resolve()).as_posix()
        new_source_id = hashlib.sha256(destination.read_bytes()).hexdigest()[:24]
        return {
            "error": None, "origin_source_id": source_id, "source_id": new_source_id,
            "input_file": relative_key, "input_file_path": destination,
        }

    def _start_rerun(source_id: str) -> dict[str, Any]:
        """Queue one image; bulk submissions use the same preparation step."""
        prepared = _prepare_rerun(source_id)
        if prepared["error"]:
            return {"error": prepared["error"], "job_id": None, "rerun_source_id": None}
        active_table_model = active_table_cell_model(workspace_root()) or {}
        job = enqueue_job("61", {
            "table_model_id": "active" if active_table_model else "generic-ppstructure",
            "mapping_profile_id": "",
            "input_file": prepared["input_file"],
        })
        record_test_pipeline_source(
            workspace_root(), prepared["source_id"], origin_source_id=source_id,
            job_id=str(job["job_id"]), input_file_path=prepared["input_file_path"],
        )
        return {"error": None, "job_id": str(job["job_id"]), "rerun_source_id": prepared["source_id"]}

    def _all_input_rows() -> list[dict[str, Any]]:
        """Every image the proefpagina list can act on -- not just already-trained ones.

        Mirrors Inputselectie's own candidate set (``input_files()`` under
        the active project's input root, the same root ``_start_rerun()``
        searches), so "which images can I pick here" matches what
        Inputselectie shows, plus any trained source whose original DICOM has
        since been removed from the input directory (so it doesn't just
        vanish from this list). Each row is tagged ``trained``
        (``extracted_output/<id>.json`` exists, so a retest has a real
        trainingspipeline result to compare against) to keep the two kinds
        visually distinct instead of looking interchangeable.
        """
        test_source_ids = test_pipeline_source_ids(workspace_root())
        extracted_output_ids = _extracted_output_ids()
        render_ids = _render_ids()

        def _is_trained(source_id: str) -> bool:
            return source_id in extracted_output_ids

        def _render_exists(source_id: str) -> bool:
            return source_id in render_ids

        trained_rows = [
            {"source_id": str(row["source_id"]), "render_exists": bool(row.get("render_exists")), "trained": True}
            for row in source_rows()
            if str(row["source_id"]) not in test_source_ids and _is_trained(str(row["source_id"]))
        ]
        trained_ids = {row["source_id"] for row in trained_rows}

        input_root = Path(project_manager.active().input_path).resolve()
        untrained_rows: list[dict[str, Any]] = []
        seen_untrained: set[str] = set()
        for path in input_files(input_root):
            source_id = input_file_source_id(path)
            if source_id in test_source_ids or source_id in trained_ids or source_id in seen_untrained:
                continue
            seen_untrained.add(source_id)
            untrained_rows.append({
                "source_id": source_id, "render_exists": _render_exists(source_id), "trained": False,
            })

        return trained_rows + untrained_rows

    def _render_missing_thumbnails() -> int:
        """Save ``source_renders/<id>.png`` for every listed row that doesn't have one yet.

        Purely a decode-and-save of the original file -- no detection, no
        database writes -- so unlike ``prepare_source_renders`` (used by the
        Panel Setup / table-region-detect flow, which also resets that
        source's review state on every call) this never disturbs an
        already-reviewed or already-trained source. It only fills in the
        list's "geen render" placeholders, e.g. for images Inputselectie
        knows about that have never been run through anything yet.
        """
        input_root = Path(project_manager.active().input_path).resolve()
        render_root = workspace_root() / "source_renders"
        render_root.mkdir(parents=True, exist_ok=True)
        dicom_settings = getattr(loaded_config, "dicom", None)
        rendered = 0
        for row in _all_input_rows():
            if row.get("render_exists"):
                continue
            source_id = str(row["source_id"])
            original = find_input_file_by_source_id(input_root, source_id)
            if original is None:
                continue
            try:
                decoded = load_input(original, dicom_settings)
            except Exception:
                continue
            if cv2.imwrite(str(render_root / f"{source_id}.png"), decoded.image):
                rendered += 1
        return rendered

    @app.post("/test-pipeline/render-thumbnails")
    def test_pipeline_render_thumbnails():
        """Fill in missing thumbnails on the list without testing anything."""
        rendered = _render_missing_thumbnails()
        if rendered:
            flash(f"{rendered} thumbnail(s) gerenderd.", "success")
        else:
            flash("Geen ontbrekende thumbnails gevonden.", "info")
        return redirect(url_for("test_pipeline"))

    @app.get("/test-pipeline")
    def test_pipeline():
        """List every input image with its current proefpagina-retest status.

        A picker plus a status list and compact table/mapping counts for
        completed retests -- no upload form or inline datablok. Covers every
        image Inputselectie offers, not only ones the training pipeline
        already produced a datablok for (see ``_all_input_rows()``); each row
        is marked "Getraind" or "Nog niet getraind" so a retest with nothing
        to compare against is never mistaken for one that does. The actual
        comparison lives on ``test_pipeline_compare()``.
        """
        rerun_error = RERUN_ERROR_MESSAGES.get(str(request.args.get("rerun_error") or ""), "")

        # Scoped to action 61 (proefpagina reruns) specifically, and given a
        # generous limit: job_statuses() truncates to its N *most recently
        # created* jobs across the whole app before this callsite ever sees
        # them. "Geselecteerde opnieuw testen" can queue dozens of reruns in one go, and an
        # unscoped job_statuses(20) would push earlier ones straight out of
        # that window -- their row would then show "Testen" again even
        # though a rerun is genuinely still queued or just finished, since
        # neither has_output nor a job entry would be found for it.
        jobs = job_statuses(200, action_ids={"61"})
        extracted_output_ids = _extracted_output_ids()
        # One read of test_pipeline_sources.json for the whole list instead of
        # up to three re-reads (latest rerun / job id / reviewed flag) per row --
        # see test_pipeline_sources_snapshot()'s own docstring.
        sources_snapshot = test_pipeline_sources_snapshot(workspace_root())
        rows = []
        for row in _all_input_rows():
            source_id = str(row["source_id"])
            rerun_source_id = sources_snapshot["latest_rerun_by_origin"].get(source_id)
            status = "untested"
            compare_url = None
            running_job_id = None
            differing_count = 0
            table_summary = None
            processed_at_iso = ""
            processed_at_label = ""
            reviewed = False
            if rerun_source_id:
                has_output = rerun_source_id in extracted_output_ids
                job_id = sources_snapshot["jobs"].get(rerun_source_id)
                job = next((item for item in jobs if str(item.get("job_id") or "") == job_id), None)
                if has_output:
                    status = "tested"
                    compare_url = url_for("test_pipeline_compare", source_id=rerun_source_id)
                    # Same field-by-field rule the compare screen itself uses
                    # (STAP 7), computed here too so a deviation is visible
                    # straight from the list -- no need to open every "getest"
                    # row's compare screen just to find out which ones differ.
                    # Cached by file mtime (see _cached_differing_count()) --
                    # recomputing this from scratch for every "getest" row on
                    # every page view was the single biggest contributor to a
                    # real ~24s page load.
                    run_summary = _cached_table_summary(rerun_source_id)
                    table_summary = run_summary["table_summary"]
                    processed_at_iso = run_summary["processed_at_iso"]
                    processed_at_label = run_summary["processed_at_label"]
                    if row.get("trained"):
                        differing_count = _cached_differing_count(rerun_source_id, source_id)
                    reviewed = rerun_source_id in sources_snapshot["reviewed_ids"]
                elif job and str(job.get("status") or "") in RUNNING_JOB_STATUSES:
                    status = "running"
                    running_job_id = job_id
                elif job and str(job.get("status") or "") in FAILED_JOB_STATUSES:
                    status = "failed"
                # else: job aged out of job_statuses()'s window with no output --
                # treated as "untested" so "Testen" stays available rather than
                # getting stuck showing a stale state forever.

            rows.append({
                "source_id": source_id,
                "render_exists": bool(row.get("render_exists")),
                "trained": bool(row.get("trained")),
                "rerun_source_id": rerun_source_id,
                "status": status,
                "compare_url": compare_url,
                "running_job_id": running_job_id,
                "differing_count": differing_count,
                "table_summary": table_summary,
                "processed_at_iso": processed_at_iso,
                "processed_at_label": processed_at_label,
                "reviewed": reviewed,
            })

        needs_review_count = sum(
            1 for row in rows if row["status"] == "tested" and row["differing_count"] and not row["reviewed"]
        )

        # Poll /api/status for just these specific job ids and navigate back to
        # this same list exactly once, the moment none of them are still
        # pending/running -- never a blind setInterval/setTimeout reload loop,
        # which would hammer the server and the browser with full-page reloads
        # for as long as any run happens to be slow. See
        # test_reactive_pages_poll_json_without_full_page_reload (frontend
        # tests) for the same rule applied to the React clients; this legacy
        # Jinja page follows it by hand since it has no such test of its own.
        running_job_ids = [row["running_job_id"] for row in rows if row["running_job_id"]]

        return render_template(
            "test_pipeline.html", rows=rows, rerun_error=rerun_error, running_job_ids=running_job_ids,
            needs_review_count=needs_review_count,
        )

    @app.post("/test-pipeline/beoordeeld/<source_id>")
    def test_pipeline_mark_reviewed(source_id: str):
        """Toggle whether a proefpagina compare run needs no further review.

        Used when a "wijkt af" row turns out fine on inspection -- e.g. the
        retest found *more* values than the training data has, because the
        training data itself is incomplete rather than the retest being
        wrong. Marking it here lets the list (``test_pipeline()``) separate
        "nog te beoordelen" from "al bekeken, geen actie nodig" instead of
        flagging every deviation as outstanding forever. Called from both the
        compare screen (toggles the one run it's showing) and, via fetch with
        the same ``X-Test-Pipeline-Async`` convention the rerun routes use,
        without a full page reload.
        """
        reviewed = str(request.form.get("reviewed") or "") != "0"
        mark_test_pipeline_reviewed(workspace_root(), source_id, reviewed)
        if request.headers.get("X-Test-Pipeline-Async"):
            return {"ok": True, "reviewed": reviewed}
        return redirect(request.referrer or url_for("test_pipeline"))

    @app.post("/test-pipeline/opnieuw-testen/<source_id>")
    def test_pipeline_rerun(source_id: str):
        """Reprocess an already-assessed training-pipeline image through the proefpagina.

        Locates the original DICOM in the active project's input directory --
        the only place it still exists, since ``detection_sources`` only
        stores the rendered PNG -- and hands a byte-distinct copy to the same
        job as a fresh upload would (see ``test_pipeline_rerun.py`` for why
        the copy must differ from the original byte-for-byte: reprocessing
        byte-identical content would land on the training source's own
        source_id and silently overwrite its result). The resulting run is
        recorded with ``source_id`` as its origin and this job's id, so the
        proefpagina list can show live status and, once finished, link to the
        stage-by-stage comparison. See ``_start_rerun()`` for the mechanics,
        shared with the bulk "Geselecteerde opnieuw testen" route below.

        The list page's "Testen"/"Opnieuw proberen" buttons call this via
        ``fetch`` (marked by the ``X-Test-Pipeline-Async`` header) so a click
        only queues the job and updates that one row in place -- never a full
        page navigation -- letting the user queue several reruns back to back
        without waiting on each one. A plain form submission (no header,
        JS-disabled fallback) still gets the original redirect behaviour.
        """
        result = _start_rerun(source_id)
        if request.headers.get("X-Test-Pipeline-Async"):
            if result["error"]:
                return {
                    "ok": False,
                    "error": result["error"],
                    "message": RERUN_ERROR_MESSAGES.get(result["error"], ""),
                }, 400
            return {"ok": True, "job_id": result["job_id"], "rerun_source_id": result["rerun_source_id"]}
        if result["error"]:
            return redirect(url_for("test_pipeline", rerun_error=result["error"]))
        return redirect(url_for("test_pipeline"))

    @app.post("/test-pipeline/geselecteerd-opnieuw-testen")
    def test_pipeline_rerun_selected():
        """Queue selected images in bounded batches with one model session each."""
        requested_ids = list(dict.fromkeys(
            str(item).strip() for item in request.form.getlist("source_ids") if str(item).strip()
        ))
        if not requested_ids:
            flash("Geen afbeeldingen geselecteerd.", "info")
            return redirect(url_for("test_pipeline"))
        jobs = job_statuses(200, action_ids={"61"})  # see test_pipeline()'s comment on this call
        prepared: list[dict[str, Any]] = []
        for source_id in requested_ids:
            rerun_source_id = latest_rerun_of_source(workspace_root(), source_id)
            if rerun_source_id:
                has_output = safe_workspace_file(Path("extracted_output") / f"{rerun_source_id}.json").is_file()
                job_id = job_of_test_pipeline_source(workspace_root(), rerun_source_id)
                job = next((item for item in jobs if str(item.get("job_id") or "") == job_id), None)
                if not has_output and job and str(job.get("status") or "") in RUNNING_JOB_STATUSES:
                    continue
            item = _prepare_rerun(source_id)
            if item["error"] is None:
                prepared.append(item)
        if prepared:
            active_table_model = active_table_cell_model(workspace_root()) or {}
            for offset in range(0, len(prepared), 20):
                batch = prepared[offset:offset + 20]
                batch_id = uuid.uuid4().hex
                write_json_atomic(
                    workspace_root() / "test_pipeline_batches" / f"{batch_id}.json",
                    {"images": [
                        {"input_file": item["input_file"], "source_id": item["source_id"]}
                        for item in batch
                    ]},
                )
                job = enqueue_job("61", {
                    "table_model_id": "active" if active_table_model else "generic-ppstructure",
                    "mapping_profile_id": "", "input_file": f"__batch__:{batch_id}",
                })
                for item in batch:
                    record_test_pipeline_source(
                        workspace_root(), item["source_id"], origin_source_id=item["origin_source_id"],
                        job_id=str(job["job_id"]), input_file_path=item["input_file_path"],
                    )
            flash(f"{len(prepared)} geselecteerde afbeelding(en) worden in batches van maximaal 20 getest.", "success")
        else:
            flash("Geen van de geselecteerde afbeeldingen kon opnieuw getest worden (al bezig, of niet gevonden).", "info")
        return redirect(url_for("test_pipeline"))

    @app.get("/test-pipeline/vergelijk/<source_id>")
    def test_pipeline_compare(source_id: str):
        """The full pipeline, stage by stage, new (left) next to old (right).

        ``source_id`` is a proefpagina rerun; its origin (the training
        pipeline's own assessment of the same image) is looked up and both
        are loaded stage by stage with the exact same builders the
        single-source ``/output-review/...`` pages use (``routes_documents.py``),
        so a deviation is visible at the specific stage it first appears in --
        Tabelherkenning, Celdetectie, Rasterisering, welke kolommen/rijen naar
        Recognition gingen, Uitlezen, or only in the final Datablok -- instead
        of only at the end result.
        """
        origin_source_id = origin_of_test_pipeline_source(workspace_root(), source_id)
        if not origin_source_id:
            abort(404)

        root = workspace_root()

        def _stage(builder: Callable[..., dict[str, Any] | None], load_source_id: str) -> dict[str, Any] | None:
            return builder(
                load_source_id, workspace_root=root, safe_workspace_file=safe_workspace_file, database=database
            )

        # Stages 2-7 follow the app's own numbered workflow (PROCESS_STEPS in
        # webui.py), not an invented 1-4 summary. STAP 2.5 (_identification_
        # stage_data) is inserted between Tabelherkenning and Celdetectie: it
        # shows the OCR relations (value/label/context text) Pipeline B
        # produced for *table-structure* purposes -- i.e. deciding each
        # window's Links/Rechts side (see _window_sides_from_relations) --
        # never the per-cell OCR used for data extraction later on, which
        # stays on Celdetectie/Uitlezen. It exists so a window that stayed
        # "Onbekend" on Tabelherkenning can be diagnosed here: no relation
        # landed inside it, or its context text didn't match the left/right
        # vocabulary. Celdetectie (_cells_stage_data) shows Pipeline A's
        # loose, un-rasterized boxes exactly as detected; Rasterisering
        # (_rasterized_cells_stage_data) reshapes that same geometry to one
        # shared column raster (rasterize_table_columns()) and shows it as a
        # plain box overlay, not a text grid -- this stage is about the
        # reshaped cell *shape*, not which text ended up in which cell. This
        # compare screen only presents already-computed run results, it does
        # not change what the pipeline itself records. "Welke kolommen/rijen"
        # and "Uitlezen" both read from this run's own materialized samples
        # (no detector-internal geometry re-derivation); "mapping resultaten"
        # is the existing Datablok stage.
        new_tables, old_tables = _stage(_tables_stage_data, source_id), _stage(_tables_stage_data, origin_source_id)
        new_identification = _stage(_identification_stage_data, source_id)
        old_identification = _stage(_identification_stage_data, origin_source_id)
        new_cells, old_cells = _stage(_cells_stage_data, source_id), _stage(_cells_stage_data, origin_source_id)
        new_rasterized_cells = _stage(_rasterized_cells_stage_data, source_id)
        old_rasterized_cells = _stage(_rasterized_cells_stage_data, origin_source_id)
        new_mapping_scope = _stage(_mapping_scope_stage_data, source_id)
        old_mapping_scope = _stage(_mapping_scope_stage_data, origin_source_id)
        new_readout = _recognition_readout_stage_data(source_id, database=database)
        old_readout = _recognition_readout_stage_data(origin_source_id, database=database)
        new_datablok = _stage(_datablok_stage_data, source_id)
        old_datablok = _stage(_datablok_stage_data, origin_source_id)

        measurement_rows = _measurement_diff_rows(new_datablok, old_datablok)
        readout_rows = _readout_diff_rows(new_readout, old_readout)
        reviewed = is_test_pipeline_source_reviewed(root, source_id)

        return render_template(
            "test_pipeline_compare.html", source_id=source_id, origin_source_id=origin_source_id,
            reviewed=reviewed,
            new_tables=new_tables, old_tables=old_tables,
            new_identification=new_identification, old_identification=old_identification,
            new_cells=new_cells, old_cells=old_cells,
            new_rasterized_cells=new_rasterized_cells, old_rasterized_cells=old_rasterized_cells,
            new_mapping_scope=new_mapping_scope, old_mapping_scope=old_mapping_scope,
            new_readout=new_readout, old_readout=old_readout,
            readout_rows=readout_rows,
            new_datablok=new_datablok, old_datablok=old_datablok,
            measurement_rows=measurement_rows,
            differing_count=sum(1 for row in measurement_rows if row["differs"]),
        )
