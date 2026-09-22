"""Track which sources came from the proefpagina, so training-pipeline review
pages (Application output / value-review) can exclude them.

The proefpagina (``/test-pipeline``) deliberately reuses the active project's
real workspace, database and active models -- that is the point, it proves
the real pipeline end to end. But that means a proefpagina run's samples land
in the exact same ``samples`` table rows that the training workflow's own
"Application output beoordelen" step reads, with nothing distinguishing a
one-off test upload from real training input. This is a small, file-based
marker (matching ``input_selection.py``'s style) recording which source_ids
came from the proefpagina, so those review pages can filter them back out
without a database schema migration.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .json_store import read_json_object, write_json_atomic
from .projects import resolve_project_workspace

MARKER_NAME = "test_pipeline_sources.json"

# Per-source artifacts a proefpagina run writes, mirrored here so "delete"
# actually frees the clutter instead of just hiding the row -- everything
# these run(s) touch under the active project's workspace, keyed by whether
# it is a single file or a whole per-source directory. Deliberately does not
# touch samples.sqlite3 (detection_sources/detected_blocks/field_mappings
# etc.): those rows are already excluded from every training-review query
# (see webui.py's value_review_counts()/value_source_rows() and
# _process_step_state_value_review()), so leaving them is inert, and removing
# them would need the same care the training workflow's own delete paths
# take -- out of scope for a proefpagina "forget this test" action.
_PER_SOURCE_FILES = ("extracted_output/{id}.json", "generic_detections/{id}.json", "localization_detections/{id}.json", "source_renders/{id}.png")
_PER_SOURCE_DIRS = ("detected_blocks/{id}", "detection_candidate_crops/{id}", "crops/original/{id}", "header_crops/{id}")


def _marker_path(workspace: str | Path) -> Path:
    return resolve_project_workspace(workspace) / MARKER_NAME


def record_test_pipeline_source(
    workspace: str | Path, source_id: str, *, origin_source_id: str | None = None, job_id: str | None = None
) -> None:
    """Mark ``source_id`` as having come from a proefpagina upload.

    Order is preserved (oldest first, most recent last) -- a re-upload of the
    same source moves it to the end -- so ``latest_rerun_of_source()`` can
    tell which rerun is the current one for a given origin when an image was
    retested more than once.

    ``origin_source_id``, when given, records that this run started from an
    already-processed training-pipeline image (see
    ``test_pipeline_rerun.py``) rather than a fresh upload, so the proefpagina
    can offer a "vergelijk met trainingspipeline" link back to that source's
    own, separately computed output.

    ``job_id``, when given, records which worker job is processing this
    source, so the "Beoordeelde afbeeldingen" list on the proefpagina can show
    a live status per image (``job_of_test_pipeline_source``) instead of only
    knowing about the single run named in the current page's URL.
    """
    source_id = str(source_id or "").strip()
    if not source_id:
        return
    path = _marker_path(workspace)
    payload = read_json_object(path, {})
    ids = [str(item) for item in (payload.get("source_ids") or []) if str(item).strip() and str(item) != source_id]
    ids.append(source_id)
    origins = {
        str(key): str(value) for key, value in (payload.get("origins") or {}).items()
        if str(key).strip() and str(value).strip()
    }
    if origin_source_id and str(origin_source_id).strip():
        origins[source_id] = str(origin_source_id).strip()
    jobs = {
        str(key): str(value) for key, value in (payload.get("jobs") or {}).items()
        if str(key).strip() and str(value).strip()
    }
    if job_id and str(job_id).strip():
        jobs[source_id] = str(job_id).strip()
    write_json_atomic(path, {"source_ids": ids, "origins": origins, "jobs": jobs})


def test_pipeline_source_ids(workspace: str | Path) -> set[str]:
    """Return every source_id previously recorded as a proefpagina upload."""
    payload = read_json_object(_marker_path(workspace), {})
    return {str(item) for item in (payload.get("source_ids") or []) if str(item).strip()}


def origin_of_test_pipeline_source(workspace: str | Path, source_id: str) -> str | None:
    """Return the training-pipeline source_id ``source_id`` was rerun from, if any.

    Only set for runs started via "Opnieuw testen" on an already-used image
    (``test_pipeline_rerun.py``); a plain DICOM upload has no origin.

    Deliberately not named ``test_pipeline_source_origin``: this module's
    filename already matches pytest's default ``test_*.py`` collection glob
    (see ``test_pipeline_source_ids`` below, a pre-existing instance of the
    same issue), and a *function* additionally starting with ``test_`` gets
    collected and run as a test itself, erroring on the required arguments
    pytest can't supply.
    """
    source_id = str(source_id or "").strip()
    if not source_id:
        return None
    payload = read_json_object(_marker_path(workspace), {})
    origins = payload.get("origins") or {}
    origin = str(origins.get(source_id) or "").strip()
    return origin or None


def latest_rerun_of_source(workspace: str | Path, origin_source_id: str) -> str | None:
    """Return the most recent proefpagina rerun of ``origin_source_id``, if any.

    The reverse of ``origin_of_test_pipeline_source``: given a training-pipeline
    source, find the proefpagina run it was last retested as, so the
    "Beoordeelde afbeeldingen" list can show that image's current test status
    (untested / bezig / getest) and link straight to its compare view.
    """
    origin_source_id = str(origin_source_id or "").strip()
    if not origin_source_id:
        return None
    payload = read_json_object(_marker_path(workspace), {})
    ids = [str(item) for item in (payload.get("source_ids") or []) if str(item).strip()]
    origins = payload.get("origins") or {}
    for candidate in reversed(ids):
        if str(origins.get(candidate) or "") == origin_source_id:
            return candidate
    return None


def job_of_test_pipeline_source(workspace: str | Path, source_id: str) -> str | None:
    """Return the worker job_id last recorded for ``source_id``, if any."""
    source_id = str(source_id or "").strip()
    if not source_id:
        return None
    payload = read_json_object(_marker_path(workspace), {})
    jobs = payload.get("jobs") or {}
    job_id = str(jobs.get(source_id) or "").strip()
    return job_id or None


def forget_test_pipeline_source(workspace: str | Path, source_id: str) -> None:
    """Remove ``source_id`` from tracking and delete its proefpagina output.

    Untracking alone would just hide the row from "Eerdere proefpagina-runs"
    while leaving its extracted_output/generic_detections/localization_detections
    JSON and renders/crops sitting in the project workspace forever -- these
    are disposable, one-off test artifacts, not training data, so "verwijderen"
    here means actually freeing that clutter, not just delisting it.
    """
    source_id = str(source_id or "").strip()
    if not source_id:
        return
    root = resolve_project_workspace(workspace)
    path = _marker_path(workspace)
    payload = read_json_object(path, {})
    ids = [str(item) for item in (payload.get("source_ids") or []) if str(item).strip() and str(item) != source_id]
    origins = {
        str(key): str(value) for key, value in (payload.get("origins") or {}).items()
        if str(key).strip() and str(value).strip() and str(key) != source_id
    }
    jobs = {
        str(key): str(value) for key, value in (payload.get("jobs") or {}).items()
        if str(key).strip() and str(value).strip() and str(key) != source_id
    }
    write_json_atomic(path, {"source_ids": ids, "origins": origins, "jobs": jobs})
    for pattern in _PER_SOURCE_FILES:
        target = root / pattern.format(id=source_id)
        target.unlink(missing_ok=True)
    for pattern in _PER_SOURCE_DIRS:
        target = root / pattern.format(id=source_id)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
