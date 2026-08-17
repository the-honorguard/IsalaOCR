from pathlib import Path


def test_runtime_installs_ppstructure_document_parser_dependencies():
    root = Path(__file__).resolve().parents[1]
    requirements = (root / "application" / "requirements" / "runtime.txt").read_text(encoding="utf-8")
    assert "paddleocr[doc-parser]==3.7.0" in requirements
    assert "paddleocr==3.7.0" not in requirements


def test_python_paddle_extra_matches_runtime_table_capability():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "application" / "pyproject.toml").read_text(encoding="utf-8")
    assert '"paddleocr[doc-parser]==3.7.0"' in pyproject
