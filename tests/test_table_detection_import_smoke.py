from pathlib import Path


def test_application_processing_and_webui_import_smoke():
    import isala_ocr.application_processing  # noqa: F401
    from isala_ocr.training.webui import create_web_app

    assert callable(create_web_app)


def test_collector_guards_missing_or_none_benchmark_runs():
    root = Path(__file__).resolve().parents[1]
    collector = (root / "application" / "src" / "isala_ocr" / "training" / "collector.py").read_text(
        encoding="utf-8"
    )

    assignment = 'benchmark_runs = table_preprocessing.get("runs") if isinstance(table_preprocessing, dict) else []'
    guard = "if not isinstance(benchmark_runs, list):\n                    benchmark_runs = []"
    assert assignment in collector
    assert guard in collector
