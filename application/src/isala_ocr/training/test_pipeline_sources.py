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


def record_test_pipeline_source(workspace: str | Path, source_id: str) -> None:
    """Mark ``source_id`` as having come from a proefpagina upload.

    Order is preserved (oldest first, most recent last) -- a re-upload of the
    same source moves it to the end -- so ``most_recent_test_pipeline_source()``
    can tell which run to fall back to when the proefpagina is opened without
    a ``source_id`` in the URL (see that function's docstring for why that
    matters).
    """
    source_id = str(source_id or "").strip()
    if not source_id:
        return
    path = _marker_path(workspace)
    payload = read_json_object(path, {})
    ids = [str(item) for item in (payload.get("source_ids") or []) if str(item).strip() and str(item) != source_id]
    ids.append(source_id)
    write_json_atomic(path, {"source_ids": ids})


def test_pipeline_source_ids(workspace: str | Path) -> set[str]:
    """Return every source_id previously recorded as a proefpagina upload."""
    payload = read_json_object(_marker_path(workspace), {})
    return {str(item) for item in (payload.get("source_ids") or []) if str(item).strip()}


def most_recent_test_pipeline_source(workspace: str | Path) -> str | None:
    """Return the most recently uploaded proefpagina source_id, if any.

    The proefpagina's "which run am I looking at" state lives entirely in the
    ``?source_id=`` URL query string, with nothing persisted server-side. That
    is fine while a job is running and redirecting through that URL, but the
    moment the user navigates away by any other route (the sidebar link,
    another page's "back" link, browser history) and returns to a bare
    ``/test-pipeline``, that query string is gone and the whole page resets
    to "klaar voor test" -- phases, JSON output, all of it -- even though the
    run's data is still sitting on disk. This lets the route fall back to
    "the last thing I actually tested" instead of a blank slate whenever the
    URL doesn't say otherwise.
    """
    payload = read_json_object(_marker_path(workspace), {})
    ids = [str(item) for item in (payload.get("source_ids") or []) if str(item).strip()]
    return ids[-1] if ids else None


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
    write_json_atomic(path, {"source_ids": ids})
    for pattern in _PER_SOURCE_FILES:
        target = root / pattern.format(id=source_id)
        target.unlink(missing_ok=True)
    for pattern in _PER_SOURCE_DIRS:
        target = root / pattern.format(id=source_id)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
