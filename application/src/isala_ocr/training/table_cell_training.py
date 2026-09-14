from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .db import TrainingDatabase, utc_now
from .localization_dataset import resolve_localization_splits
from .projects import resolve_project_workspace
from ..models import Box
from .table_cell_ground_truth import (
    bootstrap_table_cell_ground_truth, ensure_table_cell_ground_truth, list_ground_truth_cells, list_ground_truth_sources,
)
from .table_region_ground_truth import list_table_regions
from .table_panels import load_panel_profile, panel_boxes_for_image
from .json_store import read_json as _read_json, write_json_atomic as _write_json

MODEL_NAME = "RT-DETR-L_wireless_table_cell_det"
DATASET_DIRNAME = "table_cell_datasets"
RUN_DIRNAME = "table_cell_runs"
MODEL_DIRNAME = "table_cell_models"
SPLIT_NAMES = ("train", "val", "test")


def _panel_semantic_side(db: TrainingDatabase, source_id: str, panel: dict[str, Any]) -> str:
    """Recover the old OCR-derived left/right meaning for a training panel."""
    # Import lazily: application_processing.lateral uses training normalization
    # helpers, so importing it at module load would create a startup cycle.
    from ..application_processing.lateral import relation_lateral_side
    px1, py1, px2, py2 = (float(panel.get(key) or 0) for key in ("x1", "y1", "x2", "y2"))
    sides: set[str] = set()
    for relation in db.list_detected_relations(source_id):
        side = relation_lateral_side(relation)
        if side not in {"left", "right"}:
            continue
        cx = (float(relation.get("label_x1") or 0) + float(relation.get("label_x2") or 0)) / 2
        cy = (float(relation.get("label_y1") or 0) + float(relation.get("label_y2") or 0)) / 2
        if px1 <= cx <= px2 and py1 <= cy <= py2:
            sides.add(side)
    return next(iter(sides)) if len(sides) == 1 else ("ambiguous" if len(sides) > 1 else "")


def _panel_semantic_assignment(db: TrainingDatabase, source_id: str, panel: dict[str, Any]) -> dict[str, Any]:
    """Persist OCR header/context evidence for the user-configured table name."""
    px1, py1, px2, py2 = (float(panel.get(key) or 0) for key in ("x1", "y1", "x2", "y2"))
    texts: list[str] = []
    for relation in db.list_detected_relations(source_id):
        cx = (float(relation.get("label_x1") or 0) + float(relation.get("label_x2") or 0)) / 2
        cy = (float(relation.get("label_y1") or 0) + float(relation.get("label_y2") or 0)) / 2
        if px1 <= cx <= px2 and py1 <= cy <= py2:
            for key in ("context_text", "header_text", "column_header", "label_text"):
                value = str(relation.get(key) or "").strip()
                if value and value not in texts:
                    texts.append(value)
    configured = str(panel.get("name") or panel.get("panel_id") or "").strip()
    return {
        "table_name": configured,
        "header_text": " | ".join(texts[:20]),
        "assignment_source": "configured_panel_name_and_ocr_context" if texts else "configured_panel_name",
    }


def _latest_pointer(root: Path) -> Path:
    return root / DATASET_DIRNAME / "latest.txt"


def _resolve_dataset(root: Path, dataset: str = "latest") -> Path:
    base = root / DATASET_DIRNAME
    if dataset == "latest":
        pointer = _latest_pointer(root)
        if not pointer.is_file():
            raise FileNotFoundError("Nog geen table-cell trainingsdataset gebouwd")
        dataset = pointer.read_text(encoding="utf-8-sig").strip()
    path = base / dataset
    if not path.is_dir():
        raise FileNotFoundError(f"Table-cell dataset bestaat niet: {path}")
    return path


def _current_table_annotations(db: TrainingDatabase, source_id: str) -> list[dict[str, Any]]:
    """Return only positive GT belonging to the current table-first detection pass.

    Historic PicoDet/manual geometry may intentionally remain in SQLite. Candidate-backed
    annotations are therefore accepted only when the current candidate is a table-cell;
    candidate-less additions count only when they were created after the current source
    detection timestamp. This mirrors the table-first quality calculation.
    """
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT a.*, s.render_path, s.image_width, s.image_height, s.detected_at,
                   c.source_kind, r.notes, r.reason_code
            FROM detection_annotations a
            JOIN detection_sources s ON s.source_id=a.source_id
            LEFT JOIN detection_candidates c
              ON c.source_id=a.source_id AND c.candidate_id=a.candidate_id
            LEFT JOIN detection_reviews r ON r.review_id=a.review_id
            WHERE a.source_id=?
              AND a.active=1
              AND a.training_role='positive'
              AND (
                    (a.candidate_id<>'' AND c.source_kind LIKE '%table_cell%')
                 OR (a.candidate_id='' AND a.provenance='added' AND a.created_at>=s.detected_at)
              )
            ORDER BY a.y1,a.x1
            """,
            (source_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _overlap_fraction(box: tuple[int, int, int, int], panel: tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = box
    px1, py1, px2, py2 = panel
    ix1, iy1 = max(x1, px1), max(y1, py1)
    ix2, iy2 = min(x2, px2), min(y2, py2)
    intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area = max(1, (x2 - x1) * (y2 - y1))
    return intersection / area


def _review_fingerprint(
    *, source_splits: dict[str, str], panels: list[dict[str, Any]], annotations: list[dict[str, Any]]
) -> str:
    payload = {
        "splits": source_splits,
        "panels": [
            {key: panel.get(key) for key in ("panel_id", "name", "x1", "y1", "x2", "y2")}
            for panel in panels
        ],
        "annotations": [
            {
                "source_id": item.get("source_id"),
                "annotation_id": item.get("annotation_id"),
                "box": [item.get("x1"), item.get("y1"), item.get("x2"), item.get("y2")],
            }
            for item in annotations
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _dataset_identity(review_fingerprint: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"table-cells-{stamp}-{review_fingerprint[:8]}"


def _dataset_source_state(root: Path, db: TrainingDatabase) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any] | None]:
    """Return sources + authoritative annotations for table-cell dataset building.

    After the first dataset has established canonical GT, later Step-3 runs must
    never replace the supervision used by Step 4/6.
    """
    canonical = ensure_table_cell_ground_truth(root)
    if canonical is not None:
        by_id = {str(item["source_id"]): item for item in db.list_detection_sources()}
        gt_sources = {str(item["source_id"]): item for item in list_ground_truth_sources(root)}
        source_ids = sorted(str(key) for key in (canonical.get("sources") or {}).keys())
        sources = [
            {
                **by_id[source_id],
                "gt_review_completed": bool((gt_sources.get(source_id) or {}).get("review_completed", True)),
            }
            for source_id in source_ids if source_id in by_id
        ]
        by_source = {source_id: [{**item, "annotation_id": item.get("gt_id")} for item in list_ground_truth_cells(root, source_id)] for source_id in source_ids}
        return sources, by_source, canonical
    # Step 6 candidate reviews are already usable supervision.  Do not require
    # the older whole-source review flag: that flag belongs to the legacy GT
    # flow and prevented explicitly accepted/rejected table cells from reaching
    # the first training round.
    all_sources = db.list_detection_sources()
    by_source = {str(item["source_id"]): _current_table_annotations(db, str(item["source_id"])) for item in all_sources}
    sources = [item for item in all_sources if by_source.get(str(item["source_id"])) or bool(item.get("review_completed"))]
    by_source = {str(item["source_id"]): by_source.get(str(item["source_id"]), []) for item in sources}
    return sources, by_source, None


def _latest_training_feedback(root: Path) -> dict[str, Any]:
    # Late import avoids the comparison -> training import cycle at module load.
    try:
        from .table_model_comparison import latest_completed_training_feedback
        return latest_completed_training_feedback(root)
    except Exception:
        return {"available": False, "fingerprint": "", "model_error_count": 0, "panel_weights": {}}


def _training_panels(
    root: Path, db: TrainingDatabase, sources: list[dict[str, Any]], canonical: dict[str, Any] | None
) -> dict[str, list[dict[str, Any]]]:
    """Return per-source regions for dataset crops.

    Reviewed table-region GT is preferred for training crops. Detector regions are
    the fallback for projects without region GT, and canonical cell GT is the
    stable last fallback. None of these becomes a hard runtime crop for Step 3.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    canonical_sources = (canonical or {}).get("sources") if isinstance(canonical, dict) else {}
    legacy_profile = load_panel_profile(root)
    # One bulk query pair instead of a database.list_detection_table_geometry()
    # (two full-table SELECTs) per source, for the fallback path below.
    geometry_by_source = db.list_detection_table_geometry_by_source()
    for source in sources:
        source_id = str(source.get("source_id") or "")
        regions = list_table_regions(root, source_id)
        if not regions:
            regions = geometry_by_source.get(source_id, {}).get("regions") or []
        panels: list[dict[str, Any]] = []
        for region in regions:
            try:
                box = Box(int(region["x1"]), int(region["y1"]), int(region["x2"]), int(region["y2"]))
            except (KeyError, TypeError, ValueError):
                continue
            panels.append({
                "panel_id": str(region.get("table_id") or region.get("region_id") or f"table-{len(panels) + 1}"),
                "name": str(region.get("table_id") or region.get("label") or f"Tabel {len(panels) + 1}"),
                "box": box,
                "x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2,
            })
        if not panels and isinstance(canonical_sources, dict):
            cells = (canonical_sources.get(source_id) or {}).get("cells") or []
            grouped: dict[str, list[dict[str, Any]]] = {}
            for cell in cells:
                grouped.setdefault(str(cell.get("table_id") or cell.get("panel_id") or "__default__"), []).append(cell)
            for table_id, table_cells in grouped.items():
                try:
                    box = Box(
                        min(int(item["x1"]) for item in table_cells),
                        min(int(item["y1"]) for item in table_cells),
                        max(int(item["x2"]) for item in table_cells),
                        max(int(item["y2"]) for item in table_cells),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                panels.append({"panel_id": table_id, "name": table_id, "box": box, "x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2})
        if not panels and legacy_profile.get("panels"):
            # Compatibility fallback for older workspaces that predate detected
            # table-region geometry. New runs take the branches above first.
            width = int(source.get("image_width") or legacy_profile.get("reference_width") or 0)
            height = int(source.get("image_height") or legacy_profile.get("reference_height") or 0)
            for item in panel_boxes_for_image(legacy_profile, width, height):
                box = item["box"]
                panels.append({
                    "panel_id": str(item.get("panel_id") or ""), "name": str(item.get("name") or ""), "box": box,
                    "x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2,
                })
        if panels:
            result[source_id] = panels
    return result


def table_cell_dataset_preview(workspace: str | Path) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    sources, by_source, canonical = _dataset_source_state(root, db)
    panels_by_source = _training_panels(root, db, sources, canonical)
    panels = [
        {"source_id": source_id, "panel_id": item["panel_id"], "name": item["name"], "x1": item["x1"], "y1": item["y1"], "x2": item["x2"], "y2": item["y2"]}
        for source_id, items in panels_by_source.items() for item in items
    ]
    source_ids = [str(item["source_id"]) for item in sources]
    split = resolve_localization_splits(root, source_ids)
    annotations = [item for source_id in source_ids for item in by_source.get(source_id, [])]
    annotation_count = len(annotations)
    fingerprint = _review_fingerprint(source_splits=dict(split.get("assignments") or {}), panels=panels, annotations=annotations) if panels and sources else ""
    if canonical and int(canonical.get("revision") or 0) == 1 and str(canonical.get("base_review_fingerprint") or ""):
        fingerprint = str(canonical.get("base_review_fingerprint") or "")
    incomplete_gt_sources = [str(item["source_id"]) for item in sources if canonical and not bool(item.get("gt_review_completed"))]
    training_feedback = _latest_training_feedback(root)
    return {
        "ready": bool(panels and sources and annotation_count and not incomplete_gt_sources),
        "review_fingerprint": fingerprint,
        "training_feedback_fingerprint": str(training_feedback.get("fingerprint") or ""),
        "training_feedback": training_feedback,
        "panel_count": len(panels),
        "source_count": len(sources),
        "annotation_count": annotation_count,
        "canonical_ground_truth": bool(canonical),
        "gt_review_open_source_count": len(incomplete_gt_sources),
        "gt_review_open_source_ids": incomplete_gt_sources,
        "splits": dict(split.get("counts") or {}),
        "warnings": list(split.get("warnings") or []),
    }


def build_table_cell_dataset(workspace: str | Path) -> dict[str, Any]:
    from PIL import Image

    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    sources, by_source, canonical = _dataset_source_state(root, db)
    if not sources:
        raise ValueError("Beoordeel eerst minimaal één cel als goedgekeurd in Stap 6")
    if canonical is not None:
        incomplete_gt_sources = [str(item["source_id"]) for item in sources if not bool(item.get("gt_review_completed"))]
        if incomplete_gt_sources:
            raise ValueError(
                f"Controleer eerst alle canonieke GT-bronnen in Stap 4; nog {len(incomplete_gt_sources)} bron(nen) open"
            )
    source_ids = [str(item["source_id"]) for item in sources]
    split_state = resolve_localization_splits(root, source_ids)
    source_splits = dict(split_state.get("assignments") or {})
    all_annotations: list[dict[str, Any]] = []
    for source_id in source_ids:
        all_annotations.extend(by_source.get(source_id, []))
    if not all_annotations:
        raise ValueError("De beoordeelde cellen bevatten nog geen goedgekeurde positieve voorbeelden")
    panels_by_source = _training_panels(root, db, sources, canonical)
    if not panels_by_source:
        raise ValueError("Er zijn nog geen gedetecteerde tabelregio’s beschikbaar")
    profile_panels = [
        {"source_id": source_id, "panel_id": item["panel_id"], "name": item["name"], "x1": item["x1"], "y1": item["y1"], "x2": item["x2"], "y2": item["y2"]}
        for source_id, items in panels_by_source.items() for item in items
    ]

    review_fingerprint = _review_fingerprint(
        source_splits=source_splits, panels=profile_panels, annotations=all_annotations
    )
    training_feedback = _latest_training_feedback(root)
    training_feedback_fingerprint = str(training_feedback.get("fingerprint") or "")
    panel_weights = dict(training_feedback.get("panel_weights") or {})
    dataset_id = _dataset_identity(review_fingerprint + ":" + training_feedback_fingerprint)
    dataset_root = root / DATASET_DIRNAME / dataset_id
    images_root = dataset_root / "images"
    annotations_root = dataset_root / "annotations"
    images_root.mkdir(parents=True, exist_ok=False)
    annotations_root.mkdir(parents=True, exist_ok=True)

    coco: dict[str, dict[str, Any]] = {
        split: {"images": [], "annotations": [], "categories": [{"id": 1, "name": "table_cell"}]}
        for split in SPLIT_NAMES
    }
    split_panel_counts = {split: 0 for split in SPLIT_NAMES}
    split_annotation_counts = {split: 0 for split in SPLIT_NAMES}
    image_id = 1
    annotation_id = 1
    panel_records: list[dict[str, Any]] = []
    hard_example_image_count = 0
    hard_example_panel_count = 0

    for source in sorted(sources, key=lambda item: str(item["source_id"])):
        source_id = str(source["source_id"])
        split = source_splits.get(source_id, "train")
        render_path = root / str(source.get("render_path") or "")
        if not render_path.is_file():
            raise FileNotFoundError(f"Bronrender ontbreekt voor {source_id}: {render_path}")
        with Image.open(render_path) as image:
            image = image.convert("RGB")
            width, height = image.size
            panel_boxes = panels_by_source.get(source_id, [])
            if not panel_boxes:
                raise ValueError(f"Geen gedetecteerde tabelregio beschikbaar voor {source_id}")
            source_annotations = by_source.get(source_id, [])
            for panel in panel_boxes:
                box = panel["box"]
                px1, py1, px2, py2 = box.x1, box.y1, box.x2, box.y2
                panel_annotations = []
                for item in source_annotations:
                    raw_box = (int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"]))
                    if _overlap_fraction(raw_box, (px1, py1, px2, py2)) < 0.60:
                        continue
                    x1 = max(px1, raw_box[0]); y1 = max(py1, raw_box[1])
                    x2 = min(px2, raw_box[2]); y2 = min(py2, raw_box[3])
                    if x2 <= x1 or y2 <= y1:
                        continue
                    panel_annotations.append((item, x1 - px1, y1 - py1, x2 - px1, y2 - py1))

                # Keep reviewed panels even when they contain no positives: the crop is
                # valid background supervision and prevents false positives from becoming
                # invisible to the detector during training.
                panel_id = str(panel.get("panel_id") or f"panel-{len(panel_records)+1}")
                filename = f"{source_id}__{panel_id}.png"
                crop = image.crop((px1, py1, px2, py2))
                crop.save(images_root / filename)
                panel_width, panel_height = crop.size
                image_record = {
                    "id": image_id,
                    "file_name": filename,
                    "width": panel_width,
                    "height": panel_height,
                }
                coco[split]["images"].append(image_record)
                panel_records.append({
                    "source_id": source_id,
                    "panel_id": panel_id,
                    "panel_name": str(panel.get("name") or panel_id),
                    "split": split,
                    "file_name": filename,
                    "box": [px1, py1, px2, py2],
                    "annotation_count": len(panel_annotations),
                    "semantic_side": _panel_semantic_side(db, source_id, panel),
                    "semantic_assignment": _panel_semantic_assignment(db, source_id, panel),
                })
                split_panel_counts[split] += 1
                for item, x1, y1, x2, y2 in panel_annotations:
                    record = {
                        "id": annotation_id,
                        "image_id": image_id,
                        "category_id": 1,
                        "bbox": [x1, y1, x2 - x1, y2 - y1],
                        "area": (x2 - x1) * (y2 - y1),
                        "iscrowd": 0,
                    }
                    coco[split]["annotations"].append(record)
                    annotation_id += 1
                    split_annotation_counts[split] += 1
                image_id += 1

                # Step-7 model errors become hard examples in the *train split
                # only*. Validation/test stay untouched so iteration metrics remain
                # comparable. Functionally-correct geometry is never oversampled.
                panel_key = f"{source_id}::{panel_id}"
                multiplier = max(1, int(panel_weights.get(panel_key, 1) or 1)) if split == "train" else 1
                if multiplier > 1:
                    hard_example_panel_count += 1
                    for hard_index in range(2, multiplier + 1):
                        hard_filename = f"{source_id}__{panel_id}__hard{hard_index}.png"
                        crop.save(images_root / hard_filename)
                        coco[split]["images"].append({
                            "id": image_id,
                            "file_name": hard_filename,
                            "width": panel_width,
                            "height": panel_height,
                            "hard_example_of": filename,
                        })
                        split_panel_counts[split] += 1
                        hard_example_image_count += 1
                        for item, x1, y1, x2, y2 in panel_annotations:
                            coco[split]["annotations"].append({
                                "id": annotation_id,
                                "image_id": image_id,
                                "category_id": 1,
                                "bbox": [x1, y1, x2 - x1, y2 - y1],
                                "area": (x2 - x1) * (y2 - y1),
                                "iscrowd": 0,
                            })
                            annotation_id += 1
                            split_annotation_counts[split] += 1
                        image_id += 1

    for split in SPLIT_NAMES:
        (annotations_root / f"instance_{split}.json").write_text(
            json.dumps(coco[split], indent=2, ensure_ascii=False), encoding="utf-8"
        )

    manifest = {
        "schema_version": 2,
        "dataset_id": dataset_id,
        "type": "table_cell_detection",
        "format": "COCODetDataset",
        "model_family": MODEL_NAME,
        "path": dataset_root.relative_to(root).as_posix(),
        "created_at": utc_now(),
        "review_fingerprint": review_fingerprint,
        "training_feedback_fingerprint": training_feedback_fingerprint,
        "training_feedback": {
            "run_id": str(training_feedback.get("run_id") or ""),
            "model_id": str(training_feedback.get("model_id") or ""),
            "model_error_count": int(training_feedback.get("model_error_count") or 0),
            "decision_counts": dict(training_feedback.get("decision_counts") or {}),
            "policy": str(training_feedback.get("policy") or ""),
        } if training_feedback.get("available") else {},
        "hard_example_panel_count": hard_example_panel_count,
        "hard_example_image_count": hard_example_image_count,
        "panel_profile_updated_at": "",
        "panel_geometry_source": "table_region_gt_or_detected_regions_or_canonical_gt",
        "source_splits": source_splits,
        "source_count": len(sources),
        "panel_count": len(panel_records),
        "annotation_count": len(all_annotations),
        "training_annotation_count": sum(split_annotation_counts.values()),
        "training_image_count": sum(split_panel_counts.values()),
        "splits": {
            split: {
                "sources": sum(1 for value in source_splits.values() if value == split),
                "panels": split_panel_counts[split],
                "annotations": split_annotation_counts[split],
            }
            for split in SPLIT_NAMES
        },
        "panels": panel_records,
        "review_policy": "one functional table cell = one positive bounding box",
        "ground_truth_source": "canonical" if canonical else "initial_step4_review",
    }
    _write_json(dataset_root / "manifest.json", manifest)
    _latest_pointer(root).parent.mkdir(parents=True, exist_ok=True)
    _latest_pointer(root).write_text(dataset_id + "\n", encoding="ascii")
    # The first completed Step-4 dataset becomes the persistent editable baseline.
    # Subsequent builds read the canonical GT and never overwrite it.
    if not canonical:
        bootstrap_table_cell_ground_truth(root)
    return manifest


def validate_table_cell_dataset(workspace: str | Path, dataset: str = "latest") -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    dataset_root = _resolve_dataset(root, dataset)
    errors: list[str] = []
    warnings: list[str] = []
    split_counts: dict[str, dict[str, int]] = {}
    for split in SPLIT_NAMES:
        path = dataset_root / "annotations" / f"instance_{split}.json"
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            errors.append(f"Ongeldige COCO JSON: {path.name}")
            continue
        images = payload.get("images") if isinstance(payload.get("images"), list) else []
        annotations = payload.get("annotations") if isinstance(payload.get("annotations"), list) else []
        image_by_id = {int(item.get("id")): item for item in images if isinstance(item, dict) and item.get("id") is not None}
        for item in images:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("file_name") or "")
            image_path = dataset_root / "images" / filename
            if not image_path.is_file():
                errors.append(f"Afbeelding ontbreekt: {filename}")
        seen: set[tuple[int, int, int, int, int]] = set()
        for annotation in annotations:
            if not isinstance(annotation, dict):
                errors.append(f"Ongeldige annotation in {path.name}")
                continue
            image_id = int(annotation.get("image_id") or -1)
            image = image_by_id.get(image_id)
            bbox = annotation.get("bbox")
            if image is None or not isinstance(bbox, list) or len(bbox) != 4:
                errors.append(f"Ongeldige annotation/image reference in {path.name}")
                continue
            try:
                x, y, w, h = [float(value) for value in bbox]
                width, height = int(image.get("width") or 0), int(image.get("height") or 0)
            except (TypeError, ValueError):
                errors.append(f"Niet-numerieke bbox in {path.name}")
                continue
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width + 0.5 or y + h > height + 0.5:
                errors.append(f"BBox buiten afbeelding in {path.name}: {bbox}")
                continue
            key = (image_id, round(x), round(y), round(w), round(h))
            if key in seen:
                warnings.append(f"Dubbele bbox in {path.name}: image {image_id} {bbox}")
            seen.add(key)
        split_counts[split] = {"images": len(images), "annotations": len(annotations)}
    if split_counts.get("train", {}).get("images", 0) < 1:
        errors.append("Train-split bevat geen panelafbeeldingen")
    if split_counts.get("val", {}).get("images", 0) < 1:
        warnings.append("Validation-split is leeg; modelverbetering kan dan niet betrouwbaar worden beoordeeld")
    report = {
        "dataset_id": dataset_root.name,
        "dataset_path": dataset_root.relative_to(root).as_posix(),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "splits": split_counts,
        "validated_at": utc_now(),
    }
    _write_json(dataset_root / "validation.json", report)
    return report


def latest_table_cell_dataset(workspace: str | Path) -> dict[str, Any] | None:
    root = resolve_project_workspace(workspace)
    try:
        dataset_root = _resolve_dataset(root, "latest")
    except FileNotFoundError:
        return None
    manifest = _read_json(dataset_root / "manifest.json", {}) or {}
    validation = _read_json(dataset_root / "validation.json", {}) or {}
    return {**manifest, "validation": validation}


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    lx1, ly1, lx2, ly2 = left
    rx1, ry1, rx2, ry2 = right
    ix1, iy1 = max(lx1, rx1), max(ly1, ry1)
    ix2, iy2 = min(lx2, rx2), min(ly2, ry2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = max(1e-9, (lx2-lx1)*(ly2-ly1) + (rx2-rx1)*(ry2-ry1) - inter)
    return inter / union


def _prediction_box(item: dict[str, Any]) -> tuple[float, float, float, float] | None:
    raw = item.get("coordinate") or item.get("bbox") or item.get("box")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        values = tuple(float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if str(item.get("bbox_format") or "xyxy").lower() in {"xywh", "coco"}:
        x, y, w, h = values
        return x, y, x + w, y + h
    return values  # type: ignore[return-value]


# A single (confidence, IoU) operating point is easy to saturate on a small,
# fixed validation split: confidence=0.25 is a permissive acceptance bar and
# IoU=0.50 is a loose overlap requirement, so "1.0 precision/recall" there does
# not mean the detector is flawless -- it means this split no longer
# discriminates at that point. The sweep below re-scores the same predictions
# at stricter combinations so a run-over-run comparison has somewhere to move.
DEFAULT_SWEEP_CONFIDENCE_THRESHOLDS: tuple[float, ...] = (0.10, 0.25, 0.50, 0.75, 0.90)
DEFAULT_SWEEP_IOU_THRESHOLDS: tuple[float, ...] = (0.50, 0.65, 0.75, 0.85, 0.95)
_SATURATION_EPSILON = 1e-9


def _load_table_cell_predictions_by_stem(
    predictions_payload: dict[str, Any], images: list[dict[str, Any]]
) -> dict[str, list[tuple[float, tuple[float, float, float, float]]]]:
    """Parse the raw prediction JSON once so a threshold sweep can reuse it."""
    predictions = predictions_payload.get("predictions") if isinstance(predictions_payload, dict) else {}
    if not isinstance(predictions, dict):
        raise ValueError("Prediction-bestand bevat geen predictions-object")
    scored_by_stem: dict[str, list[tuple[float, tuple[float, float, float, float]]]] = {}
    for image in images:
        if not isinstance(image, dict):
            continue
        stem = Path(str(image.get("file_name") or "")).stem
        raw_predictions = predictions.get(stem) if isinstance(predictions.get(stem), list) else []
        scored: list[tuple[float, tuple[float, float, float, float]]] = []
        for item in raw_predictions:
            if not isinstance(item, dict):
                continue
            try:
                score = float(item.get("score") or item.get("confidence") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            box = _prediction_box(item)
            if box is not None:
                scored.append((score, box))
        scored_by_stem[stem] = scored
    return scored_by_stem


def _score_table_cell_operating_point(
    images: list[dict[str, Any]],
    gt_by_image: dict[int, list[tuple[float, float, float, float]]],
    scored_by_stem: dict[str, list[tuple[float, tuple[float, float, float, float]]]],
    *,
    confidence: float,
    iou_threshold: float,
) -> dict[str, Any]:
    """Match predictions against ground truth at one (confidence, IoU) point."""
    tp = fp = fn = 0
    image_results = []
    for image in images:
        if not isinstance(image, dict):
            continue
        image_id = int(image.get("id") or -1)
        stem = Path(str(image.get("file_name") or "")).stem
        truth = list(gt_by_image.get(image_id, []))
        pred = sorted(
            (row for row in scored_by_stem.get(stem, []) if row[0] >= confidence),
            key=lambda row: row[0], reverse=True,
        )
        matched_truth: set[int] = set()
        image_tp = 0
        image_fp = 0
        for score, box in pred:
            best_index = -1
            best_iou = 0.0
            for index, gt in enumerate(truth):
                if index in matched_truth:
                    continue
                current = _iou(box, gt)
                if current > best_iou:
                    best_iou = current
                    best_index = index
            if best_index >= 0 and best_iou >= iou_threshold:
                matched_truth.add(best_index)
                image_tp += 1
            else:
                image_fp += 1
        image_fn = len(truth) - len(matched_truth)
        tp += image_tp; fp += image_fp; fn += image_fn
        image_results.append({"file_name": image.get("file_name"), "tp": image_tp, "fp": image_fp, "fn": image_fn})

    recall = tp / max(1, tp + fn)
    precision = tp / max(1, tp + fp)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return {
        "confidence": confidence,
        "iou_threshold": iou_threshold,
        "tp": tp, "fp": fp, "fn": fn,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "false_positives_per_panel": fp / max(1, len(images)),
        "images": image_results,
    }


def evaluate_table_cell_predictions(
    workspace: str | Path,
    predictions_path: str | Path,
    *,
    dataset_id: str = "latest",
    split: str = "val",
    confidence: float = 0.25,
    iou_threshold: float = 0.50,
    confidence_thresholds: Iterable[float] | None = None,
    iou_thresholds: Iterable[float] | None = None,
) -> dict[str, Any]:
    """Evaluate predictions at one operating point, plus a stricter sweep.

    The top-level ``tp``/``fp``/``fn``/``precision``/``recall``/``f1``/``images``
    fields are the single point at ``confidence``/``iou_threshold`` exactly as
    before (existing callers/consumers are unaffected). ``sweep`` additionally
    re-scores the same predictions across a grid of stricter confidence/IoU
    combinations (``confidence_thresholds`` x ``iou_thresholds``, defaulting to
    ``DEFAULT_SWEEP_CONFIDENCE_THRESHOLDS``/``DEFAULT_SWEEP_IOU_THRESHOLDS``) so
    a run that already scores 1.0 at the loose default point still has
    somewhere to show a regression or an improvement.
    """
    if split not in SPLIT_NAMES:
        raise ValueError(f"Onbekende split: {split}")
    root = resolve_project_workspace(workspace)
    dataset_root = _resolve_dataset(root, dataset_id)
    ground_truth = _read_json(dataset_root / "annotations" / f"instance_{split}.json", {}) or {}
    predictions_payload = _read_json(Path(predictions_path), {}) or {}
    images = ground_truth.get("images") if isinstance(ground_truth.get("images"), list) else []
    annotations = ground_truth.get("annotations") if isinstance(ground_truth.get("annotations"), list) else []
    gt_by_image: dict[int, list[tuple[float, float, float, float]]] = {}
    for item in annotations:
        if not isinstance(item, dict) or not isinstance(item.get("bbox"), list) or len(item["bbox"]) != 4:
            continue
        x, y, w, h = [float(value) for value in item["bbox"]]
        gt_by_image.setdefault(int(item.get("image_id") or -1), []).append((x, y, x+w, y+h))
    scored_by_stem = _load_table_cell_predictions_by_stem(predictions_payload, images)

    primary = _score_table_cell_operating_point(
        images, gt_by_image, scored_by_stem, confidence=confidence, iou_threshold=iou_threshold
    )

    sweep_confidences = sorted({
        max(0.0, min(1.0, float(value)))
        for value in (*(confidence_thresholds or DEFAULT_SWEEP_CONFIDENCE_THRESHOLDS), confidence)
    })
    sweep_ious = sorted({
        max(0.0, min(1.0, float(value)))
        for value in (*(iou_thresholds or DEFAULT_SWEEP_IOU_THRESHOLDS), iou_threshold)
    })
    sweep: list[dict[str, Any]] = []
    for sweep_confidence in sweep_confidences:
        for sweep_iou in sweep_ious:
            point = _score_table_cell_operating_point(
                images, gt_by_image, scored_by_stem, confidence=sweep_confidence, iou_threshold=sweep_iou
            )
            sweep.append({key: value for key, value in point.items() if key != "images"})

    saturated = bool(images) and (
        abs(primary["precision"] - 1.0) < _SATURATION_EPSILON and abs(primary["recall"] - 1.0) < _SATURATION_EPSILON
    )
    # The highest IoU threshold (at the requested confidence) that is still a
    # clean match. A saturated primary point that only holds up to IoU 0.55
    # is much weaker evidence than one that holds to 0.95, even though both
    # report precision=recall=1.0 at the loose default point.
    strictest_clean_iou_threshold = max(
        (
            point["iou_threshold"] for point in sweep
            if abs(point["confidence"] - confidence) < _SATURATION_EPSILON and point["fp"] == 0 and point["fn"] == 0
        ),
        default=None,
    )
    note = ""
    if saturated:
        note = (
            f"Precisie/recall/F1 zijn 1.0 bij confidence={confidence}/IoU={iou_threshold} op maar "
            f"{len(images)} panelen -- dat is het zachtste punt in de sweep en verzadigt makkelijk op een "
            "kleine, vaste validatieset. Het zegt dat dit meetpunt hier niet meer onderscheidt, niet dat het "
            "model foutloos is. Vergelijk 'strictest_clean_iou_threshold' en 'sweep' tussen trainingsronden "
            "om een echt verschil te zien."
        )

    report = {
        "dataset_id": dataset_root.name,
        "split": split,
        "confidence": confidence,
        "iou_threshold": iou_threshold,
        "tp": primary["tp"], "fp": primary["fp"], "fn": primary["fn"],
        "recall": primary["recall"],
        "precision": primary["precision"],
        "f1": primary["f1"],
        "false_positives_per_panel": primary["false_positives_per_panel"],
        "panel_count": len(images),
        "evaluated_at": utc_now(),
        "images": primary["images"],
        "saturated": saturated,
        "strictest_clean_iou_threshold": strictest_clean_iou_threshold,
        "sweep": sweep,
        "note": note,
    }
    return report


def _models_root(root: Path) -> Path:
    return root / MODEL_DIRNAME


def register_table_cell_model(
    workspace: str | Path,
    *,
    model_id: str,
    run_id: str,
    dataset_id: str,
    inference_dir: str | Path,
    device: str,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    source = Path(inference_dir)
    if not source.is_dir():
        raise FileNotFoundError(f"Inference model ontbreekt: {source}")
    model_root = _models_root(root) / model_id
    target = model_root / "inference"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    # Docker Desktop bind mounts on Windows do not reliably support POSIX
    # metadata operations used by shutil.copytree(copy_function=copy2).  Model
    # registration only needs the exported bytes and directory structure, not
    # ownership/mode/timestamp preservation.  Copy bytes explicitly so a fully
    # trained run cannot fail at the final registration step because copystat
    # is unsupported by the host filesystem.
    copied_files = 0
    try:
        for item in source.rglob("*"):
            relative = item.relative_to(source)
            destination = target / relative
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if item.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, destination)
                copied_files += 1
    except OSError as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise RuntimeError(
            f"Table-cell inference model kopieren mislukt: {source} -> {target}: {exc}"
        ) from exc
    if copied_files == 0:
        shutil.rmtree(target, ignore_errors=True)
        raise FileNotFoundError(f"Inference model bevat geen bestanden: {source}")

    run_metadata = _read_json(root / RUN_DIRNAME / run_id / "table_cell_run.json", {}) or {}
    run_metadata = run_metadata if isinstance(run_metadata, dict) else {}
    payload = {
        "model_id": model_id,
        "model_name": MODEL_NAME,
        "run_id": run_id,
        "parent_model_id": str(run_metadata.get("parent_model_id") or ""),
        "training_mode": str(run_metadata.get("training_mode") or "fresh"),
        "learning_rate": run_metadata.get("learning_rate"),
        "epochs": run_metadata.get("epochs"),
        "dataset_id": dataset_id,
        "device": device,
        "inference_dir": target.relative_to(root).as_posix(),
        "evaluation": evaluation or {},
        "created_at": utc_now(),
        "active": False,
    }
    _write_json(model_root / "model.json", payload)
    (_models_root(root) / "latest.txt").write_text(model_id + "\n", encoding="ascii")
    return payload


def list_table_cell_models(workspace: str | Path) -> list[dict[str, Any]]:
    root = resolve_project_workspace(workspace)
    base = _models_root(root)
    active = _read_json(base / "active.json", {}) or {}
    active_id = str(active.get("model_id") or "") if isinstance(active, dict) else ""
    models = []
    if base.is_dir():
        for path in base.iterdir():
            if not path.is_dir():
                continue
            payload = _read_json(path / "model.json", {}) or {}
            if not isinstance(payload, dict) or not payload.get("model_id"):
                continue
            item = dict(payload)
            item["active"] = str(item.get("model_id") or "") == active_id
            models.append(item)
    return sorted(models, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def table_cell_model_history(workspace: str | Path) -> dict[str, Any]:
    """Chronological trend of registered table-cell models and their evaluation.

    A single run's ``evaluate_table_cell_predictions`` report cannot tell you
    whether a fixed, small validation split has stopped discriminating between
    model generations -- it only knows about the run it was called for. This
    walks every registered model (``list_table_cell_models``, which already
    stores each model's ``evaluation`` payload) in training order so a
    saturated metric across several consecutive rounds is visible at a glance,
    without needing any new persistent storage.
    """
    models = sorted(list_table_cell_models(workspace), key=lambda item: str(item.get("created_at") or ""))
    rows: list[dict[str, Any]] = []
    for model in models:
        evaluation = model.get("evaluation") if isinstance(model.get("evaluation"), dict) else {}
        rows.append({
            "model_id": str(model.get("model_id") or ""),
            "created_at": str(model.get("created_at") or ""),
            "active": bool(model.get("active")),
            "training_mode": str(model.get("training_mode") or ""),
            "learning_rate": model.get("learning_rate"),
            "epochs": model.get("epochs"),
            "dataset_id": str(model.get("dataset_id") or ""),
            "precision": evaluation.get("precision"),
            "recall": evaluation.get("recall"),
            "f1": evaluation.get("f1"),
            "panel_count": evaluation.get("panel_count"),
            # Only present for evaluations produced after the sweep was added;
            # older registered models simply report these as null/absent.
            "saturated": evaluation.get("saturated"),
            "strictest_clean_iou_threshold": evaluation.get("strictest_clean_iou_threshold"),
        })

    saturated_streak = 0
    for row in reversed(rows):
        if row["saturated"] is not True:
            break
        saturated_streak += 1

    note = ""
    if saturated_streak >= 2:
        note = (
            f"De laatste {saturated_streak} geregistreerde modellen scoren allemaal 'saturated' (precisie/recall "
            "1.0 op het standaard meetpunt). Deze validatiesplit onderscheidt momenteel geen modelgeneraties meer "
            "-- vergroot of verlevendig de vaste val-set, of vertrouw voor vergelijkingen tussen ronden op "
            "'strictest_clean_iou_threshold' en de bredere COCO-AP uit de trainingslog in plaats van dit getal."
        )

    return {
        "model_count": len(rows),
        "saturated_streak": saturated_streak,
        "note": note,
        "models": rows,
    }


def active_table_cell_model(workspace: str | Path) -> dict[str, Any] | None:
    root = resolve_project_workspace(workspace)
    payload = _read_json(_models_root(root) / "active.json", {}) or {}
    if not isinstance(payload, dict) or not payload.get("model_id"):
        return None
    relative = str(payload.get("inference_dir") or "")
    path = root / relative
    if not path.is_dir():
        return None
    return {**payload, "inference_path": str(path)}


def activate_table_cell_model(workspace: str | Path, model_id: str = "latest") -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    base = _models_root(root)
    if model_id == "latest":
        pointer = base / "latest.txt"
        if not pointer.is_file():
            raise FileNotFoundError("Er is nog geen getraind table-cell model")
        model_id = pointer.read_text(encoding="utf-8-sig").strip()
    model = _read_json(base / model_id / "model.json", {}) or {}
    if not isinstance(model, dict) or str(model.get("model_id") or "") != model_id:
        raise FileNotFoundError(f"Table-cell model niet gevonden: {model_id}")
    inference_dir = root / str(model.get("inference_dir") or "")
    if not inference_dir.is_dir():
        raise FileNotFoundError(f"Inference directory ontbreekt voor {model_id}")
    evaluation = model.get("evaluation") if isinstance(model.get("evaluation"), dict) else {}
    if evaluation and float(evaluation.get("f1") or 0.0) <= 0.0:
        raise ValueError(
            f"Model {model_id} mag niet worden geactiveerd: de vaste validatie heeft F1=0 "
            f"({evaluation.get('tp', 0)} TP, {evaluation.get('fp', 0)} FP, {evaluation.get('fn', 0)} FN)."
        )
    payload = {**model, "active": True, "activated_at": utc_now()}
    _write_json(base / "active.json", payload)
    return payload


def table_cell_training_state(workspace: str | Path) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    dataset = latest_table_cell_dataset(root)
    models = list_table_cell_models(root)
    active = active_table_cell_model(root)
    latest_run = None
    runs_root = root / RUN_DIRNAME
    pointer = runs_root / "latest.txt"
    if pointer.is_file():
        run_id = pointer.read_text(encoding="utf-8-sig").strip()
        latest_run = _read_json(runs_root / run_id / "table_cell_run.json", {}) or None
    preview = table_cell_dataset_preview(root)
    dataset_current = bool(
        dataset
        and preview.get("review_fingerprint")
        and dataset.get("review_fingerprint") == preview.get("review_fingerprint")
        and str(dataset.get("training_feedback_fingerprint") or "") == str(preview.get("training_feedback_fingerprint") or "")
    )
    return {
        "preview": preview,
        "dataset": dataset,
        "dataset_current": dataset_current,
        "models": models,
        "latest_model": models[0] if models else None,
        "active_model": active,
        "latest_run": latest_run,
        "training_feedback": preview.get("training_feedback") or {},
    }
