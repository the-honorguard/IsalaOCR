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
import uuid
from pathlib import Path
from typing import Any, Callable

from flask import Flask, abort, flash, redirect, render_template, request, url_for

from .input_selection import input_file_source_id, input_files
from .projects import ProjectManager
from .routes_documents import (
    _cells_stage_data, _datablok_stage_data, _mapping_scope_stage_data, _measurement_diff_rows,
    _rasterized_cells_stage_data, _recognition_readout_stage_data, _tables_stage_data,
)
from .table_cell_training import active_table_cell_model
from .test_pipeline_rerun import duplicate_dicom_with_fresh_identity, find_input_file_by_source_id
from .test_pipeline_sources import (
    forget_test_pipeline_source, job_of_test_pipeline_source, latest_rerun_of_source,
    origin_of_test_pipeline_source, record_test_pipeline_source, test_pipeline_source_ids,
)

RERUN_ERROR_MESSAGES = {
    "not_found": "Het originele DICOM-bestand voor deze afbeelding is niet gevonden in de inputmap.",
    "invalid_path": "Ongeldig doelpad voor de rerun-kopie.",
    "copy_failed": "Kon geen rerun-kopie maken van het originele DICOM-bestand.",
}

RUNNING_JOB_STATUSES = {"pending", "running"}
FAILED_JOB_STATUSES = {"failed", "error"}


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
) -> None:
    def _start_rerun(source_id: str) -> dict[str, Any]:
        """Kick off a proefpagina rerun of ``source_id``.

        Returns ``{"error": None, "job_id": ..., "rerun_source_id": ...}`` on
        success, or ``{"error": <key of RERUN_ERROR_MESSAGES>, "job_id": None,
        "rerun_source_id": None}`` on failure. Shared by the single-row
        "Testen" route and the bulk "Alles testen" route so both apply the
        exact same rerun mechanics (see ``test_pipeline_rerun()``'s docstring
        for why the copy must be byte-distinct from the original). Only
        *queues* the job (``enqueue_job`` just writes a "pending" job file and
        returns immediately) -- the worker that actually picks it up and
        drives it to "running" runs out-of-process, so this call itself never
        blocks on that.

        The job is told exactly which file to process via its own
        ``options["input_file"]`` (a path relative to ``/input``, forwarded
        all the way to ``run-application-pipeline.ps1``'s ``-InputFile``,
        which resolves and passes it straight to the CLI instead of the
        project's whole input directory). Earlier this wrote the same target
        into the shared ``input_selection.json`` Inputselectie itself edits
        -- but the worker only reads that file once this job's container
        actually starts, which can be minutes after several reruns were
        queued back to back; a later "Testen" click's write would silently
        overwrite an earlier, still-queued job's target before it got read,
        so that job processed the wrong image and its own rerun never got an
        ``extracted_output``. Passing the file straight through the job's own
        options removes the shared mutable state entirely, so queuing several
        reruns in a row can no longer race.
        """
        input_root = Path(project_manager.active().input_path).resolve()
        original = find_input_file_by_source_id(input_root, source_id)
        if original is None:
            return {"error": "not_found", "job_id": None, "rerun_source_id": None}
        try:
            destination = _test_upload_destination(project_manager, original.name)
        except ValueError:
            return {"error": "invalid_path", "job_id": None, "rerun_source_id": None}
        try:
            duplicate_dicom_with_fresh_identity(original, destination)
        except (OSError, ValueError, RuntimeError):
            return {"error": "copy_failed", "job_id": None, "rerun_source_id": None}
        relative_key = destination.relative_to(Path("/input").resolve()).as_posix()

        new_source_id = hashlib.sha256(destination.read_bytes()).hexdigest()[:24]
        active_table_model = active_table_cell_model(workspace_root()) or {}
        job = enqueue_job("61", {
            "table_model_id": "active" if active_table_model else "generic-ppstructure",
            "mapping_profile_id": "",
            "input_file": relative_key,
        })
        record_test_pipeline_source(
            workspace_root(), new_source_id, origin_source_id=source_id, job_id=str(job["job_id"]),
        )
        return {"error": None, "job_id": str(job["job_id"]), "rerun_source_id": new_source_id}

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

        def _is_trained(source_id: str) -> bool:
            return safe_workspace_file(Path("extracted_output") / f"{source_id}.json").is_file()

        def _render_exists(source_id: str) -> bool:
            return (workspace_root() / "source_renders" / f"{source_id}.png").is_file()

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

    @app.get("/test-pipeline")
    def test_pipeline():
        """List every input image with its current proefpagina-retest status.

        Deliberately just this: a picker plus a status list, nothing else --
        no upload form, no model chips, no inline datablok. Covers every
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
        # them. "Alles testen" can queue dozens of reruns in one go, and an
        # unscoped job_statuses(20) would push earlier ones straight out of
        # that window -- their row would then show "Testen" again even
        # though a rerun is genuinely still queued or just finished, since
        # neither has_output nor a job entry would be found for it.
        jobs = job_statuses(200, action_ids={"61"})
        rows = []
        for row in _all_input_rows():
            source_id = str(row["source_id"])
            rerun_source_id = latest_rerun_of_source(workspace_root(), source_id)
            status = "untested"
            compare_url = None
            running_job_id = None
            differing_count = 0
            if rerun_source_id:
                has_output = safe_workspace_file(Path("extracted_output") / f"{rerun_source_id}.json").is_file()
                job_id = job_of_test_pipeline_source(workspace_root(), rerun_source_id)
                job = next((item for item in jobs if str(item.get("job_id") or "") == job_id), None)
                if has_output:
                    status = "tested"
                    compare_url = url_for("test_pipeline_compare", source_id=rerun_source_id)
                    # Same field-by-field rule the compare screen itself uses
                    # (STAP 7), computed here too so a deviation is visible
                    # straight from the list -- no need to open every "getest"
                    # row's compare screen just to find out which ones differ.
                    new_datablok = _datablok_stage_data(
                        rerun_source_id, workspace_root=workspace_root(),
                        safe_workspace_file=safe_workspace_file, database=database,
                    )
                    old_datablok = _datablok_stage_data(
                        source_id, workspace_root=workspace_root(),
                        safe_workspace_file=safe_workspace_file, database=database,
                    )
                    diff_rows = _measurement_diff_rows(new_datablok, old_datablok)
                    differing_count = sum(1 for item in diff_rows if item["differs"])
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
            })

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
        )

    @app.post("/test-pipeline/verwijderen/<source_id>")
    def test_pipeline_forget(source_id: str):
        """Delete one proefpagina run's tracking entry and output artifacts.

        Scoped deliberately to the proefpagina's own disposable output (see
        ``forget_test_pipeline_source()``'s docstring) -- never the shared
        samples database other training-review pages depend on. Used from the
        proefpagina list to reset a "getest"/"mislukt" row back to untested.
        """
        forget_test_pipeline_source(workspace_root(), source_id)
        return redirect(url_for("test_pipeline"))

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
        shared with the bulk "Alles testen" route below.

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

    @app.post("/test-pipeline/alles-testen")
    def test_pipeline_rerun_all():
        """Kick off a proefpagina rerun for every image on the list, trained or not.

        "Alles" is literal: every listed image gets a fresh rerun against the
        currently active models, including ones already "getest" and ones
        never trained at all -- this is a bulk refresh, not just a "fill in
        the untested ones" action. Only a row already "Bezig..." (a rerun
        genuinely in flight, per the same check the list itself uses) is
        skipped, so a click here never queues a second job on top of one
        still running for the same image.
        """
        jobs = job_statuses(200, action_ids={"61"})  # see test_pipeline()'s comment on this call
        started = 0
        for row in _all_input_rows():
            source_id = str(row["source_id"])
            rerun_source_id = latest_rerun_of_source(workspace_root(), source_id)
            if rerun_source_id:
                has_output = safe_workspace_file(Path("extracted_output") / f"{rerun_source_id}.json").is_file()
                job_id = job_of_test_pipeline_source(workspace_root(), rerun_source_id)
                job = next((item for item in jobs if str(item.get("job_id") or "") == job_id), None)
                if not has_output and job and str(job.get("status") or "") in RUNNING_JOB_STATUSES:
                    continue
            if _start_rerun(source_id)["error"] is None:
                started += 1
        if started:
            flash(f"{started} afbeelding(en) worden opnieuw getest.", "success")
        else:
            flash("Geen afbeeldingen om te testen (alles is al bezig).", "info")
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
        # webui.py), not an invented 1-4 summary. Celdetectie
        # (_cells_stage_data) shows Pipeline A's loose, un-rasterized boxes
        # exactly as detected; Rasterisering (_rasterized_cells_stage_data)
        # reshapes that same geometry to one shared column raster
        # (rasterize_table_columns()) and shows it as a plain box overlay, not
        # a text grid -- this stage is about the reshaped cell *shape*, not
        # which text ended up in which cell. This compare screen only
        # presents already-computed run results, it does not change what the
        # pipeline itself records. "Welke kolommen/rijen" and "Uitlezen" both
        # read from this run's own materialized samples (no detector-internal
        # geometry re-derivation); "mapping resultaten" is the existing
        # Datablok stage.
        new_tables, old_tables = _stage(_tables_stage_data, source_id), _stage(_tables_stage_data, origin_source_id)
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

        return render_template(
            "test_pipeline_compare.html", source_id=source_id, origin_source_id=origin_source_id,
            new_tables=new_tables, old_tables=old_tables,
            new_cells=new_cells, old_cells=old_cells,
            new_rasterized_cells=new_rasterized_cells, old_rasterized_cells=old_rasterized_cells,
            new_mapping_scope=new_mapping_scope, old_mapping_scope=old_mapping_scope,
            new_readout=new_readout, old_readout=old_readout,
            new_datablok=new_datablok, old_datablok=old_datablok,
            measurement_rows=measurement_rows,
            differing_count=sum(1 for row in measurement_rows if row["differs"]),
        )
