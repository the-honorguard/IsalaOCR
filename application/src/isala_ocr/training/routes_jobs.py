"""Job-queue management routes, split out of webui.create_web_app.

Covers the filesystem job queue's web surface: the management page,
delete/clear/retry, manual job creation, the recognition-comparison
shortcut, and the two read-only /api/jobs/<job_id> endpoints the
activity dock polls.

``job_statuses``, ``worker_state``, ``enqueue_job``,
``current_recognition_gate`` and ``jobs_root`` stay in webui.py (each
is used by other route groups there too) and are passed in
explicitly, along with the ``ACTIONS`` registry, the active
``project_manager`` and the ``_utcnow`` timestamp helper.

``_read_log_text`` and ``re_job_id`` move here because every caller of
either lives in this route group; keeping their definitions in
webui.py would have meant importing back from webui.py into this
module while webui.py itself is still importing this module - a
circular import. No test imports either helper by name directly.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

from .projects import DEFAULT_PROJECT_ID, ProjectManager


def _read_log_text(path: Path) -> str:
    """Read PowerShell/cmd output without showing an apparently blank NUL-filled log."""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if not raw:
        return ""
    encodings: list[str]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ["utf-16", "utf-8-sig"]
    elif raw.count(b"\x00") > max(2, len(raw) // 8):
        encodings = ["utf-16-le", "utf-16-be", "utf-8-sig"]
    else:
        encodings = ["utf-8-sig", "cp1252"]
    for encoding in encodings:
        try:
            return raw.decode(encoding).replace("\x00", "")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").replace("\x00", "")


def re_job_id(value: str) -> bool:
    return value.startswith("job-") and all(c.isalnum() or c in "-_" for c in value)


def register_job_routes(
    app: Flask,
    *,
    jobs_root: Path,
    job_statuses: Callable[..., list[dict[str, Any]]],
    cached_job_payload: Callable[..., dict[str, Any] | None],
    worker_state: Callable[[], dict[str, Any]],
    enqueue_job: Callable[..., dict[str, Any]],
    current_recognition_gate: Callable[[], dict[str, Any]],
    project_manager: ProjectManager,
    actions: dict[str, str],
    utcnow: Callable[[], str],
) -> None:
    def _job_paths(job_id: str) -> list[Path]:
        return [
            jobs_root / folder / f"{job_id}.json"
            for folder in ("pending", "running", "completed", "failed", "status")
        ] + [
            jobs_root / "logs" / f"{job_id}.worker.log",
            jobs_root / "logs" / f"{job_id}.log",
            jobs_root / "logs" / f"{job_id}.log.err",
        ]

    def _lookup_job(job_id: str) -> dict[str, Any] | None:
        """Look up one job by ID directly instead of scanning the whole queue.

        /api/jobs/<job_id> and /api/jobs/<job_id>/log are what the activity
        dock polls every ~2 seconds while any job is running; calling
        job_statuses(1000) - a full glob-and-parse pass over every job the
        queue has ever seen - just to find one job by ID meant every poll
        cycle paid for the entire job history, twice. Mirrors job_statuses()'s
        own precedence (status/ is canonical, then the legacy per-state
        folders) and its active-project filter.
        """
        payload = cached_job_payload(jobs_root / "status" / f"{job_id}.json")
        if payload is None:
            for folder, fallback_status in (
                ("pending", "pending"), ("running", "running"),
                ("completed", "completed"), ("failed", "failed"),
            ):
                payload = cached_job_payload(jobs_root / folder / f"{job_id}.json", fallback_status)
                if payload is not None:
                    break
        if payload is None:
            return None
        if str(payload.get("project_id") or DEFAULT_PROJECT_ID) != project_manager.active_project_id():
            return None
        return payload

    @app.get("/jobs/manage")
    def manage_jobs():
        status_filter=str(request.args.get("status", "all")).strip().lower()
        all_items=job_statuses(1000)
        counts_by_status={key:sum(1 for item in all_items if str(item.get("status")) == key)
                          for key in ("pending", "running", "completed", "failed")}
        items=all_items
        if status_filter in {"pending", "running", "completed", "failed"}:
            items=[item for item in items if str(item.get("status")) == status_filter]
        return render_template("jobs.html", jobs=items, queue_counts=counts_by_status,
                               status_filter=status_filter, worker=worker_state())

    @app.post("/jobs/<job_id>/delete")
    def delete_job(job_id: str):
        if not re_job_id(job_id): abort(404)
        item=_lookup_job(job_id)
        if item is None: abort(404)
        if str(item.get("status")) == "running":
            flash("Een actieve taak kan niet worden verwijderd. Wacht tot deze klaar is.", "error")
            return redirect(url_for("manage_jobs"))
        for path in _job_paths(job_id):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        flash(f"Taak verwijderd: {job_id}", "success")
        return redirect(url_for("manage_jobs"))

    @app.post("/jobs/clear")
    def clear_jobs():
        target=str(request.form.get("status", "")).strip().lower()
        if target not in {"pending", "completed", "failed"}: abort(400)
        removed=0
        for item in job_statuses(1000):
            if str(item.get("status")) != target: continue
            job_id=str(item.get("job_id") or "")
            if not re_job_id(job_id): continue
            for path in _job_paths(job_id):
                try: path.unlink(missing_ok=True)
                except OSError: pass
            removed += 1
        flash(f"{removed} {target}-taak/taken verwijderd.", "success")
        return redirect(url_for("manage_jobs"))

    @app.post("/jobs/<job_id>/retry")
    def retry_job(job_id: str):
        if not re_job_id(job_id): abort(404)
        old=_lookup_job(job_id)
        if old is None: abort(404)
        if str(old.get("status")) == "running": abort(409)
        action_id=str(old.get("action_id") or "")
        options=old.get("options") if isinstance(old.get("options"), dict) else {}
        job_type=str(old.get("job_type") or "")
        if job_type == "artifact_delete":
            new_job_id=f"job-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
            payload={"job_id":new_job_id,"job_type":"artifact_delete","action_id":"",
                     "action_name":str(old.get("action_name") or "Artifact verwijderen"),
                     "project_id":str(old.get("project_id") or project_manager.active_project_id()),
                     "project_name":str(old.get("project_name") or project_manager.active().name),
                     "options":options,"status":"pending","progress_percent":0,"progress_mode":"indeterminate",
                     "progress_label":"Verwijderen in wachtrij","created_at":utcnow(),"updated_at":utcnow(),
                     "retried_from":job_id}
        else:
            if action_id not in actions: abort(400)
            if action_id in {"24", "25", "26", "27", "28"} and not current_recognition_gate().get("ready"):
                abort(423, description="Recognition is locked until approved Recognition-GT samples are available")
            new_job_id=f"job-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
            payload={"job_id":new_job_id,"action_id":action_id,"action_name":actions[action_id],
                     "project_id":str(old.get("project_id") or project_manager.active_project_id()),
                     "project_name":str(old.get("project_name") or project_manager.active().name),
                     "options":options,"status":"pending","progress_percent":0,"progress_mode":"indeterminate",
                     "progress_label":"In wachtrij","created_at":utcnow(),"updated_at":utcnow(),
                     "retried_from":job_id}
        temp=jobs_root/"pending"/(new_job_id+".json.tmp")
        final=jobs_root/"pending"/(new_job_id+".json")
        temp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8"); temp.replace(final)
        (jobs_root/"status"/(new_job_id+".json")).write_text(
            json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
        flash(f"Taak opnieuw in wachtrij geplaatst: {actions[action_id]}", "success")
        return redirect(url_for("manage_jobs", job_id=new_job_id))

    @app.post("/jobs/compare-all")
    def create_compare_jobs():
        if not current_recognition_gate().get("ready"):
            abort(423, description="Recognition gate is closed until approved Recognition-GT samples are available")
        payload = enqueue_job("27")
        flash("Recognition-evaluatie en modelvergelijking ingepland.", "success")
        destination = request.referrer or url_for("process_step", step_key="recognition-evaluate")
        separator = "&" if "?" in destination else "?"
        return redirect(f"{destination}{separator}job_id={payload['job_id']}")

    @app.post("/jobs")
    def create_job():
        action_id=str(request.form.get("action_id","")).strip()
        if action_id not in actions:
            abort(400)
        # Recognition remains a hard server-side boundary. Hiding buttons is
        # not sufficient because queued/replayed HTTP requests must not start
        # recognition work without approved Recognition-GT samples.
        if action_id in {"24", "25", "26", "27", "28"} and not current_recognition_gate().get("ready"):
            abort(423, description="Recognition is locked until approved Recognition-GT samples are available")
        options={}
        if action_id == "2":
            table_model_id = str(request.form.get("table_model_id") or "").strip()
            if table_model_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", table_model_id):
                abort(400)
            if table_model_id:
                options["table_model_id"] = table_model_id
        if action_id in {"2", "20", "21", "22"}:
            source_id=str(request.form.get("source_id","")).strip()
            if source_id:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", source_id):
                    abort(400)
                options["source_id"]=source_id
        if action_id == "26":
            device=str(request.form.get("device","gpu")).strip().lower()
            if device not in {"cpu","gpu"}:
                abort(400)
            options["device"]=device
        if action_id in {"50", "51", "53"}:
            start_from = str(request.form.get("start_from") or "standard").strip().lower()
            if start_from not in {"standard", "active"}:
                abort(400)
            options["start_from"] = start_from
        payload = enqueue_job(action_id, options)
        job_id = str(payload["job_id"])
        flash(f"Taak gestart: {actions[action_id]}","success")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.best == "application/json":
            return jsonify(payload), 202
        destination=request.referrer or url_for("process_step",step_key="detect-candidates")
        separator="&" if "?" in destination else "?"
        return redirect(f"{destination}{separator}job_id={job_id}")

    @app.get("/api/jobs/<job_id>")
    def job_status(job_id:str):
        if not re_job_id(job_id): abort(404)
        match=_lookup_job(job_id)
        if match is None: abort(404)
        return jsonify(match)

    @app.get("/api/jobs/<job_id>/log")
    def job_log(job_id:str):
        if not re_job_id(job_id): abort(404)
        stream=str(request.args.get("stream") or "overview").strip().lower()
        if stream not in {"overview","stdout","stderr","worker"}:
            abort(400)
        match=_lookup_job(job_id)
        worker=worker_state()
        lifecycle=[]
        if match:
            created=str(match.get("created_at") or "")
            started=str(match.get("started_at") or "")
            finished=str(match.get("finished_at") or "")
            lifecycle.append(f"[{created or '--'}] Taak aangemaakt: {match.get('action_name') or job_id}")
            lifecycle.append(f"Taak-ID: {job_id}")
            status=str(match.get("status") or "pending")
            if status == "pending":
                if worker.get("online"):
                    lifecycle.append("Status: in wachtrij; de PowerShell-worker is online en pakt de taak automatisch op.")
                else:
                    lifecycle.append("Status: in wachtrij; de PowerShell-worker is niet bereikbaar. Start IsalaOCR opnieuw of open de wachtrij voor diagnose.")
            elif status == "running":
                lifecycle.append(f"[{started or '--'}] Status: worker heeft de taak opgepakt en voert deze uit.")
            elif status == "completed":
                lifecycle.append(f"[{finished or '--'}] Status: taak succesvol voltooid.")
            elif status == "failed":
                lifecycle.append(f"[{finished or '--'}] Status: taak mislukt (exitcode {match.get('exit_code', 'onbekend')}).")

        worker_text=_read_log_text(jobs_root/"logs"/(job_id+".worker.log"))
        stdout_text=_read_log_text(jobs_root/"logs"/(job_id+".log"))
        stderr_text=_read_log_text(jobs_root/"logs"/(job_id+".log.err"))

        if stream == "stdout":
            text=stdout_text
            if not text.strip():
                if match and str(match.get("status")) in {"pending","running"}:
                    text="Nog geen STDOUT-uitvoer ontvangen. Normale PowerShell/Docker-uitvoer verschijnt hier automatisch."
                else:
                    text="Geen STDOUT-uitvoer voor deze taak."
        elif stream == "stderr":
            text=stderr_text
            if not text.strip():
                text="Geen STDERR-uitvoer voor deze taak."
        elif stream == "worker":
            text=worker_text
            if not text.strip():
                text="Nog geen worker-uitvoer voor deze taak."
        else:
            sections=[]
            if worker_text.strip(): sections.append("--- WORKER ---\n"+worker_text.strip())
            if stdout_text.strip(): sections.append("--- STDOUT ---\n"+stdout_text.strip())
            if stderr_text.strip(): sections.append("--- STDERR ---\n"+stderr_text.strip())
            if match and not sections and str(match.get("status")) in {"pending", "running"}:
                lifecycle.append("Nog geen scriptuitvoer ontvangen. Deze status blijft zichtbaar totdat PowerShell of Docker een regel schrijft.")
            text="\n".join(lifecycle + ([""] if lifecycle and sections else []) + sections)
            if not text.strip():
                text="Nog geen taakuitvoer beschikbaar."

        response=app.response_class(text[-100000:], mimetype="text/plain")
        response.headers["Cache-Control"]="no-store, max-age=0"
        response.headers["X-Isala-Log-Stream"]=stream
        return response
