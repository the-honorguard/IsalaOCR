"""``TrainingDatabase`` localization dataset/evaluation/model methods.

Split out of ``db.py`` (see ``documentation/architecture/db-webui-split-plan.md``)
as a mixin, following the same pattern as ``db_samples.py``.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db_constants import utc_now


class LocalizationMixin:
    def save_localization_dataset(self, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO localization_datasets(
                    dataset_id,path,image_count,annotation_count,negative_image_count,split_json,manifest_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    str(payload["dataset_id"]), str(payload["path"]), int(payload.get("image_count") or 0),
                    int(payload.get("annotation_count") or 0), int(payload.get("negative_image_count") or 0),
                    json.dumps(payload.get("splits") or {}, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False), str(payload.get("created_at") or utc_now()),
                ),
            )

    def list_localization_datasets(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM localization_datasets ORDER BY created_at DESC").fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            for source,target in (("split_json","splits"),("manifest_json","manifest")):
                try: item[target]=json.loads(item.pop(source) or "{}")
                except (TypeError,ValueError): item[target]={}
            manifest = item.get("manifest") if isinstance(item.get("manifest"), dict) else {}
            item["ignored_annotation_count"] = int(manifest.get("ignored_annotation_count") or 0)
            item["coco_annotation_count"] = int(manifest.get("coco_annotation_count") or item.get("annotation_count") or 0)
            result.append(item)
        return result

    def save_localization_evaluation(self, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO localization_evaluations(
                    evaluation_id,model_id,dataset_id,kind,split,metrics_json,predictions_path,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    str(payload["evaluation_id"]), str(payload.get("model_id") or ""),
                    str(payload.get("dataset_id") or ""), str(payload.get("kind") or "baseline"),
                    str(payload.get("split") or "test"), json.dumps(payload.get("metrics") or {}, ensure_ascii=False),
                    str(payload.get("predictions_path") or ""), str(payload.get("created_at") or utc_now()),
                ),
            )

    def list_localization_evaluations(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            if kind:
                rows=db.execute("SELECT * FROM localization_evaluations WHERE kind=? ORDER BY created_at DESC",(kind,)).fetchall()
            else:
                rows=db.execute("SELECT * FROM localization_evaluations ORDER BY created_at DESC").fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            try: item["metrics"]=json.loads(item.pop("metrics_json") or "{}")
            except (TypeError,ValueError): item["metrics"]={}
            result.append(item)
        return result

    def register_localization_model(self, payload: dict[str, Any], *, activate: bool = False) -> None:
        now=utc_now()
        with self.connect() as db:
            if activate:
                db.execute("UPDATE localization_models SET active=0")
            db.execute(
                """
                INSERT INTO localization_models(
                    model_id,model_name,path,status,device,dataset_id,metrics_json,active,registered_at,activated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(model_id) DO UPDATE SET
                    model_name=excluded.model_name,path=excluded.path,status=excluded.status,
                    device=excluded.device,dataset_id=excluded.dataset_id,metrics_json=excluded.metrics_json,
                    active=excluded.active,activated_at=excluded.activated_at
                """,
                (
                    str(payload["model_id"]), str(payload.get("model_name") or "PicoDet-S"),
                    str(payload.get("path") or ""), str(payload.get("status") or "registered"),
                    str(payload.get("device") or ""), str(payload.get("dataset_id") or ""),
                    json.dumps(payload.get("metrics") or {}, ensure_ascii=False), 1 if activate else 0,
                    str(payload.get("registered_at") or now), now if activate else payload.get("activated_at"),
                ),
            )
            if activate:
                db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('active_localization_model_id',?)", (str(payload["model_id"]),))

    def active_localization_model(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row=db.execute("SELECT * FROM localization_models WHERE active=1 ORDER BY activated_at DESC LIMIT 1").fetchone()
        if row is None: return None
        item=dict(row)
        try: item["metrics"]=json.loads(item.pop("metrics_json") or "{}")
        except (TypeError,ValueError): item["metrics"]={}
        return item

    def list_localization_models(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows=db.execute("SELECT * FROM localization_models ORDER BY active DESC,registered_at DESC").fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            try: item["metrics"]=json.loads(item.pop("metrics_json") or "{}")
            except (TypeError,ValueError): item["metrics"]={}
            result.append(item)
        return result

    def get_localization_model(self, model_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row=db.execute("SELECT * FROM localization_models WHERE model_id=?", (str(model_id),)).fetchone()
        if row is None:
            return None
        item=dict(row)
        try: item["metrics"]=json.loads(item.pop("metrics_json") or "{}")
        except (TypeError,ValueError): item["metrics"]={}
        return item

    def get_localization_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row=db.execute("SELECT * FROM localization_evaluations WHERE evaluation_id=?", (str(evaluation_id),)).fetchone()
        if row is None:
            return None
        item=dict(row)
        try: item["metrics"]=json.loads(item.pop("metrics_json") or "{}")
        except (TypeError,ValueError): item["metrics"]={}
        return item

    def delete_localization_dataset_record(self, dataset_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM localization_datasets WHERE dataset_id=?", (str(dataset_id),))

    def delete_localization_evaluation(self, evaluation_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM localization_evaluations WHERE evaluation_id=?", (str(evaluation_id),))

    def delete_localization_model(self, model_id: str) -> None:
        with self.connect() as db:
            row=db.execute("SELECT active FROM localization_models WHERE model_id=?", (str(model_id),)).fetchone()
            if row is not None and int(row["active"] or 0):
                raise ValueError("Active localization model cannot be deleted; activate another model first")
            db.execute("DELETE FROM localization_models WHERE model_id=?", (str(model_id),))
            current=db.execute("SELECT value FROM metadata WHERE key='active_localization_model_id'").fetchone()
            if current is not None and str(current["value"] or "") == str(model_id):
                db.execute("DELETE FROM metadata WHERE key='active_localization_model_id'")

    def rewrite_localization_paths(self, old_prefix: str, new_prefix: str) -> None:
        """Rewrite a stored path prefix in localization_models/-evaluations.

        Used by ``projects.duplicate()``/``rename()`` to update the paths a
        duplicated or renamed project's own localization models/evaluations
        point at. Previously this table/column knowledge was duplicated in
        ``projects.py`` via a bare ``sqlite3.connect()`` on the project's
        database file, with a silent ``except sqlite3.OperationalError: pass``
        per table -- meaning a schema change here could silently break that
        rewrite with no test or error to catch it. Centralizing it here means
        a schema change is felt in one place.
        """
        with self.connect() as db:
            for table, column in (("localization_models", "path"), ("localization_evaluations", "predictions_path")):
                try:
                    db.execute(
                        f"UPDATE {table} SET {column}=REPLACE({column}, ?, ?) WHERE {column} LIKE ?",
                        (old_prefix, new_prefix, old_prefix + "%"),
                    )
                except sqlite3.OperationalError:
                    pass
