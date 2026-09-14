"""``TrainingDatabase`` generic-detection (blocks/relations) storage methods.

Split out of ``db.py`` (see ``documentation/architecture/db-webui-split-plan.md``)
as a mixin, following the same pattern as ``db_samples.py``. Some methods here
call ``self._relation_snapshot_in_connection(...)`` / use ``relation_signature``,
which belong to the relation-feedback group (``db_relation_feedback.py``) - that
still works because both mixins combine onto the same ``TrainingDatabase``
instance via ``self``.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db_constants import utc_now
from .relation_feedback import relation_signature


class GenericDetectionMixin:
    @staticmethod
    def _invalidate_mapped_samples_in_connection(
        db: sqlite3.Connection,
        source_id: str,
        field_keys: list[str] | tuple[str, ...] | set[str],
        *,
        reason: str,
    ) -> int:
        """Retire ROI/value reviews that were created from a mapping that changed.

        A mapped crop must never remain eligible for recognition or dataset export
        after its semantic mapping or source geometry changes. The old crop is kept
        for diagnostics, but the sample is marked stale until action 21 materializes
        the current confirmed mapping again.
        """
        keys = sorted({str(key) for key in field_keys if str(key)})
        if not keys:
            return 0
        placeholders = ",".join("?" for _ in keys)
        rows = db.execute(
            f"SELECT * FROM samples WHERE source_id=? AND field_key IN ({placeholders}) AND extraction_method='mapped_generic'",
            [source_id, *keys],
        ).fetchall()
        if not rows:
            return 0
        now = utc_now()
        for existing in rows:
            if existing["status"] != "pending" or existing["exact_label"] is not None:
                db.execute(
                    """
                    INSERT INTO review_history(
                        sample_id, status, exact_label, notes, content_class,
                        crop_sha256, reviewed_at, invalidated_at, reason
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        existing["sample_id"], existing["status"], existing["exact_label"],
                        existing["notes"], existing["content_class"], existing["crop_sha256"],
                        existing["reviewed_at"], now, reason,
                    ),
                )
        db.execute(
            f"""
            UPDATE samples SET
                extraction_method='mapped_generic_stale',
                raw_ocr='', raw_confidence=0, raw_variant='mapping_changed',
                status='pending', exact_label=NULL, notes='', content_class='unknown', reviewed_at=NULL,
                roi_review_status='pending', roi_review_notes=?, roi_reviewed_at=NULL,
                review_generation=review_generation+1, updated_at=?
            WHERE source_id=? AND field_key IN ({placeholders}) AND extraction_method='mapped_generic'
            """,
            [f"Opnieuw materialiseren vereist: {reason}", now, source_id, *keys],
        )
        return len(rows)

    def invalidate_mapped_samples(
        self, source_id: str, field_keys: list[str] | tuple[str, ...] | set[str], *, reason: str
    ) -> int:
        with self.connect() as db:
            return self._invalidate_mapped_samples_in_connection(
                db, source_id, field_keys, reason=reason
            )

    def replace_generic_detection(
        self,
        source: dict[str, Any],
        blocks: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> None:
        source_id = str(source["source_id"])
        now = utc_now()
        with self.connect() as db:
            # Preserve confirmed mappings only when the exact referenced block IDs
            # still exist. A mapping to deleted geometry is not a valid suggestion:
            # retire its ROI and remove the orphan mapping so fresh suggestions can
            # be computed against the new detection graph.
            confirmed = db.execute(
                "SELECT * FROM field_mappings WHERE source_id=? AND status='confirmed'",
                (source_id,),
            ).fetchall()
            # Suggestions depend on the current detection geometry. Recreate them
            # after every detection run instead of retaining references to stale
            # blocks or relations. Confirmed mappings are handled separately.
            db.execute(
                "DELETE FROM field_mappings WHERE source_id=? AND status<>'confirmed'",
                (source_id,),
            )
            db.execute("DELETE FROM detected_relations WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM detected_blocks WHERE source_id=?", (source_id,))
            db.execute(
                """
                INSERT INTO detection_sources(
                    source_id, image_width, image_height, render_path, detector_version,
                    token_count, block_count, relation_count, detected_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    image_width=excluded.image_width,
                    image_height=excluded.image_height,
                    render_path=excluded.render_path,
                    detector_version=excluded.detector_version,
                    token_count=excluded.token_count,
                    block_count=excluded.block_count,
                    relation_count=excluded.relation_count,
                    detected_at=excluded.detected_at,
                    updated_at=excluded.updated_at
                """,
                (
                    source_id, int(source["image_width"]), int(source["image_height"]),
                    str(source.get("render_path") or ""), str(source.get("detector_version") or ""),
                    int(source.get("token_count") or 0), len(blocks), len(relations), now, now,
                ),
            )
            for block in blocks:
                db.execute(
                    """
                    INSERT INTO detected_blocks(
                        block_id, source_id, block_type, role, text, normalized_text,
                        confidence, x1, y1, x2, y2, line_index, sequence_index,
                        parent_block_id, context_text, crop_path, table_id, row_index,
                        column_index, row_span, column_span, geometry_source,
                        recognition_text, recognition_confidence, recognition_model,
                        created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        block["block_id"], source_id, block["block_type"], block["role"],
                        block.get("text", ""), block.get("normalized_text", ""),
                        float(block.get("confidence") or 0), int(block["x1"]), int(block["y1"]),
                        int(block["x2"]), int(block["y2"]), int(block.get("line_index") or 0),
                        int(block.get("sequence_index") or 0), str(block.get("parent_block_id") or ""),
                        str(block.get("context_text") or ""), str(block.get("crop_path") or ""),
                        str(block.get("table_id") or ""), int(block.get("row_index", -1)),
                        int(block.get("column_index", -1)), int(block.get("row_span") or 1),
                        int(block.get("column_span") or 1), str(block.get("geometry_source") or "ocr"),
                        str(block.get("recognition_text") or ""),
                        float(block.get("recognition_confidence") or 0),
                        str(block.get("recognition_model") or ""),
                        now, now,
                    ),
                )
            for relation in relations:
                db.execute(
                    """
                    INSERT INTO detected_relations(
                        relation_id, source_id, label_block_id, value_block_id,
                        unit_block_id, relation_type, confidence, rank, context_text,
                        status, table_id, row_index, value_column_index, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,'proposed',?,?,?,?,?)
                    """,
                    (
                        relation["relation_id"], source_id, str(relation.get("label_block_id") or ""),
                        relation["value_block_id"], str(relation.get("unit_block_id") or ""),
                        relation.get("relation_type", "same_line_right"),
                        float(relation.get("confidence") or 0), int(relation.get("rank") or 1),
                        str(relation.get("context_text") or ""), str(relation.get("table_id") or ""),
                        int(relation.get("row_index", -1)), int(relation.get("value_column_index", -1)),
                        now, now,
                    ),
                )
            # Re-apply feedback after a new detection pass. Relation IDs can move
            # when OCR geometry changes, therefore the durable feedback key is a
            # normalized text/value/geometry signature rather than relation_id.
            prior_feedback = {
                str(row["relation_signature"]): str(row["verdict"])
                for row in db.execute(
                    "SELECT relation_signature, verdict FROM mapping_relation_feedback WHERE source_id=? AND active=1",
                    (source_id,),
                ).fetchall()
            }
            for relation in relations:
                relation_id = str(relation["relation_id"])
                snapshot = self._relation_snapshot_in_connection(db, source_id, relation_id)
                if snapshot is None:
                    continue
                verdict = prior_feedback.get(relation_signature(snapshot))
                if verdict in {"accepted", "rejected"}:
                    db.execute(
                        "UPDATE detected_relations SET status=?, updated_at=? WHERE relation_id=?",
                        (verdict, now, relation_id),
                    )

            valid_block_ids = {str(item["block_id"]) for item in blocks}
            valid_relation_ids = {str(item["relation_id"]) for item in relations}
            for mapping in confirmed:
                if (
                    str(mapping["value_block_id"]) not in valid_block_ids
                    or (str(mapping["label_block_id"] or "") and str(mapping["label_block_id"]) not in valid_block_ids)
                    or (str(mapping["relation_id"] or "") and str(mapping["relation_id"]) not in valid_relation_ids)
                ):
                    self._invalidate_mapped_samples_in_connection(
                        db, source_id, [str(mapping["field_key"])], reason="detection_changed"
                    )
                    db.execute(
                        "DELETE FROM field_mappings WHERE mapping_id=?",
                        (mapping["mapping_id"],),
                    )

    def list_detection_sources(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT s.*,
                       SUM(CASE WHEN m.status='confirmed' THEN 1 ELSE 0 END) AS confirmed_mapping_count,
                       SUM(CASE WHEN m.status='suggested' THEN 1 ELSE 0 END) AS suggested_mapping_count
                FROM detection_sources s
                LEFT JOIN field_mappings m ON m.source_id=s.source_id
                GROUP BY s.source_id
                ORDER BY s.detected_at DESC, s.source_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_detection_source(self, source_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM detection_sources WHERE source_id=?", (source_id,)).fetchone()
        return dict(row) if row else None

    def list_detected_blocks(
        self,
        source_id: str,
        *,
        role: str | None = None,
        semantic_only: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["source_id=?"]
        params: list[Any] = [source_id]
        if role and role != "all":
            clauses.append("role=?")
            params.append(role)
        if semantic_only:
            clauses.append("block_type IN ('semantic','table_cell')")
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM detected_blocks WHERE {' AND '.join(clauses)} ORDER BY y1, x1, line_index, sequence_index",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_detected_block(self, block_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM detected_blocks WHERE block_id=?", (block_id,)).fetchone()
        return dict(row) if row else None

    def get_detected_relation(self, relation_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM detected_relations WHERE relation_id=?", (relation_id,)
            ).fetchone()
        return dict(row) if row else None
