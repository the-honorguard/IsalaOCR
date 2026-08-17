from pathlib import Path


def test_queue_management_routes_and_template_exist():
    root = Path(__file__).resolve().parents[1]
    webui = (root / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    template = (root / "application/src/isala_ocr/training/templates/jobs.html").read_text(encoding="utf-8")
    base = (root / "application/src/isala_ocr/training/templates/base.html").read_text(encoding="utf-8")
    assert '@app.get("/jobs/manage")' in webui
    assert '@app.post("/jobs/<job_id>/delete")' in webui
    assert '@app.post("/jobs/clear")' in webui
    assert '@app.post("/jobs/<job_id>/retry")' in webui
    assert "Actieve taak beveiligd" in template
    assert "Wachtrij" in base


def test_worker_has_visible_console_status():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "automation/powershell/webui-worker.ps1").read_text(encoding="utf-8")
    assert "webworker v$WorkerVersion gestart" in worker
    assert "Taak gevonden" in worker
    assert "Voltooid:" in worker
