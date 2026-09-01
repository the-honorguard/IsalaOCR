from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "application/src/isala_ocr/training/webui.py"
TEMPLATE = ROOT / "application/src/isala_ocr/training/templates/react_localization_workbench.html"
CLIENT = ROOT / "frontend/src/localization-workbench.ts"
BUILT = ROOT / "application/src/isala_ocr/training/static/react/localization-workbench.js"


def test_step4_has_dedicated_react_route_and_mount() -> None:
    webui = WEBUI.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    assert 'if step_key == "localization-dataset":' in webui
    assert '"react_localization_workbench.html"' in webui
    assert 'id="react-localization-workbench"' in template
    assert "NIEUWE INTERFACE" not in template
    assert ">REACT<" not in template


def test_reactive_backend_contract_keeps_rest_endpoints() -> None:
    webui = WEBUI.read_text(encoding="utf-8")
    for route in (
        '/api/v2/localization/workbench',
        '/api/v2/localization/split',
        '/api/v2/jobs',
    ):
        assert route in webui


def test_step4_client_polls_without_page_reload() -> None:
    source = CLIENT.read_text(encoding="utf-8")
    built = BUILT.read_text(encoding="utf-8")
    assert 'new EventSource' not in source
    assert 'window.setTimeout(() => this.refresh(false), delay)' in source
    assert 'active ? 2500 : 12000' in source
    assert '/api/v2/localization/workbench' in source
    assert 'fetch("/api/v2/jobs"' in source
    assert 'fetch("/api/v2/localization/split"' in source
    assert "window.location.reload" not in source
    assert "window.location.reload" not in built


def test_step4_client_keeps_exact_three_phase_workflow() -> None:
    source = CLIENT.read_text(encoding="utf-8")
    assert 'this.startJob("5")' in source  # dataset build
    assert 'this.startJob("6")' in source  # validate
    assert 'this.startJob("7")' in source  # GPU train
    assert 'this.startJob("8")' in source  # CPU train
    assert "NVIDIA GPU trainen" in source
    assert "Dataset valideren" in source


def test_react_runtime_is_local_and_labeler_already_copies_static_assets() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    dockerfile = (ROOT / "infrastructure/docker/Dockerfile.labeler").read_text(encoding="utf-8")
    assert "https://" not in template
    assert "react-vendor/react.production.min.js" in template
    assert "react-vendor/react-dom.production.min.js" in template
    assert (ROOT / "application/src/isala_ocr/training/static/react-vendor/react.production.min.js").is_file()
    assert (ROOT / "application/src/isala_ocr/training/static/react-vendor/react-dom.production.min.js").is_file()
    assert "COPY application/src/isala_ocr/training /app/src/isala_ocr/training" in dockerfile


def test_frontend_source_and_compiled_asset_are_both_packaged() -> None:
    assert (ROOT / "frontend/package.json").is_file()
    assert (ROOT / "frontend/tsconfig.json").is_file()
    assert CLIENT.is_file()
    assert BUILT.is_file()
    assert BUILT.stat().st_size > 10_000
