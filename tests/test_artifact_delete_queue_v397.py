from pathlib import Path


def test_worker_executes_artifact_delete_as_queued_job() -> None:
    root = Path(__file__).resolve().parents[1]
    worker = (root / "automation/powershell/webui-worker.ps1").read_text(encoding="utf-8")
    compose = (root / "infrastructure/docker/compose.yaml").read_text(encoding="utf-8")
    runner = root / "automation/training_runtime/artifact_delete_runner.py"
    assert 'job_type -eq "artifact_delete"' in worker
    assert "artifact_delete_runner.py --job-file" in worker
    assert "../../automation/training_runtime:/opt/isala-training:ro" in compose
    assert runner.is_file()


def test_delete_endpoint_only_enqueues_and_never_calls_sync_delete() -> None:
    root = Path(__file__).resolve().parents[1]
    # This route now lives in routes_localization_v2.py (split out of webui.py).
    webui = (root / "application/src/isala_ocr/training/routes_localization_v2.py").read_text(encoding="utf-8")
    start = webui.index('@app.post("/api/v2/localization/artifacts/delete")')
    end = webui.index('@app.post("/api/v2/localization/split")', start)
    route = webui[start:end]
    assert "enqueue_artifact_delete_job" in route
    assert "delete_localization_artifact(" not in route
    assert '"queued": True' in route
