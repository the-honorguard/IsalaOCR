from pathlib import Path

from isala_ocr.config import load_config


def test_production_config_loads():
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "application" / "config" / "app.yaml")
    assert config.profile.name == "philips_cmr_volume_result_v1"
    assert len(config.profile.fields) == 16
    assert len(config.profile.consistency_rules) == 4
