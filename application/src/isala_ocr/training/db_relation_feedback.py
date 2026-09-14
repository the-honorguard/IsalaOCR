"""``TrainingDatabase`` relation-feedback methods.

Split out of ``db.py`` (see ``documentation/architecture/db-webui-split-plan.md``)
as a mixin, following the same pattern as ``db_samples.py``. Some methods here
call ``self._invalidate_mapped_samples_in_connection(...)`` / ``self.get_detection_source(...)``,
which belong to the generic-detection group (``db_generic_detection.py``) -
that still works because both mixins combine onto the same
``TrainingDatabase`` instance via ``self``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from .db_constants import utc_now
from .relation_feedback import (
    RELATION_FEEDBACK_REASONS, VALID_RELATION_FEEDBACK_VERDICTS,
    relation_signature, relation_snapshot,
)


class RelationFeedbackMixin:
    def _relation_snapshot_in_connection(
        self, db: sqlite3.Connection, source_id: str, relation_id: str
    ) -> dict[str, Any] | None:
        row = db.execute(
            """
            SELECT r.*,
                   s.image_width, s.image_height,
                   lb.text AS label_text, lb.x1 AS label_x1, lb.y1 AS label_y1,
                   lb.x2 AS label_x2, lb.y2 AS label_y2,
                   vb.text AS value_text, vb.x1 AS value_x1, vb.y1 AS value_y1,
                   vb.x2 AS value_x2, vb.y2 AS value_y2
            FROM detected_relations r
            JOIN detection_sources s ON s.source_id=r.source_id
            LEFT JOIN detected_blocks lb ON lb.block_id=r.label_block_id
            JOIN detected_blocks vb ON vb.block_id=r.value_block_id
            WHERE r.source_id=? AND r.relation_id=?
            """,
            (source_id, relation_id),
        ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        source = {
            "source_id": source_id,
            "image_width": int(row["image_width"] or 1),
            "image_height": int(row["image_height"] or 1),
        }
        return relation_snapshot(payload, source)

    def _record_relation_feedback_in_connection(
        self,
        db: sqlite3.Connection,
        *,
        source_id: str,
        relation_id: str,
        verdict: str,
        reason_code: str = "",
        reason_detail: str = "",
    ) -> dict[str, Any]:
        verdict = str(verdict or "").strip().lower()
        reason_code = str(reason_code or "").strip().lower()
        if verdict not in VALID_RELATION_FEEDBACK_VERDICTS:
            raise ValueError(f"Unsupported relation feedback verdict: {verdict}")
        if verdict == "rejected" and reason_code not in RELATION_FEEDBACK_REASONS:
            raise ValueError("Choose a valid rejection reason")
        if verdict == "accepted":
            reason_code = ""
            reason_detail = ""

        snapshot = self._relation_snapshot_in_connection(db, source_id, relation_id)
        if snapshot is None:
            raise ValueError("Relation does not belong to the selected source")
        signature = relation_signature(snapshot)
        feedback_id = hashlib.sha256(f"{source_id}|{signature}".encode("utf-8")).hexdigest()[:32]
        now = utc_now()
        db.execute(
            """
            INSERT INTO mapping_relation_feedback(
                feedback_id, source_id, relation_id, relation_signature, verdict,
                reason_code, reason_detail, snapshot_json, active, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,1,?,?)
            ON CONFLICT(source_id, relation_signature) DO UPDATE SET
                feedback_id=excluded.feedback_id,
                relation_id=excluded.relation_id,
                verdict=excluded.verdict,
                reason_code=excluded.reason_code,
                reason_detail=excluded.reason_detail,
                snapshot_json=excluded.snapshot_json,
                active=1,
                updated_at=excluded.updated_at
            """,
            (
                feedback_id, source_id, relation_id, signature, verdict,
                reason_code, str(reason_detail or "").strip(),
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now, now,
            ),
        )
        db.execute(
            "UPDATE detected_relations SET status=?, updated_at=? WHERE source_id=? AND relation_id=?",
            ("rejected" if verdict == "rejected" else "accepted", now, source_id, relation_id),
        )
        return {
            "feedback_id": feedback_id,
            "source_id": source_id,
            "relation_id": relation_id,
            "relation_signature": signature,
            "verdict": verdict,
            "reason_code": reason_code,
            "reason_detail": str(reason_detail or "").strip(),
            "snapshot": snapshot,
            "active": 1,
        }

    def record_relation_feedback(
        self,
        *,
        source_id: str,
        relation_id: str,
        verdict: str,
        reason_code: str = "",
        reason_detail: str = "",
    ) -> dict[str, Any]:
        with self.connect() as db:
            if str(verdict).strip().lower() == "rejected":
                mappings = db.execute(
                    "SELECT * FROM field_mappings WHERE source_id=? AND relation_id=?",
                    (source_id, relation_id),
                ).fetchall()
                for mapping in mappings:
                    self._invalidate_mapped_samples_in_connection(
                        db, source_id, [str(mapping["field_key"])], reason="relation_rejected"
                    )
                    db.execute("DELETE FROM field_mappings WHERE mapping_id=?", (mapping["mapping_id"],))
            return self._record_relation_feedback_in_connection(
                db,
                source_id=source_id,
                relation_id=relation_id,
                verdict=verdict,
                reason_code=reason_code,
                reason_detail=reason_detail,
            )

    def clear_relation_feedback(self, source_id: str, relation_id: str) -> int:
        with self.connect() as db:
            snapshot = self._relation_snapshot_in_connection(db, source_id, relation_id)
            if snapshot is None:
                raise ValueError("Relation does not belong to the selected source")
            signature = relation_signature(snapshot)
            result = db.execute(
                "DELETE FROM mapping_relation_feedback WHERE source_id=? AND relation_signature=?",
                (source_id, signature),
            )
            db.execute(
                "UPDATE detected_relations SET status='proposed', updated_at=? WHERE source_id=? AND relation_id=?",
                (utc_now(), source_id, relation_id),
            )
            return int(result.rowcount if result.rowcount is not None else 0)

    def list_relation_feedback(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE active=1" if active_only else ""
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM mapping_relation_feedback {where} ORDER BY updated_at DESC"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["snapshot"] = json.loads(str(item.pop("snapshot_json") or "{}"))
            except json.JSONDecodeError:
                item["snapshot"] = {}
            result.append(item)
        return result

    def relation_feedback_stats(self) -> dict[str, Any]:
        with self.connect() as db:
            verdict_rows = db.execute(
                "SELECT verdict, COUNT(*) AS amount FROM mapping_relation_feedback WHERE active=1 GROUP BY verdict"
            ).fetchall()
            reason_rows = db.execute(
                """
                SELECT reason_code, COUNT(*) AS amount
                FROM mapping_relation_feedback
                WHERE active=1 AND verdict='rejected'
                GROUP BY reason_code ORDER BY amount DESC, reason_code
                """
            ).fetchall()
        stats: dict[str, Any] = {"accepted": 0, "rejected": 0, "total": 0, "reasons": {}}
        for row in verdict_rows:
            verdict = str(row["verdict"])
            if verdict in {"accepted", "rejected"}:
                stats[verdict] = int(row["amount"])
        stats["total"] = int(stats["accepted"]) + int(stats["rejected"])
        stats["reasons"] = {str(row["reason_code"]): int(row["amount"]) for row in reason_rows}
        return stats

    def feedback_for_relations(self, source_id: str, relations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        examples = [item for item in self.list_relation_feedback() if str(item.get("source_id") or "") == source_id]
        if not examples:
            return {}
        source = self.get_detection_source(source_id) or {"source_id": source_id}
        by_signature = {str(item.get("relation_signature") or ""): item for item in examples}
        result: dict[str, dict[str, Any]] = {}
        for relation in relations:
            snapshot = relation_snapshot(relation, source)
            item = by_signature.get(relation_signature(snapshot))
            if item is not None:
                result[str(relation["relation_id"])] = item
        return result

    def list_detected_relations(self, source_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT r.*,
                       lb.text AS label_text, lb.normalized_text AS label_normalized,
                       lb.crop_path AS label_crop_path, lb.x1 AS label_x1, lb.y1 AS label_y1,
                       lb.x2 AS label_x2, lb.y2 AS label_y2,
                       COALESCE(NULLIF(vb.recognition_text,''), vb.text) AS value_text,
                       vb.text AS value_locator_text,
                       vb.recognition_text AS value_recognition_text,
                       vb.recognition_confidence AS value_recognition_confidence,
                       vb.recognition_model AS value_recognition_model,
                       vb.normalized_text AS value_normalized,
                       vb.crop_path AS value_crop_path, vb.confidence AS value_confidence,
                       vb.x1 AS value_x1, vb.y1 AS value_y1, vb.x2 AS value_x2, vb.y2 AS value_y2,
                       ub.text AS unit_text, ub.crop_path AS unit_crop_path,
                       fm.mapping_id, fm.field_key AS mapped_field_key,
                       fm.status AS mapping_status, fm.mapping_confidence, fm.notes AS mapping_notes
                FROM detected_relations r
                LEFT JOIN detected_blocks lb ON lb.block_id=r.label_block_id
                JOIN detected_blocks vb ON vb.block_id=r.value_block_id
                LEFT JOIN detected_blocks ub ON ub.block_id=r.unit_block_id
                LEFT JOIN field_mappings fm ON fm.source_id=r.source_id AND fm.relation_id=r.relation_id
                WHERE r.source_id=?
                ORDER BY CASE WHEN r.relation_type='table_cell' THEN 0 ELSE 1 END,
                         COALESCE(NULLIF(r.table_id,''), r.source_id), r.row_index,
                         vb.y1, vb.x1, r.rank, r.confidence DESC
                """,
                (source_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_relation_contexts(
        self, source_id: str, contexts_by_relation: dict[str, str]
    ) -> int:
        """Persist refreshed table/panel context without rerunning detection."""
        if not contexts_by_relation:
            return 0
        updated = 0
        with self.connect() as db:
            for relation_id, context_text in contexts_by_relation.items():
                result = db.execute(
                    """UPDATE detected_relations
                       SET context_text=?, updated_at=?
                       WHERE source_id=? AND relation_id=?""",
                    (str(context_text or ""), utc_now(), source_id, relation_id),
                )
                updated += int(result.rowcount or 0)
        return updated
