#!/usr/bin/env python3
"""Train and run the Pipeline A field-localization detector with PaddleX.

This runtime intentionally never imports IsalaOCR recognition samples. It consumes
only COCO full-image localization datasets created by Detection Review Studio.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PADDLEX_ROOT = Path(os.environ.get("ISALA_PADDLEX_SOURCE_ROOT", "/opt/paddlex-source"))
MODEL_NAME = "PicoDet-S"


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for token in str(value).split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
        if len(parts) == 3:
            break
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _is_unsafe_cpu_paddle_version(value: str) -> bool:
    """PaddlePaddle 3.3.x has a known PIR -> oneDNN CPU inference regression."""
    major, minor, _patch = _version_tuple(value)
    return major == 3 and minor == 3


def _verify_cpu_inference_paddle() -> str:
    import paddle  # type: ignore

    version = str(getattr(paddle, "__version__", "unknown"))
    if _is_unsafe_cpu_paddle_version(version):
        raise RuntimeError(
            "PaddlePaddle 3.3.x is not supported for IsalaOCR CPU localization inference. "
            "That release family has an upstream PIR/oneDNN regression that raises "
            "ConvertPirAttribute2RuntimeAttribute for Paddle static models such as PicoDet-S. "
            "Rebuild training image revision 3.8.5 from Stap 1 · Voorbereiding; the supported CPU pin is "
            "PaddlePaddle 3.2.2."
        )
    return version


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SMALL_DATASET_MAX_IMAGES = 32


def coco_train_stats(dataset: Path) -> dict[str, int]:
    """Return the independent-image and annotation counts used for training."""
    annotation_path = dataset / "annotations" / "instance_train.json"
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    images = payload.get("images") or []
    annotations = payload.get("annotations") or []
    image_ids = {int(item.get("id")) for item in images}
    annotated_ids = {int(item.get("image_id")) for item in annotations if item.get("image_id") is not None}
    return {
        "images": len(images),
        "annotations": len(annotations),
        "negative_images": len(image_ids - annotated_ids),
    }


def resolve_training_settings(
    dataset: Path,
    *,
    epochs: int = 0,
    batch_size: int = 0,
    learning_rate: float = 0.0,
    warmup_steps: int = -1,
    eval_interval: int = 0,
) -> dict[str, Any]:
    """Choose conservative settings from independent source-image count.

    PaddleX's PicoDet-S defaults (batch 16 / LR 0.08 / 100 warmup steps) are
    intended for much larger datasets.  With only a handful of independent
    images they can leave almost the entire run in warmup and produce too few
    optimizer updates to learn anything.  Explicit CLI values always win.
    """
    stats = coco_train_stats(dataset)
    train_images = max(1, int(stats["images"]))
    if train_images <= SMALL_DATASET_MAX_IMAGES:
        profile = "small-dataset"
        defaults = {
            "epochs": 150,
            "batch_size": 2,
            "learning_rate": 0.005,
            "warmup_steps": 20,
            "eval_interval": 5,
        }
    elif train_images <= 128:
        profile = "medium-dataset"
        defaults = {
            "epochs": 100,
            "batch_size": 8,
            "learning_rate": 0.02,
            "warmup_steps": 50,
            "eval_interval": 5,
        }
    else:
        profile = "paddlex-standard"
        defaults = {
            "epochs": 80,
            "batch_size": 16,
            "learning_rate": 0.08,
            "warmup_steps": 100,
            "eval_interval": 1,
        }

    effective = {
        "profile": profile,
        "train_images": train_images,
        "train_annotations": int(stats["annotations"]),
        "train_negative_images": int(stats.get("negative_images") or 0),
        "epochs": int(epochs) if int(epochs) > 0 else defaults["epochs"],
        "batch_size": int(batch_size) if int(batch_size) > 0 else defaults["batch_size"],
        "learning_rate": float(learning_rate) if float(learning_rate) > 0 else defaults["learning_rate"],
        "warmup_steps": int(warmup_steps) if int(warmup_steps) >= 0 else defaults["warmup_steps"],
        "eval_interval": int(eval_interval) if int(eval_interval) > 0 else defaults["eval_interval"],
    }
    effective["steps_per_epoch"] = max(1, math.ceil(train_images / max(1, effective["batch_size"])))
    effective["estimated_optimizer_steps"] = effective["steps_per_epoch"] * effective["epochs"]
    warnings: list[str] = []
    if effective["batch_size"] > train_images:
        warnings.append(
            f"Batch size {effective['batch_size']} is larger than the {train_images} training images; "
            "this yields only one optimizer update per epoch."
        )
    if effective["warmup_steps"] >= effective["estimated_optimizer_steps"]:
        warnings.append(
            f"Warmup ({effective['warmup_steps']} steps) covers the complete estimated training run "
            f"({effective['estimated_optimizer_steps']} optimizer steps)."
        )
    if train_images <= SMALL_DATASET_MAX_IMAGES:
        warnings.append(
            f"Small independent source set ({train_images} train images): overfitting risk is high; "
            "a two-image sanity-overfit check should pass before the full run."
        )
    if int(stats.get("negative_images") or 0) == 0:
        warnings.append(
            "Geen expliciete negatieve afbeeldingen in de train-split; voeg gecontroleerde beelden zonder tabel toe."
        )
    effective["warnings"] = warnings
    return effective


def write_effective_training_files(
    output: Path,
    *,
    dataset: Path,
    config: Path,
    pretrain: Path,
    device: str,
    settings: dict[str, Any],
) -> None:
    """Persist the exact IsalaOCR overrides before PaddleX starts."""
    payload = {
        "schema_version": 1,
        "created_at": utc_now(),
        "model_name": MODEL_NAME,
        "dataset": str(dataset),
        "paddlex_base_config": str(config),
        "pretrain_weight_path": str(pretrain),
        "device": device,
        **settings,
    }
    (output / "training_config.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    yaml_lines = [
        "# IsalaOCR effective PaddleDetection training settings",
        f"# Base PaddleX config: {config}",
        "Global:",
        f"  model: {MODEL_NAME}",
        f"  dataset_dir: {dataset}",
        f"  device: {device}",
        f"  output: {output}",
        "Train:",
        "  num_classes: 1",
        f"  epochs_iters: {settings['epochs']}",
        f"  batch_size: {settings['batch_size']}",
        f"  learning_rate: {settings['learning_rate']}",
        f"  warmup_steps: {settings['warmup_steps']}",
        f"  eval_interval: {settings['eval_interval']}",
        f"  pretrain_weight_path: {pretrain}",
        "IsalaOCR:",
        f"  profile: {settings['profile']}",
        f"  train_images: {settings['train_images']}",
        f"  train_annotations: {settings['train_annotations']}",
        f"  train_negative_images: {settings['train_negative_images']}",
        f"  steps_per_epoch: {settings['steps_per_epoch']}",
        f"  estimated_optimizer_steps: {settings['estimated_optimizer_steps']}",
    ]
    (output / "training_overrides.yml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    # Fallback copy; run_command replaces this with PaddleX's generated detector YAML when it can observe it.
    (output / "effective_paddledet.yml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")


def _copy_sanity_dataset(dataset: Path, target: Path, image_limit: int = 2) -> dict[str, Any]:
    """Create a tiny train/val COCO dataset from reviewed training sources."""
    source_payload = json.loads((dataset / "annotations" / "instance_train.json").read_text(encoding="utf-8"))
    images = list(source_payload.get("images") or [])[: max(1, int(image_limit))]
    if not images:
        raise RuntimeError("Sanity check cannot run because the training split has no images.")
    image_ids = {int(item["id"]) for item in images}
    annotations = [item for item in (source_payload.get("annotations") or []) if int(item.get("image_id", -1)) in image_ids]
    if not annotations:
        raise RuntimeError("Sanity check cannot run because the selected train images have no positive annotations.")
    categories = list(source_payload.get("categories") or [{"id": 1, "name": "field_roi"}])
    (target / "images").mkdir(parents=True, exist_ok=True)
    (target / "annotations").mkdir(parents=True, exist_ok=True)
    for image in images:
        name = str(image.get("file_name") or "")
        source = dataset / "images" / name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, target / "images" / Path(name).name)
        image["file_name"] = Path(name).name
    payload = {"images": images, "annotations": annotations, "categories": categories}
    for split in ("train", "val", "test"):
        (target / "annotations" / f"instance_{split}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    return {"images": len(images), "annotations": len(annotations)}


def _box_iou_xyxy(a: list[float], b: list[float]) -> float:
    left = max(a[0], b[0]); top = max(a[1], b[1])
    right = min(a[2], b[2]); bottom = min(a[3], b[3])
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


def evaluate_sanity_predictions(
    dataset: Path, predictions_path: Path, *, threshold: float = 0.01, split: str = "train"
) -> dict[str, Any]:
    gt_payload = json.loads((dataset / "annotations" / f"instance_{split}.json").read_text(encoding="utf-8"))
    prediction_payload = json.loads(predictions_path.read_text(encoding="utf-8"))
    by_image_id = {int(item["id"]): Path(str(item.get("file_name") or "")).stem for item in gt_payload.get("images") or []}
    truth: dict[str, list[list[float]]] = {stem: [] for stem in by_image_id.values()}
    for annotation in gt_payload.get("annotations") or []:
        stem = by_image_id.get(int(annotation.get("image_id", -1)))
        bbox = annotation.get("bbox") or []
        if stem and isinstance(bbox, list) and len(bbox) == 4:
            x, y, w, h = map(float, bbox)
            truth.setdefault(stem, []).append([x, y, x + w, y + h])
    predictions = prediction_payload.get("predictions") or {}
    total_truth = sum(len(items) for items in truth.values())
    total_predictions = 0
    true_positives = 0
    for stem, truth_boxes in truth.items():
        unmatched = set(range(len(truth_boxes)))
        candidates = []
        for item in predictions.get(stem, []) or []:
            if float(item.get("score") or 0.0) < threshold:
                continue
            coords = item.get("coordinate") or []
            if isinstance(coords, list) and len(coords) == 4:
                candidates.append([float(v) for v in coords])
        total_predictions += len(candidates)
        for candidate in sorted(candidates, key=lambda box: box[0]):
            best = None; best_iou = 0.0
            for index in unmatched:
                value = _box_iou_xyxy(candidate, truth_boxes[index])
                if value > best_iou:
                    best, best_iou = index, value
            if best is not None and best_iou >= 0.50:
                unmatched.remove(best)
                true_positives += 1
    recall = true_positives / total_truth if total_truth else 0.0
    precision = true_positives / total_predictions if total_predictions else 0.0
    negatives = sum(1 for items in truth.values() if not items)
    passed = (
        (total_predictions == 0 if total_truth == 0 else recall >= 0.80 and precision >= 0.80)
        and bool(total_truth or negatives)
    )
    return {
        "threshold": threshold,
        "ground_truth": total_truth,
        "predictions": total_predictions,
        "true_positives": true_positives,
        "recall_at_iou_0_50": recall,
        "precision_at_iou_0_50": precision,
        "negative_images": negatives,
        "passed": passed,
    }


def evaluate_test_predictions(dataset: Path, predictions_path: Path, *, threshold: float = 0.25) -> dict[str, Any]:
    """Score the independent test split, including explicit no-table images."""
    result = evaluate_sanity_predictions(dataset, predictions_path, threshold=threshold, split="test")
    result["split"] = "test"
    return result


def object_detection_config() -> Path:
    root = PADDLEX_ROOT / "paddlex" / "configs" / "modules" / "object_detection"
    candidates = [
        root / "PicoDet-S.yaml",
        root / "PicoDet-S.yml",
        root / "PicoDet-S_layout_3cls.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = sorted(root.glob("PicoDet-S*.y*ml")) if root.is_dir() else []
    if matches:
        return matches[0]
    raise FileNotFoundError(f"PaddleX {MODEL_NAME} config was not found below {root}")


def paddlex_subprocess_environment(*, eval_artifact_dir: Path | None = None) -> dict[str, str]:
    """Return the environment used by nested PaddleX/PaddleDetection commands.

    The localization runtime is bind-mounted from the host and therefore can
    carry small compatibility modules independently from the multi-gigabyte
    reusable training image.  Put this directory first on PYTHONPATH so
    PaddleDetection's legacy ``import pkg_resources`` resolves to the IsalaOCR
    compatibility shim when the image's setuptools no longer ships that module.
    """
    environment = os.environ.copy()
    runtime_root = Path(__file__).resolve().parent
    compatibility_directory = str(runtime_root / "paddledet_compat")
    runtime_directory = str(runtime_root)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (compatibility_directory, runtime_directory, existing) if part
    )
    if eval_artifact_dir is not None:
        eval_artifact_dir = Path(eval_artifact_dir).resolve()
        eval_artifact_dir.mkdir(parents=True, exist_ok=True)
        environment["ISALA_PADDLEDET_EVAL_ARTIFACT_DIR"] = str(eval_artifact_dir)
    else:
        environment.pop("ISALA_PADDLEDET_EVAL_ARTIFACT_DIR", None)
    return environment


def run_command(
    arguments: list[str],
    *,
    log_path: Path | None = None,
    eval_artifact_dir: Path | None = None,
    effective_config_path: Path | None = None,
) -> None:
    """Run PaddleX while mirroring combined stdout/stderr to the live terminal.

    PaddleX and PaddleDetection do not consistently use the same output stream.
    Combining both streams here prevents the job UI from showing only the final
    IsalaOCR wrapper error while hiding the actionable PaddleX exception.
    """
    print("Executing:", " ".join(arguments), flush=True)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    tail: list[str] = []
    handle = log_path.open("w", encoding="utf-8", errors="replace") if log_path is not None else None
    try:
        process = subprocess.Popen(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            errors="replace",
            env=paddlex_subprocess_environment(eval_artifact_dir=eval_artifact_dir),
        )
        assert process.stdout is not None
        captured_config = False
        for line in process.stdout:
            print(line, end="", flush=True)
            if handle is not None:
                handle.write(line)
                handle.flush()
            if effective_config_path is not None and not captured_config and "--config" in line:
                match = re.search(r"--config(?:['\",\s]+)(/[^'\",\]\s]+\.ya?ml)", line)
                if match:
                    source_config = Path(match.group(1))
                    if source_config.is_file():
                        effective_config_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_config, effective_config_path)
                        captured_config = True
                        print(f"Captured generated PaddleDetection config: {effective_config_path}", flush=True)
            tail.append(line.rstrip("\n"))
            if len(tail) > 80:
                tail.pop(0)
        return_code = process.wait()
    finally:
        if handle is not None:
            handle.close()
    if return_code:
        detail = "\n".join(tail[-30:]).strip()
        message = f"PaddleX exited with code {return_code}."
        if detail:
            message += f" Last output:\n{detail}"
        raise RuntimeError(message)


def validate_paddlex_coco_layout(dataset: Path) -> None:
    """Fail early with PaddleX's exact COCODetDataset image-path semantics."""
    problems: list[str] = []
    splits = ["train", "val"]
    if (dataset / "annotations" / "instance_test.json").is_file():
        splits.append("test")
    for split in splits:
        annotation_path = dataset / "annotations" / f"instance_{split}.json"
        if not annotation_path.is_file():
            problems.append(f"missing {annotation_path.relative_to(dataset)}")
            continue
        try:
            payload = json.loads(annotation_path.read_text(encoding="utf-8"))
        except Exception as exc:
            problems.append(f"cannot read {annotation_path.name}: {exc}")
            continue
        for image in payload.get("images") or []:
            raw_name = str(image.get("file_name") or "")
            rel = Path(raw_name)
            if not raw_name or rel.is_absolute() or ".." in rel.parts:
                problems.append(f"{annotation_path.name}: invalid file_name {raw_name!r}")
                continue
            expected = dataset / "images" / rel
            if expected.is_file():
                continue
            legacy = dataset / rel
            if rel.parts and rel.parts[0] == "images" and legacy.is_file():
                problems.append(
                    f"{annotation_path.name}: file_name {raw_name!r} contains an 'images/' prefix; "
                    "PaddleX prepends its own images directory and would search for "
                    f"{expected.relative_to(dataset)}. Rebuild the localization dataset with IsalaOCR 3.8.15+."
                )
            else:
                problems.append(
                    f"{annotation_path.name}: image not found at PaddleX path "
                    f"{expected.relative_to(dataset)}"
                )
            if len(problems) >= 12:
                break
        if len(problems) >= 12:
            break
    if problems:
        print("PaddleX COCO compatibility check failed:", file=sys.stderr, flush=True)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr, flush=True)
        raise RuntimeError(
            "Localization dataset is valid COCO for IsalaOCR but not in PaddleX's expected "
            "COCODetDataset image-path layout."
        )
    print("PaddleX COCO compatibility check: OK", flush=True)


def print_paddlex_check_result(output: Path) -> None:
    candidates = [output / "check_dataset_result.json", output.parent / "check_dataset_result.json"]
    for candidate in candidates:
        if candidate.is_file():
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                print("PaddleX check_dataset_result.json:", file=sys.stderr, flush=True)
                print(json.dumps(payload, indent=2, ensure_ascii=False), file=sys.stderr, flush=True)
            except Exception as exc:
                print(f"Could not read PaddleX validation result {candidate}: {exc}", file=sys.stderr, flush=True)
            return


def find_inference_dir(output: Path) -> Path:
    candidates = [
        output / "best_model" / "inference",
        output / "best_model",
        output / "inference",
    ]
    candidates.extend(path for path in output.rglob("inference") if path.is_dir())
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.iterdir()):
            return candidate
    raise FileNotFoundError(f"No exported/inference model found below {output}")


def command_validate(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    validate_paddlex_coco_layout(dataset)
    config = object_detection_config()
    command = [
        sys.executable, str(PADDLEX_ROOT / "main.py"),
        "-c", str(config),
        "-o", "Global.mode=check_dataset",
        "-o", f"Global.dataset_dir={dataset}",
        "-o", f"Global.output={output}",
        "-o", "CheckDataset.split.enable=False",
    ]
    print("Executing:", " ".join(command), flush=True)
    completed = subprocess.run(command, check=False, env=paddlex_subprocess_environment())
    if completed.returncode:
        print_paddlex_check_result(output)
        raise SystemExit(completed.returncode)
    marker = output / "isala_paddlex_validation.json"
    marker.write_text(json.dumps({
        "status": "ok", "ok": True, "dataset": str(dataset), "config": str(config),
        "validated_at": utc_now(),
    }, indent=2), encoding="utf-8")
    print(marker.read_text(encoding="utf-8"), flush=True)
    return 0


def _train_model(
    dataset: Path,
    output: Path,
    *,
    device_arg: str,
    epochs: int = 0,
    batch_size: int = 0,
    learning_rate: float = 0.0,
    warmup_steps: int = -1,
    eval_interval: int = 0,
) -> dict[str, Any]:
    validate_paddlex_coco_layout(dataset)
    if not (dataset / "annotations" / "instance_train.json").is_file():
        raise FileNotFoundError(f"COCO train annotations are missing below {dataset}")
    output.mkdir(parents=True, exist_ok=True)
    config = object_detection_config()
    device = "gpu:0" if str(device_arg).lower().startswith("gpu") else "cpu"
    pretrain = Path(os.environ.get(
        "ISALA_PICODET_PRETRAIN",
        "/models/training/PicoDet-S_pretrained.pdparams",
    ))
    if not pretrain.is_file() or pretrain.stat().st_size <= 1024 * 1024:
        raise FileNotFoundError(
            "PicoDet-S training pretrain weight is missing. Expected an offline "
            f"weight >1 MiB at {pretrain}. Open Stap 1 - Voorbereiding and run "
            "GPU PaddleDetection / PicoDet-S download, or retry training so the "
            "host launcher can download the official weight first."
        )
    settings = resolve_training_settings(
        dataset,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        warmup_steps=warmup_steps,
        eval_interval=eval_interval,
    )
    print(f"Using local PicoDet-S pretrain weight: {pretrain} ({pretrain.stat().st_size} bytes)", flush=True)
    print(
        "Effective training profile: "
        f"{settings['profile']} | images={settings['train_images']} | annotations={settings['train_annotations']} | "
        f"batch={settings['batch_size']} | epochs={settings['epochs']} | lr={settings['learning_rate']} | "
        f"warmup={settings['warmup_steps']} | eval_every={settings['eval_interval']} | "
        f"~{settings['estimated_optimizer_steps']} optimizer steps",
        flush=True,
    )
    for warning in settings.get("warnings") or []:
        print(f"TRAINING WARNING: {warning}", flush=True)
    write_effective_training_files(
        output, dataset=dataset, config=config, pretrain=pretrain, device=device, settings=settings
    )
    command = [
        sys.executable,
        str(PADDLEX_ROOT / "main.py"),
        "-c", str(config),
        "-o", "Global.mode=train",
        "-o", f"Global.dataset_dir={dataset}",
        "-o", f"Global.device={device}",
        "-o", f"Global.output={output}",
        "-o", f"Train.epochs_iters={settings['epochs']}",
        "-o", f"Train.batch_size={settings['batch_size']}",
        "-o", f"Train.learning_rate={settings['learning_rate']}",
        "-o", f"Train.warmup_steps={settings['warmup_steps']}",
        "-o", f"Train.eval_interval={settings['eval_interval']}",
        "-o", "Train.num_classes=1",
        "-o", f"Train.pretrain_weight_path={pretrain}",
        "-o", "EvalDataset.anno_path=annotations/instance_val.json",
        "-o", "TestDataset.anno_path=annotations/instance_test.json",
    ]
    eval_artifact_dir = output / "evaluation_artifacts"
    print(f"PaddleDetection evaluation artifacts: {eval_artifact_dir}", flush=True)
    run_command(
        command,
        log_path=output / "paddlex_train.log",
        eval_artifact_dir=eval_artifact_dir,
        effective_config_path=output / "effective_paddledet.yml",
    )
    inference = find_inference_dir(output)
    test_evaluation: dict[str, Any] = {"status": "missing", "passed": False}
    test_annotations = dataset / "annotations" / "instance_test.json"
    if test_annotations.is_file():
        test_payload = json.loads(test_annotations.read_text(encoding="utf-8"))
        if test_payload.get("images"):
            test_predictions = output / "evaluation_artifacts" / "test_predictions.json"
            run_command(
                [
                    sys.executable, str(Path(__file__).resolve()), "predict",
                    "--model-dir", str(inference), "--input", str(dataset / "images"),
                    "--output", str(test_predictions), "--device", device_arg, "--threshold", "0.25",
                ],
                log_path=output / "evaluation_artifacts" / "test_predict.log",
            )
            test_evaluation = evaluate_test_predictions(dataset, test_predictions)
            test_evaluation["status"] = "completed"
    (output / "evaluation_artifacts").mkdir(parents=True, exist_ok=True)
    (output / "evaluation_artifacts" / "test_evaluation.json").write_text(
        json.dumps(test_evaluation, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    metadata = {
        "status": "trained",
        "model_name": MODEL_NAME,
        "dataset": str(dataset),
        "device": device,
        "epochs": settings["epochs"],
        "batch_size": settings["batch_size"],
        "learning_rate": settings["learning_rate"],
        "warmup_steps": settings["warmup_steps"],
        "eval_interval": settings["eval_interval"],
        "training_profile": settings["profile"],
        "steps_per_epoch": settings["steps_per_epoch"],
        "estimated_optimizer_steps": settings["estimated_optimizer_steps"],
        "config": str(config),
        "training_config": str(output / "training_config.json"),
        "effective_paddledet_config": str(output / "effective_paddledet.yml"),
        "output": str(output),
        "inference_dir": str(inference),
        "test_evaluation": test_evaluation,
        "completed_at": utc_now(),
    }
    (output / "isala_localization_run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)
    return metadata


def command_train(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset).resolve()
    output = Path(args.output).resolve()
    _train_model(
        dataset,
        output,
        device_arg=args.device,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        warmup_steps=args.warmup_steps,
        eval_interval=args.eval_interval,
    )
    return 0


def command_sanity_check(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    stats = coco_train_stats(dataset)
    result_path = output / "sanity_check.json"
    if int(stats["images"]) > SMALL_DATASET_MAX_IMAGES and not args.force:
        result = {
            "status": "skipped",
            "passed": True,
            "reason": f"Training split has {stats['images']} images; sanity-overfit is only automatic for <= {SMALL_DATASET_MAX_IMAGES} images.",
            "created_at": utc_now(),
        }
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2), flush=True)
        return 0

    sanity_dataset = output / "sanity_dataset"
    sanity_run = output / "sanity_run"
    if sanity_dataset.exists():
        shutil.rmtree(sanity_dataset)
    if sanity_run.exists():
        shutil.rmtree(sanity_run)
    subset = _copy_sanity_dataset(dataset, sanity_dataset, image_limit=args.images)
    print(
        f"Running sanity-overfit check on {subset['images']} training images / {subset['annotations']} boxes before full training...",
        flush=True,
    )
    metadata = _train_model(
        sanity_dataset,
        sanity_run,
        device_arg=args.device,
        epochs=args.epochs if args.epochs > 0 else 60,
        batch_size=1,
        learning_rate=args.learning_rate if args.learning_rate > 0 else 0.002,
        warmup_steps=args.warmup_steps if args.warmup_steps >= 0 else 5,
        eval_interval=args.eval_interval if args.eval_interval > 0 else 10,
    )
    predictions_path = output / "sanity_predictions.json"
    prediction_args = argparse.Namespace(
        model_dir=metadata["inference_dir"],
        input=str(sanity_dataset / "images"),
        output=str(predictions_path),
        device=args.device,
        threshold=0.01,
    )
    command_predict(prediction_args)
    result = evaluate_sanity_predictions(sanity_dataset, predictions_path, threshold=0.01)
    result.update({
        "status": "ok" if result["passed"] else "failed",
        "created_at": utc_now(),
        "dataset": str(dataset),
        "sanity_dataset": str(sanity_dataset),
        "sanity_run": str(sanity_run),
        "training_profile": "sanity-overfit",
        "criterion": "At least one prediction at confidence 0.01 on the same images used for sanity training.",
    })
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    if not result["passed"]:
        raise RuntimeError(
            "Sanity-overfit check produced zero predictions on its own training images. "
            "Full training was stopped because the problem is in training/export/inference, not generalization. "
            f"See {result_path}."
        )
    # Keep small diagnostics, not a second complete detector checkpoint tree.
    for source_name, target_name in (
        ("paddlex_train.log", "sanity_paddlex_train.log"),
        ("training_config.json", "sanity_training_config.json"),
        ("effective_paddledet.yml", "sanity_effective_paddledet.yml"),
        ("training_overrides.yml", "sanity_training_overrides.yml"),
    ):
        source = sanity_run / source_name
        if source.is_file():
            shutil.copy2(source, output / target_name)
    shutil.rmtree(sanity_run, ignore_errors=True)
    shutil.rmtree(sanity_dataset, ignore_errors=True)
    return 0



def _result_json(result: Any) -> dict[str, Any]:
    raw = getattr(result, "json", None)
    if callable(raw):
        raw = raw()
    if raw is None and isinstance(result, dict):
        raw = result
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    return dict(raw) if isinstance(raw, dict) else {}


def _boxes_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    current: Any = payload
    for key in ("res", "result", "data"):
        if isinstance(current, dict) and isinstance(current.get(key), dict):
            current = current[key]
            break
    boxes = current.get("boxes") if isinstance(current, dict) else None
    if not isinstance(boxes, list):
        boxes = payload.get("boxes")
    output: list[dict[str, Any]] = []
    if not isinstance(boxes, list):
        return output
    for item in boxes:
        if not isinstance(item, dict):
            continue
        coordinate = item.get("coordinate") or item.get("bbox") or item.get("box")
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 4:
            continue
        try:
            score = float(item.get("score") or item.get("confidence") or 0.0)
            coords = [float(value) for value in coordinate]
        except (TypeError, ValueError):
            continue
        output.append({
            "score": score,
            "coordinate": coords,
            "bbox_format": "xyxy",
            "label": item.get("label") or item.get("class_name") or "field_roi",
            "class_id": item.get("cls_id", item.get("class_id", 0)),
        })
    return output


def command_predict(args: argparse.Namespace) -> int:
    model_dir = Path(args.model_dir).resolve()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    if not model_dir.is_dir():
        raise FileNotFoundError(model_dir)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    # Ensure the checksum-pinned source tree wins over stale distribution metadata
    # inherited from the vendor base image.
    sys.path.insert(0, str(PADDLEX_ROOT))
    from paddlex import create_model  # type: ignore

    device = "gpu:0" if str(args.device).lower().startswith("gpu") else "cpu"
    if device == "cpu":
        _verify_cpu_inference_paddle()
    model = create_model(model_name=MODEL_NAME, model_dir=str(model_dir), device=device)
    if input_path.is_file():
        images = [input_path]
    else:
        images = sorted(
            path for path in input_path.rglob("*")
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
        )
    predictions: dict[str, list[dict[str, Any]]] = {}
    for index, image in enumerate(images, start=1):
        print(f"Predicting {index}/{len(images)}: {image.name}", flush=True)
        items: list[dict[str, Any]] = []
        for result in model.predict(str(image), batch_size=1, threshold=float(args.threshold)):
            items.extend(_boxes_from_payload(_result_json(result)))
        predictions[image.stem] = items
    payload = {
        "model_name": MODEL_NAME,
        "model_dir": str(model_dir),
        "device": device,
        "threshold": float(args.threshold),
        "created_at": utc_now(),
        "predictions": predictions,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "ok", "images": len(images), "predictions": sum(map(len, predictions.values())), "output": str(output_path)}, indent=2), flush=True)
    return 0


def command_prepare(args: argparse.Namespace) -> int:
    """Materialize the official PicoDet-S inference baseline into the shared cache."""
    import numpy as np
    import cv2
    sys.path.insert(0, str(PADDLEX_ROOT))
    from paddlex import create_model  # type: ignore

    paddle_version = _verify_cpu_inference_paddle()
    model = create_model(model_name=MODEL_NAME, device="cpu")
    synthetic = np.full((128, 384, 3), 255, dtype=np.uint8)
    cv2.rectangle(synthetic, (30, 35), (170, 80), (0, 0, 0), 2)
    # Trigger lazy downloads/initialization without relying on prediction quality.
    result_count = 0
    for _ in model.predict(synthetic, batch_size=1, threshold=0.95):
        result_count += 1
    manifest = {
        "status": "prepared", "model_name": MODEL_NAME,
        "cache_home": os.environ.get("PADDLE_PDX_CACHE_HOME", ""),
        "paddle_version": paddle_version,
        "smoke_result_count": result_count, "prepared_at": utc_now(),
    }
    path = Path(args.manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


def command_check(_: argparse.Namespace) -> int:
    config = object_detection_config()
    print(json.dumps({
        "status": "ok",
        "paddlex_root": str(PADDLEX_ROOT),
        "model_name": MODEL_NAME,
        "config": str(config),
        "main_py": str(PADDLEX_ROOT / "main.py"),
    }, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.set_defaults(func=command_check)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--manifest", default="/models/paddlex/isala_localization_model_manifest.json")
    prepare.set_defaults(func=command_prepare)

    validate = sub.add_parser("validate")
    validate.add_argument("--dataset", required=True)
    validate.add_argument("--output", required=True)
    validate.set_defaults(func=command_validate)

    train = sub.add_parser("train")
    train.add_argument("--dataset", required=True)
    train.add_argument("--output", required=True)
    train.add_argument("--device", choices=["cpu", "gpu"], default="cpu")
    train.add_argument("--epochs", type=int, default=0, help="0 = automatic profile")
    train.add_argument("--batch-size", type=int, default=0, help="0 = automatic profile")
    train.add_argument("--learning-rate", type=float, default=0.0, help="0 = automatic profile")
    train.add_argument("--warmup-steps", type=int, default=-1, help="-1 = automatic profile")
    train.add_argument("--eval-interval", type=int, default=0, help="0 = automatic profile")
    train.set_defaults(func=command_train)

    sanity = sub.add_parser("sanity-check")
    sanity.add_argument("--dataset", required=True)
    sanity.add_argument("--output", required=True)
    sanity.add_argument("--device", choices=["cpu", "gpu"], default="cpu")
    sanity.add_argument("--images", type=int, default=2)
    sanity.add_argument("--epochs", type=int, default=0)
    sanity.add_argument("--learning-rate", type=float, default=0.0)
    sanity.add_argument("--warmup-steps", type=int, default=-1)
    sanity.add_argument("--eval-interval", type=int, default=0)
    sanity.add_argument("--force", action="store_true")
    sanity.set_defaults(func=command_sanity_check)

    predict = sub.add_parser("predict")
    predict.add_argument("--model-dir", required=True)
    predict.add_argument("--input", required=True)
    predict.add_argument("--output", required=True)
    predict.add_argument("--device", choices=["cpu", "gpu"], default="cpu")
    predict.add_argument("--threshold", type=float, default=0.25)
    predict.set_defaults(func=command_predict)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
