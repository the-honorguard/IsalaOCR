from pathlib import Path


def test_gate_derivation_is_fail_closed_and_not_global_500_source():
    root = Path(__file__).resolve().parents[1]
    source = (root / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    assert "def _safe_detection_gate(" in source
    assert '"ready": False' in source
    assert '"state": "error"' in source
    assert "webui_errors.log" in source
    # pipeline_gate_global reuses the pipeline_gate already computed earlier in
    # common_context() (a perf fix removed the redundant second
    # navigation_pipeline_gate() call) rather than deriving it inline here.
    assert 'pipeline_gate = navigation_pipeline_gate()' in source
    assert 'pipeline_gate_global": pipeline_gate,' in source
    assert 'detection_gate_global": (navigation_detection_gate() if localization_strategy() != "table_first"' in source
    assert 'return request_cached("current_detection_gate", load)' in source
    assert '"gate": _safe_detection_gate(project_workspace, target_db=db)' in source


def test_unhandled_500_gets_local_diagnostic_reference():
    root = Path(__file__).resolve().parents[1]
    source = (root / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    assert "@app.errorhandler(500)" in source
    assert "unhandled_http_500" in source
    assert "webui_errors.log" in source
