from __future__ import annotations

import hashlib
import json
import shutil
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import Box
from .projects import resolve_project_workspace
from .db import TrainingDatabase, utc_now


SPLIT_NAMES = ("train", "val", "test")
SPLIT_CONFIG_FILENAME = "localization_split_config.json"
SPLIT_PENDING_FILENAME = "localization_split_pending.flag"


def _legacy_split_for_source(source_id: str) -> str:
    """Historical 70/15/15 hash split, kept only for old dataset compatibility."""
    bucket = int(hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 70:
        return "train"
    if bucket < 85:
        return "val"
    return "test"


def _split_for_source(source_id: str) -> str:
    """Deprecated compatibility helper for code/tests predating configurable splits."""
    return _legacy_split_for_source(source_id)


def _safe_auto_split_targets(source_count: int) -> dict[str, int]:
    """Return deterministic targets that keep a useful hold-out set for small projects.

    From eight completed sources onward we reserve at least two validation images
    and three test images. With 14 sources this intentionally becomes 9/2/3.
    Tiny projects still retain at least one train and one validation image where
    mathematically possible.
    """
    n = max(0, int(source_count))
    if n == 0:
        return {"train": 0, "val": 0, "test": 0}
    if n == 1:
        return {"train": 1, "val": 0, "test": 0}
    if n == 2:
        return {"train": 1, "val": 1, "test": 0}
    if n < 8:
        return {"train": n - 2, "val": 1, "test": 1}
    val = max(2, int(round(n * 0.15)))
    test = max(3, int(round(n * 0.15)))
    # Always leave at least one training source. Prefer shrinking validation
    # before the test set because the detection gate consumes the test split.
    while val + test >= n and val > 1:
        val -= 1
    while val + test >= n and test > 1:
        test -= 1
    return {"train": n - val - test, "val": val, "test": test}


def _split_config_path(root: Path) -> Path:
    return root / SPLIT_CONFIG_FILENAME


def load_localization_split_config(workspace: str | Path) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    path = _split_config_path(root)
    if not path.is_file():
        return {"mode": "auto", "targets": {}, "overrides": {}, "updated_at": ""}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {"mode": "auto", "targets": {}, "overrides": {}, "updated_at": ""}
    if not isinstance(payload, dict):
        return {"mode": "auto", "targets": {}, "overrides": {}, "updated_at": ""}
    mode = str(payload.get("mode") or "auto")
    if mode not in {"auto", "counts"}:
        mode = "auto"
    raw_targets = payload.get("targets") if isinstance(payload.get("targets"), dict) else {}
    targets = {name: max(0, int(raw_targets.get(name) or 0)) for name in SPLIT_NAMES}
    raw_overrides = payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {}
    overrides = {str(source_id): str(split) for source_id, split in raw_overrides.items() if str(split) in SPLIT_NAMES}
    return {"mode": mode, "targets": targets, "overrides": overrides, "updated_at": str(payload.get("updated_at") or "")}


def _stable_source_order(source_ids: list[str]) -> list[str]:
    return sorted(source_ids, key=lambda source_id: (hashlib.sha256(source_id.encode("utf-8")).hexdigest(), source_id))


def resolve_localization_splits(workspace: str | Path, source_ids: list[str] | set[str]) -> dict[str, Any]:
    """Resolve exact per-source train/val/test assignment for preview and build."""
    root = resolve_project_workspace(workspace)
    ids = sorted({str(source_id) for source_id in source_ids})
    config = load_localization_split_config(root)
    auto_targets = _safe_auto_split_targets(len(ids))
    requested = dict(auto_targets)
    warnings: list[str] = []
    if config["mode"] == "counts":
        candidate = {name: int(config["targets"].get(name) or 0) for name in SPLIT_NAMES}
        if sum(candidate.values()) == len(ids) and (not ids or candidate["train"] > 0):
            requested = candidate
        else:
            warnings.append(
                f"Opgeslagen split-aantallen ({candidate['train']}/{candidate['val']}/{candidate['test']}) "
                f"passen niet bij {len(ids)} afgeronde afbeeldingen; veilige automatische verdeling wordt gebruikt."
            )
    overrides = {source_id: split for source_id, split in config["overrides"].items() if source_id in ids}
    fixed_counts = {name: sum(1 for split in overrides.values() if split == name) for name in SPLIT_NAMES}
    if any(fixed_counts[name] > requested[name] for name in SPLIT_NAMES):
        warnings.append("Handmatige bron-splits overschrijden de ingestelde aantallen; de verdeling is automatisch hersteld.")
        overrides = {}
        fixed_counts = {name: 0 for name in SPLIT_NAMES}

    assignment = dict(overrides)
    remaining = [source_id for source_id in _stable_source_order(ids) if source_id not in assignment]
    for split in SPLIT_NAMES:
        need = max(0, requested[split] - fixed_counts[split])
        if need <= 0:
            continue
        # Preserve the historical hash preference where possible, but enforce the
        # exact configured split counts. This keeps existing projects relatively
        # stable while fixing small-dataset 10/2/2-style outcomes.
        preferred = [source_id for source_id in remaining if _legacy_split_for_source(source_id) == split]
        chosen = preferred[:need]
        if len(chosen) < need:
            chosen.extend(source_id for source_id in remaining if source_id not in chosen)
            chosen = chosen[:need]
        for source_id in chosen:
            assignment[source_id] = split
        chosen_set = set(chosen)
        remaining = [source_id for source_id in remaining if source_id not in chosen_set]
    # Defensive fallback for malformed future configs; never silently drop a source.
    for source_id in remaining:
        assignment[source_id] = "train"
    actual = {name: sum(1 for split in assignment.values() if split == name) for name in SPLIT_NAMES}
    return {
        "mode": config["mode"],
        "targets": requested,
        "auto_targets": auto_targets,
        "overrides": overrides,
        "assignments": assignment,
        "counts": actual,
        "warnings": warnings,
        "updated_at": config.get("updated_at") or "",
    }


def save_localization_split_config(
    workspace: str | Path, *, mode: str, targets: dict[str, int] | None = None, overrides: dict[str, str] | None = None
) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    eligible = sorted(str(item["source_id"]) for item in db.list_detection_sources() if bool(item.get("review_completed")))
    if mode not in {"auto", "counts"}:
        raise ValueError("Splitmodus moet 'auto' of 'counts' zijn")
    if mode == "auto":
        normalized_targets = _safe_auto_split_targets(len(eligible))
    else:
        targets = targets or {}
        normalized_targets = {name: max(0, int(targets.get(name) or 0)) for name in SPLIT_NAMES}
        if sum(normalized_targets.values()) != len(eligible):
            raise ValueError(
                f"Train + val + test moet exact {len(eligible)} afgeronde afbeeldingen zijn "
                f"(nu {sum(normalized_targets.values())})."
            )
        if eligible and normalized_targets["train"] < 1:
            raise ValueError("Minimaal één afgeronde afbeelding moet in train staan.")
    normalized_overrides = {
        str(source_id): str(split) for source_id, split in (overrides or {}).items()
        if str(source_id) in eligible and str(split) in SPLIT_NAMES
    }
    fixed_counts = {name: sum(1 for split in normalized_overrides.values() if split == name) for name in SPLIT_NAMES}
    for name in SPLIT_NAMES:
        if fixed_counts[name] > normalized_targets[name]:
            raise ValueError(
                f"Er zijn {fixed_counts[name]} handmatige {name}-keuzes, maar het doel voor {name} is {normalized_targets[name]}."
            )
    before = resolve_localization_splits(root, eligible)
    payload = {
        "schema_version": 1,
        "mode": mode,
        "targets": normalized_targets,
        "overrides": normalized_overrides,
        "updated_at": utc_now(),
    }
    _split_config_path(root).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    after = resolve_localization_splits(root, eligible)
    if before.get("assignments") != after.get("assignments"):
        (root / SPLIT_PENDING_FILENAME).write_text(str(payload["updated_at"]) + "\n", encoding="utf-8")
    return after


def _dataset_source_splits(root: Path, dataset_id: str = "") -> dict[str, str]:
    """Read immutable split membership from a built dataset manifest."""
    try:
        dataset_root = _resolve_dataset(root, dataset_id or "latest")
        manifest = json.loads((dataset_root / "manifest.json").read_text(encoding="utf-8"))
        mapping = manifest.get("source_splits") if isinstance(manifest, dict) else None
        if isinstance(mapping, dict):
            return {str(source_id): str(split) for source_id, split in mapping.items() if str(split) in SPLIT_NAMES}
    except (OSError, ValueError, TypeError, FileNotFoundError):
        pass
    return {}


def _dataset_id(annotations: list[dict[str, Any]], source_ids: set[str], source_splits: dict[str, str] | None = None) -> str:
    # Positive, ignored and negative-only reviewed images all influence the
    # immutable dataset identity.
    geometry = [
        f"{item.get('training_role','positive')}:{item['source_id']}:{item['x1']},{item['y1']},{item['x2']},{item['y2']}"
        for item in sorted(annotations, key=lambda row: (row["source_id"], row["y1"], row["x1"], row.get("training_role", "positive")))
    ]
    payload = "|".join([*(f"source:{source_id}:{(source_splits or {}).get(source_id, '')}" for source_id in sorted(source_ids)), *geometry])
    # Microseconds prevent a repeated build of unchanged ground truth in the same
    # second from colliding with an existing immutable dataset directory.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"loc-{stamp}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:8]}"


def _context_patch_box(box: Box, *, image_width: int, image_height: int) -> Box:
    """Return a compact training window around one explicitly reviewed region."""
    pad_x = max(24, int(round(box.width * 1.25)))
    pad_y = max(18, int(round(box.height * 2.0)))
    return Box(
        max(0, box.x1 - pad_x), max(0, box.y1 - pad_y),
        min(image_width, box.x2 + pad_x), min(image_height, box.y2 + pad_y),
    )



def localization_dataset_preview(workspace: str | Path) -> dict[str, Any]:
    """Return the exact source/ROI selection that a localization build will use.

    Only sources explicitly marked ``review_completed`` are eligible. This preview
    intentionally uses the same detection annotations and split function as the
    builder so the UI cannot promise a different dataset than the build creates.
    """
    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    annotations = db.list_detection_annotations(active_only=True, include_ignored=True)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in annotations:
        by_source.setdefault(str(item["source_id"]), []).append(item)
    rows: list[dict[str, Any]] = []
    totals = {
        "sources": 0, "ready_sources": 0, "excluded_sources": 0,
        "candidate_rois": 0, "pending_rois": 0, "positive_rois": 0,
        "negative_rois": 0, "adjusted_rois": 0, "incorrect_rois": 0,
        "irrelevant_rois": 0, "added_rois": 0,
    }
    ready_ids = [str(source["source_id"]) for source in db.list_detection_sources() if bool(source.get("review_completed"))]
    split_plan = resolve_localization_splits(root, ready_ids)
    split_counts = {"train": 0, "val": 0, "test": 0}
    for source in db.list_detection_sources():
        source_id = str(source["source_id"])
        counts = db.detection_review_counts(source_id)
        ready = bool(source.get("review_completed"))
        source_annotations = by_source.get(source_id, [])
        positive = sum(1 for item in source_annotations if str(item.get("training_role") or "positive") == "positive")
        negative = sum(1 for item in source_annotations if str(item.get("training_role") or "positive") == "negative")
        split = str(split_plan["assignments"].get(source_id) or "") if ready else ""
        rows.append({
            "source_id": source_id,
            "ready": ready,
            "included": ready,
            "completed_at": source.get("review_completed_at"),
            "split": split,
            "split_override": split_plan["overrides"].get(source_id, ""),
            "candidate_total": int(counts.get("candidate_total") or 0),
            "pending": int(counts.get("pending") or 0),
            "positive": positive,
            "negative": negative,
            "adjusted": int(counts.get("adjusted") or 0),
            "incorrect": int(counts.get("rejected") or 0),
            "irrelevant": int(counts.get("irrelevant") or 0),
            "added": int(counts.get("added") or 0),
            "render_path": str(source.get("render_path") or ""),
        })
        totals["sources"] += 1
        totals["candidate_rois"] += int(counts.get("candidate_total") or 0)
        # Pending is intentionally global: it explains why non-completed source
        # images are still excluded from the training set. All actual training
        # ROI counters below are restricted to completed/eligible sources.
        totals["pending_rois"] += int(counts.get("pending") or 0)
        if ready:
            totals["ready_sources"] += 1
            totals["positive_rois"] += positive
            totals["negative_rois"] += negative
            totals["adjusted_rois"] += int(counts.get("adjusted") or 0)
            totals["incorrect_rois"] += int(counts.get("rejected") or 0)
            totals["irrelevant_rois"] += int(counts.get("irrelevant") or 0)
            totals["added_rois"] += int(counts.get("added") or 0)
            split_counts[split] += 1
        else:
            totals["excluded_sources"] += 1
    rows.sort(key=lambda row: (not row["ready"], row["source_id"]))
    latest_pointer = root / "localization_datasets" / "latest.txt"
    built_splits = _dataset_source_splits(root) if latest_pointer.is_file() else {}
    split_pending = (root / SPLIT_PENDING_FILENAME).is_file() or (
        latest_pointer.is_file() and built_splits != split_plan["assignments"]
    )
    return {
        "totals": totals, "splits": split_counts, "sources": rows,
        "split_plan": split_plan, "split_pending": split_pending,
    }

def build_localization_dataset(workspace: str | Path) -> dict[str, Any]:
    """Build project-specific localization training data from explicit reviews only.

    Only source images explicitly marked ``review_completed`` are eligible. They
    are used as complete full-screen supervision. Every incomplete image is excluded
    entirely, even if individual ROI decisions already exist. Review reason codes are
    audit/analysis metadata only.
    """
    import cv2

    root = resolve_project_workspace(workspace)
    project_meta: dict[str, Any] = {}
    project_file = root / "project.json"
    if project_file.is_file():
        try:
            payload = json.loads(project_file.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                project_meta = {
                    "project_id": str(payload.get("project_id") or root.name),
                    "use_case_id": str(payload.get("use_case_id") or ""),
                }
        except (OSError, ValueError, TypeError):
            project_meta = {}
    db = TrainingDatabase(root / "samples.sqlite3")
    all_sources = {str(item["source_id"]): item for item in db.list_detection_sources()}
    ready_source_ids = {source_id for source_id, item in all_sources.items() if bool(item.get("review_completed"))}
    if not ready_source_ids:
        raise ValueError(
            "No review-completed source images are available. Mark at least one image as 'Afbeelding klaar' in Detection Review."
        )
    annotations = [
        item for item in db.list_detection_annotations(active_only=True, include_ignored=True)
        if str(item["source_id"]) in ready_source_ids
    ]
    positive_annotations = [item for item in annotations if str(item.get("training_role") or "positive") == "positive"]
    negative_annotations = [item for item in annotations if str(item.get("training_role") or "positive") == "negative"]
    if not positive_annotations:
        raise ValueError(
            "The review-completed images contain no positive localization examples. "
            "Include or adjust at least one ROI before building the detector dataset."
        )

    source_ids = sorted(ready_source_ids)
    sources = {source_id: all_sources[source_id] for source_id in source_ids if source_id in all_sources}
    annotations_by_source: dict[str, list[dict[str, Any]]] = {}
    for item in annotations:
        annotations_by_source.setdefault(str(item["source_id"]), []).append(item)

    split_plan = resolve_localization_splits(root, list(sources))
    source_splits = dict(split_plan["assignments"])
    dataset_id = _dataset_id(annotations, set(sources), source_splits)
    dataset_root = root / "localization_datasets" / dataset_id
    images_dir = dataset_root / "images"
    annotations_dir = dataset_root / "annotations"
    images_dir.mkdir(parents=True, exist_ok=False)
    annotations_dir.mkdir(parents=True, exist_ok=True)

    split_images: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
    split_annotations: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
    image_counter = 1
    annotation_counter = 1
    full_source_count = 0
    patch_source_count = 0
    negative_image_count = 0

    def add_image_record(*, source_id: str, path: Path, width: int, height: int) -> tuple[int, str]:
        nonlocal image_counter
        split = source_splits[source_id]
        image_id = image_counter
        image_counter += 1
        # PaddleX COCODetDataset resolves every COCO ``file_name`` below
        # ``<dataset>/images`` itself. Keep this field relative to that image
        # directory (normally just the basename); including an ``images/``
        # prefix would make PaddleX look for ``images/images/<file>``.
        split_images[split].append({
            "id": image_id,
            "file_name": path.name,
            "width": int(width),
            "height": int(height),
        })
        return image_id, split

    for source_id in sorted(sources):
        source = sources[source_id]
        assert source is not None
        render = root / str(source["render_path"])
        if not render.is_file():
            raise FileNotFoundError(f"Source render is missing: {render}")
        image = cv2.imread(str(render))
        if image is None:
            raise ValueError(f"Source render could not be read: {render}")
        height, width = image.shape[:2]
        reviewed = annotations_by_source.get(source_id, [])
        # Eligibility is an explicit image-level decision. Once an image is marked
        # ready, the complete screenshot is safe supervision: positive annotations
        # are objects; every other pixel is background for this project.
        target = images_dir / f"{source_id}.png"
        shutil.copy2(render, target)
        image_id, split = add_image_record(source_id=source_id, path=target, width=width, height=height)
        full_source_count += 1
        source_positive_count = 0
        for item in reviewed:
            if str(item.get("training_role") or "positive") != "positive":
                continue
            x1, y1, x2, y2 = (int(item[key]) for key in ("x1", "y1", "x2", "y2"))
            bw, bh = x2 - x1, y2 - y1
            if bw <= 0 or bh <= 0:
                continue
            split_annotations[split].append({
                "id": annotation_counter, "image_id": image_id, "category_id": 1,
                "bbox": [x1, y1, bw, bh], "area": bw * bh, "iscrowd": 0, "ignore": 0,
            })
            annotation_counter += 1
            source_positive_count += 1
        if source_positive_count == 0:
            negative_image_count += 1

    categories = [{"id": 1, "name": "field_roi", "supercategory": "field"}]
    for split in ("train", "val", "test"):
        payload = {
            "info": {
                "description": "IsalaOCR project-specific field localization dataset",
                "version": "2.0", "created_at": utc_now(),
                "supervision": "explicit_reviews_only",
            },
            "licenses": [],
            "images": split_images[split],
            "annotations": split_annotations[split],
            "categories": categories,
        }
        (annotations_dir / f"instance_{split}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    manifest = {
        "dataset_id": dataset_id,
        **project_meta,
        "path": dataset_root.relative_to(root).as_posix(),
        "created_at": utc_now(),
        "format": "COCODetDataset",
        "class_names": ["field_roi"],
        "image_count": sum(len(items) for items in split_images.values()),
        "source_count": len(sources),
        "full_source_image_count": full_source_count,
        "review_patch_image_count": patch_source_count,
        "annotation_count": sum(len(items) for items in split_annotations.values()),
        "positive_review_count": len(positive_annotations),
        "negative_review_count": len(negative_annotations),
        "ignored_annotation_count": 0,
        "coco_annotation_count": sum(len(items) for items in split_annotations.values()),
        "negative_image_count": negative_image_count,
        "open_candidate_count": int(db.detection_review_counts().get("pending") or 0),
        "splits": {
            split: {"images": len(split_images[split]), "annotations": len(split_annotations[split])}
            for split in SPLIT_NAMES
        },
        "source_splits": source_splits,
        "split_policy": {
            "mode": split_plan["mode"],
            "targets": split_plan["targets"],
            "overrides": split_plan["overrides"],
        },
        "pipeline": "field_localization",
        "supervision_policy": "completed_sources_only",
        "source": "only images explicitly marked review_completed are included; incomplete images are excluded entirely",
        "eligible_source_count": len(sources),
        "excluded_source_count": max(0, len(all_sources) - len(sources)),
    }
    (dataset_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (root / "localization_datasets" / "latest.txt").write_text(dataset_id + "\n", encoding="utf-8")
    db.save_localization_dataset(manifest)
    try:
        (root / SPLIT_PENDING_FILENAME).unlink(missing_ok=True)
    except OSError:
        pass
    return manifest


def _resolve_dataset(root: Path, dataset: str = "latest") -> Path:
    base = root / "localization_datasets"
    if dataset == "latest":
        pointer = base / "latest.txt"
        if not pointer.is_file():
            raise FileNotFoundError("No localization dataset has been built yet")
        dataset = pointer.read_text(encoding="utf-8").strip()
    path = base / dataset
    if not path.is_dir():
        raise FileNotFoundError(path)
    return path


def validate_localization_dataset(workspace: str | Path, dataset: str = "latest") -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    dataset_root = _resolve_dataset(root, dataset)
    errors: list[str] = []
    warnings: list[str] = []
    totals = {"images": 0, "annotations": 0, "ignored_annotations": 0}
    for split in ("train", "val", "test"):
        path = dataset_root / "annotations" / f"instance_{split}.json"
        if not path.is_file():
            errors.append(f"Missing annotation file: {path.name}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Invalid JSON in {path.name}: {exc}")
            continue
        images = payload.get("images") or []
        annotations = payload.get("annotations") or []
        categories = payload.get("categories") or []
        if categories != [{"id": 1, "name": "field_roi", "supercategory": "field"}]:
            errors.append(f"{path.name} must contain exactly the field_roi category")
        if split in {"train", "val"} and not images:
            errors.append(f"{split} split contains no images; collect/review more independent sources")
        if split == "test" and len(images) < 3:
            warnings.append(f"test split contains {len(images)} image(s); the default detection gate requires at least 3")
        image_by_id = {int(item["id"]): item for item in images}
        totals["images"] += len(images)
        totals["annotations"] += sum(1 for item in annotations if not int(item.get("iscrowd") or item.get("ignore") or 0))
        totals["ignored_annotations"] += sum(1 for item in annotations if int(item.get("iscrowd") or item.get("ignore") or 0))
        seen_ids: set[int] = set()
        for item in annotations:
            aid = int(item.get("id") or 0)
            if aid in seen_ids:
                errors.append(f"Duplicate annotation id {aid} in {split}")
            seen_ids.add(aid)
            image = image_by_id.get(int(item.get("image_id") or 0))
            if image is None:
                errors.append(f"Annotation {aid} references missing image")
                continue
            bbox = item.get("bbox") or []
            if len(bbox) != 4:
                errors.append(f"Annotation {aid} has invalid bbox")
                continue
            x, y, width, height = (float(value) for value in bbox)
            if width <= 0 or height <= 0 or x < 0 or y < 0:
                errors.append(f"Annotation {aid} has non-positive/out-of-bounds bbox")
            if x + width > float(image["width"]) + 1 or y + height > float(image["height"]) + 1:
                errors.append(f"Annotation {aid} exceeds image bounds")
        for image in images:
            raw_name = str(image.get("file_name") or "")
            file_name = Path(raw_name)
            if not raw_name or file_name.is_absolute() or ".." in file_name.parts:
                errors.append(f"Invalid COCO image file_name: {raw_name!r}")
                continue
            # PaddleX's COCODetDataset checker prepends ``images/`` to the
            # COCO file_name. Mirror that exact resolution here instead of
            # accepting paths that only our own validator understands.
            file_path = dataset_root / "images" / file_name
            if not file_path.is_file():
                legacy_path = dataset_root / file_name
                if file_name.parts and file_name.parts[0] == "images" and legacy_path.is_file():
                    errors.append(
                        f"PaddleX-incompatible image path {raw_name!r}: file_name must be relative "
                        "to the dataset images directory and must not start with 'images/'. "
                        "Rebuild this localization dataset."
                    )
                else:
                    errors.append(f"Missing image for PaddleX: images/{raw_name}")
    if totals["images"] < 5:
        warnings.append("Fewer than 5 reviewed source images; detector training will not generalize reliably")
    if totals["annotations"] < 20:
        warnings.append("Fewer than 20 positive field ROI annotations; collect more geometry corrections before training")
    report = {
        "status": "ok" if not errors else "invalid",
        "dataset_id": dataset_root.name,
        "dataset_path": dataset_root.relative_to(root).as_posix(),
        "totals": totals,
        "errors": errors,
        "warnings": warnings,
        "validated_at": utc_now(),
    }
    (dataset_root / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _normalize_prediction_map(payload: Any) -> dict[str, list[dict[str, Any]]]:
    if isinstance(payload, dict) and isinstance(payload.get("predictions"), dict):
        payload = payload["predictions"]
    if not isinstance(payload, dict):
        raise ValueError("Prediction payload must be an object keyed by source_id")
    result: dict[str, list[dict[str, Any]]] = {}
    for source_id, items in payload.items():
        if isinstance(items, dict) and isinstance(items.get("boxes"), list):
            items = items["boxes"]
        if not isinstance(items, list):
            continue
        result[str(source_id)] = [dict(item) for item in items if isinstance(item, dict)]
    return result


def _box_from_prediction(item: dict[str, Any]) -> Box | None:
    coordinate = item.get("coordinate") or item.get("bbox") or item.get("box")
    if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 4:
        return None
    try:
        values = [float(value) for value in coordinate]
    except (TypeError, ValueError):
        return None
    if str(item.get("bbox_format") or "xyxy").lower() == "xywh":
        x1, y1, width, height = values
        x2, y2 = x1 + width, y1 + height
    else:
        x1, y1, x2, y2 = values
    x1, x2 = sorted((int(round(x1)), int(round(x2))))
    y1, y2 = sorted((int(round(y1)), int(round(y2))))
    if x2 <= x1 or y2 <= y1:
        return None
    return Box(x1, y1, x2, y2)


def _prediction_score(item: dict[str, Any]) -> float:
    try:
        return float(item.get("score") if item.get("score") is not None else item.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _current_localization_dataset_id(root: Path) -> str:
    pointer = root / "localization_datasets" / "latest.txt"
    try:
        return pointer.read_text(encoding="utf-8-sig").strip() if pointer.is_file() else ""
    except OSError:
        return ""


def _evaluation_source_ids(
    root: Path, db: TrainingDatabase, *, dataset_id: str = "", split: str = "test"
) -> list[str]:
    reviewed_sources = {str(item["source_id"]) for item in db.list_detection_reviews()}
    reviewed_sources.update(str(item["source_id"]) for item in db.list_detection_annotations(active_only=True))
    source_ids = sorted(
        source_id for source_id in reviewed_sources
        if int(db.detection_review_counts(source_id).get("pending") or 0) == 0
        and int(db.detection_review_counts(source_id).get("positive") or 0) > 0
    )
    if split in set(SPLIT_NAMES):
        dataset_splits = _dataset_source_splits(root, dataset_id)
        if dataset_splits:
            source_ids = [source_id for source_id in source_ids if dataset_splits.get(source_id) == split]
        else:
            source_ids = [source_id for source_id in source_ids if _legacy_split_for_source(source_id) == split]
    return source_ids


def _ground_truth_fingerprint(
    root: Path, db: TrainingDatabase, *, source_ids: list[str], dataset_id: str, split: str
) -> str:
    rows: list[str] = [f"dataset:{dataset_id}", f"split:{split}"]
    dataset_splits = _dataset_source_splits(root, dataset_id)
    for source_id in source_ids:
        source = db.get_detection_source(source_id) or {}
        rows.append(
            f"source:{source_id}:{int(source.get('image_width') or 0)}x{int(source.get('image_height') or 0)}:"
            f"{dataset_splits.get(source_id, '')}"
        )
        annotations = db.list_detection_annotations(source_id, active_only=True, include_ignored=True)
        for item in sorted(
            annotations,
            key=lambda row: (
                str(row.get("training_role") or "positive"), int(row.get("y1") or 0), int(row.get("x1") or 0),
                int(row.get("y2") or 0), int(row.get("x2") or 0), str(row.get("annotation_id") or ""),
            ),
        ):
            rows.append(
                "annotation:" + ":".join((
                    source_id, str(item.get("training_role") or "positive"),
                    str(int(item.get("x1") or 0)), str(int(item.get("y1") or 0)),
                    str(int(item.get("x2") or 0)), str(int(item.get("y2") or 0)),
                ))
            )
    return hashlib.sha256("|".join(rows).encode("utf-8")).hexdigest()


def localization_ground_truth_fingerprint(
    workspace: str | Path, *, dataset_id: str = "", split: str = "test"
) -> str:
    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    effective_dataset_id = dataset_id or _current_localization_dataset_id(root)
    source_ids = _evaluation_source_ids(root, db, dataset_id=effective_dataset_id, split=split)
    if not source_ids:
        return ""
    return _ground_truth_fingerprint(
        root, db, source_ids=source_ids, dataset_id=effective_dataset_id, split=split
    )


def _candidate_prediction_map(db: TrainingDatabase, source_kind: str | None = None) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for source in db.list_detection_sources():
        source_id = str(source["source_id"])
        candidates = db.list_detection_candidates(source_id, include_rejected=True)
        if source_kind:
            candidates = [item for item in candidates if source_kind in str(item.get("source_kind") or "")]
        result[source_id] = [
            {
                "score": float(item.get("confidence") or 0),
                "coordinate": [int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"])],
                "source_kind": str(item.get("source_kind") or ""),
            }
            for item in candidates
        ]
    return result


def _evaluate_prediction_map(
    workspace: Path,
    predictions_by_source: dict[str, list[dict[str, Any]]],
    *,
    kind: str,
    model_id: str = "",
    dataset_id: str = "",
    predictions_path: str = "",
    iou_threshold: float = 0.75,
    auto_accept_iou: float = 0.90,
    minimum_confidence: float = 0.0,
    thresholds: dict[str, Any] | None = None,
    split: str = "test",
    persist: bool = True,
    update_gate: bool = True,
) -> dict[str, Any]:
    from .detection_gate import greedy_detection_metrics, intersection_over_union, passes_detection_gate

    db = TrainingDatabase(workspace / "samples.sqlite3")
    effective_dataset_id = dataset_id or _current_localization_dataset_id(workspace)
    source_ids = _evaluation_source_ids(
        workspace, db, dataset_id=effective_dataset_id, split=split
    )
    if not source_ids:
        raise ValueError(
            f"No fully reviewed localization sources are available in split '{split}'. "
            "Partial explicit reviews can train the model, but gate evaluation requires complete held-out sources."
        )

    aggregate = {"tp": 0, "fp": 0, "fn": 0, "ious": []}
    direct_match_count = 0
    total_truth = 0
    raw_prediction_total = 0
    scored_prediction_total = 0
    ignored_prediction_count = 0
    per_source: list[dict[str, Any]] = []

    for source_id in source_ids:
        reviewed = db.list_detection_annotations(source_id, active_only=True, include_ignored=True)
        truths = [
            Box(int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"]))
            for item in reviewed if str(item.get("training_role") or "positive") == "positive"
        ]
        negative_boxes = [
            Box(int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"]))
            for item in reviewed if str(item.get("training_role") or "positive") == "negative"
        ]
        source_items = [item for item in predictions_by_source.get(source_id, []) if isinstance(item, dict)]
        raw_predictions = [box for item in source_items if (box := _box_from_prediction(item)) is not None]
        filtered_items = [item for item in source_items if _prediction_score(item) >= float(minimum_confidence)]
        predictions = [box for item in filtered_items if (box := _box_from_prediction(item)) is not None]
        raw_prediction_total += len(raw_predictions)
        scored_prediction_total += len(predictions)
        source_ignored_predictions = 0
        metrics = greedy_detection_metrics(predictions, truths, iou_threshold=iou_threshold)
        aggregate["tp"] += int(metrics["true_positives"])
        aggregate["fp"] += int(metrics["false_positives"])
        aggregate["fn"] += int(metrics["false_negatives"])
        aggregate["ious"].extend(metrics["matched_ious"])
        total_truth += len(truths)
        for truth in truths:
            best_iou = max((intersection_over_union(prediction, truth) for prediction in predictions), default=0.0)
            if best_iou >= auto_accept_iou:
                direct_match_count += 1
        per_source.append({
            "source_id": source_id,
            "prediction_count": len(raw_predictions),
            "scored_prediction_count": len(predictions),
            "ignored_prediction_count": source_ignored_predictions,
            "ground_truth_count": len(truths),
            "negative_review_region_count": len(negative_boxes),
            **{key: value for key, value in metrics.items() if key != "matched_ious"},
        })

    tp, fp, fn = aggregate["tp"], aggregate["fp"], aggregate["fn"]
    fingerprint = _ground_truth_fingerprint(
        workspace, db, source_ids=source_ids, dataset_id=effective_dataset_id, split=split
    )
    metrics = {
        "iou_threshold": float(iou_threshold),
        "auto_accept_iou_threshold": float(auto_accept_iou),
        "minimum_confidence": float(minimum_confidence),
        "precision": tp / max(1, tp + fp),
        "recall": tp / max(1, tp + fn),
        "mean_iou": statistics.fmean(aggregate["ious"]) if aggregate["ious"] else 0.0,
        "median_iou": statistics.median(aggregate["ious"]) if aggregate["ious"] else 0.0,
        "false_positives_per_image": fp / max(1, len(source_ids)),
        "auto_accept_rate": direct_match_count / max(1, total_truth),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "raw_predictions": raw_prediction_total,
        "scored_predictions": scored_prediction_total,
        "evaluated_images": len(source_ids),
        "ground_truth_rois": total_truth,
        "ignored_predictions": ignored_prediction_count,
        "ground_truth_fingerprint": fingerprint,
    }
    thresholds = thresholds or {}
    gate_passed, gate_failures = passes_detection_gate(metrics, thresholds) if thresholds else (False, ["No gate thresholds supplied"])
    digest = hashlib.sha256(json.dumps({"metrics": metrics, "model_id": model_id, "split": split}, sort_keys=True).encode()).hexdigest()[:8]
    evaluation_id = f"loc-eval-{kind}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{digest}" if persist else ""
    payload = {
        "evaluation_id": evaluation_id,
        "model_id": model_id,
        "dataset_id": effective_dataset_id,
        "kind": kind,
        "split": split,
        "created_at": utc_now(),
        "ground_truth_fingerprint": fingerprint,
        "minimum_confidence": float(minimum_confidence),
        "metrics": metrics,
        "gate_passed": gate_passed,
        "gate_failures": gate_failures,
        "per_source": per_source,
        "predictions_path": predictions_path,
    }
    if persist:
        output_dir = workspace / "localization_evaluations" / evaluation_id
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evaluation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        db.save_localization_evaluation(payload)
        if kind == "trained" and update_gate:
            active = db.active_localization_model()
            if gate_passed and active and str(active.get("model_id") or "") == str(model_id or ""):
                db.set_detection_gate(
                    True,
                    reason="Actieve field detector is opnieuw geëvalueerd en haalt de actuele detection gate.",
                    evaluation_id=evaluation_id,
                )
            elif gate_passed:
                db.set_detection_gate(
                    False,
                    reason="Laatste getrainde field detector haalt de detection gate; activeer dit model om Pipeline B vrij te geven.",
                    evaluation_id=evaluation_id,
                )
            else:
                db.set_detection_gate(
                    False,
                    reason="Laatste getrainde field detector haalt de detection gate niet: " + "; ".join(gate_failures),
                    evaluation_id=evaluation_id,
                )
    return payload


def _detection_match_details(
    prediction_items: list[dict[str, Any]],
    truth_items: list[dict[str, Any]],
    negative_items: list[dict[str, Any]],
    *,
    minimum_confidence: float,
    iou_threshold: float,
) -> dict[str, Any]:
    """Return the exact TP/FP/FN assignments used by the quality visualizer.

    The normal gate evaluator only needs aggregate metrics.  Step 5 needs the
    matching assignments as well, so a reviewer can see *why* a prediction was
    counted as a false positive or a missed field.  This helper intentionally
    mirrors the greedy highest-IoU matching used by ``greedy_detection_metrics``.
    """
    from .detection_gate import intersection_over_union

    predictions: list[tuple[int, dict[str, Any], Box, float]] = []
    for index, item in enumerate(prediction_items):
        if not isinstance(item, dict):
            continue
        score = _prediction_score(item)
        box = _box_from_prediction(item)
        if box is None or score < float(minimum_confidence):
            continue
        predictions.append((index, item, box, score))

    truths: list[tuple[int, dict[str, Any], Box]] = []
    for index, item in enumerate(truth_items):
        try:
            box = Box(int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"]))
        except (KeyError, TypeError, ValueError):
            continue
        truths.append((index, item, box))

    negatives: list[tuple[int, dict[str, Any], Box]] = []
    for index, item in enumerate(negative_items):
        try:
            box = Box(int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"]))
        except (KeyError, TypeError, ValueError):
            continue
        negatives.append((index, item, box))

    pairs: list[tuple[float, int, int]] = []
    for p_pos, (_, _, prediction, _) in enumerate(predictions):
        for g_pos, (_, _, truth) in enumerate(truths):
            iou = intersection_over_union(prediction, truth)
            if iou >= float(iou_threshold):
                pairs.append((iou, p_pos, g_pos))
    pairs.sort(reverse=True)
    matched_predictions: dict[int, tuple[int, float]] = {}
    matched_truths: dict[int, tuple[int, float]] = {}
    for iou, p_pos, g_pos in pairs:
        if p_pos in matched_predictions or g_pos in matched_truths:
            continue
        matched_predictions[p_pos] = (g_pos, iou)
        matched_truths[g_pos] = (p_pos, iou)

    def box_payload(box: Box) -> list[int]:
        return [int(box.x1), int(box.y1), int(box.x2), int(box.y2)]

    true_positives: list[dict[str, Any]] = []
    false_positives: list[dict[str, Any]] = []
    false_negatives: list[dict[str, Any]] = []
    cause_counts = {
        "duplicate": 0,
        "localization": 0,
        "negative_region": 0,
        "unmatched": 0,
    }

    for p_pos, (raw_index, raw_item, prediction, score) in enumerate(predictions):
        matched = matched_predictions.get(p_pos)
        best_truth_iou = 0.0
        best_truth_pos: int | None = None
        for g_pos, (_, _, truth) in enumerate(truths):
            iou = intersection_over_union(prediction, truth)
            if iou > best_truth_iou:
                best_truth_iou = iou
                best_truth_pos = g_pos
        best_negative_iou = 0.0
        for _, _, negative in negatives:
            best_negative_iou = max(best_negative_iou, intersection_over_union(prediction, negative))

        base = {
            "prediction_index": int(raw_index),
            "box": box_payload(prediction),
            "score": float(score),
            "best_truth_iou": float(best_truth_iou),
            "best_negative_iou": float(best_negative_iou),
        }
        if matched is not None:
            g_pos, iou = matched
            truth_index, truth_item, truth = truths[g_pos]
            true_positives.append({
                **base,
                "kind": "tp",
                "iou": float(iou),
                "truth_index": int(truth_index),
                "truth_annotation_id": str(truth_item.get("annotation_id") or ""),
                "truth_box": box_payload(truth),
            })
            continue

        # If this prediction still overlaps a truth above the matching threshold,
        # that truth has already been claimed by a better-scoring/IoU prediction:
        # this is a duplicate/NMS issue rather than a missing annotation.
        if best_truth_iou >= float(iou_threshold):
            cause = "duplicate"
        elif best_negative_iou >= 0.50:
            cause = "negative_region"
        elif best_truth_iou > 0.05:
            cause = "localization"
        else:
            cause = "unmatched"
        cause_counts[cause] += 1
        truth_box = None
        truth_annotation_id = ""
        if best_truth_pos is not None:
            _, truth_item, truth = truths[best_truth_pos]
            truth_box = box_payload(truth)
            truth_annotation_id = str(truth_item.get("annotation_id") or "")
        false_positives.append({
            **base,
            "kind": "fp",
            "cause": cause,
            "nearest_truth_box": truth_box,
            "nearest_truth_annotation_id": truth_annotation_id,
        })

    for g_pos, (truth_index, truth_item, truth) in enumerate(truths):
        if g_pos in matched_truths:
            continue
        best_prediction_iou = 0.0
        best_prediction_score = 0.0
        best_prediction_box: list[int] | None = None
        for _, _, prediction, score in predictions:
            iou = intersection_over_union(prediction, truth)
            if iou > best_prediction_iou:
                best_prediction_iou = iou
                best_prediction_score = float(score)
                best_prediction_box = box_payload(prediction)
        false_negatives.append({
            "kind": "fn",
            "truth_index": int(truth_index),
            "truth_annotation_id": str(truth_item.get("annotation_id") or ""),
            "box": box_payload(truth),
            "best_prediction_iou": float(best_prediction_iou),
            "best_prediction_score": float(best_prediction_score),
            "best_prediction_box": best_prediction_box,
        })

    return {
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "cause_counts": cause_counts,
        "prediction_count": len(predictions),
        "ground_truth_count": len(truths),
        "negative_region_count": len(negatives),
    }


def _frozen_dataset_split(
    root: Path, *, dataset_id: str, split: str
) -> tuple[Path, list[dict[str, Any]], str]:
    """Load the exact COCO ground truth that belonged to an evaluation dataset.

    Visual diagnostics must describe the frozen dataset that was actually used for
    training/evaluation. Re-reading mutable review rows from samples.sqlite3 can
    make an old evaluation silently change meaning after somebody edits Detection
    Review, and it also makes the visualizer unnecessarily dependent on DB schema
    details. The COCO artifact is the canonical evaluation ground truth.
    """
    dataset_root = _resolve_dataset(root, dataset_id)
    annotation_path = dataset_root / "annotations" / f"instance_{split}.json"
    if not annotation_path.is_file():
        raise FileNotFoundError(f"Dataset annotation file does not exist: {annotation_path}")
    payload = json.loads(annotation_path.read_text(encoding="utf-8-sig"))
    images = payload.get("images") if isinstance(payload, dict) else None
    annotations = payload.get("annotations") if isinstance(payload, dict) else None
    if not isinstance(images, list) or not isinstance(annotations, list):
        raise ValueError(f"Dataset annotation file is invalid: {annotation_path.name}")

    annotations_by_image: dict[int, list[dict[str, Any]]] = {}
    for item in annotations:
        if not isinstance(item, dict) or int(item.get("ignore") or item.get("iscrowd") or 0):
            continue
        try:
            image_id = int(item.get("image_id"))
            bbox = item.get("bbox") or []
            if len(bbox) != 4:
                continue
            x, y, width, height = (float(value) for value in bbox)
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        annotations_by_image.setdefault(image_id, []).append({
            "annotation_id": f"coco:{item.get('id', '')}",
            "training_role": "positive",
            "x1": int(round(x)),
            "y1": int(round(y)),
            "x2": int(round(x + width)),
            "y2": int(round(y + height)),
        })

    sources: list[dict[str, Any]] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        raw_name = str(image.get("file_name") or "").strip()
        file_name = Path(raw_name)
        if not raw_name or file_name.is_absolute() or ".." in file_name.parts:
            continue
        try:
            image_id = int(image.get("id"))
            width = int(image.get("width") or 0)
            height = int(image.get("height") or 0)
        except (TypeError, ValueError):
            continue
        source_id = file_name.stem
        image_path = dataset_root / "images" / file_name
        sources.append({
            "source_id": source_id,
            "image_id": image_id,
            "image_width": width,
            "image_height": height,
            "image_path": image_path,
            "truth_items": annotations_by_image.get(image_id, []),
        })

    fingerprint = hashlib.sha256(annotation_path.read_bytes()).hexdigest()
    return dataset_root, sources, fingerprint


def localization_dataset_image_path(
    workspace: str | Path, *, dataset_id: str, source_id: str, split: str = "test"
) -> Path:
    """Resolve one frozen evaluation image without trusting a URL-derived path."""
    root = resolve_project_workspace(workspace)
    _, sources, _ = _frozen_dataset_split(root, dataset_id=dataset_id, split=split)
    wanted = str(source_id or "")
    for source in sources:
        if str(source.get("source_id") or "") != wanted:
            continue
        path = Path(source["image_path"])
        if path.is_file():
            return path
        raise FileNotFoundError(f"Dataset image does not exist: {path}")
    raise FileNotFoundError(f"Source {wanted!r} is not part of dataset {dataset_id!r} split {split!r}.")


def localization_evaluation_details(
    workspace: str | Path,
    predictions_file: str | Path,
    *,
    model_id: str,
    dataset_id: str = "",
    minimum_confidence: float = 0.25,
    iou_threshold: float = 0.75,
    canonical_iou_threshold: float | None = None,
    split: str = "test",
) -> dict[str, Any]:
    """Build visual TP/FP/FN diagnostics from the frozen evaluation dataset."""
    root = resolve_project_workspace(workspace)
    path = Path(predictions_file)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        raise FileNotFoundError(f"Prediction file does not exist: {path}")
    raw_payload = json.loads(path.read_text(encoding="utf-8-sig"))
    prediction_map = _normalize_prediction_map(raw_payload)
    effective_dataset_id = dataset_id or _current_localization_dataset_id(root)
    if not effective_dataset_id:
        raise ValueError("Deze evaluatie verwijst niet naar een localization-dataset.")

    _, frozen_sources, ground_truth_fingerprint = _frozen_dataset_split(
        root, dataset_id=effective_dataset_id, split=split
    )
    if not frozen_sources:
        raise ValueError(f"No localization sources are available in frozen dataset split '{split}'.")

    # Rejected review regions are useful only as an explanatory hint. They are
    # deliberately best-effort: the actual TP/FP/FN ground truth comes exclusively
    # from the frozen COCO dataset above, so a stale/migrating review DB can never
    # break the visualizer or change an old evaluation.
    negative_by_source: dict[str, list[dict[str, Any]]] = {}
    try:
        db = TrainingDatabase(root / "samples.sqlite3")
        for source in frozen_sources:
            source_id = str(source.get("source_id") or "")
            annotations = db.list_detection_annotations(source_id, active_only=True, include_ignored=True)
            negative_by_source[source_id] = [
                item for item in annotations
                if str(item.get("training_role") or "positive") == "negative"
            ]
    except Exception:
        negative_by_source = {}

    rows: list[dict[str, Any]] = []
    totals = {"tp": 0, "fp": 0, "fn": 0, "predictions": 0, "truth": 0}
    causes = {"duplicate": 0, "localization": 0, "negative_region": 0, "unmatched": 0}
    for source in frozen_sources:
        source_id = str(source.get("source_id") or "")
        truth_items = list(source.get("truth_items") or [])
        negative_items = list(negative_by_source.get(source_id) or [])
        match = _detection_match_details(
            list(prediction_map.get(source_id) or []), truth_items, negative_items,
            minimum_confidence=float(minimum_confidence), iou_threshold=float(iou_threshold),
        )
        tp = len(match["true_positives"])
        fp = len(match["false_positives"])
        fn = len(match["false_negatives"])
        totals["tp"] += tp
        totals["fp"] += fp
        totals["fn"] += fn
        totals["predictions"] += int(match["prediction_count"])
        totals["truth"] += int(match["ground_truth_count"])
        for key in causes:
            causes[key] += int((match.get("cause_counts") or {}).get(key) or 0)
        image_path = Path(source.get("image_path") or "")
        rows.append({
            "source_id": source_id,
            "image_width": int(source.get("image_width") or 0),
            "image_height": int(source.get("image_height") or 0),
            "render_available": image_path.is_file(),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            **match,
        })
    rows.sort(key=lambda item: (-int(item.get("fp") or 0), -int(item.get("fn") or 0), str(item.get("source_id") or "")))

    precision = totals["tp"] / max(1, totals["tp"] + totals["fp"])
    recall = totals["tp"] / max(1, totals["tp"] + totals["fn"])
    fp_per_image = totals["fp"] / max(1, len(rows))
    gate_iou = float(canonical_iou_threshold if canonical_iou_threshold is not None else iou_threshold)
    sweep_thresholds = sorted({0.50, 0.75, float(iou_threshold), gate_iou})
    iou_sweep: list[dict[str, Any]] = []
    for sweep_iou in sweep_thresholds:
        sweep_totals = {"tp": 0, "fp": 0, "fn": 0, "predictions": 0, "truth": 0}
        for source in frozen_sources:
            source_id = str(source.get("source_id") or "")
            match = _detection_match_details(
                list(prediction_map.get(source_id) or []),
                list(source.get("truth_items") or []),
                list(negative_by_source.get(source_id) or []),
                minimum_confidence=float(minimum_confidence),
                iou_threshold=sweep_iou,
            )
            sweep_totals["tp"] += len(match["true_positives"])
            sweep_totals["fp"] += len(match["false_positives"])
            sweep_totals["fn"] += len(match["false_negatives"])
            sweep_totals["predictions"] += int(match["prediction_count"])
            sweep_totals["truth"] += int(match["ground_truth_count"])
        sweep_precision = sweep_totals["tp"] / max(1, sweep_totals["tp"] + sweep_totals["fp"])
        sweep_recall = sweep_totals["tp"] / max(1, sweep_totals["tp"] + sweep_totals["fn"])
        iou_sweep.append({
            "iou_threshold": sweep_iou,
            "is_gate_iou": abs(sweep_iou - gate_iou) < 1e-9,
            "metrics": {
                "true_positives": sweep_totals["tp"],
                "false_positives": sweep_totals["fp"],
                "false_negatives": sweep_totals["fn"],
                "scored_predictions": sweep_totals["predictions"],
                "ground_truth_rois": sweep_totals["truth"],
                "precision": sweep_precision,
                "recall": sweep_recall,
                "false_positives_per_image": sweep_totals["fp"] / max(1, len(frozen_sources)),
            },
        })
    explanations: list[dict[str, str]] = []
    if totals["fp"]:
        dominant = max(causes, key=lambda key: causes[key])
        labels = {
            "duplicate": "veel dubbele detecties rond hetzelfde veld",
            "localization": "veel kaders liggen wel bij een echt veld maar halen de IoU-drempel niet",
            "negative_region": "het model detecteert relatief vaak regio's die eerder expliciet als negatief zijn beoordeeld",
            "unmatched": "veel detecties hebben vrijwel geen overlap met de bevroren dataset-ground-truth",
        }
        explanations.append({"tone": "warning", "text": f"Grootste FP-categorie: {labels[dominant]} ({causes[dominant]} van {totals['fp']} FP)."})
        if dominant == "unmatched":
            explanations.append({"tone": "info", "text": "Open enkele rode kaders. Zijn dit echte velden, dan ontbreekt waarschijnlijk ground truth in deze dataset; zijn het geen velden, dan zijn het echte false positives voor retraining/hard negatives."})
        elif dominant == "duplicate":
            explanations.append({"tone": "info", "text": "Dubbele rode kaders wijzen vooral naar confidence/NMS-calibratie; meer labels alleen lossen dat meestal niet op."})
        elif dominant == "localization":
            explanations.append({"tone": "info", "text": "Rode kaders vlak naast oranje referentiekaders betekenen dat de detector het veld ongeveer vindt maar de box onvoldoende nauwkeurig plaatst."})
    if totals["fn"]:
        explanations.append({"tone": "info", "text": f"Er zijn {totals['fn']} gemiste referentievelden (oranje). Bekijk of ze een terugkerend type/positie hebben voordat je opnieuw traint."})

    return {
        "schema_version": 2,
        "generated_at": utc_now(),
        "model_id": model_id,
        "dataset_id": effective_dataset_id,
        "split": split,
        "minimum_confidence": float(minimum_confidence),
        "iou_threshold": float(iou_threshold),
        "canonical_iou_threshold": gate_iou,
        "iou_sweep": iou_sweep,
        "prediction_generation_threshold": float(raw_payload.get("threshold") or 0.0) if isinstance(raw_payload, dict) else 0.0,
        "ground_truth_source": "frozen_coco_dataset",
        "ground_truth_fingerprint": ground_truth_fingerprint,
        "summary": {
            "true_positives": totals["tp"],
            "false_positives": totals["fp"],
            "false_negatives": totals["fn"],
            "scored_predictions": totals["predictions"],
            "ground_truth_rois": totals["truth"],
            "precision": precision,
            "recall": recall,
            "false_positives_per_image": fp_per_image,
            "cause_counts": causes,
            "evaluated_images": len(rows),
        },
        "explanations": explanations,
        "sources": rows,
    }

def evaluate_candidate_detector(
    workspace: str | Path,
    *,
    kind: str = "baseline",
    source_kind: str | None = None,
    iou_threshold: float = 0.75,
    thresholds: dict[str, Any] | None = None,
    model_id: str = "",
    dataset_id: str = "",
    split: str = "test",
) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    return _evaluate_prediction_map(
        root,
        _candidate_prediction_map(db, source_kind),
        kind=kind,
        model_id=model_id,
        dataset_id=dataset_id or _current_localization_dataset_id(root),
        iou_threshold=iou_threshold,
        thresholds=thresholds,
        split=split,
    )


def evaluate_prediction_file(
    workspace: str | Path,
    predictions_file: str | Path,
    *,
    model_id: str,
    dataset_id: str = "",
    iou_threshold: float = 0.75,
    minimum_confidence: float = 0.25,
    thresholds: dict[str, Any] | None = None,
    split: str = "test",
) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    path = Path(predictions_file)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _evaluate_prediction_map(
        root,
        _normalize_prediction_map(payload),
        kind="trained",
        model_id=model_id,
        dataset_id=dataset_id,
        predictions_path=path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path),
        iou_threshold=iou_threshold,
        minimum_confidence=minimum_confidence,
        thresholds=thresholds,
        split=split,
    )


def diagnose_prediction_file(
    workspace: str | Path,
    predictions_file: str | Path,
    *,
    model_id: str,
    dataset_id: str = "",
    confidence_thresholds: list[float] | tuple[float, ...] = (0.01, 0.05, 0.10, 0.15, 0.20, 0.25, 0.35, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95),
    iou_threshold: float = 0.75,
    thresholds: dict[str, Any] | None = None,
    splits: tuple[str, ...] = ("train", "val", "test"),
) -> dict[str, Any]:
    """Diagnose a trained detector and turn metrics into a next-action pipeline.

    Confidence calibration is deliberately validation-driven. Test metrics may be
    present for historical/backward-compatible reports, but they are never used to
    choose the operating threshold or the model-improvement advice.
    """
    root = resolve_project_workspace(workspace)
    path = Path(predictions_file)
    raw_payload = json.loads(path.read_text(encoding="utf-8-sig"))
    prediction_map = _normalize_prediction_map(raw_payload)
    effective_dataset_id = dataset_id or _current_localization_dataset_id(root)
    normalized_thresholds = sorted({max(0.0, min(1.0, float(value))) for value in confidence_thresholds})
    if not normalized_thresholds:
        raise ValueError("At least one confidence threshold is required")
    gate_thresholds = dict(thresholds or {})

    split_results: dict[str, list[dict[str, Any]]] = {}
    split_errors: dict[str, str] = {}
    for split in splits:
        rows: list[dict[str, Any]] = []
        for confidence in normalized_thresholds:
            try:
                result = _evaluate_prediction_map(
                    root, prediction_map, kind="diagnostic", model_id=model_id,
                    dataset_id=effective_dataset_id,
                    predictions_path=path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path),
                    iou_threshold=iou_threshold, minimum_confidence=confidence, thresholds=gate_thresholds,
                    split=split, persist=False, update_gate=False,
                )
            except ValueError as exc:
                split_errors[split] = str(exc)
                rows = []
                break
            metrics = dict(result.get("metrics") or {})
            precision = float(metrics.get("precision") or 0.0)
            recall = float(metrics.get("recall") or 0.0)
            f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
            calibration_failures: list[str] = []
            calibration_checks = [
                ("recall", float(metrics.get("recall") or 0.0), float(gate_thresholds.get("minimum_recall", 0.95)), ">="),
                ("precision", float(metrics.get("precision") or 0.0), float(gate_thresholds.get("minimum_precision", 0.90)), ">="),
                ("auto_accept_rate", float(metrics.get("auto_accept_rate") or 0.0), float(gate_thresholds.get("minimum_auto_accept_rate", 0.85)), ">="),
                ("false_positives_per_image", float(metrics.get("false_positives_per_image") if metrics.get("false_positives_per_image") is not None else 999.0), float(gate_thresholds.get("maximum_false_positives_per_image", 1.0)), "<="),
            ]
            for name, value, target, operator in calibration_checks:
                passed = value >= target if operator == ">=" else value <= target
                if not passed:
                    calibration_failures.append(f"{name} {value:.3f} {operator} {target:.3f} niet gehaald")
            rows.append({
                "threshold": confidence,
                "f1": f1,
                "gate_passed": bool(result.get("gate_passed")),
                "gate_failures": list(result.get("gate_failures") or []),
                "calibration_passed": not calibration_failures,
                "calibration_failures": calibration_failures,
                "metrics": metrics,
            })
        split_results[split] = rows

    def row_metrics(row: dict[str, Any] | None) -> dict[str, Any]:
        return dict((row or {}).get("metrics") or {})

    def row_at(rows: list[dict[str, Any]], confidence: float | None) -> dict[str, Any] | None:
        if confidence is None or not rows:
            return None
        return min(rows, key=lambda item: abs(float(item.get("threshold") or 0.0) - float(confidence)))

    validation_rows = split_results.get("val") or []
    train_rows = split_results.get("train") or []
    test_rows = split_results.get("test") or []
    minimum_recall = float(gate_thresholds.get("minimum_recall", 0.95))
    minimum_precision = float(gate_thresholds.get("minimum_precision", 0.90))
    maximum_fp = float(gate_thresholds.get("maximum_false_positives_per_image", 1.0))

    # The production confidence must come from validation, never from test.
    recall_qualified = [
        row for row in validation_rows
        if float(row_metrics(row).get("recall") or 0.0) >= minimum_recall
    ]
    production_candidates = [row for row in recall_qualified if bool(row.get("calibration_passed"))]
    production = min(
        production_candidates,
        key=lambda row: (
            float(row_metrics(row).get("false_positives_per_image") or 999999.0),
            -float(row_metrics(row).get("precision") or 0.0),
            -float(row_metrics(row).get("recall") or 0.0),
            -float(row.get("threshold") or 0.0),
        ),
        default=None,
    )
    if recall_qualified:
        diagnostic = min(
            recall_qualified,
            key=lambda row: (
                float(row_metrics(row).get("false_positives_per_image") or 999999.0),
                -float(row_metrics(row).get("precision") or 0.0),
                -float(row.get("f1") or 0.0),
            ),
        )
    else:
        diagnostic = max(
            validation_rows,
            key=lambda row: (
                float(row.get("f1") or 0.0),
                float(row_metrics(row).get("recall") or 0.0),
                float(row_metrics(row).get("precision") or 0.0),
                -float(row_metrics(row).get("false_positives_per_image") or 0.0),
            ),
            default=None,
        )
    if diagnostic is None:
        diagnostic = max(
            test_rows or train_rows,
            key=lambda row: float(row.get("f1") or 0.0),
            default=None,
        )

    diagnostic_threshold = float(diagnostic.get("threshold")) if diagnostic else None
    production_threshold = float(production.get("threshold")) if production else None
    train_at_diagnostic = row_at(train_rows, diagnostic_threshold)
    validation_at_diagnostic = row_at(validation_rows, diagnostic_threshold)
    test_at_diagnostic = row_at(test_rows, diagnostic_threshold)
    test_at_production = row_at(test_rows, production_threshold)

    # Build a frozen-dataset error breakdown on validation at the chosen diagnostic
    # threshold. This is the evidence source for the smart next-action advice.
    validation_details: dict[str, Any] | None = None
    validation_details_error = ""
    if diagnostic_threshold is not None and effective_dataset_id and "val" in splits:
        try:
            validation_details = localization_evaluation_details(
                root, path, model_id=model_id, dataset_id=effective_dataset_id,
                minimum_confidence=diagnostic_threshold, iou_threshold=iou_threshold, split="val",
            )
        except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError) as exc:
            validation_details_error = str(exc)

    train_best = max(train_rows, key=lambda row: float(row.get("f1") or 0.0), default=None)
    train_max_recall = max((float(row_metrics(row).get("recall") or 0.0) for row in train_rows), default=0.0)
    train_best_f1 = float((train_best or {}).get("f1") or 0.0)
    train_metrics = row_metrics(train_at_diagnostic)
    val_metrics = row_metrics(validation_at_diagnostic)
    test_metrics = row_metrics(test_at_diagnostic)
    causes = dict(((validation_details or {}).get("summary") or {}).get("cause_counts") or {})
    val_summary = dict((validation_details or {}).get("summary") or {})
    total_fp = int(val_summary.get("false_positives") or val_metrics.get("false_positives") or 0)
    total_fn = int(val_summary.get("false_negatives") or val_metrics.get("false_negatives") or 0)
    localization_fp = int(causes.get("localization") or 0)
    duplicate_fp = int(causes.get("duplicate") or 0)
    unmatched_fp = int(causes.get("unmatched") or 0)
    negative_fp = int(causes.get("negative_region") or 0)
    localization_ratio = localization_fp / max(1, total_fp)
    duplicate_ratio = duplicate_fp / max(1, total_fp)
    unmatched_ratio = unmatched_fp / max(1, total_fp)
    train_recall = float(train_metrics.get("recall") or 0.0)
    train_precision = float(train_metrics.get("precision") or 0.0)
    val_recall = float(val_metrics.get("recall") or 0.0)
    val_precision = float(val_metrics.get("precision") or 0.0)
    val_fp_per_image = float(val_metrics.get("false_positives_per_image") or 0.0)
    recall_gap = max(0.0, train_recall - val_recall)
    precision_gap = max(0.0, train_precision - val_precision)

    train_sanity_failed = bool(train_rows) and (train_max_recall < 0.85 or train_best_f1 < 0.70)
    generalization_gap = bool(train_at_diagnostic and validation_at_diagnostic) and (recall_gap >= 0.20 or precision_gap >= 0.20)

    diagnosis_code = "review_validation_errors"
    diagnosis_label = "Validatiefouten analyseren"
    diagnosis_summary = "De validation-resultaten halen de Detection Gate nog niet. Analyseer de dominante foutcategorie voordat je opnieuw traint."
    action_code = "review_validation_errors"
    action_label = "Bekijk validation-fouten"
    action_description = "Open representatieve FP/FN-voorbeelden en corrigeer eerst het dominante patroon."
    focus_filter = "all"
    focus_cause = "all"
    focus_split = "val"
    evidence: list[str] = []

    if production is not None:
        diagnosis_code = "validation_ready"
        diagnosis_label = "Validation is voldoende"
        diagnosis_summary = f"Validation haalt de gate bij confidence {production_threshold:.2f}. Deze confidence is de production-kandidaat en mag nu zonder verdere tuning op de hold-out test worden beoordeeld."
        action_code = "final_test"
        action_label = "Bekijk finale test"
        action_description = "Gebruik de validation-gekozen confidence ongewijzigd voor de finale test. Tune niet op de testresultaten."
        focus_split = "test"
        evidence.append(f"Validation gate PASS bij confidence {production_threshold:.2f}.")
    elif train_sanity_failed:
        diagnosis_code = "training_fit"
        diagnosis_label = "Model leert de trainingsdata onvoldoende"
        diagnosis_summary = "Het model kan zelfs op TRAIN onvoldoende stabiel de gelabelde velden terugvinden. Eerst training/data/input onderzoeken; extra threshold-tuning gaat dit niet oplossen."
        action_code = "inspect_training_errors"
        action_label = "Analyseer trainingsfouten"
        action_description = "Bekijk gemiste/onjuiste detecties op TRAIN en controleer labels, box-consistentie, objectgrootte en inputresolutie voordat je opnieuw traint."
        focus_split = "train"
        evidence.extend([
            f"Maximale train-recall over de sweep: {train_max_recall:.1%}.",
            f"Beste train-F1 over de sweep: {train_best_f1:.1%}.",
        ])
    elif generalization_gap:
        diagnosis_code = "generalization_gap"
        diagnosis_label = "Groot verschil tussen train en validation"
        diagnosis_summary = "Het model presteert duidelijk beter op trainingsbeelden dan op validation. Dat wijst op onvoldoende variatie/coverage of overfitting."
        action_code = "improve_generalization"
        action_label = "Bekijk slechtste validation-beelden"
        action_description = "Zoek welke layout/veldposities in validation structureel slechter zijn en voeg vergelijkbare, onafhankelijk gereviewde voorbeelden aan TRAIN toe."
        focus_split = "val"
        evidence.extend([
            f"Recall-gap train→validation: {recall_gap:.1%}.",
            f"Precision-gap train→validation: {precision_gap:.1%}.",
        ])
    elif localization_ratio >= 0.30 and localization_fp >= 5:
        diagnosis_code = "box_localization"
        diagnosis_label = "Bounding-box-localisatie is het hoofdprobleem"
        diagnosis_summary = f"{localization_fp} van {total_fp} validation-FP ({localization_ratio:.0%}) liggen bij een echt veld maar halen de IoU-drempel niet. Het model vindt dus vaak ongeveer de juiste plek, maar het kader is onvoldoende nauwkeurig."
        action_code = "review_near_matches"
        action_label = f"Analyseer {localization_fp} near-matches"
        action_description = "Controleer eerst of de ground-truth boxes consequent zijn. Als de labels kloppen, richt de volgende trainingsronde op nauwkeurigere localisatie/inputresolutie in plaats van alleen meer epochs."
        focus_filter = "fp"
        focus_cause = "localization"
        evidence.append(f"Near-match aandeel in validation-FP: {localization_ratio:.0%}.")
    elif duplicate_ratio >= 0.10 and duplicate_fp >= 3:
        diagnosis_code = "duplicates"
        diagnosis_label = "Dubbele detecties zijn het hoofdprobleem"
        diagnosis_summary = f"{duplicate_fp} van {total_fp} validation-FP zijn extra kaders rond een veld dat al correct gematcht is."
        action_code = "tune_nms"
        action_label = f"Bekijk {duplicate_fp} duplicates"
        action_description = "Controleer NMS/fusion en confidence voordat je opnieuw labelt of traint. Meer labels lossen echte duplicates meestal niet op."
        focus_filter = "fp"
        focus_cause = "duplicate"
        evidence.append(f"Duplicate-aandeel in validation-FP: {duplicate_ratio:.0%}.")
    elif unmatched_ratio >= 0.30 and unmatched_fp >= 5:
        diagnosis_code = "unmatched_false_positives"
        diagnosis_label = "Veel detecties hebben geen ground-truth match"
        diagnosis_summary = f"{unmatched_fp} van {total_fp} validation-FP hebben vrijwel geen overlap met een gelabeld veld. Dit zijn echte false positives óf ontbrekende annotations."
        action_code = "review_unmatched_fp"
        action_label = f"Controleer {unmatched_fp} unmatched FP"
        action_description = "Bevestig ontbrekende labels expliciet. Als het echt geen veld is, verzamel vergelijkbare hard negatives voor een volgende dataset."
        focus_filter = "fp"
        focus_cause = "unmatched"
        evidence.append(f"Unmatched aandeel in validation-FP: {unmatched_ratio:.0%}.")
    elif val_recall < minimum_recall:
        diagnosis_code = "false_negatives"
        diagnosis_label = "Te veel echte velden worden gemist"
        diagnosis_summary = f"Validation-recall is {val_recall:.1%} terwijl minimaal {minimum_recall:.1%} vereist is. Confidence alleen kan dit niet oplossen als de maximale validation-recall in de sweep te laag blijft."
        action_code = "review_false_negatives"
        action_label = f"Analyseer {total_fn} gemiste velden"
        action_description = "Bekijk terugkerende posities/layouts van de FN en voeg representatieve positieve voorbeelden toe of corrigeer inconsistente labels."
        focus_filter = "fn"
        evidence.append(f"Validation recall: {val_recall:.1%} / doel {minimum_recall:.1%}.")
    elif val_precision < minimum_precision or val_fp_per_image > maximum_fp:
        diagnosis_code = "false_positives"
        diagnosis_label = "Te veel echte false positives"
        diagnosis_summary = f"Validation-precision is {val_precision:.1%} en FP/beeld {val_fp_per_image:.1f}. De detector moet achtergrond/negatieve patronen beter leren onderscheiden."
        action_code = "add_hard_negatives"
        action_label = "Analyseer false positives"
        action_description = "Bekijk de hoogste-confidence FP en voeg vergelijkbare niet-velden als hard negatives toe aan de volgende trainingsdataset."
        focus_filter = "fp"
        evidence.extend([
            f"Validation precision: {val_precision:.1%} / doel {minimum_precision:.1%}.",
            f"Validation FP/beeld: {val_fp_per_image:.1f} / maximaal {maximum_fp:.1f}.",
        ])

    if diagnostic_threshold is not None:
        evidence.insert(0, f"Diagnostische confidence is {diagnostic_threshold:.2f}, gekozen op VALIDATION.")
    if validation_details_error:
        evidence.append(f"Visuele validation-analyse kon niet volledig worden opgebouwd: {validation_details_error}")

    top_problem_sources: list[dict[str, Any]] = []
    for source in sorted(
        list((validation_details or {}).get("sources") or []),
        key=lambda item: (-(int(item.get("fp") or 0) + int(item.get("fn") or 0)), -int(item.get("fp") or 0)),
    )[:5]:
        top_problem_sources.append({
            "source_id": str(source.get("source_id") or ""),
            "tp": int(source.get("tp") or 0),
            "fp": int(source.get("fp") or 0),
            "fn": int(source.get("fn") or 0),
        })

    final_test_state = "blocked"
    final_test_summary = "Finale test blijft geblokkeerd totdat validation een production-confidence oplevert."
    if production_threshold is not None:
        if test_at_production is None:
            final_test_state = "ready"
            final_test_summary = f"Validation is voldoende. Voer de finale test uit op confidence {production_threshold:.2f} zonder die threshold nog te wijzigen."
        elif bool(test_at_production.get("gate_passed")):
            final_test_state = "pass"
            final_test_summary = f"De hold-out test haalt de gate bij de validation-gekozen confidence {production_threshold:.2f}."
        else:
            final_test_state = "fail"
            final_test_summary = "Validation was voldoende, maar de hold-out test faalt. Tune niet op deze testset; verbeter train/validation coverage en gebruik later een nieuwe onaangeraakte hold-out voor de volgende finale meting."

    pipeline_status = "ready_for_final_test" if production_threshold is not None else "improve"
    if final_test_state == "pass":
        pipeline_status = "passed"
    elif final_test_state == "fail":
        pipeline_status = "final_test_failed"

    improvement_pipeline = {
        "schema_version": 1,
        "status": pipeline_status,
        "headline": diagnosis_label,
        "summary": diagnosis_summary,
        "primary_diagnosis": {
            "code": diagnosis_code,
            "label": diagnosis_label,
            "summary": diagnosis_summary,
            "evidence": evidence,
        },
        "recommended_action": {
            "code": action_code,
            "label": action_label,
            "description": action_description,
            "focus_split": focus_split,
            "focus_filter": focus_filter,
            "focus_cause": focus_cause,
        },
        "calibration": {
            "source_split": "val",
            "diagnostic_threshold": diagnostic_threshold,
            "production_threshold": production_threshold,
            "production_ready": production_threshold is not None,
            "minimum_recall": minimum_recall,
            "minimum_precision": minimum_precision,
            "maximum_false_positives_per_image": maximum_fp,
            "reason": (
                f"Production-confidence {production_threshold:.2f} is gekozen op validation en haalt alle gate-criteria."
                if production_threshold is not None else
                "Geen validation-threshold haalt alle gate-criteria; threshold-tuning is daarom niet de volgende stap."
            ),
        },
        "error_breakdown": {
            "false_positives": total_fp,
            "false_negatives": total_fn,
            "near_match": localization_fp,
            "duplicate": duplicate_fp,
            "unmatched": unmatched_fp,
            "negative_region": negative_fp,
        },
        "top_problem_sources": top_problem_sources,
        "stages": [
            {
                "id": "train_sanity", "title": "1. Training sanity-check",
                "status": "fail" if train_sanity_failed else "pass",
                "summary": (
                    f"TRAIN leert onvoldoende: max recall {train_max_recall:.1%}, beste F1 {train_best_f1:.1%}."
                    if train_sanity_failed else
                    f"TRAIN heeft voldoende leersignaal voor verdere diagnose (max recall {train_max_recall:.1%}, beste F1 {train_best_f1:.1%})."
                ),
            },
            {
                "id": "validation_calibration", "title": "2. Validation + confidence-calibratie",
                "status": "pass" if production_threshold is not None else "fail",
                "summary": (
                    f"Production-kandidaat gevonden op confidence {production_threshold:.2f}."
                    if production_threshold is not None else
                    f"Geen threshold haalt de validation-gate. Diagnostische confidence: {diagnostic_threshold:.2f}." if diagnostic_threshold is not None else
                    "Geen validation-resultaat beschikbaar."
                ),
            },
            {
                "id": "error_analysis", "title": "3. Automatische foutanalyse",
                "status": "pass" if production_threshold is not None else "action",
                "summary": diagnosis_summary,
            },
            {
                "id": "final_test", "title": "4. Finale hold-out test",
                "status": final_test_state,
                "summary": final_test_summary,
            },
        ],
    }

    floor = normalized_thresholds[0]
    test_floor = next((row for row in test_rows if float(row.get("threshold") or -1) == floor), None)
    canonical = next((row for row in test_rows if abs(float(row.get("threshold") or 0) - 0.25) < 1e-9), None)
    train_floor = next((row for row in train_rows if float(row.get("threshold") or -1) == floor), None)
    test_floor_metrics = row_metrics(test_floor)
    canonical_metrics = row_metrics(canonical)
    train_floor_metrics = row_metrics(train_floor)
    diagnosis: list[str] = []
    if int(test_floor_metrics.get("scored_predictions") or 0) == 0:
        diagnosis.append(f"Geen enkele voorspelling bij confidence {floor:.2f}; controleer training/export/inference voordat je opnieuw traint.")
    elif int(canonical_metrics.get("scored_predictions") or 0) == 0:
        diagnosis.append("Er zijn voorspellingen onder 0.25 maar niet op de huidige operationele threshold; confidence-calibratie is waarschijnlijk een factor.")
    if float(train_floor_metrics.get("recall") or 0.0) <= 0.10:
        diagnosis.append("Recall is ook op de trainingssplit vrijwel nul bij de laagste threshold; dit wijst eerder op underfitting of een training/export/inference-probleem dan op alleen generalisatie.")
    elif float(train_floor_metrics.get("recall") or 0.0) >= 0.50 and float(test_floor_metrics.get("recall") or 0.0) <= 0.10:
        diagnosis.append("Train-recall is duidelijk hoger dan test-recall; met deze kleine bronset is overfitting/generalisation gap waarschijnlijk.")

    payload = {
        "schema_version": 2,
        "created_at": utc_now(),
        "model_id": model_id,
        "dataset_id": effective_dataset_id,
        "predictions_path": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path),
        "prediction_generation_threshold": float(raw_payload.get("threshold") or 0.0) if isinstance(raw_payload, dict) else 0.0,
        "thresholds": normalized_thresholds,
        "splits": split_results,
        "split_errors": split_errors,
        # Backward-compatible alias. It is now explicitly validation-driven.
        "recommended_threshold": diagnostic_threshold,
        "recommended_source_split": "val" if validation_rows else None,
        "recommended_gate_passed": bool(production is not None),
        "production_threshold": production_threshold,
        "diagnosis": diagnosis,
        "improvement_pipeline": improvement_pipeline,
    }
    diagnostic_id = f"loc-diagnostic-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]}"
    payload["diagnostic_id"] = diagnostic_id
    output_dir = root / "localization_diagnostics"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{diagnostic_id}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "latest_trained.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def derived_detection_gate_state(
    workspace: str | Path, *, thresholds: dict[str, Any] | None = None
) -> dict[str, Any]:
    from .detection_gate import passes_detection_gate

    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    stored = db.detection_gate()
    active = db.active_localization_model()
    evaluations = db.list_localization_evaluations("trained")
    current_dataset_id = _current_localization_dataset_id(root)
    thresholds = thresholds or {}

    def evaluation_state(item: dict[str, Any]) -> tuple[bool, bool, list[str], str]:
        metrics = item.get("metrics") or {}
        dataset_id = str(item.get("dataset_id") or current_dataset_id)
        split = str(item.get("split") or "test")
        current_fp = localization_ground_truth_fingerprint(root, dataset_id=dataset_id, split=split)
        eval_fp = str(metrics.get("ground_truth_fingerprint") or "")
        fingerprint_current = bool(current_fp and eval_fp and current_fp == eval_fp)
        passed, failures = passes_detection_gate(metrics, thresholds) if thresholds else (False, ["No gate thresholds supplied"])
        return fingerprint_current, passed, failures, current_fp

    current_evaluations = [
        item for item in evaluations
        if str(item.get("dataset_id") or current_dataset_id) == current_dataset_id
        and str(item.get("split") or "test") == "test"
    ]

    if active:
        active_id = str(active.get("model_id") or "")
        active_eval = next((
            item for item in current_evaluations
            if str(item.get("model_id") or "") == active_id
        ), None)
        if active_eval is not None:
            fp_current, passed, failures, current_fp = evaluation_state(active_eval)
            if fp_current and passed and bool(stored.get("ready")):
                return {
                    **stored, "ready": True, "state": "open",
                    "reason": "Actieve field detector haalt de detection gate op de actuele ground truth en testscope.",
                    "evaluation_id": str(active_eval.get("evaluation_id") or ""),
                    "model_id": active_id, "failures": [], "fingerprint_current": True,
                    "current_fingerprint": current_fp,
                }

    # Evaluations on archived/alternate datasets are useful for comparison, but
    # must never change the gate for the current work dataset.
    latest = current_evaluations[0] if current_evaluations else None
    if latest is None:
        return {**stored, "ready": False, "state": "not_evaluated", "failures": [], "fingerprint_current": False}
    fp_current, passed, failures, current_fp = evaluation_state(latest)
    evaluation_id = str(latest.get("evaluation_id") or "")
    model_id = str(latest.get("model_id") or "")
    if not fp_current:
        return {
            **stored, "ready": False, "state": "stale",
            "reason": "Detection ground truth, dataset-scope of split is gewijzigd sinds de laatste getrainde evaluatie; evalueer de field detector opnieuw.",
            "evaluation_id": evaluation_id, "model_id": model_id, "failures": [],
            "fingerprint_current": False, "current_fingerprint": current_fp,
        }
    if not passed:
        return {
            **stored, "ready": False, "state": "failed",
            "reason": "Laatste getrainde field detector haalt de detection gate niet: " + "; ".join(failures),
            "evaluation_id": evaluation_id, "model_id": model_id, "failures": failures,
            "fingerprint_current": True, "current_fingerprint": current_fp,
        }
    if not active or str(active.get("model_id") or "") != model_id:
        return {
            **stored, "ready": False, "state": "awaiting_activation",
            "reason": "Laatste getrainde field detector haalt de quality gate maar is nog niet als actieve detector geactiveerd.",
            "evaluation_id": evaluation_id, "model_id": model_id, "failures": [],
            "fingerprint_current": True, "current_fingerprint": current_fp,
        }
    return {
        **stored, "ready": False, "state": "activation_state_mismatch",
        "reason": "Het model en de evaluatie zijn geldig, maar de persistente activation gate is niet open; activeer de field detector opnieuw.",
        "evaluation_id": evaluation_id, "model_id": model_id, "failures": [],
        "fingerprint_current": True, "current_fingerprint": current_fp,
    }


def merge_localization_predictions(
    workspace: str | Path,
    predictions_file: str | Path,
    *,
    model_id: str,
    minimum_confidence: float = 0.25,
    iou_threshold: float = 0.55,
    containment_threshold: float = 0.92,
) -> dict[str, Any]:
    """Fuse predictions from the active object detector with current neutral geometry.

    This still produces Pipeline A candidates only; no OCR text or field semantics
    are introduced here.
    """
    import cv2
    from .localization import LocalizationCandidate, fuse_candidates, trained_detector_candidates, write_candidate_crops

    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    prediction_map = _normalize_prediction_map(json.loads(Path(predictions_file).read_text(encoding="utf-8")))
    changed_sources = 0
    candidate_count = 0
    for source_id, raw_predictions in prediction_map.items():
        source = db.get_detection_source(source_id)
        if source is None:
            continue
        width, height = int(source["image_width"]), int(source["image_height"])
        existing = [
            LocalizationCandidate(
                candidate_id=str(item["candidate_id"]), source_id=source_id,
                box=Box(int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"])),
                confidence=float(item.get("confidence") or 0),
                source_kind=str(item.get("source_kind") or "geometry"),
                source_refs=tuple(str(ref) for ref in item.get("source_refs") or []),
            )
            for item in db.list_detection_candidates(source_id, include_rejected=True)
        ]
        trained = trained_detector_candidates(
            source_id, raw_predictions, image_width=width, image_height=height,
            minimum_confidence=minimum_confidence, model_id=model_id,
        )
        fused = fuse_candidates(
            source_id, [*existing, *trained], iou_threshold=iou_threshold,
            containment_threshold=containment_threshold,
        )
        render_path = root / str(source.get("render_path") or "")
        image = cv2.imread(str(render_path)) if render_path.is_file() else None
        crop_paths = write_candidate_crops(root, source_id, image, fused) if image is not None else {}
        geometry = db.list_detection_table_geometry(source_id)
        cells_by_table: dict[str, list[dict[str, Any]]] = {}
        for cell in geometry["cells"]:
            cells_by_table.setdefault(str(cell["table_id"]), []).append(cell)
        tables = [
            {**region, "cells": cells_by_table.get(str(region["table_id"]), [])}
            for region in geometry["regions"]
        ]
        candidate_dicts = []
        for candidate in fused:
            item = candidate.as_dict()
            item["crop_path"] = crop_paths.get(candidate.candidate_id, "")
            candidate_dicts.append(item)
        source_payload = dict(source)
        source_payload["detector_version"] = f"{source.get('detector_version') or 'geometry'}+trained:{model_id}"
        db.replace_localization_detection(source_payload, candidate_dicts, tables)
        changed_sources += 1
        candidate_count += len(candidate_dicts)
    return {
        "status": "ok",
        "model_id": model_id,
        "predictions_file": str(predictions_file),
        "sources_updated": changed_sources,
        "candidate_count": candidate_count,
    }


def compare_localization_evaluations(
    workspace: str | Path, *, dataset_id: str = "", model_id: str = "",
    baseline_evaluation_id: str = "", trained_evaluation_id: str = "",
) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    baselines = db.list_localization_evaluations("baseline")
    trained_items = db.list_localization_evaluations("trained")
    if baseline_evaluation_id:
        baseline = next((item for item in baselines if str(item.get("evaluation_id") or "") == baseline_evaluation_id), None)
    else:
        baseline = next((
            item for item in baselines
            if not dataset_id or str(item.get("dataset_id") or "") == dataset_id
        ), None)
    if trained_evaluation_id:
        trained = next((item for item in trained_items if str(item.get("evaluation_id") or "") == trained_evaluation_id), None)
    else:
        trained = next((
            item for item in trained_items
            if (not dataset_id or str(item.get("dataset_id") or "") == dataset_id)
            and (not model_id or str(item.get("model_id") or "") == model_id)
        ), None)
    if baseline is None or trained is None:
        raise ValueError("Both a baseline and trained localization evaluation are required for the selected dataset/model")
    bm, tm = baseline["metrics"], trained["metrics"]
    baseline_fp = str(bm.get("ground_truth_fingerprint") or "")
    trained_fp = str(tm.get("ground_truth_fingerprint") or "")
    comparison = {
        "created_at": utc_now(),
        "baseline_evaluation_id": baseline["evaluation_id"],
        "trained_evaluation_id": trained["evaluation_id"],
        "same_split": baseline.get("split") == trained.get("split"),
        "same_dataset": str(baseline.get("dataset_id") or "") == str(trained.get("dataset_id") or ""),
        "same_ground_truth": bool(baseline_fp and trained_fp and baseline_fp == trained_fp),
        "metrics": {
            key: {"baseline": bm.get(key), "trained": tm.get(key), "delta": (float(tm.get(key) or 0)-float(bm.get(key) or 0))}
            for key in ("precision","recall","mean_iou","median_iou","auto_accept_rate","false_positives_per_image")
        },
    }
    path = root / "localization_evaluations" / "latest_comparison.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    return comparison


def detection_quality_report(
    workspace: str | Path, *, thresholds: dict[str, Any] | None = None
) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    db = TrainingDatabase(root / "samples.sqlite3")
    report = {
        "created_at": utc_now(),
        "review_counts": db.detection_review_counts(),
        "gate": derived_detection_gate_state(root, thresholds=thresholds),
        "active_model": db.active_localization_model(),
        "baseline": (db.list_localization_evaluations("baseline") or [None])[0],
        "trained": (db.list_localization_evaluations("trained") or [None])[0],
        "comparison": None,
        "diagnostics": None,
    }
    comparison_path = root / "localization_evaluations" / "latest_comparison.json"
    if comparison_path.is_file():
        try:
            report["comparison"] = json.loads(comparison_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    diagnostics_path = root / "localization_diagnostics" / "latest_trained.json"
    if diagnostics_path.is_file():
        try:
            report["diagnostics"] = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    output = root / "localization_evaluations" / "quality_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
