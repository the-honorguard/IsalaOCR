from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.table_cell_ground_truth import (
    add_ground_truth_cell,
    bootstrap_table_cell_ground_truth,
    delete_ground_truth_cell,
    list_ground_truth_cells,
    update_ground_truth_cell,
)
from isala_ocr.training.table_cell_training import table_cell_dataset_preview
from isala_ocr.training.table_panels import save_panel_profile


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_frozen_dataset(root: Path) -> None:
    dataset_id = "table-cells-baseline"
    base = root / "table_cell_datasets" / dataset_id
    (base / "images").mkdir(parents=True)
    _write(base / "manifest.json", {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "path": f"table_cell_datasets/{dataset_id}",
        "review_fingerprint": "original-fingerprint",
        "created_at": "2026-08-14T09:00:00+00:00",
        "panels": [{
            "source_id": "source-a", "panel_id": "lv", "panel_name": "LV", "split": "train",
            "file_name": "source-a__lv.png", "box": [100, 50, 200, 150], "annotation_count": 1,
        }],
    })
    coco = {
        "images": [{"id": 1, "file_name": "source-a__lv.png", "width": 100, "height": 100}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 20, 30, 10], "area": 300, "iscrowd": 0}],
        "categories": [{"id": 1, "name": "table_cell"}],
    }
    _write(base / "annotations" / "instance_train.json", coco)
    empty = {"images": [], "annotations": [], "categories": [{"id": 1, "name": "table_cell"}]}
    _write(base / "annotations" / "instance_val.json", empty)
    _write(base / "annotations" / "instance_test.json", empty)
    (root / "table_cell_datasets" / "latest.txt").write_text(dataset_id + "\n", encoding="ascii")

    (root / "source_renders").mkdir(parents=True)
    Image.new("RGB", (300, 200), "white").save(root / "source_renders" / "source-a.png")
    db = TrainingDatabase(root / "samples.sqlite3")
    db.replace_localization_detection({
        "source_id": "source-a", "image_width": 300, "image_height": 200,
        "render_path": "source_renders/source-a.png", "detector_version": "new-model", "token_count": 0,
    }, [{
        "candidate_id": "new-prediction", "source_id": "source-a", "confidence": 0.9,
        "source_kind": "table_cell", "source_refs": [], "crop_path": "",
        "x1": 20, "y1": 20, "x2": 40, "y2": 40,
    }], [])
    save_panel_profile(root, panels=[{"panel_id":"lv","name":"LV","x1":100/300,"y1":50/200,"x2":200/300,"y2":150/200}],
                       reference_source_id="source-a", reference_width=300, reference_height=200)


def test_frozen_dataset_bootstraps_full_image_canonical_gt_and_ignores_new_predictions(tmp_path: Path) -> None:
    _seed_frozen_dataset(tmp_path)
    payload = bootstrap_table_cell_ground_truth(tmp_path)
    assert payload is not None
    assert payload["base_dataset_id"] == "table-cells-baseline"
    assert payload["base_review_fingerprint"] == "original-fingerprint"
    cells = list_ground_truth_cells(tmp_path, "source-a")
    assert len(cells) == 1
    assert [cells[0][key] for key in ("x1", "y1", "x2", "y2")] == [110, 70, 140, 80]
    assert cells[0]["x1"] != 20  # current Step-3 prediction is not Step-4 GT

    preview = table_cell_dataset_preview(tmp_path)
    assert preview["canonical_ground_truth"] is True
    assert preview["annotation_count"] == 1
    assert preview["review_fingerprint"] == "original-fingerprint"


def test_canonical_gt_is_directly_editable_and_marks_dataset_stale(tmp_path: Path) -> None:
    _seed_frozen_dataset(tmp_path)
    bootstrap_table_cell_ground_truth(tmp_path)
    cell = list_ground_truth_cells(tmp_path, "source-a")[0]
    update_ground_truth_cell(tmp_path, "source-a", cell["gt_id"], (111, 71, 141, 81))
    preview = table_cell_dataset_preview(tmp_path)
    assert preview["review_fingerprint"] != "original-fingerprint"

    added = add_ground_truth_cell(tmp_path, "source-a", (120, 90, 150, 100))
    assert len(list_ground_truth_cells(tmp_path, "source-a")) == 2
    delete_ground_truth_cell(tmp_path, "source-a", added["gt_id"])
    assert len(list_ground_truth_cells(tmp_path, "source-a")) == 1


def test_step4_template_has_explicit_canonical_gt_mode() -> None:
    root = Path(__file__).resolve().parents[1]
    index = (root / "application/src/isala_ocr/training/templates/detection_review_index.html").read_text(encoding="utf-8")
    studio = (root / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    webui = (root / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    assert "Canonieke Ground Truth" in index
    assert "detectorpredictions staan alleen in Stap 7" in studio
    assert "canonical_table_gt_mode" in webui
    assert '"title":"GT Studio"' in webui
