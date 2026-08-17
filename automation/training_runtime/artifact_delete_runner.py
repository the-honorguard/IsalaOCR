#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
KINDS = {"dataset", "model", "evaluation", "run"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def safe_tree(path: Path, parent: Path) -> Path:
    target = path.resolve()
    allowed = parent.resolve()
    try:
        target.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError(f"Unsafe artifact path outside workspace: {target}") from exc
    return target


class ArtifactDeleteRunner:
    def __init__(self, workspace: Path):
        self.root = workspace.resolve()
        self.db_path = self.root / "samples.sqlite3"
        if not self.db_path.is_file():
            raise RuntimeError(f"Projectdatabase ontbreekt: {self.db_path}")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def selection_path(self) -> Path:
        return self.root / "localization_artifact_selection.json"

    def selection(self) -> dict[str, Any]:
        value = read_json(self.selection_path(), {})
        return value if isinstance(value, dict) else {}

    def update_selection(self, **updates: str) -> None:
        current = self.selection()
        for key, value in updates.items():
            current[key] = str(value or "")
        current["updated_at"] = utcnow()
        write_json_atomic(self.selection_path(), current)

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def row(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as db:
            value = db.execute(sql, params).fetchone()
            return dict(value) if value is not None else None

    def current_dataset_id(self) -> str:
        pointer = self.root / "localization_datasets" / "latest.txt"
        try:
            return pointer.read_text(encoding="utf-8-sig").strip() if pointer.is_file() else ""
        except OSError:
            return ""

    def set_current_dataset(self, dataset_id: str) -> None:
        dataset = self.row("SELECT * FROM localization_datasets WHERE dataset_id=?", (dataset_id,))
        if dataset is None:
            raise RuntimeError("De vervangende werkdataset bestaat niet meer.")
        dataset_root = safe_tree(
            self.root / str(dataset.get("path") or f"localization_datasets/{dataset_id}"),
            self.root / "localization_datasets",
        )
        manifest = read_json(dataset_root / "manifest.json", {})
        if not isinstance(manifest, dict):
            raise RuntimeError("Manifest van de vervangende werkdataset ontbreekt of is ongeldig.")
        source_splits = manifest.get("source_splits") if isinstance(manifest.get("source_splits"), dict) else {}
        eligible: set[str] = set()
        try:
            eligible = {
                str(row["source_id"])
                for row in self.rows("SELECT source_id FROM detection_sources WHERE review_completed=1")
            }
        except sqlite3.Error:
            eligible = set()
        split_compatible = bool(source_splits) and set(map(str, source_splits.keys())) == eligible
        split_config = self.root / "localization_split_config.json"
        pending = self.root / "localization_split_pending.flag"
        if split_compatible:
            targets = {
                name: sum(1 for split in source_splits.values() if str(split) == name)
                for name in ("train", "val", "test")
            }
            write_json_atomic(split_config, {
                "schema_version": 1,
                "mode": "counts",
                "targets": targets,
                "overrides": {str(k): str(v) for k, v in source_splits.items()},
                "updated_at": utcnow(),
            })
            pending.unlink(missing_ok=True)
        else:
            pending.write_text(utcnow() + "\n", encoding="utf-8")
        pointer_root = self.root / "localization_datasets"
        pointer_root.mkdir(parents=True, exist_ok=True)
        temp = pointer_root / "latest.txt.tmp"
        temp.write_text(dataset_id, encoding="ascii")
        temp.replace(pointer_root / "latest.txt")
        self.update_selection(evaluation_dataset_id=dataset_id)

    def remove_evaluation(self, evaluation_id: str) -> None:
        row = self.row("SELECT * FROM localization_evaluations WHERE evaluation_id=?", (evaluation_id,))
        if row is None:
            raise RuntimeError("Onbekende localization-evaluatie")
        path = safe_tree(self.root / "localization_evaluations" / evaluation_id, self.root / "localization_evaluations")
        if path.is_dir():
            shutil.rmtree(path)
        with self.connect() as db:
            db.execute("DELETE FROM localization_evaluations WHERE evaluation_id=?", (evaluation_id,))
            db.commit()
        comparison_path = self.root / "localization_evaluations" / "latest_comparison.json"
        comparison = read_json(comparison_path, {})
        if isinstance(comparison, dict) and evaluation_id in {
            str(comparison.get("baseline_evaluation_id") or ""),
            str(comparison.get("trained_evaluation_id") or ""),
        }:
            comparison_path.unlink(missing_ok=True)
        selection = self.selection()
        updates: dict[str, str] = {}
        if str(selection.get("baseline_evaluation_id") or "") == evaluation_id:
            updates["baseline_evaluation_id"] = ""
        if str(selection.get("trained_evaluation_id") or "") == evaluation_id:
            updates["trained_evaluation_id"] = ""
        if updates:
            self.update_selection(**updates)

    def remove_model(self, model_id: str, *, cascade: bool) -> None:
        model = self.row("SELECT * FROM localization_models WHERE model_id=?", (model_id,))
        if model is None:
            raise RuntimeError("Onbekend field-detector-model")
        if int(model.get("active") or 0):
            raise RuntimeError("Het actieve field-detector-model kan niet worden verwijderd. Activeer eerst een ander model.")
        dependencies = self.rows("SELECT * FROM localization_evaluations WHERE model_id=?", (model_id,))
        if dependencies and not cascade:
            raise RuntimeError(f"Model wordt gebruikt door {len(dependencies)} evaluatie(s); bevestig cascade verwijderen.")
        for item in dependencies:
            self.remove_evaluation(str(item.get("evaluation_id") or ""))
        run_dir: Path | None = None
        raw_path = str(model.get("path") or "")
        if raw_path:
            path = Path(raw_path)
            if not path.is_absolute():
                path = self.root / path
            try:
                relative = path.resolve().relative_to(self.root)
                if len(relative.parts) >= 2 and relative.parts[0] == "localization_runs":
                    run_dir = safe_tree(self.root / relative.parts[0] / relative.parts[1], self.root / "localization_runs")
            except (OSError, ValueError):
                run_dir = None
        with self.connect() as db:
            db.execute("DELETE FROM localization_models WHERE model_id=?", (model_id,))
            db.commit()
        if run_dir is not None and run_dir.is_dir():
            shutil.rmtree(run_dir)
        selection = self.selection()
        if str(selection.get("evaluation_model_id") or "") == model_id:
            self.update_selection(evaluation_model_id="", trained_evaluation_id="")

    def remove_dataset(self, dataset_id: str, *, cascade: bool, replacement_dataset_id: str) -> None:
        dataset = self.row("SELECT * FROM localization_datasets WHERE dataset_id=?", (dataset_id,))
        if dataset is None:
            raise RuntimeError("Onbekende localization-dataset")
        models = self.rows("SELECT * FROM localization_models WHERE dataset_id=?", (dataset_id,))
        active = [item for item in models if int(item.get("active") or 0)]
        if active:
            ids = ", ".join(str(item.get("model_id") or "") for item in active)
            raise RuntimeError(f"Deze dataset hoort bij het actieve field-detector-model ({ids}); activeer eerst een ander model.")
        evaluations = self.rows("SELECT * FROM localization_evaluations WHERE dataset_id=?", (dataset_id,))
        dependency_count = len(models) + len(evaluations)
        if dependency_count and not cascade:
            raise RuntimeError(f"Dataset heeft {dependency_count} afhankelijke model/evaluatie-artifact(s); bevestig cascade verwijderen.")
        is_current = self.current_dataset_id() == dataset_id
        if is_current:
            alternatives = [
                str(item.get("dataset_id") or "")
                for item in self.rows("SELECT dataset_id FROM localization_datasets ORDER BY created_at DESC")
                if str(item.get("dataset_id") or "") != dataset_id
            ]
            if not alternatives:
                raise RuntimeError("Dit is de enige werkdataset. Bouw of bewaar eerst een andere dataset.")
            replacement = str(replacement_dataset_id or "").strip()
            if replacement not in alternatives:
                raise RuntimeError("Kies een geldige vervangende werkdataset voordat deze dataset wordt verwijderd.")
            print(f"[1/4] Werkdataset omschakelen naar {replacement}", flush=True)
            self.set_current_dataset(replacement)
        if cascade:
            print(f"[2/4] Afhankelijke artifacts verwijderen ({dependency_count})", flush=True)
            for item in list(models):
                model_id = str(item.get("model_id") or "")
                if self.row("SELECT model_id FROM localization_models WHERE model_id=?", (model_id,)) is not None:
                    self.remove_model(model_id, cascade=True)
            for item in list(evaluations):
                evaluation_id = str(item.get("evaluation_id") or "")
                if self.row("SELECT evaluation_id FROM localization_evaluations WHERE evaluation_id=?", (evaluation_id,)) is not None:
                    self.remove_evaluation(evaluation_id)
        print("[3/4] Datasetbestanden verwijderen", flush=True)
        path = safe_tree(
            self.root / str(dataset.get("path") or f"localization_datasets/{dataset_id}"),
            self.root / "localization_datasets",
        )
        if path.is_dir():
            shutil.rmtree(path)
        with self.connect() as db:
            db.execute("DELETE FROM localization_datasets WHERE dataset_id=?", (dataset_id,))
            db.commit()
        selection = self.selection()
        if str(selection.get("evaluation_dataset_id") or "") == dataset_id:
            self.update_selection(evaluation_dataset_id=self.current_dataset_id())
        print("[4/4] Datasetregister bijgewerkt", flush=True)

    def remove_run(self, run_id: str, *, cascade: bool) -> None:
        path = safe_tree(self.root / "localization_runs" / run_id, self.root / "localization_runs")
        if not path.is_dir():
            raise RuntimeError("Onbekende localization-run")
        registration = read_json(path / "isala_model_registration.json", {})
        model_id = str(registration.get("model_id") or "") if isinstance(registration, dict) else ""
        if model_id and self.row("SELECT model_id FROM localization_models WHERE model_id=?", (model_id,)) is not None:
            self.remove_model(model_id, cascade=cascade)
            return
        shutil.rmtree(path)

    def delete(self, kind: str, artifact_id: str, *, cascade: bool, replacement_dataset_id: str) -> None:
        kind = str(kind or "").strip().lower()
        artifact_id = str(artifact_id or "").strip()
        if kind not in KINDS:
            raise RuntimeError("Onbekend artifacttype")
        if not SAFE_ID.fullmatch(artifact_id):
            raise RuntimeError("Ongeldig artifact-ID")
        if replacement_dataset_id and not SAFE_ID.fullmatch(replacement_dataset_id):
            raise RuntimeError("Ongeldig vervangend dataset-ID")
        if kind == "evaluation":
            self.remove_evaluation(artifact_id)
        elif kind == "model":
            self.remove_model(artifact_id, cascade=cascade)
        elif kind == "dataset":
            self.remove_dataset(artifact_id, cascade=cascade, replacement_dataset_id=replacement_dataset_id)
        else:
            self.remove_run(artifact_id, cascade=cascade)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-file", required=True)
    parser.add_argument("--workspace-base", default="/training/workspace")
    args = parser.parse_args()
    job_file = Path(args.job_file)
    payload = read_json(job_file, {})
    if not isinstance(payload, dict) or str(payload.get("job_type") or "") != "artifact_delete":
        raise RuntimeError("Ongeldige artifact-delete job")
    project_id = str(payload.get("project_id") or "").strip()
    if not SAFE_ID.fullmatch(project_id):
        raise RuntimeError("Ongeldig project-ID in delete job")
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    kind = str(options.get("kind") or "")
    artifact_id = str(options.get("id") or "")
    cascade = bool(options.get("cascade"))
    replacement = str(options.get("replacement_dataset_id") or "")
    print(f"Artifact verwijderen: {kind} {artifact_id}", flush=True)
    runner = ArtifactDeleteRunner(Path(args.workspace_base) / "projects" / project_id)
    runner.delete(kind, artifact_id, cascade=cascade, replacement_dataset_id=replacement)
    print(json.dumps({"ok": True, "kind": kind, "id": artifact_id, "deleted_at": utcnow()}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
