"""``TrainingDatabase`` sample/ROI/header-review methods.

Split out of ``db.py`` (see ``documentation/architecture/db-webui-split-plan.md``)
as a mixin: ``TrainingDatabase`` inherits from ``SamplesMixin`` so its public
API (``TrainingDatabase(path).upsert_sample(...)`` etc.) is unchanged. Methods
here still operate on ``self`` (the same ``TrainingDatabase`` instance) and
call ``self.connect()``, which is defined on the core class in ``db.py``.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db_constants import (
    MISSING_MARKERS,
    VALID_CONTENT_CLASSES,
    VALID_HEADER_REVIEW_STATUSES,
    VALID_OCR_CONTENT_FILTERS,
    VALID_STATUSES,
    utc_now,
    validate_exact_label,
)


class SamplesMixin:
    @staticmethod
    def _invalidates_review(existing: sqlite3.Row, values: dict[str, Any]) -> tuple[bool, str]:
        old_hash = str(existing["crop_sha256"] or "")
        new_hash = str(values.get("crop_sha256") or "")
        if old_hash and new_hash and old_hash != new_hash:
            return True, "crop_pixels_changed"
        old_method = str(existing["extraction_method"] or "fixed_roi")
        new_method = str(values.get("extraction_method") or "fixed_roi")
        if old_method != new_method and existing["status"] != "pending":
            return True, f"extraction_method_changed:{old_method}->{new_method}"
        return False, ""

    def upsert_sample(self, sample: dict[str, Any]) -> bool:
        now = utc_now()
        values = {
            "extraction_method": "fixed_roi",
            "locator_confidence": 0.0,
            "locator_label_text": "",
            "locator_version": "",
            "locator_label_x1": -1,
            "locator_label_y1": -1,
            "locator_label_x2": -1,
            "locator_label_y2": -1,
            "header_crop_path": "",
            "header_crop_sha256": "",
            "crop_sha256": "",
            **sample,
            "created_at": sample.get("created_at", now),
            "updated_at": now,
        }
        values.setdefault("header_target_field_key", str(values.get("field_key") or ""))
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM samples WHERE sample_id=?", (values["sample_id"],)
            ).fetchone()
            if existing:
                invalidate, reason = self._invalidates_review(existing, values)
                invalidate_header_review = (
                    str(existing["locator_label_text"] or "")
                    != str(values.get("locator_label_text") or "")
                )
                if invalidate and (
                    existing["status"] != "pending" or existing["exact_label"] is not None
                ):
                    db.execute(
                        """
                        INSERT INTO review_history(
                            sample_id, status, exact_label, notes, content_class,
                            crop_sha256, reviewed_at, invalidated_at, reason
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            existing["sample_id"],
                            existing["status"],
                            existing["exact_label"],
                            existing["notes"],
                            existing["content_class"],
                            existing["crop_sha256"],
                            existing["reviewed_at"],
                            now,
                            reason,
                        ),
                    )
                db.execute(
                    """
                    UPDATE samples SET
                        crop_path=:crop_path,
                        raw_ocr=:raw_ocr,
                        raw_confidence=:raw_confidence,
                        raw_variant=:raw_variant,
                        image_width=:image_width,
                        image_height=:image_height,
                        roi_x1=:roi_x1, roi_y1=:roi_y1, roi_x2=:roi_x2, roi_y2=:roi_y2,
                        extraction_method=:extraction_method,
                        locator_confidence=:locator_confidence,
                        locator_label_text=:locator_label_text,
                        locator_version=:locator_version,
                        locator_label_x1=:locator_label_x1,
                        locator_label_y1=:locator_label_y1,
                        locator_label_x2=:locator_label_x2,
                        locator_label_y2=:locator_label_y2,
                        header_crop_path=:header_crop_path,
                        header_crop_sha256=:header_crop_sha256,
                        crop_sha256=:crop_sha256,
                        status=CASE WHEN :invalidate_review THEN 'pending' ELSE status END,
                        exact_label=CASE WHEN :invalidate_review THEN NULL ELSE exact_label END,
                        content_class=CASE WHEN :invalidate_review THEN 'unknown' ELSE content_class END,
                        notes=CASE WHEN :invalidate_review THEN '' ELSE notes END,
                        reviewed_at=CASE WHEN :invalidate_review THEN NULL ELSE reviewed_at END,
                        roi_review_status=CASE WHEN :invalidate_review THEN 'pending' ELSE roi_review_status END,
                        roi_review_notes=CASE WHEN :invalidate_review THEN '' ELSE roi_review_notes END,
                        roi_reviewed_at=CASE WHEN :invalidate_review THEN NULL ELSE roi_reviewed_at END,
                        review_generation=review_generation + CASE WHEN :invalidate_review THEN 1 ELSE 0 END,
                        header_review_status=CASE WHEN :invalidate_header_review THEN 'pending' ELSE header_review_status END,
                        header_target_field_key=CASE WHEN :invalidate_header_review THEN field_key ELSE header_target_field_key END,
                        header_exact_label=CASE WHEN :invalidate_header_review THEN '' ELSE header_exact_label END,
                        header_review_notes=CASE WHEN :invalidate_header_review THEN '' ELSE header_review_notes END,
                        header_reviewed_at=CASE WHEN :invalidate_header_review THEN NULL ELSE header_reviewed_at END,
                        updated_at=:updated_at
                    WHERE sample_id=:sample_id
                    """,
                    {**values, "invalidate_review": 1 if invalidate else 0, "invalidate_header_review": 1 if invalidate_header_review else 0},
                )
                return False
            db.execute(
                """
                INSERT INTO samples(
                    sample_id, source_id, profile, field_key, field_label, crop_path,
                    raw_ocr, raw_confidence, raw_variant, status, exact_label, notes,
                    image_width, image_height, roi_x1, roi_y1, roi_x2, roi_y2,
                    extraction_method, locator_confidence, locator_label_text,
                    locator_version, locator_label_x1, locator_label_y1,
                    locator_label_x2, locator_label_y2, header_crop_path,
                    header_crop_sha256, header_review_status, header_target_field_key,
                    header_exact_label, header_review_notes, header_reviewed_at,
                    crop_sha256, content_class, review_generation, created_at, updated_at
                ) VALUES(
                    :sample_id, :source_id, :profile, :field_key, :field_label, :crop_path,
                    :raw_ocr, :raw_confidence, :raw_variant, 'pending', NULL, '',
                    :image_width, :image_height, :roi_x1, :roi_y1, :roi_x2, :roi_y2,
                    :extraction_method, :locator_confidence, :locator_label_text,
                    :locator_version, :locator_label_x1, :locator_label_y1,
                    :locator_label_x2, :locator_label_y2, :header_crop_path,
                    :header_crop_sha256, 'pending', :header_target_field_key,
                    '', '', NULL, :crop_sha256, 'unknown', 0, :created_at, :updated_at
                )
                """,
                values,
            )
            return True

    def get(self, sample_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM samples WHERE sample_id=?", (sample_id,)).fetchone()
        return dict(row) if row else None

    def review(
        self,
        sample_id: str,
        status: str,
        exact_label: str | None,
        notes: str = "",
        content_class: str | None = None,
    ) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Unsupported sample status: {status}")
        if content_class is None:
            content_class = "value" if status == "accepted" else "unknown"
        if content_class not in VALID_CONTENT_CLASSES:
            raise ValueError(f"Unsupported content class: {content_class}")
        if status == "accepted":
            if exact_label is None:
                raise ValueError("Accepted samples require an exact label")
            validate_exact_label(exact_label)
            if content_class not in {"value", "placeholder"}:
                raise ValueError("Accepted samples must be a value or placeholder")
        else:
            exact_label = None
            if status == "no_value":
                content_class = "no_value"
            elif content_class != "no_value":
                content_class = "unknown"
        now = utc_now()
        with self.connect() as db:
            changed = db.execute(
                """
                UPDATE samples SET status=?, exact_label=?, notes=?, content_class=?,
                    reviewed_at=?, updated_at=?
                WHERE sample_id=?
                """,
                (status, exact_label, notes, content_class, now, now, sample_id),
            ).rowcount
            if not changed:
                raise KeyError(sample_id)

    def review_header(
        self,
        sample_id: str,
        status: str,
        target_field_key: str | None = None,
        exact_label: str = "",
        notes: str = "",
    ) -> None:
        if status not in VALID_HEADER_REVIEW_STATUSES:
            raise ValueError(f"Unsupported header review status: {status}")
        exact_label = validate_exact_label(str(exact_label or ""))
        target = str(target_field_key or "").strip()
        now = utc_now()
        reviewed_at = None if status == "pending" else now
        with self.connect() as db:
            existing = db.execute(
                "SELECT field_key, locator_label_text FROM samples WHERE sample_id=?",
                (sample_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(sample_id)
            if status == "accepted":
                if not str(existing["locator_label_text"] or "").strip():
                    raise ValueError("A header without OCR text cannot be used for normalization training")
                if not target:
                    raise ValueError("Accepted header reviews require a target field")
            elif not target:
                target = str(existing["field_key"] or "")
            db.execute(
                """
                UPDATE samples SET header_review_status=?, header_target_field_key=?,
                    header_exact_label=?, header_review_notes=?, header_reviewed_at=?,
                    updated_at=?
                WHERE sample_id=?
                """,
                (status, target, exact_label, notes, reviewed_at, now, sample_id),
            )

    def header_review_counts(self) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT header_review_status, COUNT(*) AS amount FROM samples "
                "WHERE TRIM(locator_label_text)<>'' GROUP BY header_review_status"
            ).fetchall()
        counts = {status: 0 for status in VALID_HEADER_REVIEW_STATUSES}
        for row in rows:
            status = str(row["header_review_status"] or "pending")
            if status in counts:
                counts[status] = int(row["amount"])
        counts["total"] = sum(counts.values())
        return counts

    def list_header_samples(
        self,
        status: str | None = None,
        *,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["TRIM(locator_label_text)<>''"]
        params: list[Any] = []
        if status and status != "all":
            if status not in VALID_HEADER_REVIEW_STATUSES:
                raise ValueError(f"Unsupported header review status: {status}")
            clauses.append("header_review_status=?")
            params.append(status)
        params.extend([limit, offset])
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM samples
                WHERE {' AND '.join(clauses)}
                ORDER BY CASE header_review_status
                           WHEN 'pending' THEN 0 WHEN 'deferred' THEN 1
                           WHEN 'rejected' THEN 2 ELSE 3 END,
                         locator_confidence ASC, source_id, roi_y1, field_key
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def header_training_rows(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT sample_id, field_key, locator_label_text,
                       header_review_status, header_target_field_key, header_exact_label
                FROM samples
                WHERE header_review_status='accepted'
                ORDER BY source_id, field_key
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def review_roi(self, sample_id: str, status: str, notes: str = "") -> None:
        if status not in {"pending", "correct", "incorrect", "deferred"}:
            raise ValueError(f"Unsupported ROI review status: {status}")
        now = utc_now()
        reviewed_at = None if status == "pending" else now
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM samples WHERE sample_id=?", (sample_id,)
            ).fetchone()
            if existing is None:
                raise KeyError(sample_id)

            # A value decision is only valid while the spatial crop is approved.
            # Moving a ROI back to pending or marking it incorrect therefore
            # invalidates the value decision without losing its audit history.
            invalidate_value = status != "correct" and (
                existing["status"] != "pending" or existing["exact_label"] is not None
            )
            if invalidate_value:
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
                        existing["reviewed_at"], now, f"roi_review_changed_to_{status}",
                    ),
                )
            db.execute(
                """
                UPDATE samples SET roi_review_status=?, roi_review_notes=?,
                    roi_reviewed_at=?,
                    status=CASE WHEN ? THEN 'pending' ELSE status END,
                    exact_label=CASE WHEN ? THEN NULL ELSE exact_label END,
                    notes=CASE WHEN ? THEN '' ELSE notes END,
                    content_class=CASE WHEN ? THEN 'unknown' ELSE content_class END,
                    reviewed_at=CASE WHEN ? THEN NULL ELSE reviewed_at END,
                    review_generation=review_generation + CASE WHEN ? THEN 1 ELSE 0 END,
                    updated_at=?
                WHERE sample_id=?
                """,
                (
                    status, notes, reviewed_at,
                    invalidate_value, invalidate_value, invalidate_value, invalidate_value,
                    invalidate_value, invalidate_value, now, sample_id,
                ),
            )

    def list_samples(
        self,
        status: str | None = None,
        field_key: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
        ocr_content: str = "all",
        extraction_method: str | None = None,
        roi_review_status: str | None = None,
        exclude_sample_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if ocr_content not in VALID_OCR_CONTENT_FILTERS:
            raise ValueError(f"Unsupported OCR content filter: {ocr_content}")
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if field_key:
            clauses.append("field_key=?")
            params.append(field_key)
        if min_confidence is not None:
            clauses.append("raw_confidence>=?")
            params.append(float(min_confidence))
        if max_confidence is not None:
            clauses.append("raw_confidence<?")
            params.append(float(max_confidence))
        if extraction_method:
            clauses.append("extraction_method=?")
            params.append(extraction_method)
        if roi_review_status:
            if roi_review_status not in {"pending", "correct", "incorrect", "deferred"}:
                raise ValueError(f"Unsupported ROI review status: {roi_review_status}")
            clauses.append("roi_review_status=?")
            params.append(roi_review_status)
        if exclude_sample_id:
            clauses.append("sample_id<>?")
            params.append(exclude_sample_id)

        trimmed = "TRIM(raw_ocr)"
        marker_placeholders = ",".join("?" for _ in MISSING_MARKERS)
        if ocr_content == "text":
            clauses.append(f"{trimmed}<>'' AND {trimmed} NOT IN ({marker_placeholders})")
            params.extend(MISSING_MARKERS)
        elif ocr_content == "blank":
            clauses.append(f"{trimmed}=''")
        elif ocr_content == "missing":
            clauses.append(f"{trimmed} IN ({marker_placeholders})")
            params.extend(MISSING_MARKERS)
        elif ocr_content == "blank_or_missing":
            clauses.append(f"({trimmed}='' OR {trimmed} IN ({marker_placeholders}))")
            params.extend(MISSING_MARKERS)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        query = f"""
            SELECT * FROM samples {where}
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                     CASE extraction_method WHEN 'fixed_fallback' THEN 0 ELSE 1 END,
                     raw_confidence ASC, field_key, sample_id
            LIMIT ? OFFSET ?
        """
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def accepted(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM samples WHERE status='accepted' AND exact_label IS NOT NULL "
                "AND roi_review_status='correct' ORDER BY source_id, field_key"
            ).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS count FROM samples GROUP BY status"
            ).fetchall()
            total = db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            classes = db.execute(
                "SELECT content_class, COUNT(*) AS count FROM samples GROUP BY content_class"
            ).fetchall()
        result = {status: 0 for status in VALID_STATUSES}
        result.update({row["status"]: int(row["count"]) for row in rows})
        result["total"] = int(total)
        for row in classes:
            result[f"class_{row['content_class']}"] = int(row["count"])
        return result

    def mapped_sample_counts(self) -> dict[str, int]:
        """Aggregate mapped-sample state in SQLite instead of loading all rows."""
        with self.connect() as db:
            row = db.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN raw_variant='awaiting_value_recognition' THEN 1 ELSE 0 END) AS awaiting_recognition,
                    SUM(CASE WHEN raw_variant<>'awaiting_value_recognition' THEN 1 ELSE 0 END) AS recognized,
                    SUM(CASE WHEN roi_review_status='correct' THEN 1 ELSE 0 END) AS roi_correct
                FROM samples
                WHERE extraction_method='mapped_generic'
                """
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "awaiting_recognition": int(row["awaiting_recognition"] or 0),
            "recognized": int(row["recognized"] or 0),
            "roi_correct": int(row["roi_correct"] or 0),
        }

    def source_summary_rows(self) -> list[dict[str, Any]]:
        """Per-source sample aggregates for the source overview page.

        Split out of ``webui.py``'s ``source_rows()`` (CODE_REVIEW_v3.16.0.md,
        sectie Hoog) -- that closure now only adds the ``render_exists`` flag,
        which needs ``workspace_root()`` and stays in webui.py.
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT source_id, MIN(profile) profile, COUNT(*) sample_count,
                       SUM(CASE WHEN extraction_method LIKE 'dynamic_%' THEN 1 ELSE 0 END) dynamic_count,
                       SUM(CASE WHEN extraction_method IN ('fixed_fallback','fixed_roi') THEN 1 ELSE 0 END) fallback_count,
                       AVG(locator_confidence) average_locator_confidence,
                       AVG(raw_confidence) average_confidence,
                       MIN(raw_confidence) minimum_confidence,
                       MAX(updated_at) updated_at
                FROM samples GROUP BY source_id ORDER BY updated_at DESC, source_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def samples_for_source(self, source_id: str) -> list[dict[str, Any]]:
        """All samples for one source, in ROI reading order.

        Split out of ``webui.py``'s ``source_samples()``.
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM samples WHERE source_id=? ORDER BY roi_y1, roi_x1, field_key",
                (source_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def roi_review_status_counts(self) -> dict[str, int]:
        """ROI-review status counts, excluding stale generic-mapping remnants.

        Split out of ``webui.py``'s ``roi_review_counts()``.
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT roi_review_status, COUNT(*) AS amount FROM samples WHERE extraction_method<>'mapped_generic_stale' GROUP BY roi_review_status"
            ).fetchall()
        counts = {"pending": 0, "correct": 0, "incorrect": 0, "deferred": 0}
        for row in rows:
            counts[str(row["roi_review_status"])] = int(row["amount"])
        counts["total"] = sum(counts.values())
        return counts

    def roi_review_status_counts_by_source(self) -> dict[str, dict[str, int]]:
        """Per-source ROI-review status counts, excluding stale generic-mapping remnants.

        Split out of ``routes_roi_review.py``'s ``roi_review_home()``
        (CODE_REVIEW_v3.16.0.md, sectie Hoog).
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT source_id, roi_review_status, COUNT(*) AS amount
                FROM samples
                WHERE extraction_method<>'mapped_generic_stale'
                GROUP BY source_id, roi_review_status
                """
            ).fetchall()
        counts_by_source: dict[str, dict[str, int]] = {}
        for row in rows:
            local = counts_by_source.setdefault(
                str(row["source_id"]),
                {"pending": 0, "correct": 0, "incorrect": 0, "deferred": 0},
            )
            local[str(row["roi_review_status"])] = int(row["amount"])
        return counts_by_source

    def roi_correct_status_counts(self) -> dict[str, int]:
        """Value-review-eligible sample counts by status (ROI already correct).

        Split out of ``labeler.py``'s ``value_counts()`` (CODE_REVIEW_v3.16.0.md,
        sectie Hoog). Unlike ``mapped_value_review_status_counts()``, this has
        no ``extraction_method='mapped_generic'`` filter -- the standalone
        labeler tool counts across every extraction method.
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT status, COUNT(*) AS amount
                FROM samples
                WHERE roi_review_status='correct'
                GROUP BY status
                """
            ).fetchall()
        counts = {
            "pending": 0,
            "accepted": 0,
            "no_value": 0,
            "unreadable": 0,
            "excluded": 0,
        }
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["amount"])
        counts["total"] = sum(counts.values())
        counts["reviewed"] = counts["total"] - counts["pending"]
        return counts

    def mapped_value_review_status_counts(self) -> dict[str, int]:
        """Value-review status counts for the currently mapped application output.

        Split out of ``webui.py``'s ``value_review_counts()``.
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT status, COUNT(*) AS amount
                FROM samples
                WHERE extraction_method='mapped_generic'
                  AND roi_review_status='correct'
                  AND NOT (extraction_method='mapped_generic' AND raw_variant='awaiting_value_recognition')
                GROUP BY status
                """
            ).fetchall()
        counts = {
            "pending": 0, "accepted": 0, "no_value": 0,
            "unreadable": 0, "excluded": 0,
        }
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["amount"])
        counts["total"] = sum(counts.values())
        counts["reviewed"] = counts["total"] - counts["pending"]
        counts["problems"] = counts["unreadable"] + counts["excluded"]
        return counts

    def mapped_value_review_source_rows(self) -> list[dict[str, Any]]:
        """Group only current mapped samples for the value-review step, by source.

        Split out of ``webui.py``'s ``value_source_rows()``.
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT source_id, COUNT(*) sample_count,
                       SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) pending,
                       SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) accepted,
                       SUM(CASE WHEN status='no_value' THEN 1 ELSE 0 END) no_value,
                       SUM(CASE WHEN status IN ('unreadable','excluded') THEN 1 ELSE 0 END) problems,
                       AVG(raw_confidence) average_confidence,
                       MAX(updated_at) updated_at
                FROM samples
                WHERE extraction_method='mapped_generic'
                  AND roi_review_status='correct'
                  AND NOT (extraction_method='mapped_generic' AND raw_variant='awaiting_value_recognition')
                GROUP BY source_id
                ORDER BY updated_at DESC, source_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def mapped_value_review_source_samples(self, source_id: str) -> list[dict[str, Any]]:
        """Mapped, ROI-correct samples for one source, for the value-review step.

        Split out of ``webui.py``'s ``value_source_samples()``.
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM samples
                WHERE source_id=? AND extraction_method='mapped_generic'
                  AND roi_review_status='correct'
                  AND NOT (extraction_method='mapped_generic' AND raw_variant='awaiting_value_recognition')
                ORDER BY roi_y1, roi_x1, field_key
                """,
                (source_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def accepted_exact_labels(self, extraction_method: str) -> list[str]:
        """Exact labels of accepted samples for one extraction method.

        Split out of ``recognition_ground_truth_web.py``'s
        ``_rebuild_format_profile()`` (CODE_REVIEW_v3.16.0.md, sectie Hoog).
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT exact_label FROM samples WHERE extraction_method=? AND status='accepted' AND exact_label IS NOT NULL",
                (extraction_method,),
            ).fetchall()
        return [str(row["exact_label"] or "") for row in rows]

    def has_accepted_exact_label(self, extraction_method: str) -> bool:
        """Whether at least one accepted, labelled sample exists for a method.

        Split out of ``recognition_ground_truth_web.py``'s
        ``format_profile_for_review()``.
        """
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM samples WHERE extraction_method=? AND status='accepted' AND exact_label IS NOT NULL LIMIT 1",
                (extraction_method,),
            ).fetchone()
        return row is not None

    def accepted_exact_label_rows(self, extraction_method: str) -> list[dict[str, Any]]:
        """sample_id/source_id/raw_ocr/exact_label for accepted, labelled samples.

        Split out of ``recognition_ground_truth_web.py``'s
        ``recognition_gt_formats()``.
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT sample_id, source_id, raw_ocr, exact_label
                FROM samples
                WHERE extraction_method=? AND status='accepted' AND exact_label IS NOT NULL
                ORDER BY source_id, sample_id
                """,
                (extraction_method,),
            ).fetchall()
        return [dict(row) for row in rows]

    def accepted_exact_label_samples(self, extraction_method: str) -> list[dict[str, Any]]:
        """Full rows of accepted, labelled samples for one extraction method.

        Split out of ``dataset.py``'s ``build_dataset()`` (CODE_REVIEW_v3.16.0.md,
        sectie Hoog). Unlike ``accepted_exact_label_rows()`` (4 columns, for
        the format-review page), this returns every column -- the recognition
        training-dataset builder needs the full sample row.
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM samples
                WHERE extraction_method=?
                  AND status='accepted'
                  AND exact_label IS NOT NULL
                ORDER BY source_id, sample_id
                """,
                (extraction_method,),
            ).fetchall()
        return [dict(row) for row in rows]

    def samples_source_counts(
        self, extraction_method: str, status: str | None = None, sort: str = "source"
    ) -> list[dict[str, Any]]:
        """Per-source total/pending/accepted/excluded counts for one extraction method.

        Split out of ``recognition_ground_truth_web.py``'s ``source_rows()``.
        ``sort`` picks a fixed ``ORDER BY`` (never interpolated from request
        input directly) matching that function's ``source``/``pending``/
        ``errors`` modes.
        """
        where = "WHERE extraction_method=?"
        params: list[str] = [extraction_method]
        if status:
            where += " AND status=?"
            params.append(status)
        order_by = "source_id"
        if sort == "errors":
            order_by = "pending DESC, excluded DESC, source_id"
        elif sort == "pending":
            order_by = "pending DESC, source_id"
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT source_id,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS accepted,
                       SUM(CASE WHEN status IN ('unreadable','excluded','no_value') THEN 1 ELSE 0 END) AS excluded
                FROM samples
                {where}
                GROUP BY source_id
                ORDER BY {order_by}
                """,
                params,
            ).fetchall()
        return [
            {
                "source_id": str(row["source_id"]),
                "total": int(row["total"] or 0),
                "pending": int(row["pending"] or 0),
                "accepted": int(row["accepted"] or 0),
                "excluded": int(row["excluded"] or 0),
            }
            for row in rows
        ]

    def samples_for_source_and_method(self, source_id: str, extraction_method: str) -> list[dict[str, Any]]:
        """All samples for one source and extraction method, in ROI reading order.

        Split out of ``recognition_ground_truth_web.py``'s ``source_samples()``.
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM samples
                WHERE source_id=? AND extraction_method=?
                ORDER BY roi_y1, roi_x1, sample_id
                """,
                (source_id, extraction_method),
            ).fetchall()
        return [dict(row) for row in rows]

    def samples_status_counts(self, extraction_method: str) -> dict[str, int]:
        """total/pending/accepted/excluded counts for one extraction method.

        Split out of ``recognition_ground_truth.py``'s ``recognition_gt_counts()``
        (CODE_REVIEW_v3.16.0.md, sectie Hoog).
        """
        with self.connect() as db:
            row = db.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS accepted,
                    SUM(CASE WHEN status IN ('unreadable','excluded','no_value') THEN 1 ELSE 0 END) AS excluded
                FROM samples
                WHERE extraction_method=?
                """,
                (extraction_method,),
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "pending": int(row["pending"] or 0),
            "accepted": int(row["accepted"] or 0),
            "excluded": int(row["excluded"] or 0),
        }

    def duplicate_pending_matches(self) -> list[dict[str, Any]]:
        """Pending samples whose crop pixel-matches an already-accepted one.

        Split out of ``routes_value_review.py``'s ``duplicates_apply()``
        (CODE_REVIEW_v3.16.0.md, sectie Hoog). Returns one row per
        (pending sample_id, matching accepted exact_label/content_class),
        exactly as the original self-join did -- the caller still
        deduplicates on ``sample_id`` (a pending sample can pixel-match more
        than one accepted sample).
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT p.sample_id, a.exact_label, a.content_class
                FROM samples p JOIN samples a
                  ON p.crop_sha256=a.crop_sha256 AND p.field_key=a.field_key
                WHERE p.status='pending' AND p.roi_review_status='correct'
                  AND p.crop_sha256<>''
                  AND a.status='accepted' AND a.roi_review_status='correct'
                  AND a.exact_label IS NOT NULL
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_stale_mapped_generic_samples(
        self, keep_sample_ids: set[str], processed_source_ids: set[str] | None
    ) -> list[str]:
        """Demote no-longer-current 'mapped_generic' samples to 'mapped_generic_stale'.

        Split out of ``mapping.py``'s ``materialize_confirmed_mappings()``
        (CODE_REVIEW_v3.16.0.md, sectie Hoog). A new table/raster mapping pass
        is authoritative; older ``mapped_generic`` rows for a source that was
        just (re)processed must move out of the active method so they stop
        showing up in the ROI-review queue. ``processed_source_ids=None``
        means "every source, not just a specific one" (mirrors the caller's
        own ``source_id is None`` scope check).
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT sample_id, source_id FROM samples WHERE extraction_method='mapped_generic'"
            ).fetchall()
            stale_ids = [
                str(row["sample_id"])
                for row in rows
                if (
                    str(row["sample_id"]) not in keep_sample_ids
                    and (processed_source_ids is None or str(row["source_id"]) in processed_source_ids)
                )
            ]
            if stale_ids:
                db.executemany(
                    """
                    UPDATE samples
                    SET extraction_method='mapped_generic_stale',
                        roi_review_status='deferred',
                        updated_at=datetime('now')
                    WHERE sample_id=? AND extraction_method='mapped_generic'
                    """,
                    [(sample_id,) for sample_id in stale_ids],
                )
        return stale_ids

    def mark_stale_samples(
        self, extraction_method: str, keep_sample_ids: set[str], stale_extraction_method: str
    ) -> list[str]:
        """Demote samples of ``extraction_method`` not in ``keep_sample_ids`` to stale.

        Split out of ``recognition_ground_truth.py``'s
        ``materialize_recognition_ground_truth()``, which rebuilds Recognition
        GT samples from canonical table-cell geometry and needs to mark any
        previously-materialized sample that geometry no longer produced.
        Read and update happen in the same ``self.connect()`` transaction, as
        before.
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT sample_id FROM samples WHERE extraction_method=?",
                (extraction_method,),
            ).fetchall()
            stale_ids = [str(row["sample_id"]) for row in rows if str(row["sample_id"]) not in keep_sample_ids]
            for sample_id in stale_ids:
                db.execute(
                    "UPDATE samples SET extraction_method=?, roi_review_status='deferred', updated_at=datetime('now') WHERE sample_id=?",
                    (stale_extraction_method, sample_id),
                )
        return stale_ids

    def samples_by_method(self, extraction_method: str, status: str | None = None) -> list[dict[str, Any]]:
        """All samples for one extraction method, optionally filtered by status.

        Split out of ``recognition_ground_truth_web.py``'s ``all_samples()``.
        """
        where = "WHERE extraction_method=?"
        params: list[str] = [extraction_method]
        if status:
            where += " AND status=?"
            params.append(status)
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM samples
                {where}
                ORDER BY source_id, roi_y1, roi_x1, sample_id
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]
