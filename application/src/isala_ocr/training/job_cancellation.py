from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, flash, redirect, request

from .json_store import read_json_object, write_json_atomic

_JOB_ID = re.compile(r"^job-[A-Za-z0-9._:-]+$")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json_atomic(path, payload)


def _read_json(path: Path) -> dict[str, Any] | None:
    return read_json_object(path) or None


def install_job_cancellation(app: Flask, workspace: str | Path) -> None:
    """Install host-worker mediated cancellation for WebUI jobs.

    The Flask app runs in Docker and never kills a Windows process directly.
    Active jobs receive a marker consumed by webui-worker.ps1. Cancelled job
    records are stored in the existing failed bucket while retaining the
    explicit ``cancelled`` status, so legacy retry/delete cleanup keeps working.
    """

    jobs_root = Path(workspace) / "webui" / "jobs"
    (jobs_root / "cancel").mkdir(parents=True, exist_ok=True)

    @app.post("/jobs/<job_id>/cancel")
    def cancel_job(job_id: str):
        if not _JOB_ID.fullmatch(job_id):
            abort(404)

        status_path = jobs_root / "status" / f"{job_id}.json"
        payload = _read_json(status_path)
        if payload is None:
            for folder in ("pending", "running", "completed", "failed"):
                payload = _read_json(jobs_root / folder / f"{job_id}.json")
                if payload is not None:
                    break
        if payload is None:
            abort(404)

        status = str(payload.get("status") or "").strip().lower()
        now = _utcnow()

        if status == "pending":
            pending_path = jobs_root / "pending" / f"{job_id}.json"
            cancelled_path = jobs_root / "failed" / f"{job_id}.json"
            # The worker may claim the job between the status read and this move.
            # If so, fall through to the running cancellation-marker path.
            if pending_path.exists():
                payload.update({
                    "status": "cancelled",
                    "exit_code": 130,
                    "finished_at": now,
                    "updated_at": now,
                    "progress_percent": 100,
                    "progress_mode": "determinate",
                    "progress_label": "Geannuleerd vóór start",
                    "cancellation_requested_at": now,
                })
                _write_json(status_path, payload)
                _write_json(cancelled_path, payload)
                try:
                    pending_path.unlink(missing_ok=True)
                except OSError:
                    pass
                flash(f"Taak geannuleerd: {job_id}", "success")
                return redirect(request.referrer or "/jobs/manage")
            status = "running"

        if status == "running":
            marker = {"job_id": job_id, "requested_at": now, "requested_via": "webui"}
            _write_json(jobs_root / "cancel" / f"{job_id}.json", marker)
            payload["cancellation_requested_at"] = now
            payload["updated_at"] = now
            payload["progress_label"] = "Annulering aangevraagd…"
            _write_json(status_path, payload)
            flash(f"Annulering aangevraagd voor {job_id}.", "success")
            return redirect(request.referrer or "/jobs/manage")

        if status == "cancelled":
            flash("Deze taak is al geannuleerd.", "success")
            return redirect(request.referrer or "/jobs/manage")

        flash("Alleen taken in de wachtrij of actieve taken kunnen worden geannuleerd.", "error")
        return redirect(request.referrer or "/jobs/manage")
