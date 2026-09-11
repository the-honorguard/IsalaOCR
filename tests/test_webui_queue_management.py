from pathlib import Path


def test_queue_management_routes_and_template_exist():
    root = Path(__file__).resolve().parents[1]
    # Job-queue routes were split out of webui.py into their own module.
    routes_jobs = (root / "application/src/isala_ocr/training/routes_jobs.py").read_text(encoding="utf-8")
    template = (root / "application/src/isala_ocr/training/templates/jobs.html").read_text(encoding="utf-8")
    base = (root / "application/src/isala_ocr/training/templates/base.html").read_text(encoding="utf-8")
    assert '@app.get("/jobs/manage")' in routes_jobs
    assert '@app.post("/jobs/<job_id>/delete")' in routes_jobs
    assert '@app.post("/jobs/clear")' in routes_jobs
    assert '@app.post("/jobs/<job_id>/retry")' in routes_jobs
    # An active job's Retry/Delete buttons are hidden client-side, and the
    # server flashes an explanatory message if it's still deleted anyway.
    assert "{% if job.status in ['pending','running'] %}" in template
    assert "Een actieve taak kan niet worden verwijderd" in routes_jobs
    assert "Wachtrij" in base


def test_worker_has_visible_console_status():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "automation/powershell/webui-worker.ps1").read_text(encoding="utf-8")
    assert "webworker v$WorkerVersion gestart" in worker
    assert "Taak gevonden" in worker
    assert "Voltooid:" in worker
