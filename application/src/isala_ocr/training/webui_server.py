from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from flask import request

from . import webui as webui_module
from .comparison_review_queue_web import install_comparison_review_queue
from .job_cancellation import install_job_cancellation
from .recognition_ground_truth_web import install_recognition_ground_truth_review
from .recognition_model_factory import install_recognition_model_factory_metadata
from .json_store import read_json_object, write_json_atomic


def _read_json(path: Path) -> dict:
    return read_json_object(path)


def _write_json(path: Path, payload: dict) -> None:
    write_json_atomic(path, payload)


def _worker_is_live_for(worker: dict, job_id: str) -> bool:
    heartbeat = str(worker.get("heartbeat_at") or worker.get("started_at") or "")
    if not heartbeat or str(worker.get("current_job_id") or "") != job_id:
        return False
    try:
        parsed = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    except ValueError:
        return False
    return 0 <= age <= 15


def install_stale_job_reconciliation(app, workspace: str | Path) -> None:
    """Repair stale pending/running status records before v2 duplicate checks."""
    jobs_root = Path(workspace) / "webui" / "jobs"

    @app.before_request
    def reconcile_stale_v2_job_statuses():
        if request.method != "POST" or request.path != "/api/v2/jobs":
            return None
        body = request.get_json(silent=True) or {}
        action_id = str(body.get("action_id") or "").strip()
        if not action_id:
            return None

        worker = _read_json(jobs_root / "worker.json")
        status_root = jobs_root / "status"
        now = datetime.now(timezone.utc).isoformat()

        for status_path in status_root.glob("*.json"):
            payload = _read_json(status_path)
            if str(payload.get("action_id") or "") != action_id:
                continue
            status = str(payload.get("status") or "").strip().lower()
            if status not in {"pending", "running"}:
                continue

            job_id = str(payload.get("job_id") or status_path.stem)
            pending_path = jobs_root / "pending" / f"{job_id}.json"
            running_path = jobs_root / "running" / f"{job_id}.json"
            worker_owns_job = _worker_is_live_for(worker, job_id)

            if status == "pending":
                live = pending_path.is_file() or (running_path.is_file() and worker_owns_job)
            else:
                live = running_path.is_file() and worker_owns_job
            if live:
                continue

            payload.update({
                "status": "failed",
                "exit_code": 125,
                "finished_at": now,
                "updated_at": now,
                "progress_percent": 100,
                "progress_mode": "determinate",
                "progress_label": "Onderbroken taak automatisch hersteld",
                "recovered_stale_status": True,
            })
            _write_json(status_path, payload)

            source = running_path if running_path.is_file() else pending_path
            if source.is_file():
                failed_path = jobs_root / "failed" / source.name
                failed_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    source.replace(failed_path)
                except OSError:
                    pass
        return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", default="/training/workspace")
    p.add_argument("--models", default="/models")
    p.add_argument("--output", default="/output")
    p.add_argument("--project", default="/project")
    p.add_argument("--config", default="/app/config/app.yaml")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8088)
    a = p.parse_args()
    from waitress import serve

    # Recognition is a model-training concern. Repair the legacy workflow
    # metadata before Flask captures ACTIONS/PROCESS_STEPS into its routes.
    install_recognition_model_factory_metadata(webui_module)
    app = webui_module.create_web_app(
        a.workspace,
        models_root=a.models,
        output_root=a.output,
        project_root=a.project,
        config_path=a.config,
    )
    install_recognition_ground_truth_review(app, a.workspace)
    install_comparison_review_queue(app, a.workspace)
    install_job_cancellation(app, a.workspace)
    install_stale_job_reconciliation(app, a.workspace)
    serve(app, host=a.host, port=a.port, threads=8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
