"""``TrainingDatabase`` mapping (field <-> relation) methods.

Split out of ``db.py`` (see ``documentation/architecture/db-webui-split-plan.md``)
as a mixin, following the same pattern as ``db_samples.py``. Methods here call
``self._invalidate_mapped_samples_in_connection(...)`` (``db_generic_detection.py``),
``self._record_relation_feedback_in_connection(...)`` (``db_relation_feedback.py``)
and ``self._safe_field_key(...)`` (``db_field_definitions.py``) - that still
works because every mixin combines onto the same ``TrainingDatabase`` instance
via ``self``.

Note: ``_upsert_mapping_in_connection`` is also called directly from
``mapping_fast.py`` (``database._upsert_mapping_in_connection(db, ...)``) to
batch-insert suggestions inside one transaction - unaffected by this move.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any

from .db_constants import VALID_MAPPING_STATUSES, utc_now


class MappingsMixin:
    def mapping_counts(self) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS amount FROM field_mappings GROUP BY status"
            ).fetchall()
            relation_total = int(db.execute("SELECT COUNT(*) FROM detected_relations").fetchone()[0])
            source_total = int(db.execute("SELECT COUNT(*) FROM detection_sources").fetchone()[0])
        result = {status: 0 for status in VALID_MAPPING_STATUSES}
        for row in rows:
            if row["status"] in result:
                result[str(row["status"])] = int(row["amount"])
        result["relations"] = relation_total
        result["sources"] = source_total
        result["total"] = sum(result[status] for status in VALID_MAPPING_STATUSES)
        return result

    @staticmethod
    def _mapping_component_in_source(
        db: sqlite3.Connection, table: str, key_name: str, key_value: str, source_id: str
    ) -> sqlite3.Row | None:
        return db.execute(
            f"SELECT * FROM {table} WHERE {key_name}=? AND source_id=?",
            (key_value, source_id),
        ).fetchone()

    def _upsert_mapping_in_connection(
        self,
        db: sqlite3.Connection,
        *,
        source_id: str,
        field_key: str,
        value_block_id: str,
        label_block_id: str = "",
        unit_block_id: str = "",
        relation_id: str = "",
        status: str = "confirmed",
        mapping_confidence: float = 1.0,
        notes: str = "",
        profile_id: str = "",
    ) -> str:
        """Validate and store one mapping inside an existing transaction."""
        if status not in VALID_MAPPING_STATUSES:
            raise ValueError(f"Unsupported mapping status: {status}")
        field = db.execute(
            "SELECT field_key FROM field_definitions WHERE field_key=?", (field_key,)
        ).fetchone()
        if field is None:
            raise KeyError(field_key)
        value = self._mapping_component_in_source(
            db, "detected_blocks", "block_id", value_block_id, source_id
        )
        if value is None:
            raise ValueError("Value block does not belong to the selected source")
        if label_block_id and self._mapping_component_in_source(
            db, "detected_blocks", "block_id", label_block_id, source_id
        ) is None:
            raise ValueError("Label block does not belong to the selected source")
        if unit_block_id and self._mapping_component_in_source(
            db, "detected_blocks", "block_id", unit_block_id, source_id
        ) is None:
            raise ValueError("Unit block does not belong to the selected source")
        if relation_id:
            relation = self._mapping_component_in_source(
                db, "detected_relations", "relation_id", relation_id, source_id
            )
            if relation is None:
                raise ValueError("Relation does not belong to the selected source")
            if str(relation["status"] or "proposed") == "rejected":
                raise ValueError("Deze relatie is afgekeurd. Herstel de afkeuring voordat je hem opnieuw mapt.")
            if str(relation["value_block_id"]) != str(value_block_id):
                raise ValueError("Relation and selected value block do not match")
            expected_label = str(relation["label_block_id"] or "")
            if label_block_id and expected_label and expected_label != str(label_block_id):
                raise ValueError("Relation and selected label block do not match")

        mapping_id = hashlib.sha256(f"{source_id}|{field_key}".encode("utf-8")).hexdigest()[:32]
        now = utc_now()
        existing = db.execute(
            "SELECT * FROM field_mappings WHERE source_id=? AND field_key=?",
            (source_id, field_key),
        ).fetchone()
        mapping_changed = bool(
            existing
            and (
                str(existing["relation_id"] or "") != str(relation_id or "")
                or str(existing["label_block_id"] or "") != str(label_block_id or "")
                or str(existing["value_block_id"] or "") != str(value_block_id or "")
                or str(existing["unit_block_id"] or "") != str(unit_block_id or "")
            )
        )
        if mapping_changed:
            self._invalidate_mapped_samples_in_connection(
                db, source_id, [field_key], reason="mapping_changed"
            )

        # One observed value must not silently feed multiple semantic fields. This
        # also protects manual block mappings, which do not have a relation_id.
        conflicts = db.execute(
            """
            SELECT * FROM field_mappings
            WHERE source_id=? AND field_key<>?
              AND (value_block_id=? OR (?<>'' AND relation_id=?))
            """,
            (source_id, field_key, value_block_id, relation_id, relation_id),
        ).fetchall()
        for conflict in conflicts:
            self._invalidate_mapped_samples_in_connection(
                db, source_id, [str(conflict["field_key"])], reason="relation_reassigned"
            )
            db.execute("DELETE FROM field_mappings WHERE mapping_id=?", (conflict["mapping_id"],))

        db.execute(
            """
            INSERT INTO field_mappings(
                mapping_id, source_id, relation_id, field_key, label_block_id,
                value_block_id, unit_block_id, status, mapping_confidence,
                notes, profile_id, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id, field_key) DO UPDATE SET
                mapping_id=excluded.mapping_id,
                relation_id=excluded.relation_id,
                label_block_id=excluded.label_block_id,
                value_block_id=excluded.value_block_id,
                unit_block_id=excluded.unit_block_id,
                status=excluded.status,
                mapping_confidence=excluded.mapping_confidence,
                notes=excluded.notes,
                profile_id=excluded.profile_id,
                updated_at=excluded.updated_at
            """,
            (
                mapping_id, source_id, relation_id, field_key, label_block_id,
                value_block_id, unit_block_id, status,
                max(0.0, min(1.0, float(mapping_confidence))), str(notes or ""),
                str(profile_id or ""), now, now,
            ),
        )
        if status == "confirmed" and label_block_id:
            label_row = db.execute(
                "SELECT text FROM detected_blocks WHERE block_id=? AND source_id=?",
                (label_block_id, source_id),
            ).fetchone()
            observed_label = str(label_row["text"] or "").strip() if label_row else ""
            if observed_label:
                field_row = db.execute(
                    "SELECT aliases_json FROM field_definitions WHERE field_key=?",
                    (field_key,),
                ).fetchone()
                try:
                    aliases = json.loads(field_row["aliases_json"] or "[]") if field_row else []
                except (TypeError, ValueError):
                    aliases = []
                if not isinstance(aliases, list):
                    aliases = []
                normalized_observed = re.sub(r"\s+", " ", observed_label.casefold()).strip()
                known = {
                    re.sub(r"\s+", " ", str(alias).casefold()).strip()
                    for alias in aliases
                }
                if normalized_observed and normalized_observed not in known:
                    aliases.append(observed_label)
                    db.execute(
                        "UPDATE field_definitions SET aliases_json=?, updated_at=? WHERE field_key=?",
                        (json.dumps(aliases, ensure_ascii=False), now, field_key),
                    )
        if status == "confirmed" and relation_id:
            self._record_relation_feedback_in_connection(
                db, source_id=source_id, relation_id=relation_id, verdict="accepted"
            )
        return mapping_id

    def upsert_mapping(
        self,
        *,
        source_id: str,
        field_key: str,
        value_block_id: str,
        label_block_id: str = "",
        unit_block_id: str = "",
        relation_id: str = "",
        status: str = "confirmed",
        mapping_confidence: float = 1.0,
        notes: str = "",
        profile_id: str = "",
    ) -> dict[str, Any]:
        with self.connect() as db:
            mapping_id = self._upsert_mapping_in_connection(
                db,
                source_id=source_id,
                field_key=field_key,
                value_block_id=value_block_id,
                label_block_id=label_block_id,
                unit_block_id=unit_block_id,
                relation_id=relation_id,
                status=status,
                mapping_confidence=mapping_confidence,
                notes=notes,
                profile_id=profile_id,
            )
        result = self.get_mapping(mapping_id)
        if result is None:
            raise RuntimeError("Mapping was not stored")
        return result

    def sync_relation_mappings(
        self,
        source_id: str,
        assignments: list[dict[str, str]],
    ) -> dict[str, int]:
        """Atomically synchronize relation mappings submitted by Mappingstudio.

        Every assignment must contain ``relation_id`` and may contain ``field_key``
        and ``notes``. An empty field_key explicitly removes the relation mapping.
        All relations/fields are validated before the first mutation, so a bad row
        can never leave a half-saved Mappingstudio form behind.
        """
        normalized: list[dict[str, str]] = []
        relation_ids: set[str] = set()
        selected_fields: set[str] = set()
        for item in assignments:
            relation_id = str(item.get("relation_id") or "").strip()
            field_key = str(item.get("field_key") or "").strip()
            notes = str(item.get("notes") or "")
            if not relation_id:
                raise ValueError("Mapping assignment is missing relation_id")
            if relation_id in relation_ids:
                raise ValueError(f"Relation occurs more than once in mapping form: {relation_id}")
            relation_ids.add(relation_id)
            if field_key:
                if field_key in selected_fields:
                    raise ValueError(f"Functional field occurs more than once in mapping form: {field_key}")
                selected_fields.add(field_key)
            normalized.append({"relation_id": relation_id, "field_key": field_key, "notes": notes})

        saved = 0
        removed = 0
        with self.connect() as db:
            # Preflight the complete request before changing anything.
            relation_rows: dict[str, sqlite3.Row] = {}
            for item in normalized:
                relation_id = item["relation_id"]
                relation = self._mapping_component_in_source(
                    db, "detected_relations", "relation_id", relation_id, source_id
                )
                if relation is None:
                    raise ValueError(f"Relation does not belong to the selected source: {relation_id}")
                relation_rows[relation_id] = relation
                field_key = item["field_key"]
                if field_key and db.execute(
                    "SELECT 1 FROM field_definitions WHERE field_key=? AND active=1", (field_key,)
                ).fetchone() is None:
                    raise ValueError(f"Unknown or inactive functional field: {field_key}")

            for item in normalized:
                relation_id = item["relation_id"]
                field_key = item["field_key"]
                current_rows = db.execute(
                    "SELECT * FROM field_mappings WHERE source_id=? AND relation_id=?",
                    (source_id, relation_id),
                ).fetchall()
                if not field_key:
                    for current in current_rows:
                        self._invalidate_mapped_samples_in_connection(
                            db, source_id, [str(current["field_key"])], reason="mapping_removed"
                        )
                        db.execute(
                            "DELETE FROM field_mappings WHERE mapping_id=?", (current["mapping_id"],)
                        )
                        removed += 1
                    continue

                relation = relation_rows[relation_id]
                current = next(
                    (row for row in current_rows if str(row["field_key"]) == field_key), None
                )
                if current is not None and str(current["status"]) == "confirmed" and str(current["notes"] or "") == item["notes"]:
                    continue
                self._upsert_mapping_in_connection(
                    db,
                    source_id=source_id,
                    field_key=field_key,
                    relation_id=relation_id,
                    label_block_id=str(relation["label_block_id"] or ""),
                    value_block_id=str(relation["value_block_id"]),
                    unit_block_id=str(relation["unit_block_id"] or ""),
                    status="confirmed",
                    mapping_confidence=float(relation["confidence"] or 0),
                    notes=item["notes"],
                )
                saved += 1
        return {"saved": saved, "removed": removed}

    def get_mapping(self, mapping_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT m.*, f.display_name, f.group_name, f.data_type, f.preferred_unit,
                       f.minimum_value, f.maximum_value,
                       lb.text AS label_text, lb.crop_path AS label_crop_path,
                       vb.text AS value_text, vb.crop_path AS value_crop_path,
                       vb.x1 AS value_x1, vb.y1 AS value_y1, vb.x2 AS value_x2, vb.y2 AS value_y2,
                       vb.confidence AS value_confidence,
                       ub.text AS unit_text, r.relation_type, r.table_id, r.row_index,
                       r.value_column_index, r.context_text AS relation_context, r.confidence AS relation_confidence
                FROM field_mappings m
                JOIN field_definitions f ON f.field_key=m.field_key
                LEFT JOIN detected_blocks lb ON lb.block_id=m.label_block_id
                JOIN detected_blocks vb ON vb.block_id=m.value_block_id
                LEFT JOIN detected_blocks ub ON ub.block_id=m.unit_block_id
                LEFT JOIN detected_relations r ON r.relation_id=m.relation_id
                WHERE m.mapping_id=?
                """,
                (mapping_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_mappings(self, source_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_id:
            clauses.append("m.source_id=?")
            params.append(source_id)
        if status:
            if status not in VALID_MAPPING_STATUSES:
                raise ValueError(f"Unsupported mapping status: {status}")
            clauses.append("m.status=?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT m.*, f.display_name, f.group_name, f.data_type, f.preferred_unit,
                       f.minimum_value, f.maximum_value,
                       lb.text AS label_text, lb.crop_path AS label_crop_path,
                       lb.context_text AS label_context,
                       vb.text AS value_text, vb.crop_path AS value_crop_path,
                       vb.x1 AS value_x1, vb.y1 AS value_y1, vb.x2 AS value_x2, vb.y2 AS value_y2,
                       vb.confidence AS value_confidence,
                       ub.text AS unit_text, r.context_text AS relation_context,
                       r.confidence AS relation_confidence, r.relation_type, r.table_id,
                       r.row_index, r.value_column_index
                FROM field_mappings m
                JOIN field_definitions f ON f.field_key=m.field_key
                LEFT JOIN detected_blocks lb ON lb.block_id=m.label_block_id
                JOIN detected_blocks vb ON vb.block_id=m.value_block_id
                LEFT JOIN detected_blocks ub ON ub.block_id=m.unit_block_id
                LEFT JOIN detected_relations r ON r.relation_id=m.relation_id
                {where}
                ORDER BY m.source_id, f.group_name, f.display_name
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_mapping(self, mapping_id: str) -> None:
        with self.connect() as db:
            existing = db.execute(
                "SELECT source_id, field_key FROM field_mappings WHERE mapping_id=?", (mapping_id,)
            ).fetchone()
            if existing is not None:
                self._invalidate_mapped_samples_in_connection(
                    db, str(existing["source_id"]), [str(existing["field_key"])], reason="mapping_removed"
                )
            db.execute("DELETE FROM field_mappings WHERE mapping_id=?", (mapping_id,))

    def clear_suggested_mappings(self, source_id: str) -> int:
        with self.connect() as db:
            result = db.execute(
                "DELETE FROM field_mappings WHERE source_id=? AND status='suggested'", (source_id,)
            )
            return int(result.rowcount if result.rowcount is not None else 0)

    def clear_all_mappings(self) -> int:
        """Remove the complete generated mapping set before a rebuild.

        Canonical Detection-GT, Recognition-GT and relation feedback live in
        separate stores and are intentionally unaffected. Mapped samples are
        invalidated first so an old confirmed mapping cannot remain eligible
        for export after Mapping Studio is regenerated.
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT source_id, field_key FROM field_mappings"
            ).fetchall()
            for row in rows:
                self._invalidate_mapped_samples_in_connection(
                    db,
                    str(row["source_id"]),
                    [str(row["field_key"])],
                    reason="mapping_dataset_rebuilt",
                )
            result = db.execute("DELETE FROM field_mappings")
            return int(result.rowcount if result.rowcount is not None else 0)

    def save_mapping_profile(
        self,
        *,
        profile_id: str,
        name: str,
        source_id: str,
        description: str = "",
    ) -> dict[str, Any]:
        profile_key = self._safe_field_key(profile_id).replace(".", "-")
        mappings = self.list_mappings(source_id, status="confirmed")
        if not mappings:
            raise ValueError("No confirmed mappings are available for this source")
        rules: list[dict[str, Any]] = []
        for item in mappings:
            # Keep only the semantic table/panel selector. The remaining OCR
            # header text belongs to this example image and must not become a
            # hidden per-source mapping rule for future DICOMs.
            relation_context = str(item.get("relation_context") or item.get("label_context") or "")
            semantic_context = relation_context.split("|", 1)[0].strip()
            rules.append(
                {
                    "field_key": item["field_key"],
                    "label_text": item.get("label_text") or "",
                    "label_normalized": re.sub(r"\s+", " ", str(item.get("label_text") or "").casefold()).strip(),
                    "context_text": semantic_context,
                    "relation_type": "same_line_right",
                    "value_rank": 1,
                    "preferred_unit": item.get("preferred_unit") or "",
                }
            )
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO mapping_profiles(
                    profile_id, name, description, schema_version, rules_json,
                    source_id, active, created_at, updated_at
                ) VALUES(?,?,?,'1.0',?,?,1,?,?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    name=excluded.name, description=excluded.description,
                    rules_json=excluded.rules_json, source_id=excluded.source_id,
                    active=1, updated_at=excluded.updated_at
                """,
                (profile_key, str(name).strip() or profile_key, str(description or ""),
                 json.dumps(rules, ensure_ascii=False, indent=2), source_id, now, now),
            )
        result = self.get_mapping_profile(profile_key)
        if result is None:
            raise RuntimeError("Mapping profile was not stored")
        return result

    def get_mapping_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM mapping_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item["rules"] = json.loads(item.pop("rules_json") or "[]")
        except (TypeError, ValueError):
            item["rules"] = []
        return item

    def list_mapping_profiles(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM mapping_profiles ORDER BY updated_at DESC, name").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["rules"] = json.loads(item.pop("rules_json") or "[]")
            except (TypeError, ValueError):
                item["rules"] = []
            item["rule_count"] = len(item["rules"])
            result.append(item)
        return result

    def update_sample_recognition(
        self,
        sample_id: str,
        raw_ocr: str,
        raw_confidence: float,
        raw_variant: str = "recognition_only_mapped_generic",
    ) -> None:
        now = utc_now()
        with self.connect() as db:
            changed = db.execute(
                """
                UPDATE samples SET raw_ocr=?, raw_confidence=?, raw_variant=?,
                    status=CASE WHEN status='accepted' THEN 'pending' ELSE status END,
                    exact_label=CASE WHEN status='accepted' THEN NULL ELSE exact_label END,
                    reviewed_at=CASE WHEN status='accepted' THEN NULL ELSE reviewed_at END,
                    updated_at=?
                WHERE sample_id=?
                """,
                (str(raw_ocr), max(0.0, min(1.0, float(raw_confidence))), str(raw_variant), now, sample_id),
            ).rowcount
            if not changed:
                raise KeyError(sample_id)
