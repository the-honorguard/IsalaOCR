from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_inference_dir(path: Path) -> Path:
    candidates = [path, path / "inference", path / "best_accuracy" / "inference"]
    candidates.extend(item.parent for item in path.rglob("inference.json"))
    candidates.extend(item.parent for item in path.rglob("inference.pdmodel"))
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.pdiparams")) and (
            (candidate / "inference.json").exists()
            or (candidate / "inference.pdmodel").exists()
        ):
            return candidate
    raise FileNotFoundError(f"No exported Paddle inference model found under {path}")


def register_model(
    registry_root: str | Path,
    run_dir: str | Path,
    evaluation_file: str | Path,
    model_id: str | None = None,
) -> dict[str, Any]:
    root = Path(registry_root)
    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    evaluation = _read_json(Path(evaluation_file))
    run = Path(run_dir)
    inference = _find_inference_dir(run)
    if not model_id:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        score = evaluation.get("metrics", {}).get("exact_match_accuracy", 0.0)
        model_id = f"isala-rec-{stamp}-{score:.4f}".replace(".", "p")
    destination = models / model_id
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copytree(inference, destination / "inference")
    shutil.copy2(evaluation_file, destination / "evaluation.json")
    manifest = {
        "model_id": model_id,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": evaluation.get("dataset_id"),
        "metrics": evaluation.get("metrics", {}),
        "source_run": run.name,
        "inference_dir": "inference",
    }
    (destination / "model.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    index_path = root / "registry.json"
    index = _read_json(index_path) if index_path.exists() else {"models": []}
    index["models"] = [item for item in index.get("models", []) if item.get("model_id") != model_id]
    index["models"].append(manifest)
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return manifest


def activate_model(
    registry_root: str | Path,
    model_root: str | Path,
    model_id: str,
    minimum_exact_match: float = 0.0,
    force: bool = False,
    active_destination: str | Path | None = None,
) -> dict[str, Any]:
    registry = Path(registry_root)
    model_root_path = Path(model_root)
    if model_id.startswith("official:"):
        model_name = model_id.split(":", 1)[1]
        allowed = {"PP-OCRv6_small_rec", "PP-OCRv6_medium_rec"}
        if model_name not in allowed:
            raise ValueError(f"Unsupported official recognition model: {model_name}")
        source = model_root_path / "paddlex" / "official_models" / model_name
        if not source.is_dir():
            raise FileNotFoundError(
                f"Official model cache is missing: {source}. Run model preparation first."
            )
        destination = Path(active_destination) if active_destination is not None else model_root_path / "active-recognition"
        temporary = destination.with_name(destination.name + ".new")
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(source, temporary)
        manifest = {
            "model_id": model_id,
            "source": "official",
            "recognition_model": model_name,
            "model_name": model_name,
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": {},
        }
        (temporary / "isala_model.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        if destination.exists():
            shutil.rmtree(destination)
        temporary.rename(destination)
        active = {
            "model_id": model_id,
            "source": "official",
            "recognition_model": model_name,
            "activated_at": manifest["activated_at"],
            "path": str(destination),
            "metrics": {},
        }
        (registry / "active.json").write_text(json.dumps(active, indent=2), encoding="utf-8")
        return active

    source = registry / "models" / model_id
    manifest = _read_json(source / "model.json")
    score = float(manifest.get("metrics", {}).get("exact_match_accuracy", 0.0))
    if score < minimum_exact_match and not force:
        raise ValueError(
            f"Model exact-match accuracy {score:.4%} is below activation threshold "
            f"{minimum_exact_match:.4%}; use --force only after explicit review"
        )
    destination = Path(active_destination) if active_destination is not None else model_root_path / "active-recognition"
    temporary = destination.with_name(destination.name + ".new")
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(source / "inference", temporary)
    (temporary / "isala_model.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    if destination.exists():
        shutil.rmtree(destination)
    temporary.rename(destination)
    active = {
        "model_id": model_id,
        "activated_at": datetime.now(timezone.utc).isoformat(),
        "path": str(destination),
        "metrics": manifest.get("metrics", {}),
    }
    (registry / "active.json").write_text(json.dumps(active, indent=2), encoding="utf-8")
    return active
