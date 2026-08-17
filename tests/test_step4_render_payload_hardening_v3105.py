from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "application" / "src" / "isala_ocr" / "training" / "webui.py"
WORKBENCH = ROOT / "frontend" / "src" / "localization-workbench.ts"


def test_localization_readiness_normalizes_optional_validation_collections():
    source = WEBUI.read_text(encoding="utf-8")
    assert 'isinstance(validation.get("warnings"), list)' in source
    assert 'isinstance(validation.get("errors"), list)' in source
    assert 'isinstance(validation.get("totals"), dict)' in source


def test_step4_client_guards_legacy_optional_arrays_and_preview_shape():
    source = WORKBENCH.read_text(encoding="utf-8")
    assert 'Array.isArray(state.warnings) ? state.warnings : []' in source
    assert 'Array.isArray(state.errors) ? state.errors : []' in source
    assert 'Array.isArray(preview.sources) ? preview.sources : []' in source
    assert 'if (!preview || !preview.split_plan)' in source


def test_step4_render_boundary_reports_actual_exception():
    source = WORKBENCH.read_text(encoding="utf-8")
    assert 'Technische fout:' in source
    assert 'Technische fout:' in source
    assert 'error && error.message ? String(error.message)' in source
