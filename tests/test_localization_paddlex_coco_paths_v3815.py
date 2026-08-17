from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "automation" / "training_runtime" / "localization_runner.py"


def _runner_module():
    spec = importlib.util.spec_from_file_location("localization_runner_v3815", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_dataset(root: Path, *, file_name: str) -> None:
    (root / "annotations").mkdir(parents=True)
    (root / "images").mkdir(parents=True)
    (root / "images" / "source.png").write_bytes(b"not-an-image-needed-for-path-check")
    payload = {
        "images": [{"id": 1, "file_name": file_name, "width": 10, "height": 10}],
        "annotations": [],
        "categories": [{"id": 1, "name": "field_roi", "supercategory": "field"}],
    }
    for split in ("train", "val"):
        (root / "annotations" / f"instance_{split}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_paddlex_layout_accepts_basename_file_name(tmp_path: Path) -> None:
    module = _runner_module()
    _write_dataset(tmp_path, file_name="source.png")
    module.validate_paddlex_coco_layout(tmp_path)


def test_paddlex_layout_rejects_legacy_images_prefix_with_actionable_hint(tmp_path: Path, capsys) -> None:
    module = _runner_module()
    _write_dataset(tmp_path, file_name="images/source.png")
    with pytest.raises(RuntimeError):
        module.validate_paddlex_coco_layout(tmp_path)
    captured = capsys.readouterr()
    assert "images/images/source.png" in captured.err
    assert "Rebuild the localization dataset with IsalaOCR 3.8.15+" in captured.err


def test_validate_command_disables_paddlex_resplit_and_preflights_layout() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert '"CheckDataset.split.enable=False"' in text
    assert "validate_paddlex_coco_layout(dataset)" in text
    assert "print_paddlex_check_result(output)" in text
