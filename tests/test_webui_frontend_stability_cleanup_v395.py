from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAINING = ROOT / "application/src/isala_ocr/training"
FRONTEND = ROOT / "frontend/src"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_embedded_react_clients_match_the_bundled_react16_runtime():
    vendor = _text(TRAINING / "static/react-vendor/react.production.min.js")
    assert "16.0.0" in vendor
    for name in ("localization-workbench", "localization-quality", "localization-artifacts"):
        source = _text(FRONTEND / f"{name}.ts")
        built = _text(TRAINING / f"static/react/{name}.js")
        for content in (source, built):
            assert "React.Fragment" not in content
            assert "ReactDOM.createRoot" not in content
            assert "new EventSource" not in content
        assert "ReactDOM.render" in source


def test_reactive_pages_poll_json_without_full_page_reload():
    expectations = {
        "localization-workbench": ("2500", "12000"),
        "localization-quality": ("2500", "12000"),
        "localization-artifacts": ("3000", "15000"),
    }
    for name, (active_interval, idle_interval) in expectations.items():
        source = _text(FRONTEND / f"{name}.ts")
        assert "window.setInterval" not in source
        assert "window.setTimeout" in source
        assert active_interval in source
        assert idle_interval in source
        assert "30000" in source
        assert "document.hidden" in source
        assert "window.location.reload" not in source
        assert "location.reload" not in source


def test_interactive_webui_no_longer_forces_reload_for_manual_review_changes():
    app_js = _text(TRAINING / "static/app.js")
    review = _text(TRAINING / "templates/detection_review_studio.html")
    assert "window.location.reload" not in app_js
    assert "location.reload" not in review


def test_user_facing_templates_do_not_advertise_frontend_implementation_details():
    for name in (
        "react_localization_workbench.html",
        "react_localization_quality.html",
        "management.html",
    ):
        template = _text(TRAINING / f"templates/{name}")
        upper = template.upper()
        assert "NIEUWE INTERFACE" not in upper
        assert ">REACT<" not in upper
        assert "SSE" not in upper


def test_sidebar_and_headers_keep_only_user_relevant_context():
    base = _text(TRAINING / "templates/base.html")
    assert "DETECTIE & CROPS" in base
    # The old single "WAARDEN & OCR" section was later split into more
    # granular recognition/value sidebar sections.
    assert "RECOGNITION PREPARATION" in base
    assert "MODEL FACTORY · RECOGNITION" in base
    assert "header_counts" in base
    assert "header_counts is defined" in base
    assert "use_case_id" not in base
    assert "input_path" not in base


def test_react_pages_have_visible_error_boundaries_instead_of_blank_screens():
    assert "QualityBoundary" in _text(FRONTEND / "localization-quality.ts")
    assert "WorkbenchBoundary" in _text(FRONTEND / "localization-workbench.ts")
    assert "ArtifactBoundary" in _text(FRONTEND / "localization-artifacts.ts")
