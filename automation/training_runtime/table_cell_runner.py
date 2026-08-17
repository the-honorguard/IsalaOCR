from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODEL_NAME = "RT-DETR-L_wireless_table_cell_det"
PADDLEX_ROOT = Path(os.environ.get("ISALA_PADDLEX_SOURCE_ROOT", "/opt/paddlex-source"))
PRETRAIN_DEFAULT = "/models/training/RT-DETR-L_wireless_table_cell_det_pretrained.pdparams"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def config_path() -> Path:
    root = PADDLEX_ROOT / "paddlex" / "configs" / "modules" / "table_cells_detection"
    for name in (f"{MODEL_NAME}.yaml", f"{MODEL_NAME}.yml"):
        path = root / name
        if path.is_file():
            return path
    matches = sorted(root.glob(f"{MODEL_NAME}*.y*ml")) if root.is_dir() else []
    if matches:
        return matches[0]
    raise FileNotFoundError(f"PaddleX table-cell config not found below {root}")


def env(*, eval_artifact_dir: Path | None = None) -> dict[str, str]:
    result = os.environ.copy()
    runtime = Path(__file__).resolve().parent
    compat = runtime / "paddledet_compat"
    existing = result.get("PYTHONPATH", "")
    result["PYTHONPATH"] = os.pathsep.join(str(x) for x in (compat, runtime, existing) if str(x))
    if eval_artifact_dir is not None:
        eval_artifact_dir = Path(eval_artifact_dir).resolve()
        eval_artifact_dir.mkdir(parents=True, exist_ok=True)
        result["ISALA_PADDLEDET_EVAL_ARTIFACT_DIR"] = str(eval_artifact_dir)
    else:
        result.pop("ISALA_PADDLEDET_EVAL_ARTIFACT_DIR", None)
    return result


def run(command: list[str], *, log_path: Path | None = None, eval_artifact_dir: Path | None = None) -> None:
    print("Executing:", " ".join(command), flush=True)
    handle = None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("w", encoding="utf-8", errors="replace")
    tail: list[str] = []
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1, errors="replace", env=env(eval_artifact_dir=eval_artifact_dir),
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            if handle:
                handle.write(line); handle.flush()
            tail.append(line.rstrip())
            if len(tail) > 80:
                tail.pop(0)
        code = process.wait()
    finally:
        if handle:
            handle.close()
    if code:
        raise RuntimeError(f"PaddleX exited with code {code}. Last output:\n" + "\n".join(tail[-30:]))


def validate_coco(dataset: Path) -> dict[str, Any]:
    issues: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    for split in ("train", "val", "test"):
        path = dataset / "annotations" / f"instance_{split}.json"
        if not path.is_file():
            issues.append(f"missing {path.relative_to(dataset)}")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        images = list(payload.get("images") or [])
        annotations = list(payload.get("annotations") or [])
        counts[split] = {"images": len(images), "annotations": len(annotations)}
        for image in images:
            name = str(image.get("file_name") or "")
            if not name or not (dataset / "images" / name).is_file():
                issues.append(f"{split}: image missing: {name!r}")
                if len(issues) >= 12:
                    break
    if issues:
        raise RuntimeError("Table-cell COCO dataset is invalid:\n- " + "\n- ".join(issues))
    if counts.get("train", {}).get("images", 0) < 1 or counts.get("train", {}).get("annotations", 0) < 1:
        raise RuntimeError("Table-cell train split needs at least one image and one positive cell")
    return counts


def resolve_settings(dataset: Path, *, device: str, epochs: int, batch_size: int, learning_rate: float = 0.0) -> dict[str, Any]:
    counts = validate_coco(dataset)
    images = int(counts["train"]["images"])
    annotations = int(counts["train"]["annotations"])
    if images <= 20:
        defaults = {"epochs": 120, "batch": 2 if device == "gpu" else 1, "profile": "small-reviewed"}
    elif images <= 60:
        defaults = {"epochs": 80, "batch": 4 if device == "gpu" else 2, "profile": "medium-reviewed"}
    else:
        defaults = {"epochs": 50, "batch": 8 if device == "gpu" else 2, "profile": "standard"}
    effective_epochs = int(epochs) if int(epochs) > 0 else defaults["epochs"]
    effective_batch = int(batch_size) if int(batch_size) > 0 else defaults["batch"]
    steps = max(1, math.ceil(images / max(1, effective_batch)))
    effective_learning_rate = float(learning_rate) if float(learning_rate or 0.0) > 0 else 0.0001
    return {
        "profile": defaults["profile"], "train_images": images, "train_annotations": annotations,
        "epochs": effective_epochs, "batch_size": effective_batch, "learning_rate": effective_learning_rate,
        "warmup_steps": min(100, max(5, steps * 3)), "eval_interval": max(1, min(10, effective_epochs // 8)),
        "estimated_optimizer_steps": steps * effective_epochs,
    }


def find_weight(output: Path) -> Path:
    candidates = [
        output / "best_model" / "best_model.pdparams",
        output / "best_model" / "model.pdparams",
        output / "best_accuracy.pdparams",
    ]
    candidates.extend(sorted(output.rglob("*.pdparams"), key=lambda p: p.stat().st_mtime, reverse=True))
    for item in candidates:
        if item.is_file() and item.stat().st_size > 1024:
            return item
    raise FileNotFoundError(f"No trained .pdparams found below {output}")


def find_inference(output: Path) -> Path | None:
    candidates = [output / "best_model" / "inference", output / "best_model", output / "inference", output / "export"]
    candidates.extend(path for path in output.rglob("inference") if path.is_dir())
    for item in candidates:
        if item.is_dir() and any(item.iterdir()):
            return item
    return None


def command_check(_: argparse.Namespace) -> int:
    config = config_path()
    print(json.dumps({"status":"ok", "model_name": MODEL_NAME, "config": str(config), "main_py": str(PADDLEX_ROOT / "main.py")}, indent=2))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset).resolve(); output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    counts = validate_coco(dataset); config = config_path()
    command = [sys.executable, str(PADDLEX_ROOT / "main.py"), "-c", str(config),
               "-o", "Global.mode=check_dataset", "-o", f"Global.dataset_dir={dataset}",
               "-o", f"Global.output={output}", "-o", "CheckDataset.split.enable=False"]
    run(command, log_path=output / "paddlex_dataset_check.log")
    marker = {"status":"ok", "valid":True, "dataset":str(dataset), "counts":counts, "config":str(config), "validated_at":utc_now()}
    (output / "table_cell_paddlex_validation.json").write_text(json.dumps(marker, indent=2), encoding="utf-8")
    print(json.dumps(marker, indent=2), flush=True)
    return 0


def command_train(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset).resolve(); output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    settings = resolve_settings(
        dataset, device=args.device, epochs=args.epochs, batch_size=args.batch_size,
        learning_rate=args.learning_rate,
    )
    config = config_path(); device = "gpu:0" if args.device == "gpu" else "cpu"
    pretrain = Path(args.pretrain or PRETRAIN_DEFAULT).resolve()
    if not pretrain.is_file() or pretrain.stat().st_size <= 1024 * 1024:
        raise FileNotFoundError(f"Official {MODEL_NAME} pretrained weight missing or too small: {pretrain}")
    metadata = {"schema_version":2, "model_name":MODEL_NAME, "dataset":str(dataset), "device":device,
                "pretrain":str(pretrain), "parent_model_id":str(args.parent_model_id or ""),
                "training_mode":str(args.training_mode or "fresh"), **settings, "started_at":utc_now()}
    (output / "training_config.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    command = [sys.executable, str(PADDLEX_ROOT / "main.py"), "-c", str(config),
               "-o", "Global.mode=train", "-o", f"Global.dataset_dir={dataset}",
               "-o", f"Global.device={device}", "-o", f"Global.output={output}",
               "-o", f"Train.epochs_iters={settings['epochs']}",
               "-o", f"Train.batch_size={settings['batch_size']}",
               "-o", f"Train.learning_rate={settings['learning_rate']}",
               "-o", f"Train.warmup_steps={settings['warmup_steps']}",
               "-o", f"Train.eval_interval={settings['eval_interval']}",
               "-o", "Train.num_classes=1", "-o", f"Train.pretrain_weight_path={pretrain}"]
    run(command, log_path=output / "paddlex_train.log", eval_artifact_dir=output / "evaluation_artifacts")
    inference = find_inference(output)
    if inference is None:
        weight = find_weight(output)
        export_root = output / "export"
        export_root.mkdir(parents=True, exist_ok=True)
        export_cmd = [sys.executable, str(PADDLEX_ROOT / "main.py"), "-c", str(config),
                      "-o", "Global.mode=export", "-o", f"Global.device={device}",
                      "-o", f"Global.output={export_root}", "-o", f"Export.weight_path={weight}"]
        run(export_cmd, log_path=output / "paddlex_export.log")
        inference = find_inference(output)
    if inference is None:
        raise FileNotFoundError(f"Training completed but no inference model was exported below {output}")
    metadata.update({"status":"trained", "inference_dir":str(inference), "completed_at":utc_now()})
    (output / "table_cell_run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)
    return 0


def result_json(result: Any) -> dict[str, Any]:
    raw = getattr(result, "json", result)
    if callable(raw): raw = raw()
    if isinstance(raw, str):
        try: raw = json.loads(raw)
        except json.JSONDecodeError: raw = {}
    if isinstance(raw, dict) and isinstance(raw.get("res"), dict): raw = raw["res"]
    return dict(raw) if isinstance(raw, dict) else {}


def boxes_from(result: Any) -> list[dict[str, Any]]:
    payload = result_json(result)
    raw = payload.get("boxes") or payload.get("dt_boxes") or []
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list): return out
    for item in raw:
        if not isinstance(item, dict): continue
        coords = item.get("coordinate") or item.get("bbox") or item.get("box")
        if not isinstance(coords, (list, tuple)) or len(coords) != 4: continue
        try:
            score = float(item.get("score") or item.get("confidence") or 0.0)
            box = [float(value) for value in coords]
        except (TypeError, ValueError): continue
        out.append({"score":score, "coordinate":box, "bbox_format":"xyxy", "label":"table_cell", "class_id":0})
    return out


def command_predict(args: argparse.Namespace) -> int:
    model_dir = Path(args.model_dir).resolve(); input_path = Path(args.input).resolve(); output = Path(args.output).resolve()
    if not model_dir.is_dir(): raise FileNotFoundError(model_dir)
    if not input_path.exists(): raise FileNotFoundError(input_path)
    sys.path.insert(0, str(PADDLEX_ROOT))
    from paddlex import create_model  # type: ignore
    device = "gpu:0" if args.device == "gpu" else "cpu"
    model = create_model(model_name=MODEL_NAME, model_dir=str(model_dir), device=device)
    images = [input_path] if input_path.is_file() else sorted(p for p in input_path.rglob("*") if p.suffix.lower() in {".png",".jpg",".jpeg",".bmp",".tif",".tiff"})
    predictions: dict[str, list[dict[str, Any]]] = {}
    for index, image in enumerate(images, 1):
        print(f"Predicting {index}/{len(images)}: {image.name}", flush=True)
        found: list[dict[str, Any]] = []
        for result in model.predict(str(image), batch_size=1, threshold=float(args.threshold)):
            found.extend(boxes_from(result))
        predictions[image.stem] = found
    payload = {"model_name":MODEL_NAME, "model_dir":str(model_dir), "device":device,
               "threshold":float(args.threshold), "created_at":utc_now(), "predictions":predictions}
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"status":"ok", "images":len(images), "predictions":sum(len(v) for v in predictions.values()), "output":str(output)}, indent=2), flush=True)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IsalaOCR wireless table-cell detector training runtime")
    sub = p.add_subparsers(dest="command", required=True)
    c=sub.add_parser("check"); c.set_defaults(func=command_check)
    v=sub.add_parser("validate"); v.add_argument("--dataset", required=True); v.add_argument("--output", required=True); v.set_defaults(func=command_validate)
    t=sub.add_parser("train"); t.add_argument("--dataset", required=True); t.add_argument("--output", required=True); t.add_argument("--device", choices=["cpu","gpu"], default="gpu"); t.add_argument("--epochs", type=int, default=0); t.add_argument("--batch-size", type=int, default=0); t.add_argument("--learning-rate", type=float, default=0.0); t.add_argument("--pretrain", default=PRETRAIN_DEFAULT); t.add_argument("--parent-model-id", default=""); t.add_argument("--training-mode", choices=["fresh","continue"], default="fresh"); t.set_defaults(func=command_train)
    r=sub.add_parser("predict"); r.add_argument("--model-dir", required=True); r.add_argument("--input", required=True); r.add_argument("--output", required=True); r.add_argument("--device", choices=["cpu","gpu"], default="gpu"); r.add_argument("--threshold", type=float, default=0.01); r.set_defaults(func=command_predict)
    return p


def main() -> int:
    args = parser().parse_args(); return int(args.func(args))

if __name__ == "__main__":
    raise SystemExit(main())
