"""/test-pipeline route, split out of webui.create_web_app.

A small end-to-end proving ground for a future one-click pipeline,
deliberately kept separate from the training workflow (see its own
docstring below). Not referenced by any test's source-text-literal
check, unlike several other route groups in this refactor.

``workspace_root``, ``registry_state``, ``project_manager``,
``input_selection_path``, ``safe_workspace_file``, ``job_statuses``,
``database``, ``enqueue_job`` and ``utcnow`` are all reused by other
route groups in webui.py and are passed in explicitly.
``active_table_cell_model``, ``table_cell_training_state``,
``selection_payload`` and ``read_json`` are pure functions imported
directly from their own modules (not from webui.py).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable

from flask import Flask, render_template, request

from .input_selection import selection_payload
from .json_store import read_json
from .projects import ProjectManager
from .table_cell_training import active_table_cell_model, table_cell_training_state


def register_test_pipeline_routes(
    app: Flask,
    *,
    workspace_root: Callable[[], Path],
    registry_state: Callable[[], tuple[list[dict[str, Any]], dict[str, Any] | None]],
    project_manager: ProjectManager,
    input_selection_path: Callable[[], Path],
    safe_workspace_file: Callable[[str | Path], Path],
    job_statuses: Callable[..., list[dict[str, Any]]],
    database: Any,
    enqueue_job: Callable[..., dict[str, Any]],
    utcnow: Callable[[], str],
) -> None:
    @app.route("/test-pipeline", methods=["GET", "POST"])
    def test_pipeline():
        """Small end-to-end proving ground for a future one-click pipeline.

        Keep this route deliberately separate from the training workflow: an
        uploaded image is stored in the active project's configured input
        directory and only that image is selected for the first worker step.
        Later orchestration can extend the same page without changing the
        existing review/training contracts.
        """
        allowed_extensions = {".dcm"}
        source_id = str(request.args.get("source_id") or "").strip()[:80]
        job_id = str(request.args.get("job_id") or "").strip()[:80]
        error = ""
        uploaded_name = ""
        active_table_model = active_table_cell_model(workspace_root()) or {}
        active_table_model_id = str(active_table_model.get("model_id") or "generic-ppstructure")
        active_table_model_name = str(
            active_table_model.get("model_name") or "Generieke PP-Structure baseline"
        )
        _, active_recognition_model = registry_state()
        table_model_state = table_cell_training_state(workspace_root()) or {}
        latest_table_dataset = table_model_state.get("dataset") or {}

        if request.method == "POST":
            upload = request.files.get("image")
            original_name = str(upload.filename or "").strip() if upload else ""
            suffix = Path(original_name).suffix.lower()
            if request.content_length and request.content_length > 25 * 1024 * 1024:
                error = "De upload is te groot; gebruik maximaal 25 MB per afbeelding."
            elif upload is None or not original_name:
                error = "Kies eerst een DICOM-bestand."
            elif suffix not in allowed_extensions:
                error = "Gebruik een DICOM-bestand met de extensie .dcm."
            else:
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_name).name).strip("._")
                safe_name = (safe_name or "upload")[:120]
                if Path(safe_name).suffix.lower() not in allowed_extensions:
                    error = "De bestandsnaam bevat geen ondersteunde afbeeldings-extensie."
                else:
                    try:
                        input_root = Path(project_manager.active().input_path).resolve()
                        allowed_root = Path("/input").resolve()
                        if allowed_root != input_root and allowed_root not in input_root.parents:
                            raise ValueError("Het actieve project-inputpad valt buiten /input.")
                        input_root.mkdir(parents=True, exist_ok=True)
                        stored_name = f"test_{uuid.uuid4().hex[:12]}_{safe_name}"
                        destination = (input_root / stored_name).resolve()
                        if input_root not in destination.parents:
                            raise ValueError("Ongeldig uploadpad.")
                        upload.save(destination)
                        relative_key = destination.relative_to(allowed_root).as_posix()
                        file_bytes = destination.read_bytes()
                        source_id = hashlib.sha256(file_bytes).hexdigest()[:24]
                        input_selection_path().parent.mkdir(parents=True, exist_ok=True)
                        payload = selection_payload({relative_key}, reason="test-pipeline-upload")
                        payload["updated_at"] = utcnow()
                        input_selection_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
                        job = enqueue_job("60", {
                            "table_model_id": "active" if active_table_model else "generic-ppstructure",
                            "mapping_profile_id": str(request.form.get("mapping_profile_id") or "").strip(),
                        })
                        job_id = str(job["job_id"])
                        uploaded_name = safe_name
                    except (OSError, ValueError) as exc:
                        error = f"Upload kon niet worden klaargezet: {exc}"

        output = None
        if source_id:
            output_path = safe_workspace_file(Path("extracted_output") / f"{source_id}.json")
            if output_path.is_file():
                output = read_json(output_path, None)
        jobs = job_statuses(20)
        current_job = next((item for item in jobs if str(item.get("job_id") or "") == job_id), None)
        mapping_profiles = database.list_mapping_profiles()
        if error:
            return render_template(
                "test_pipeline.html", source_id=source_id, job_id=job_id,
                current_job=current_job, output=output, error=error,
                active_table_model_id=active_table_model_id, active_table_model_name=active_table_model_name,
                active_table_model=active_table_model,
                active_recognition_model=active_recognition_model or {},
                latest_table_dataset=latest_table_dataset,
                mapping_profiles=mapping_profiles,
            ), 400
        return render_template(
            "test_pipeline.html", source_id=source_id, job_id=job_id,
            current_job=current_job, output=output, uploaded_name=uploaded_name,
            active_table_model_id=active_table_model_id, active_table_model_name=active_table_model_name,
            active_table_model=active_table_model,
            active_recognition_model=active_recognition_model or {},
            latest_table_dataset=latest_table_dataset,
            mapping_profiles=mapping_profiles,
        )
