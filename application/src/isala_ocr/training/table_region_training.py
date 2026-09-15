from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .db import TrainingDatabase
from .localization_dataset import resolve_localization_splits
from .projects import resolve_project_workspace
from .table_region_ground_truth import list_table_region_sources
from .json_store import read_json, read_json_object, write_json_atomic


DATASET_DIRNAME = "table_region_datasets"
RUNS_DIRNAME = "table_region_runs"
MODELS_DIRNAME = "table_region_models"
SPLITS = ("train", "val", "test")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dataset_id(source_ids: list[str], regions: list[dict[str, Any]], splits: dict[str, str]) -> str:
    payload = json.dumps({"sources": source_ids, "regions": regions, "splits": splits}, sort_keys=True, separators=(",", ":"))
    return "table-regions-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def build_table_region_dataset(workspace: str | Path) -> dict[str, Any]:
    """Build a full-page COCO dataset from the per-source table-region GT."""
    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    sources_by_id = {str(item.get("source_id") or ""): item for item in db.list_detection_sources()}
    gt_sources = [item for item in list_table_region_sources(root) if bool(item.get("review_completed"))]
    if not gt_sources:
        raise ValueError("Sla eerst per lezing de tabelregio-review op in Stap 2")
    source_ids = [str(item["source_id"]) for item in gt_sources if str(item["source_id"]) in sources_by_id]
    if not source_ids:
        raise ValueError("De tabelregio-GT verwijst niet naar bekende lezingen")
    split_state = resolve_localization_splits(root, source_ids)
    splits = dict(split_state.get("assignments") or {})
    regions = [region for source in gt_sources for region in source.get("regions") or []]
    dataset_id = _dataset_id(source_ids, regions, splits)
    dataset_root = root / DATASET_DIRNAME / dataset_id
    if dataset_root.exists():
        return read_json(dataset_root / "manifest.json", {})
    images_root = dataset_root / "images"
    annotations_root = dataset_root / "annotations"
    images_root.mkdir(parents=True, exist_ok=False)
    annotations_root.mkdir(parents=True, exist_ok=True)
    coco = {
        split: {"info": {"description": "IsalaOCR table-region detector dataset", "created_at": _utcnow()},
                "licenses": [], "images": [], "annotations": [],
                "categories": [{"id": 1, "name": "table_region", "supercategory": "table"}]}
        for split in SPLITS
    }
    image_id = 1
    annotation_id = 1
    annotation_count = 0
    for source in sorted(gt_sources, key=lambda item: str(item["source_id"])):
        source_id = str(source["source_id"])
        if source_id not in sources_by_id:
            continue
        render_path = root / str(sources_by_id[source_id].get("render_path") or "")
        if not render_path.is_file():
            raise FileNotFoundError(f"Bronrender ontbreekt voor tabelregio-GT: {render_path}")
        from PIL import Image
        with Image.open(render_path) as image:
            image = image.convert("RGB")
            width, height = image.size
            filename = f"{source_id}.png"
            image.save(images_root / filename)
        split = splits.get(source_id, "train")
        coco[split]["images"].append({"id": image_id, "file_name": filename, "width": width, "height": height})
        for region in source.get("regions") or []:
            x1 = max(0, min(width, int(region.get("x1") or 0)))
            y1 = max(0, min(height, int(region.get("y1") or 0)))
            x2 = max(0, min(width, int(region.get("x2") or 0)))
            y2 = max(0, min(height, int(region.get("y2") or 0)))
            if x2 <= x1 or y2 <= y1:
                continue
            coco[split]["annotations"].append({
                "id": annotation_id, "image_id": image_id, "category_id": 1,
                "bbox": [x1, y1, x2 - x1, y2 - y1], "area": (x2 - x1) * (y2 - y1), "iscrowd": 0,
            })
            annotation_id += 1
            annotation_count += 1
        image_id += 1
    if annotation_count == 0:
        raise ValueError("De tabelregio-GT bevat geen geldige kaders")
    for split in SPLITS:
        write_json_atomic(annotations_root / f"instance_{split}.json", coco[split])
    manifest = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "type": "table_region_detection",
        "format": "COCODetDataset",
        "model_family": "PicoDet-S",
        "path": dataset_root.relative_to(root).as_posix(),
        "created_at": _utcnow(),
        "source_count": len(source_ids),
        "annotation_count": annotation_count,
        "positive_source_count": sum(1 for source in gt_sources if source.get("regions")),
        "negative_source_count": sum(1 for source in gt_sources if not source.get("regions")),
        "class_names": ["table_region"],
        "source_splits": splits,
        "splits": {split: {"images": len(coco[split]["images"]), "annotations": len(coco[split]["annotations"])} for split in SPLITS},
        "supervision": "per_source_full_page_table_region_gt_with_explicit_negatives",
    }
    write_json_atomic(dataset_root / "manifest.json", manifest)
    pointer_root = root / DATASET_DIRNAME
    pointer_root.mkdir(parents=True, exist_ok=True)
    (pointer_root / "latest.txt").write_text(dataset_id + "\n", encoding="ascii")
    return manifest


def activate_table_region_model(workspace: str | Path) -> dict[str, Any]:
    """Activate the most recently trained full-page table-region detector.

    A 1:1 transfer of the raw-PowerShell logic previously embedded in
    ``activate-table-region-model.ps1``: pick the most recently modified run
    directory under ``table_region_runs`` that has a ``model.json``, require
    a passing independent test evaluation, and write
    ``table_region_models/active.json``.
    """
    root = resolve_project_workspace(workspace)
    runs_root = root / RUNS_DIRNAME
    candidates = sorted(
        (item for item in runs_root.iterdir() if item.is_dir() and (item / "model.json").is_file()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ) if runs_root.is_dir() else []
    if not candidates:
        raise FileNotFoundError("Geen getraind tabelregio-model gevonden.")
    run_dir = candidates[0]
    model = read_json_object(run_dir / "model.json")
    evaluation_path = run_dir / "evaluation_artifacts" / "test_evaluation.json"
    if not evaluation_path.is_file():
        raise FileNotFoundError(
            "Model heeft geen onafhankelijke test-evaluatie. Train de tabelregio opnieuw voordat je activeert."
        )
    evaluation = read_json_object(evaluation_path)
    if not bool(evaluation.get("passed")):
        raise ValueError(
            "Model faalt de onafhankelijke tabelregio-test "
            f"(recall={evaluation.get('recall_at_iou_0_50')}, precision={evaluation.get('precision_at_iou_0_50')})."
        )
    relative_inference = str(model.get("inference_dir") or "").strip()
    if not relative_inference:
        raise ValueError("Training metadata heeft geen inference_dir.")
    # Checked against both path flavors (not just the host OS's own `Path`) because
    # this subcommand runs inside a Linux training container in production while
    # `model.json` can, for legacy/manually-trained runs, still carry a raw Windows
    # host path from before training itself started relativizing `inference_dir`.
    # `PurePosixPath("C:/x").is_absolute()` is False, so relying on the platform
    # `Path` alone would silently treat such a value as already-relative and write
    # a bogus path into `active.json` instead of failing loudly.
    if PureWindowsPath(relative_inference).is_absolute() or PurePosixPath(relative_inference).is_absolute():
        workspace_full = root.resolve()
        inference_full = Path(relative_inference).resolve()
        try:
            relative_inference = inference_full.relative_to(workspace_full).as_posix()
        except ValueError as exc:
            raise ValueError(
                f"Tabelregio-model staat buiten de projectworkspace: {inference_full}"
            ) from exc
    model["inference_dir"] = relative_inference
    model["test_evaluation"] = evaluation
    model["active"] = True
    write_json_atomic(root / MODELS_DIRNAME / "active.json", model)
    return model
