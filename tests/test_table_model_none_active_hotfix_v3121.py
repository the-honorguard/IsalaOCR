from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_table_model_overview_is_null_safe_before_first_activation() -> None:
    source = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    assert 'active_table_model = ((snapshot.get("table_model") or {}).get("active_model") or {})' in source
    assert ".get('active_model', {}).get('model_id')" not in source
    assert "active_table_model.get('model_id')" in source
