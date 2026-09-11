from __future__ import annotations

from pathlib import Path
import shutil

from PIL import Image

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.table_panels import save_panel_profile
from isala_ocr.training.table_cell_ground_truth import add_ground_truth_cell
from isala_ocr.training.table_cell_training import (
    activate_table_cell_model,
    build_table_cell_dataset,
    register_table_cell_model,
    table_cell_dataset_preview,
    table_cell_training_state,
    validate_table_cell_dataset,
)

ROOT = Path(__file__).resolve().parents[1]


def _seed_review(workspace: Path, source_id: str = "source-a") -> None:
    renders = workspace / "source_renders"
    renders.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (300, 200), "white").save(renders / f"{source_id}.png")
    db = TrainingDatabase(workspace / "samples.sqlite3")
    candidates = [
        {"candidate_id":"cell-1", "source_id":source_id, "confidence":0.95, "source_kind":"table_cell",
         "source_refs":["table:t:cell:1"], "crop_path":"", "x1":20,"y1":20,"x2":140,"y2":48},
        {"candidate_id":"cell-2", "source_id":source_id, "confidence":0.94, "source_kind":"table_cell",
         "source_refs":["table:t:cell:2"], "crop_path":"", "x1":150,"y1":20,"x2":270,"y2":48},
    ]
    db.replace_localization_detection({"source_id":source_id,"image_width":300,"image_height":200,
        "render_path":f"source_renders/{source_id}.png","detector_version":"ppstructure","token_count":0}, candidates, [])
    db.review_detection_candidate(source_id=source_id, candidate_id="cell-1", review_status="correct")
    db.review_detection_candidate(source_id=source_id, candidate_id="cell-2", review_status="adjusted", corrected_box=(148,18,272,50))
    db.add_detection_annotation(source_id=source_id, box=(20,60,140,88))
    db.set_detection_source_review_completed(source_id, True)


def test_reviewed_table_cells_build_validate_and_invalidate_dataset(tmp_path: Path) -> None:
    save_panel_profile(tmp_path, panels=[{"panel_id":"lv","name":"LV","x1":0.0,"y1":0.0,"x2":1.0,"y2":1.0}],
                       reference_source_id="source-a", reference_width=300, reference_height=200)
    _seed_review(tmp_path)
    preview = table_cell_dataset_preview(tmp_path)
    assert preview["ready"] is True
    assert preview["annotation_count"] == 3

    manifest = build_table_cell_dataset(tmp_path)
    assert manifest["type"] == "table_cell_detection"
    assert manifest["annotation_count"] == 3
    assert manifest["review_fingerprint"] == preview["review_fingerprint"]
    report = validate_table_cell_dataset(tmp_path)
    assert report["valid"] is True
    assert (tmp_path / manifest["path"] / "annotations" / "instance_train.json").is_file()

    state = table_cell_training_state(tmp_path)
    assert state["dataset_current"] is True
    # Once the first dataset exists, canonical GT is authoritative. A later
    # detector/DB mutation must not silently redefine Step 4; an explicit GT edit does.
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    db.add_detection_annotation(source_id="source-a", box=(150,60,270,88))
    assert table_cell_training_state(tmp_path)["dataset_current"] is True
    add_ground_truth_cell(tmp_path, "source-a", (150,60,270,88))
    state = table_cell_training_state(tmp_path)
    assert state["dataset_current"] is False


def test_table_cell_model_registration_activation_and_runtime_wiring(tmp_path: Path) -> None:
    inference = tmp_path / "run" / "inference"
    inference.mkdir(parents=True)
    (inference / "inference.yml").write_text("model: table\n", encoding="utf-8")
    registered = register_table_cell_model(tmp_path, model_id="table-model-1", run_id="run-1", dataset_id="data-1",
                                           inference_dir=inference, device="gpu", evaluation={"f1":0.9})
    assert registered["model_name"] == "RT-DETR-L_wireless_table_cell_det"
    active = activate_table_cell_model(tmp_path, "table-model-1")
    assert active["model_id"] == "table-model-1"
    state = table_cell_training_state(tmp_path)
    assert state["active_model"]["model_id"] == "table-model-1"

    table_structure = (ROOT / "application/src/isala_ocr/ocr/table_structure.py").read_text(encoding="utf-8")
    collector = (ROOT / "application/src/isala_ocr/training/collector.py").read_text(encoding="utf-8")
    assert '"wireless_table_cells_detection_model_dir": "wireless_cells_model_dir"' in table_structure
    assert 'result["wireless_cells_model_dir"] = str(selected["inference_path"])' in collector


def test_table_cell_training_actions_and_ui_are_in_primary_workflow() -> None:
    preflight = (ROOT / "automation/powershell/preflight.ps1").read_text(encoding="utf-8")
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    template = (ROOT / "application/src/isala_ocr/training/templates/table_model_training.html").read_text(encoding="utf-8")
    runner = (ROOT / "automation/training_runtime/table_cell_runner.py").read_text(encoding="utf-8")
    assert '"48" = @{ Name = "Build reviewed table-cell training dataset"' in preflight
    assert '"50" = @{ Name = "Fine-tune wireless table-cell detector on GPU"' in preflight
    assert '"key": "table-model","index":6,"group":"detection"' in webui
    assert "Dataset bouwen → valideren → trainen → activeren → nieuwe celdetectie" in template
    assert "RT-DETR-L_wireless_table_cell_det" in runner
    assert "table_cells_detection" in runner


def test_table_cell_registration_does_not_require_posix_metadata_copy(tmp_path: Path, monkeypatch) -> None:
    inference = tmp_path / "run-bindlike" / "inference"
    nested = inference / "assets"
    nested.mkdir(parents=True)
    (inference / "inference.yml").write_text("model: table\n", encoding="utf-8")
    (nested / "weights.bin").write_bytes(b"detector-bytes")

    def unsupported_copystat(*args, **kwargs):
        raise PermissionError("bind mount does not support copystat")

    monkeypatch.setattr(shutil, "copystat", unsupported_copystat)
    registered = register_table_cell_model(
        tmp_path, model_id="table-bind-safe", run_id="run-bindlike", dataset_id="data-1",
        inference_dir=inference, device="gpu", evaluation={"f1": 0.96},
    )
    copied = tmp_path / registered["inference_dir"]
    assert (copied / "inference.yml").read_text(encoding="utf-8") == "model: table\n"
    assert (copied / "assets" / "weights.bin").read_bytes() == b"detector-bytes"


def test_table_cell_train_action_recovers_completed_unregistered_run_before_retraining() -> None:
    script = (ROOT / "automation/powershell/train-table-cell-model.ps1").read_text(encoding="utf-8")
    assert "Recovering registration only; the detector will NOT be trained again." in script
    assert "validation_evaluation.json" in script
    assert "$RegisteredRunIds.ContainsKey($candidate.Name)" in script
    assert "Recovered and registered existing table-cell model" in script
