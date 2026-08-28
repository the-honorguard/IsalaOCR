from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

try:
    import flask  # noqa: F401
except ModuleNotFoundError:
    FLASK_AVAILABLE = False
else:
    FLASK_AVAILABLE = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.training.evaluator import compare_evaluations


def evaluation(model: str, predictions: list[dict], exact: float, cer: float) -> dict:
    return {
        "created_at": "2026-08-06T14:00:00+00:00",
        "dataset": "/training/workspace/datasets/dataset-1",
        "dataset_id": "dataset-1",
        "split": "test",
        "model": {"recognition_model": model},
        "metrics": {
            "samples": len(predictions),
            "exact_match_accuracy": exact,
            "character_error_rate": cer,
            "per_field": {
                "volume": {
                    "samples": len(predictions),
                    "exact_match_accuracy": exact,
                    "character_error_rate": cer,
                }
            },
        },
        "predictions": predictions,
    }


def test_comparison_contains_side_by_side_sample_results(tmp_path: Path) -> None:
    common = {"image": "images/sample.png", "source_id": "dicom-1", "field_key": "volume", "expected": "123"}
    baseline = evaluation("PP-OCRv6_medium_rec", [{**common, "observed": "128", "confidence": 0.82}], 0.0, 1 / 3)
    custom = evaluation("custom-volume-v1", [{**common, "observed": "123", "confidence": 0.97}], 1.0, 0.0)
    baseline_path = tmp_path / "baseline.json"
    custom_path = tmp_path / "custom.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    custom_path.write_text(json.dumps(custom), encoding="utf-8")

    report = compare_evaluations(baseline_path, custom_path, tmp_path / "output")

    assert report["custom"]["label"] == "custom-volume-v1"
    assert report["baseline"]["label"] == "PP-OCRv6_medium_rec"
    assert report["outcomes"]["custom_only_correct"] == 1
    row = report["sample_comparisons"][0]
    assert row["sample_id"] == ""
    assert row["custom"] == {"observed": "123", "confidence": 0.97, "correct": True}
    assert row["baseline"] == {"observed": "128", "confidence": 0.82, "correct": False}
    assert row["preferred"] == "custom"
    assert report["per_field"]["volume"]["winner"] == "custom"


def test_comparison_preserves_canonical_sample_id_for_step_11_crop(tmp_path: Path) -> None:
    common = {"image": "images/sample.png", "sample_id": "recgt-canonical", "source_id": "dicom-1", "field_key": "volume", "expected": "123"}
    baseline = evaluation("old", [{**common, "observed": "128", "confidence": 0.8}], 0.0, 1 / 3)
    custom = evaluation("new", [{**common, "observed": "123", "confidence": 0.9}], 1.0, 0.0)
    baseline_path = tmp_path / "baseline.json"
    custom_path = tmp_path / "custom.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    custom_path.write_text(json.dumps(custom), encoding="utf-8")

    report = compare_evaluations(baseline_path, custom_path, tmp_path / "output")

    assert report["sample_comparisons"][0]["sample_id"] == "recgt-canonical"


def test_comparison_rejects_different_sample_sets(tmp_path: Path) -> None:
    baseline = evaluation(
        "old",
        [{"image": "images/a.png", "source_id": "one", "field_key": "volume", "expected": "1", "observed": "1", "confidence": 1.0}],
        1.0,
        0.0,
    )
    custom = evaluation(
        "new",
        [{"image": "images/b.png", "source_id": "two", "field_key": "volume", "expected": "1", "observed": "1", "confidence": 1.0}],
        1.0,
        0.0,
    )
    baseline_path = tmp_path / "baseline.json"
    custom_path = tmp_path / "custom.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    custom_path.write_text(json.dumps(custom), encoding="utf-8")
    with pytest.raises(ValueError, match="same samples"):
        compare_evaluations(baseline_path, custom_path, tmp_path / "output")


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask missing")
def test_compare_page_has_new_left_old_right_and_correct_actions(tmp_path: Path) -> None:
    from isala_ocr.training.webui import create_web_app

    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.5.14", encoding="utf-8")
    app = create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    )
    response = app.test_client().get("/process/compare")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "LINKS · NIEUW MODEL" in text
    assert "RECHTS · OUD MODEL" in text
    assert 'name="action_id" value="13"' in text
    assert 'name="action_id" value="9"' in text
    assert 'name="action_id" value="14"' in text
    assert 'action="/jobs/compare-all"' in text


def test_compare_all_queues_actions_in_required_order(tmp_path: Path) -> None:
    if not FLASK_AVAILABLE:
        pytest.skip("Flask missing")
    from isala_ocr.training.webui import create_web_app

    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.5.14", encoding="utf-8")
    app = create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    )
    response = app.test_client().post("/jobs/compare-all", headers={"Referer": "/process/compare"})
    assert response.status_code == 302
    jobs = sorted((workspace / "webui" / "jobs" / "pending").glob("*.json"))
    assert [json.loads(path.read_text(encoding="utf-8"))["action_id"] for path in jobs] == ["13", "9", "14"]
