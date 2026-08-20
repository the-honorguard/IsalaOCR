from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .db import TrainingDatabase
from .projects import resolve_project_workspace
from .table_cell_ground_truth import list_ground_truth_cells, list_ground_truth_sources

EXTRACTION_METHOD = "canonical_gt_cell"
STALE_EXTRACTION_METHOD = "canonical_gt_cell_stale"
PROFILE = "recognition_ground_truth"


def _safe_id(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return text or hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:20]


def _crop_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recognition_gt_counts(database: TrainingDatabase) -> dict[str, int]:
    with database.connect() as db:
        row = db.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS accepted,
                SUM(CASE WHEN status IN ('unreadable','excluded','no_value') THEN 1 ELSE 0 END) AS excluded
            FROM samples
            WHERE extraction_method=?
            """,
            (EXTRACTION_METHOD,),
        ).fetchone()
    return {
        "total": int(row["total"] or 0),
        "pending": int(row["pending"] or 0),
        "accepted": int(row["accepted"] or 0),
        "excluded": int(row["excluded"] or 0),
    }


def materialize_recognition_ground_truth(
    workspace: str | Path,
    *,
    recognition_engine: Any | None = None,
) -> dict[str, Any]:
    """Materialize neutral crop->text samples directly from canonical geometry GT.

    This is Model Factory input. It deliberately has no dependency on Mapping
    Studio, field definitions, aliases, units, application profiles or structured
    output. Every canonical table-cell GT box becomes a recognition sample.
    """
    import cv2

    root = resolve_project_workspace(workspace)
    database = TrainingDatabase(root / "samples.sqlite3")
    output_root = root / "recognition_ground_truth" / "crops"
    output_root.mkdir(parents=True, exist_ok=True)

    expected_ids: set[str] = set()
    created = 0
    updated = 0
    source_count = 0
    recognized = 0

    for source in list_ground_truth_sources(root):
        source_id = str(source.get("source_id") or "").strip()
        cells = list_ground_truth_cells(root, source_id)
        if not source_id or not cells:
            continue
        render_path = root / "source_renders" / f"{source_id}.png"
        image = cv2.imread(str(render_path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"Bronrender ontbreekt voor Recognition GT: {render_path}")
        height, width = image.shape[:2]
        prepared: list[tuple[dict[str, Any], Any, Path, str]] = []
        source_dir = output_root / _safe_id(source_id)
        source_dir.mkdir(parents=True, exist_ok=True)

        for cell in cells:
            gt_id = str(cell.get("gt_id") or "").strip()
            if not gt_id:
                continue
            x1 = max(0, min(width, int(cell.get("x1") or 0)))
            y1 = max(0, min(height, int(cell.get("y1") or 0)))
            x2 = max(0, min(width, int(cell.get("x2") or 0)))
            y2 = max(0, min(height, int(cell.get("y2") or 0)))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = image[y1:y2, x1:x2].copy()
            crop_path = source_dir / f"{_safe_id(gt_id)}.png"
            if not cv2.imwrite(str(crop_path), crop):
                raise OSError(f"Kon Recognition-GT-crop niet schrijven: {crop_path}")
            sample_id = f"recgt-{_safe_id(gt_id)}"
            expected_ids.add(sample_id)
            prepared.append((cell, crop, crop_path, sample_id))

        recognized_rows: list[list[Any]] = [[] for _ in prepared]
        if recognition_engine is not None and prepared:
            recognition_engine.warmup()
            recognized_rows = recognition_engine.recognize_many([item[1] for item in prepared])
            recognized += len(prepared)

        for index, (cell, crop, crop_path, sample_id) in enumerate(prepared):
            tokens = recognized_rows[index] if index < len(recognized_rows) else []
            raw_text = " ".join(str(token.text) for token in tokens if str(token.text)).strip()
            confidence = min((float(token.confidence) for token in tokens), default=0.0)
            gt_id = str(cell.get("gt_id") or "")
            panel_name = str(cell.get("panel_name") or cell.get("panel_id") or "Tabelcel")
            relative_crop = crop_path.relative_to(root).as_posix()
            was_created = database.upsert_sample({
                "sample_id": sample_id,
                "source_id": source_id,
                "profile": PROFILE,
                "field_key": f"recognition.{_safe_id(gt_id)}",
                "field_label": panel_name,
                "crop_path": relative_crop,
                "raw_ocr": raw_text,
                "raw_confidence": confidence,
                "raw_variant": "baseline_recognition_gt" if recognition_engine is not None else "awaiting_baseline_recognition",
                "image_width": width,
                "image_height": height,
                "roi_x1": int(cell.get("x1") or 0),
                "roi_y1": int(cell.get("y1") or 0),
                "roi_x2": int(cell.get("x2") or 0),
                "roi_y2": int(cell.get("y2") or 0),
                "extraction_method": EXTRACTION_METHOD,
                "locator_confidence": 1.0,
                "locator_label_text": "",
                "locator_version": "canonical_table_cell_gt_v1",
                "crop_sha256": _crop_hash(crop_path),
            })
            # Geometry has already been approved in the canonical table-cell GT.
            # Recognition review therefore starts directly at crop -> exact text.
            database.review_roi(sample_id, "correct", "Canonieke table-cell Ground Truth")
            created += int(was_created)
            updated += int(not was_created)
        source_count += 1

    # Deleted/moved canonical cells must never remain eligible for a future
    # recognition dataset. Preserve their review history, but park them as stale.
    with database.connect() as db:
        rows = db.execute(
            "SELECT sample_id FROM samples WHERE extraction_method=?",
            (EXTRACTION_METHOD,),
        ).fetchall()
        stale_ids = [str(row["sample_id"]) for row in rows if str(row["sample_id"]) not in expected_ids]
        for sample_id in stale_ids:
            db.execute(
                "UPDATE samples SET extraction_method=?, roi_review_status='deferred', updated_at=datetime('now') WHERE sample_id=?",
                (STALE_EXTRACTION_METHOD, sample_id),
            )

    return {
        "source_count": source_count,
        "sample_count": len(expected_ids),
        "created": created,
        "updated": updated,
        "recognized": recognized,
        "stale": len(stale_ids),
        "counts": recognition_gt_counts(database),
        "extraction_method": EXTRACTION_METHOD,
    }
