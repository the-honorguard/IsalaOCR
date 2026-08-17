from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates" / "base.html"
RUNTIME = ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "job-runtime.js"


def test_base_loads_runtime_telemetry_after_main_app_script() -> None:
    base = BASE.read_text(encoding="utf-8")
    app_pos = base.index("filename='app.js'")
    runtime_pos = base.index("filename='job-runtime.js'")
    assert runtime_pos > app_pos


def test_runtime_indicator_uses_persisted_job_timestamps() -> None:
    script = RUNTIME.read_text(encoding="utf-8")
    assert "job?.started_at || job?.created_at" in script
    assert "job?.finished_at || job?.updated_at" in script
    assert "Laatste run" in script
    assert "duration_ms" in script


def test_runtime_indicator_uses_previous_successful_run_for_time_progress() -> None:
    script = RUNTIME.read_text(encoding="utf-8")
    assert "latestSuccessful" in script
    assert "elapsed / referenceMs" in script
    assert "Math.min(95" in script
    assert "op basis van vorige run" in script


def test_runtime_indicator_prefers_real_worker_progress_when_available() -> None:
    script = RUNTIME.read_text(encoding="utf-8")
    assert "progress_mode" in script
    assert "progress_percent" in script
    assert "actualProgress > 0" in script


def test_runtime_indicator_is_scoped_per_project_and_action() -> None:
    script = RUNTIME.read_text(encoding="utf-8")
    assert "isala-job-runtime:${projectId}:${actionId}" in script
    assert "input[name=\"action_id\"]" in script
