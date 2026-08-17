from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2

from ..ocr.recognition import PaddleRecognitionEngine
from .metrics import compute_metrics


def _read_annotations(dataset: Path, split: str = "test") -> list[tuple[str, str]]:
    path = dataset / f"{split}.txt"
    if not path.is_file():
        raise FileNotFoundError(path)
    rows: list[tuple[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        try:
            relative, label = line.split("\t", 1)
        except ValueError as exc:
            raise ValueError(f"Invalid annotation at {path}:{line_number}") from exc
        rows.append((relative, label))
    return rows


def evaluate_model(
    dataset_dir: str | Path,
    settings: dict[str, Any],
    output_dir: str | Path,
    model_dir: str | Path | None = None,
    split: str = "test",
    batch_size: int = 32,
) -> dict[str, Any]:
    dataset = Path(dataset_dir)
    rows = _read_annotations(dataset, split)
    if not rows:
        raise ValueError(f"Dataset split '{split}' contains no samples")
    images = []
    metadata = []
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    by_image = {item["image"]: item for item in manifest.get("samples", [])}
    for relative, label in rows:
        image = cv2.imread(str(dataset / relative), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not read evaluation image: {relative}")
        images.append(image)
        item = by_image.get(relative, {})
        metadata.append(
            {
                "image": relative,
                "expected": label,
                "field_key": item.get("field_key", "unknown"),
                "source_id": item.get("source_id", "unknown"),
            }
        )
    actual_settings = dict(settings)
    actual_settings["recognition_batch_size"] = batch_size
    engine = PaddleRecognitionEngine(actual_settings, model_dir=model_dir)
    predictions = engine.recognize_many(images)
    records = []
    for item, tokens in zip(metadata, predictions, strict=True):
        observed = tokens[0].text if tokens else ""
        confidence = tokens[0].confidence if tokens else 0.0
        records.append({**item, "observed": observed, "confidence": confidence})
    metrics = compute_metrics(records)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset),
        "dataset_id": manifest.get("dataset_id", dataset.name),
        "split": split,
        "model": engine.info(),
        "metrics": metrics,
        "predictions": records,
        "label_policy": "verbatim_no_normalization",
    }
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "evaluation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = [
        "# OCR recognition evaluation",
        "",
        f"- Dataset: `{report['dataset_id']}`",
        f"- Split: `{split}`",
        f"- Samples: {metrics['samples']}",
        f"- Exact-match accuracy: {metrics['exact_match_accuracy']:.4%}",
        f"- Character error rate: {metrics['character_error_rate']:.4%}",
        "- Text handling: verbatim; no normalization or correction",
        "",
        "## Per field",
        "",
        "| Field | Samples | Exact match | CER |",
        "|---|---:|---:|---:|",
    ]
    for field, values in metrics["per_field"].items():
        lines.append(
            f"| {field} | {values['samples']} | "
            f"{values['exact_match_accuracy']:.2%} | {values['character_error_rate']:.2%} |"
        )
    lines.extend(["", "## Most frequent confusions", ""])
    for item in metrics["confusion_pairs"][:20]:
        lines.append(f"- `{item['pair']}`: {item['count']}")
    (output / "evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def _prediction_key(record: dict[str, Any]) -> tuple[str, str, str]:
    """Return a stable identity for the same sample across two evaluations."""
    return (
        str(record.get("image", "")),
        str(record.get("source_id", "unknown")),
        str(record.get("field_key", "unknown")),
    )


def _model_label(evaluation: dict[str, Any], fallback: str) -> str:
    model = evaluation.get("model")
    if isinstance(model, dict):
        return str(
            model.get("recognition_model")
            or model.get("model_id")
            or model.get("model_dir")
            or fallback
        )
    return str(model or fallback)


def compare_evaluations(
    baseline_file: str | Path,
    custom_file: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    baseline = json.loads(Path(baseline_file).read_text(encoding="utf-8"))
    custom = json.loads(Path(custom_file).read_text(encoding="utf-8"))
    if baseline.get("dataset_id") != custom.get("dataset_id") or baseline.get("split") != custom.get("split"):
        raise ValueError("Baseline and custom evaluations must use the same dataset and split")

    baseline_predictions = {
        _prediction_key(item): item for item in baseline.get("predictions", [])
    }
    custom_predictions = {
        _prediction_key(item): item for item in custom.get("predictions", [])
    }
    if set(baseline_predictions) != set(custom_predictions):
        missing_in_custom = sorted(set(baseline_predictions) - set(custom_predictions))
        missing_in_baseline = sorted(set(custom_predictions) - set(baseline_predictions))
        raise ValueError(
            "Baseline and custom evaluations do not contain the same samples "
            f"(missing in custom: {len(missing_in_custom)}, "
            f"missing in baseline: {len(missing_in_baseline)})"
        )

    base_metrics = baseline["metrics"]
    custom_metrics = custom["metrics"]
    sample_comparisons: list[dict[str, Any]] = []
    outcome_counts = {
        "both_correct": 0,
        "custom_only_correct": 0,
        "baseline_only_correct": 0,
        "both_wrong": 0,
        "disagreements": 0,
    }
    for key in sorted(baseline_predictions):
        old = baseline_predictions[key]
        new = custom_predictions[key]
        expected = str(new.get("expected", old.get("expected", "")))
        if str(old.get("expected", "")) != expected:
            raise ValueError(f"Expected label differs between evaluations for sample: {key[0]}")
        old_observed = str(old.get("observed", ""))
        new_observed = str(new.get("observed", ""))
        old_correct = old_observed == expected
        new_correct = new_observed == expected
        if new_correct and old_correct:
            outcome = "both_correct"
        elif new_correct:
            outcome = "custom_only_correct"
        elif old_correct:
            outcome = "baseline_only_correct"
        else:
            outcome = "both_wrong"
        outcome_counts[outcome] += 1
        if new_observed != old_observed:
            outcome_counts["disagreements"] += 1
        sample_comparisons.append(
            {
                "image": key[0],
                "source_id": key[1],
                "field_key": key[2],
                "expected": expected,
                "custom": {
                    "observed": new_observed,
                    "confidence": float(new.get("confidence") or 0.0),
                    "correct": new_correct,
                },
                "baseline": {
                    "observed": old_observed,
                    "confidence": float(old.get("confidence") or 0.0),
                    "correct": old_correct,
                },
                "outcome": outcome,
                "preferred": (
                    "custom" if new_correct and not old_correct
                    else "baseline" if old_correct and not new_correct
                    else "tie"
                ),
            }
        )

    per_field: dict[str, Any] = {}
    fields = sorted(
        set(base_metrics.get("per_field", {}))
        | set(custom_metrics.get("per_field", {}))
    )
    for field in fields:
        old = base_metrics.get("per_field", {}).get(field, {})
        new = custom_metrics.get("per_field", {}).get(field, {})
        old_exact = float(old.get("exact_match_accuracy") or 0.0)
        new_exact = float(new.get("exact_match_accuracy") or 0.0)
        old_cer = float(old.get("character_error_rate") or 0.0)
        new_cer = float(new.get("character_error_rate") or 0.0)
        if new_exact > old_exact or (new_exact == old_exact and new_cer < old_cer):
            winner = "custom"
        elif old_exact > new_exact or (old_exact == new_exact and old_cer < new_cer):
            winner = "baseline"
        else:
            winner = "tie"
        per_field[field] = {
            "samples": int(new.get("samples") or old.get("samples") or 0),
            "custom": {"exact_match_accuracy": new_exact, "character_error_rate": new_cer},
            "baseline": {"exact_match_accuracy": old_exact, "character_error_rate": old_cer},
            "delta": {
                "exact_match_accuracy": new_exact - old_exact,
                "character_error_rate": new_cer - old_cer,
            },
            "winner": winner,
        }

    comparison = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": baseline.get("dataset_id"),
        "dataset": baseline.get("dataset"),
        "split": baseline.get("split"),
        "baseline": {
            "label": _model_label(baseline, "Oud model"),
            "model": baseline.get("model"),
            "metrics": base_metrics,
            "evaluation_created_at": baseline.get("created_at"),
        },
        "custom": {
            "label": _model_label(custom, "Nieuw model"),
            "model": custom.get("model"),
            "metrics": custom_metrics,
            "evaluation_created_at": custom.get("created_at"),
        },
        "delta": {
            "exact_match_accuracy": custom_metrics["exact_match_accuracy"]
            - base_metrics["exact_match_accuracy"],
            "character_error_rate": custom_metrics["character_error_rate"]
            - base_metrics["character_error_rate"],
        },
        "outcomes": outcome_counts,
        "per_field": per_field,
        "sample_comparisons": sample_comparisons,
        "custom_is_better": (
            custom_metrics["exact_match_accuracy"] >= base_metrics["exact_match_accuracy"]
            and custom_metrics["character_error_rate"] <= base_metrics["character_error_rate"]
            and (
                custom_metrics["exact_match_accuracy"] > base_metrics["exact_match_accuracy"]
                or custom_metrics["character_error_rate"] < base_metrics["character_error_rate"]
            )
        ),
        "label_policy": "verbatim_no_normalization",
    }
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison.json").write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = [
        "# Nieuw versus oud OCR-model",
        "",
        f"- Dataset: `{comparison['dataset_id']}`",
        f"- Split: `{comparison['split']}`",
        f"- Nieuw model: `{comparison['custom']['label']}`",
        f"- Oud model: `{comparison['baseline']['label']}`",
        f"- Nieuw exact match: {custom_metrics['exact_match_accuracy']:.4%}",
        f"- Oud exact match: {base_metrics['exact_match_accuracy']:.4%}",
        f"- Delta exact match: {comparison['delta']['exact_match_accuracy']:+.4%}",
        f"- Nieuw CER: {custom_metrics['character_error_rate']:.4%}",
        f"- Oud CER: {base_metrics['character_error_rate']:.4%}",
        f"- Delta CER: {comparison['delta']['character_error_rate']:+.4%}",
        f"- Alleen nieuw correct: {outcome_counts['custom_only_correct']}",
        f"- Alleen oud correct: {outcome_counts['baseline_only_correct']}",
        f"- Nieuw model strikt beter: {comparison['custom_is_better']}",
        "",
        "No output normalization or value correction was used.",
    ]
    (output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return comparison
