"""``TrainingDatabase`` detection-candidate/annotation/review methods.

Split out of ``db.py`` (see ``documentation/architecture/db-webui-split-plan.md``)
as a mixin, following the same pattern as ``db_samples.py``. Methods here call
``self.get_detection_candidate(...)`` / ``self.get_detection_source(...)``
(``db_generic_detection.py``) and ``self.set_detection_gate(...)``
(``db_detection_gate.py``) - that still works because every mixin combines
onto the same ``TrainingDatabase`` instance via ``self``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .db_constants import (
    VALID_DETECTION_RELEVANCE_REASONS,
    VALID_DETECTION_RELEVANCE_STATUSES,
    VALID_DETECTION_REVIEW_REASONS,
    VALID_DETECTION_REVIEW_STATUSES,
    utc_now,
)


class DetectionReviewMixin:
    def replace_localization_detection(
        self,
        source: dict[str, Any],
        candidates: list[dict[str, Any]],
        tables: list[dict[str, Any]] | None = None,
    ) -> None:
        source_id = str(source["source_id"])
        now = utc_now()
        tables = tables or []
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO detection_sources(
                    source_id, image_width, image_height, render_path, detector_version,
                    token_count, block_count, relation_count, detected_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,0,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    image_width=excluded.image_width, image_height=excluded.image_height,
                    render_path=excluded.render_path, detector_version=excluded.detector_version,
                    token_count=excluded.token_count, block_count=excluded.block_count,
                    relation_count=0, detected_at=excluded.detected_at,
                    review_completed=0, review_completed_at=NULL, updated_at=excluded.updated_at
                """,
                (
                    source_id, int(source["image_width"]), int(source["image_height"]),
                    str(source.get("render_path") or ""), str(source.get("detector_version") or ""),
                    int(source.get("token_count") or 0), len(candidates), now, now,
                ),
            )
            # Candidate IDs are deterministic. Preserve explicit reviews when the
            # same geometry reappears, but retire reviews whose candidate vanished.
            current_ids = {str(item["candidate_id"]) for item in candidates}
            existing_reviews = db.execute(
                "SELECT candidate_id FROM detection_reviews WHERE source_id=? AND candidate_id<>''",
                (source_id,),
            ).fetchall()
            for row in existing_reviews:
                candidate_id = str(row["candidate_id"])
                if candidate_id not in current_ids:
                    # Keep reviewed ground truth when machine geometry changes,
                    # but detach it from the vanished candidate so it remains
                    # visible/editable as persistent GT in Detection Review.
                    db.execute(
                        "UPDATE detection_reviews SET candidate_id='', updated_at=? WHERE source_id=? AND candidate_id=?",
                        (now, source_id, candidate_id),
                    )
                    db.execute(
                        "UPDATE detection_annotations SET candidate_id='', updated_at=? WHERE source_id=? AND candidate_id=? AND active=1",
                        (now, source_id, candidate_id),
                    )
            db.execute("DELETE FROM detection_candidates WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM detection_table_cells WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM detection_table_regions WHERE source_id=?", (source_id,))
            for item in candidates:
                db.execute(
                    """
                    INSERT INTO detection_candidates(
                        candidate_id, source_id, confidence, source_kind, source_refs_json,
                        crop_path, x1, y1, x2, y2, status, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?, ?, ?)
                    """,
                    (
                        str(item["candidate_id"]), source_id,
                        max(0.0, min(1.0, float(item.get("confidence") or 0))),
                        str(item.get("source_kind") or "text_geometry"),
                        json.dumps(item.get("source_refs") or [], ensure_ascii=False),
                        str(item.get("crop_path") or ""),
                        int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"]),
                        str(item.get("status") or "proposed"), now, now,
                    ),
                )
            for table in tables:
                table_id = str(table["table_id"])
                db.execute(
                    """
                    INSERT INTO detection_table_regions(
                        table_id, source_id, confidence, x1, y1, x2, y2, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        table_id, source_id, float(table.get("confidence") or 0),
                        int(table["x1"]), int(table["y1"]), int(table["x2"]), int(table["y2"]), now, now,
                    ),
                )
                for cell in table.get("cells") or []:
                    db.execute(
                        """
                        INSERT INTO detection_table_cells(
                            cell_id, table_id, source_id, row_index, column_index, confidence,
                            x1, y1, x2, y2, created_at, updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            str(cell["cell_id"]), table_id, source_id,
                            int(cell.get("row_index", -1)), int(cell.get("column_index", -1)),
                            float(cell.get("confidence") or 0), int(cell["x1"]), int(cell["y1"]),
                            int(cell["x2"]), int(cell["y2"]), now, now,
                        ),
                    )

    def list_detection_candidates(self, source_id: str, *, include_rejected: bool = True) -> list[dict[str, Any]]:
        where = "" if include_rejected else "AND c.status<>'rejected'"
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT c.*, r.review_id, r.review_status, r.reason_code,
                       r.relevance_status, r.relevance_reason, r.notes AS review_notes,
                       r.corrected_x1, r.corrected_y1, r.corrected_x2, r.corrected_y2, r.reviewed_at
                FROM detection_candidates c
                LEFT JOIN detection_reviews r ON r.source_id=c.source_id AND r.candidate_id=c.candidate_id
                WHERE c.source_id=? {where}
                ORDER BY c.y1, c.x1, c.y2, c.x2
                """,
                (source_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["source_refs"] = json.loads(item.pop("source_refs_json") or "[]")
            except (TypeError, ValueError):
                item["source_refs"] = []
            result.append(item)
        return result

    def get_detection_candidate(self, source_id: str, candidate_id: str) -> dict[str, Any] | None:
        items = [item for item in self.list_detection_candidates(source_id) if item["candidate_id"] == candidate_id]
        return items[0] if items else None

    def list_detection_table_geometry(self, source_id: str) -> dict[str, list[dict[str, Any]]]:
        with self.connect() as db:
            regions = [dict(row) for row in db.execute(
                "SELECT * FROM detection_table_regions WHERE source_id=? ORDER BY y1,x1", (source_id,)
            ).fetchall()]
            cells = [dict(row) for row in db.execute(
                "SELECT * FROM detection_table_cells WHERE source_id=? ORDER BY table_id,row_index,column_index,y1,x1",
                (source_id,),
            ).fetchall()]
        return {"regions": regions, "cells": cells}

    def list_detection_table_geometry_by_source(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Bulk regions+cells for every source, without one query pair per source.

        table_cell_training.py's _training_panels() used to call
        list_detection_table_geometry(source_id) once per source as its
        fallback path (a dedicated database.connect() per source); this
        answers the same question for every source in one query pair.
        """
        with self.connect() as db:
            region_rows = [dict(row) for row in db.execute(
                "SELECT * FROM detection_table_regions ORDER BY source_id, y1, x1"
            ).fetchall()]
            cell_rows = [dict(row) for row in db.execute(
                "SELECT * FROM detection_table_cells ORDER BY source_id, table_id, row_index, column_index, y1, x1"
            ).fetchall()]
        result: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for row in region_rows:
            result.setdefault(str(row["source_id"]), {"regions": [], "cells": []})["regions"].append(row)
        for row in cell_rows:
            result.setdefault(str(row["source_id"]), {"regions": [], "cells": []})["cells"].append(row)
        return result

    def review_detection_candidate(
        self,
        *,
        source_id: str,
        candidate_id: str,
        review_status: str,
        corrected_box: tuple[int, int, int, int] | None = None,
        reason_code: str = "",
        relevance_status: str = "relevant",
        relevance_reason: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Store explicit project-specific localization supervision.

        Correct/adjusted/relevant boxes are positive examples. Rejected boxes and
        technically correct but out-of-scope boxes are negative examples for the
        active project/use-case. Review reasons remain optional analytics metadata.
        Unreviewed candidates never become training data.
        """
        status = str(review_status).strip().lower()
        if status not in VALID_DETECTION_REVIEW_STATUSES - {"added"}:
            raise ValueError(f"Unsupported detection review status: {review_status}")
        reason = str(reason_code or "").strip().lower()
        if reason not in VALID_DETECTION_REVIEW_REASONS:
            raise ValueError("Choose a valid detection review reason")
        relevance = str(relevance_status or "relevant").strip().lower()
        if relevance not in VALID_DETECTION_RELEVANCE_STATUSES:
            raise ValueError(f"Unsupported detection relevance status: {relevance_status}")
        scope_reason = str(relevance_reason or "").strip().lower()
        if scope_reason not in VALID_DETECTION_RELEVANCE_REASONS:
            raise ValueError("Choose a valid relevance reason")
        if status == "rejected":
            relevance = "unreviewed"
            scope_reason = ""
        elif relevance == "unreviewed":
            # A geometrically accepted box needs an explicit scope decision.
            # Preserve backwards compatibility for API/CLI callers by treating
            # omitted scope as relevant.
            relevance = "relevant"

        candidate = self.get_detection_candidate(source_id, candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        width = int((self.get_detection_source(source_id) or {}).get("image_width") or 0)
        height = int((self.get_detection_source(source_id) or {}).get("image_height") or 0)
        original = (int(candidate["x1"]), int(candidate["y1"]), int(candidate["x2"]), int(candidate["y2"]))
        corrected = tuple(int(value) for value in (corrected_box or original))
        x1, y1, x2, y2 = corrected
        x1, x2 = sorted((max(0, x1), min(width, x2)))
        y1, y2 = sorted((max(0, y1), min(height, y2)))
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Corrected detection box must have a positive width and height")
        corrected = (x1, y1, x2, y2)
        if status == "correct":
            corrected = original
        if status == "adjusted" and corrected == original:
            status = "correct"

        now = utc_now()
        review_id = hashlib.sha256(f"{source_id}|{candidate_id}".encode("utf-8")).hexdigest()[:32]
        annotation_id = hashlib.sha256(f"annotation|{source_id}|{candidate_id}".encode("utf-8")).hexdigest()[:32]
        training_role = "negative" if status == "rejected" or relevance == "irrelevant" else "positive"
        with self.connect() as db:
            db.execute(
                "UPDATE detection_sources SET review_completed=0, review_completed_at=NULL, updated_at=? WHERE source_id=?",
                (now, source_id),
            )
            db.execute(
                """
                INSERT INTO detection_reviews(
                    review_id, source_id, candidate_id, review_status, reason_code,
                    relevance_status, relevance_reason, notes,
                    original_x1, original_y1, original_x2, original_y2,
                    corrected_x1, corrected_y1, corrected_x2, corrected_y2,
                    reviewed_at, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(review_id) DO UPDATE SET
                    review_status=excluded.review_status, reason_code=excluded.reason_code,
                    relevance_status=excluded.relevance_status, relevance_reason=excluded.relevance_reason,
                    notes=excluded.notes, corrected_x1=excluded.corrected_x1,
                    corrected_y1=excluded.corrected_y1, corrected_x2=excluded.corrected_x2,
                    corrected_y2=excluded.corrected_y2, reviewed_at=excluded.reviewed_at,
                    updated_at=excluded.updated_at
                """,
                (review_id, source_id, candidate_id, status, reason, relevance, scope_reason, str(notes or ""),
                 *original, *corrected, now, now, now),
            )
            candidate_state = "rejected" if status == "rejected" else ("irrelevant" if relevance == "irrelevant" else "reviewed")
            db.execute(
                "UPDATE detection_candidates SET status=?, updated_at=? WHERE source_id=? AND candidate_id=?",
                (candidate_state, now, source_id, candidate_id),
            )
            # Keep one active reviewed region per physical field. Positive and
            # negative project-specific examples both participate in deduplication.
            existing_annotations = db.execute(
                "SELECT annotation_id,x1,y1,x2,y2 FROM detection_annotations WHERE source_id=? AND active=1 AND annotation_id<>?",
                (source_id, annotation_id),
            ).fetchall()
            new_area = max(1, (corrected[2] - corrected[0]) * (corrected[3] - corrected[1]))
            for old in existing_annotations:
                ix1, iy1 = max(corrected[0], int(old["x1"])), max(corrected[1], int(old["y1"]))
                ix2, iy2 = min(corrected[2], int(old["x2"])), min(corrected[3], int(old["y2"]))
                intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                old_area = max(1, (int(old["x2"]) - int(old["x1"])) * (int(old["y2"]) - int(old["y1"])))
                overlap = intersection / max(1, min(new_area, old_area))
                if overlap >= 0.85:
                    db.execute(
                        "UPDATE detection_annotations SET active=0, updated_at=? WHERE annotation_id=?",
                        (now, str(old["annotation_id"])),
                    )
            db.execute(
                """
                INSERT INTO detection_annotations(
                    annotation_id, source_id, candidate_id, review_id, provenance, training_role,
                    x1,y1,x2,y2,active,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)
                ON CONFLICT(annotation_id) DO UPDATE SET
                    review_id=excluded.review_id, provenance=excluded.provenance, training_role=excluded.training_role,
                    x1=excluded.x1,y1=excluded.y1,x2=excluded.x2,y2=excluded.y2,
                    active=1,updated_at=excluded.updated_at
                """,
                (annotation_id, source_id, candidate_id, review_id, status, training_role, *corrected, now, now),
            )
        self.set_detection_gate(
            False,
            reason="Detection ground truth of scope is gewijzigd; evalueer en activeer de field detector opnieuw.",
        )
        return self.get_detection_candidate(source_id, candidate_id) or candidate

    def add_detection_annotation(
        self,
        *,
        source_id: str,
        box: tuple[int, int, int, int],
        reason_code: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        source = self.get_detection_source(source_id)
        if source is None:
            raise KeyError(source_id)
        width, height = int(source["image_width"]), int(source["image_height"])
        x1, y1, x2, y2 = (int(value) for value in box)
        x1, x2 = sorted((max(0, x1), min(width, x2)))
        y1, y2 = sorted((max(0, y1), min(height, y2)))
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Added detection box must have a positive width and height")
        now = utc_now()
        seed = f"manual|{source_id}|{x1},{y1},{x2},{y2}|{now}"
        review_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
        annotation_id = hashlib.sha256(("annotation|" + seed).encode("utf-8")).hexdigest()[:32]
        with self.connect() as db:
            db.execute("UPDATE detection_sources SET review_completed=0, review_completed_at=NULL, updated_at=? WHERE source_id=?", (now, source_id))
            db.execute(
                """
                INSERT INTO detection_reviews(
                    review_id,source_id,candidate_id,review_status,reason_code,relevance_status,relevance_reason,notes,
                    original_x1,original_y1,original_x2,original_y2,
                    corrected_x1,corrected_y1,corrected_x2,corrected_y2,
                    reviewed_at,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (review_id, source_id, "", "added", str(reason_code or ""), "relevant", "", str(notes or ""),
                 x1,y1,x2,y2,x1,y1,x2,y2,now,now,now),
            )
            db.execute(
                """
                INSERT INTO detection_annotations(
                    annotation_id,source_id,candidate_id,review_id,provenance,training_role,x1,y1,x2,y2,active,created_at,updated_at
                ) VALUES(?,?,'',?,'added','positive',?,?,?,?,1,?,?)
                """,
                (annotation_id, source_id, review_id, x1,y1,x2,y2,now,now),
            )
        self.set_detection_gate(
            False,
            reason="Detection ground truth is gewijzigd; evalueer en activeer de field detector opnieuw.",
        )
        return {
            "annotation_id": annotation_id, "review_id": review_id, "source_id": source_id,
            "review_status": "added", "provenance": "added", "training_role": "positive",
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "notes": str(notes or ""), "reason_code": str(reason_code or ""),
        }

    def update_manual_detection_annotation(
        self,
        annotation_id: str,
        *,
        box: tuple[int, int, int, int],
    ) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM detection_annotations WHERE annotation_id=? AND active=1",
                (annotation_id,),
            ).fetchone()
            if row is None or str(row["candidate_id"] or ""):
                raise KeyError(annotation_id)
            source = db.execute(
                "SELECT image_width,image_height FROM detection_sources WHERE source_id=?",
                (str(row["source_id"]),),
            ).fetchone()
            if source is None:
                raise KeyError(str(row["source_id"]))
            width, height = int(source["image_width"]), int(source["image_height"])
            x1, y1, x2, y2 = (int(value) for value in box)
            x1, x2 = sorted((max(0, x1), min(width, x2)))
            y1, y2 = sorted((max(0, y1), min(height, y2)))
            if x2 <= x1 or y2 <= y1:
                raise ValueError("Manual detection box must have a positive width and height")
            now = utc_now()
            db.execute(
                """
                UPDATE detection_annotations
                SET x1=?,y1=?,x2=?,y2=?,updated_at=?
                WHERE annotation_id=?
                """,
                (x1, y1, x2, y2, now, annotation_id),
            )
            review_id = str(row["review_id"] or "")
            if review_id:
                db.execute(
                    """
                    UPDATE detection_reviews
                    SET corrected_x1=?,corrected_y1=?,corrected_x2=?,corrected_y2=?,updated_at=?
                    WHERE review_id=?
                    """,
                    (x1, y1, x2, y2, now, review_id),
                )
            db.execute(
                "UPDATE detection_sources SET review_completed=0, review_completed_at=NULL, updated_at=? WHERE source_id=?",
                (now, str(row["source_id"])),
            )
        self.set_detection_gate(
            False,
            reason="Detection ground truth is gewijzigd; evalueer en activeer de field detector opnieuw.",
        )
        return {
            "annotation_id": annotation_id,
            "review_id": str(row["review_id"] or ""),
            "source_id": str(row["source_id"]),
            "review_status": "added",
            "provenance": str(row["provenance"] or "added"),
            "training_role": str(row["training_role"] or "positive"),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        }

    def delete_manual_detection_annotation(self, annotation_id: str) -> None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM detection_annotations WHERE annotation_id=?", (annotation_id,)).fetchone()
            if row is None or str(row["candidate_id"] or ""):
                raise KeyError(annotation_id)
            now = utc_now()
            db.execute("UPDATE detection_annotations SET active=0, updated_at=? WHERE annotation_id=?", (now, annotation_id))
            db.execute("UPDATE detection_sources SET review_completed=0, review_completed_at=NULL, updated_at=? WHERE source_id=?", (now, str(row["source_id"])))
        self.set_detection_gate(
            False,
            reason="Detection ground truth is gewijzigd; evalueer en activeer de field detector opnieuw.",
        )

    def accept_unreviewed_detection_candidates(self, source_id: str) -> int:
        """Accept every still-open machine candidate for one source as positive GT.

        This is intentionally source-scoped and is used only when the reviewer
        explicitly finishes an image with the "include remaining" option enabled.
        Explicit Not relevant / Incorrect / adjusted decisions are preserved.
        """
        source = self.get_detection_source(source_id)
        if source is None:
            raise KeyError(source_id)
        candidates = self.list_detection_candidates(source_id, include_rejected=True)
        pending = [item for item in candidates if not str(item.get("review_status") or "").strip()]
        for item in pending:
            self.review_detection_candidate(
                source_id=source_id,
                candidate_id=str(item["candidate_id"]),
                review_status="correct",
                relevance_status="relevant",
            )
        return len(pending)

    def set_detection_source_review_completed(
        self,
        source_id: str,
        completed: bool = True,
        *,
        accept_unreviewed: bool = False,
    ) -> dict[str, Any]:
        source = self.get_detection_source(source_id)
        if source is None:
            raise KeyError(source_id)
        if completed and accept_unreviewed:
            self.accept_unreviewed_detection_candidates(source_id)
        now = utc_now()
        if completed:
            counts = self.detection_review_counts(source_id)
            if int(counts.get("pending") or 0) > 0:
                raise ValueError(f"Nog {counts['pending']} onbeoordeelde ROI's")
        with self.connect() as db:
            db.execute(
                "UPDATE detection_sources SET review_completed=?, review_completed_at=?, updated_at=? WHERE source_id=?",
                (1 if completed else 0, now if completed else None, now, source_id),
            )
        return self.get_detection_source(source_id) or source

    def list_detection_annotations(
        self,
        source_id: str | None = None,
        *,
        active_only: bool = True,
        include_ignored: bool = False,
    ) -> list[dict[str, Any]]:
        """Return reviewed Pipeline-A geometry.

        By default only positive project-specific localization ground truth is returned.
        Callers that need audit/UI or explicit negative examples can request
        ``include_ignored=True`` (legacy parameter name kept for compatibility).
        """
        clauses: list[str] = []
        params: list[Any] = []
        if source_id:
            clauses.append("a.source_id=?")
            params.append(source_id)
        if active_only:
            clauses.append("a.active=1")
        if not include_ignored:
            clauses.append("a.training_role='positive'")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT a.*, r.review_status, r.reason_code, r.relevance_status, r.relevance_reason,
                       r.notes, r.reviewed_at, s.render_path, s.image_width, s.image_height
                FROM detection_annotations a
                LEFT JOIN detection_reviews r ON r.review_id=a.review_id
                JOIN detection_sources s ON s.source_id=a.source_id
                {where}
                ORDER BY a.source_id,a.y1,a.x1
                """, params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_detection_reviews(self, source_id: str | None = None) -> list[dict[str, Any]]:
        if source_id:
            query, params = "SELECT * FROM detection_reviews WHERE source_id=? ORDER BY reviewed_at", (source_id,)
        else:
            query, params = "SELECT * FROM detection_reviews ORDER BY reviewed_at", ()
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def detection_review_counts(self, source_id: str | None = None) -> dict[str, int]:
        """Count geometry review and workflow relevance independently."""
        with self.connect() as db:
            params: tuple[Any, ...] = (source_id,) if source_id else ()
            candidate_where = "WHERE c.source_id=?" if source_id else ""
            candidate_total = int(db.execute(
                f"SELECT COUNT(*) FROM detection_candidates c {candidate_where}", params
            ).fetchone()[0])
            rows = db.execute(
                f"""
                SELECT r.review_status, r.relevance_status, COUNT(*) amount
                FROM detection_reviews r
                JOIN detection_candidates c
                  ON c.source_id=r.source_id AND c.candidate_id=r.candidate_id
                {('WHERE r.source_id=?' if source_id else '')}
                GROUP BY r.review_status, r.relevance_status
                """, params,
            ).fetchall()
            added_params: tuple[Any, ...] = (source_id,) if source_id else ()
            added = int(db.execute(
                f"SELECT COUNT(*) FROM detection_reviews WHERE review_status='added' {('AND source_id=?' if source_id else '')}",
                added_params,
            ).fetchone()[0])
            positive_annotations = int(db.execute(
                f"SELECT COUNT(*) FROM detection_annotations WHERE active=1 AND training_role='positive' {('AND source_id=?' if source_id else '')}",
                added_params,
            ).fetchone()[0])
            ignored_annotations = int(db.execute(
                f"SELECT COUNT(*) FROM detection_annotations WHERE active=1 AND training_role='negative' {('AND source_id=?' if source_id else '')}",
                added_params,
            ).fetchone()[0])
            persistent_annotations = int(db.execute(
                f"SELECT COUNT(*) FROM detection_annotations WHERE active=1 AND candidate_id='' {('AND source_id=?' if source_id else '')}",
                added_params,
            ).fetchone()[0])
        result = {status: 0 for status in VALID_DETECTION_REVIEW_STATUSES}
        result.update({"relevant": 0, "irrelevant": 0})
        for row in rows:
            status = str(row["review_status"])
            relevance = str(row["relevance_status"] or "relevant")
            amount = int(row["amount"])
            if status in result:
                result[status] += amount
            if status in {"correct", "adjusted"} and relevance in {"relevant", "irrelevant"}:
                result[relevance] += amount
        result["added"] = added
        candidate_reviewed = result["correct"] + result["adjusted"] + result["rejected"]
        result["candidate_total"] = candidate_total
        result["candidate_reviewed"] = candidate_reviewed
        result["pending"] = max(0, candidate_total - candidate_reviewed)
        result["positive"] = positive_annotations
        result["negative"] = ignored_annotations
        result["ignored"] = ignored_annotations  # backwards-compatible UI key
        result["persistent"] = persistent_annotations
        result["total_reviews"] = candidate_reviewed + result["added"]
        return result

    def detection_review_counts_by_source(self) -> dict[str, dict[str, int]]:
        """Return the same review counters as detection_review_counts, grouped in bulk.

        The review overview used to execute 5+ SQL statements per source. This
        keeps page cost essentially constant as the number of DICOM sources grows.
        """
        with self.connect() as db:
            source_ids = [str(row[0]) for row in db.execute(
                "SELECT source_id FROM detection_sources"
            ).fetchall()]
            candidate_rows = db.execute(
                "SELECT source_id, COUNT(*) amount FROM detection_candidates GROUP BY source_id"
            ).fetchall()
            review_rows = db.execute(
                """
                SELECT r.source_id, r.review_status, r.relevance_status, COUNT(*) amount
                FROM detection_reviews r
                JOIN detection_candidates c
                  ON c.source_id=r.source_id AND c.candidate_id=r.candidate_id
                GROUP BY r.source_id, r.review_status, r.relevance_status
                """
            ).fetchall()
            added_rows = db.execute(
                """
                SELECT source_id, COUNT(*) amount
                FROM detection_reviews
                WHERE review_status='added'
                GROUP BY source_id
                """
            ).fetchall()
            annotation_rows = db.execute(
                """
                SELECT source_id, training_role, COUNT(*) amount,
                       SUM(CASE WHEN candidate_id='' THEN 1 ELSE 0 END) persistent
                FROM detection_annotations
                WHERE active=1
                GROUP BY source_id, training_role
                """
            ).fetchall()

        def empty() -> dict[str, int]:
            result = {status: 0 for status in VALID_DETECTION_REVIEW_STATUSES}
            result.update({
                "relevant": 0, "irrelevant": 0, "added": 0,
                "candidate_total": 0, "candidate_reviewed": 0, "pending": 0,
                "positive": 0, "negative": 0, "ignored": 0, "persistent": 0,
                "total_reviews": 0,
            })
            return result

        result = {source_id: empty() for source_id in source_ids}
        for row in candidate_rows:
            result.setdefault(str(row["source_id"]), empty())["candidate_total"] = int(row["amount"])
        for row in review_rows:
            item = result.setdefault(str(row["source_id"]), empty())
            status = str(row["review_status"])
            relevance = str(row["relevance_status"] or "relevant")
            amount = int(row["amount"])
            if status in item:
                item[status] += amount
            if status in {"correct", "adjusted"} and relevance in {"relevant", "irrelevant"}:
                item[relevance] += amount
        for row in added_rows:
            result.setdefault(str(row["source_id"]), empty())["added"] = int(row["amount"])
        for row in annotation_rows:
            item = result.setdefault(str(row["source_id"]), empty())
            role = str(row["training_role"] or "positive")
            amount = int(row["amount"])
            if role == "positive":
                item["positive"] += amount
            elif role == "negative":
                item["negative"] += amount
                item["ignored"] += amount
            item["persistent"] += int(row["persistent"] or 0)
        for item in result.values():
            item["candidate_reviewed"] = item["correct"] + item["adjusted"] + item["rejected"]
            item["pending"] = max(0, item["candidate_total"] - item["candidate_reviewed"])
            item["total_reviews"] = item["candidate_reviewed"] + item["added"]
        return result

    def detection_table_counts_by_source(self) -> dict[str, dict[str, int]]:
        """Count table regions/cells for all sources without N+1 queries."""
        with self.connect() as db:
            region_rows = db.execute(
                "SELECT source_id, COUNT(*) amount FROM detection_table_regions GROUP BY source_id"
            ).fetchall()
            cell_rows = db.execute(
                "SELECT source_id, COUNT(*) amount FROM detection_table_cells GROUP BY source_id"
            ).fetchall()
        result: dict[str, dict[str, int]] = {}
        for row in region_rows:
            result.setdefault(str(row["source_id"]), {"regions": 0, "cells": 0})["regions"] = int(row["amount"])
        for row in cell_rows:
            result.setdefault(str(row["source_id"]), {"regions": 0, "cells": 0})["cells"] = int(row["amount"])
        return result

    def table_first_quality_rows(self) -> dict[str, list[dict[str, Any]]]:
        """Raw rows behind the table-first quality gate (see ``table_quality.py``).

        Previously ``table_quality.py`` ran these four queries itself via a
        raw ``db.connect()`` block (CODE_REVIEW_v3.16.0.md, sectie Hoog).
        Centralizing them here means a schema change to these tables is felt
        in this one place instead of silently drifting out of sync with
        ``table_quality.py``'s own copy of the same column/table names.
        """
        with self.connect() as db:
            source_rows = db.execute(
                "SELECT source_id, review_completed FROM detection_sources ORDER BY source_id"
            ).fetchall()
            candidate_rows = db.execute(
                """
                SELECT source_id, COUNT(*) amount
                FROM detection_candidates
                WHERE source_kind LIKE '%table_cell%'
                GROUP BY source_id
                """
            ).fetchall()
            review_rows = db.execute(
                """
                SELECT r.source_id, r.review_status, r.relevance_status, COUNT(*) amount
                FROM detection_reviews r
                JOIN detection_candidates c
                  ON c.source_id=r.source_id AND c.candidate_id=r.candidate_id
                WHERE c.source_kind LIKE '%table_cell%'
                GROUP BY r.source_id, r.review_status, r.relevance_status
                """
            ).fetchall()
            added_rows = db.execute(
                """
                SELECT a.source_id, COUNT(*) amount,
                       SUM(CASE WHEN r.notes LIKE 'Geometrisch gereconstrueerd%' THEN 1 ELSE 0 END) reconstructed
                FROM detection_annotations a
                JOIN detection_sources s ON s.source_id=a.source_id
                LEFT JOIN detection_reviews r ON r.review_id=a.review_id
                WHERE a.active=1
                  AND a.training_role='positive'
                  AND a.candidate_id=''
                  AND a.provenance='added'
                  AND a.created_at >= s.detected_at
                GROUP BY a.source_id
                """
            ).fetchall()
        return {
            "source_rows": [dict(row) for row in source_rows],
            "candidate_rows": [dict(row) for row in candidate_rows],
            "review_rows": [dict(row) for row in review_rows],
            "added_rows": [dict(row) for row in added_rows],
        }

    def detection_reviews_before_baseline(
        self, reviewed_at_max: str | None, reviewed_at_min: str | None
    ) -> list[dict[str, Any]]:
        """Non-'added' detection reviews, optionally bounded by ``reviewed_at``.

        Split out of ``table_model_comparison.py``'s ``build_step4_baseline()``
        (CODE_REVIEW_v3.16.0.md, sectie Hoog). Reconstructs the historic
        PP-Structure baseline as it stood at dataset-build time: reviews after
        the dataset snapshot (``reviewed_at_max``) or before the current panel
        profile took effect (``reviewed_at_min``) are excluded.
        """
        sql = """
            SELECT source_id,review_status,original_x1,original_y1,original_x2,original_y2,reviewed_at
            FROM detection_reviews
            WHERE review_status<>'added'
        """
        params: list[Any] = []
        if reviewed_at_max:
            sql += " AND reviewed_at<=?"
            params.append(reviewed_at_max)
        if reviewed_at_min:
            sql += " AND reviewed_at>=?"
            params.append(reviewed_at_min)
        sql += " ORDER BY reviewed_at,source_id"
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def current_table_annotations(self, source_id: str) -> list[dict[str, Any]]:
        """Positive GT belonging to the current table-first detection pass.

        Split out of ``table_cell_training.py``'s ``_current_table_annotations()``
        (CODE_REVIEW_v3.16.0.md, sectie Hoog). Historic PicoDet/manual geometry
        may intentionally remain in SQLite. Candidate-backed annotations are
        therefore accepted only when the current candidate is a table-cell;
        candidate-less additions count only when they were created after the
        current source detection timestamp. This mirrors the table-first
        quality calculation (``table_first_quality_rows()`` above).
        """
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT a.*, s.render_path, s.image_width, s.image_height, s.detected_at,
                       c.source_kind, r.notes, r.reason_code
                FROM detection_annotations a
                JOIN detection_sources s ON s.source_id=a.source_id
                LEFT JOIN detection_candidates c
                  ON c.source_id=a.source_id AND c.candidate_id=a.candidate_id
                LEFT JOIN detection_reviews r ON r.review_id=a.review_id
                WHERE a.source_id=?
                  AND a.active=1
                  AND a.training_role='positive'
                  AND (
                        (a.candidate_id<>'' AND c.source_kind LIKE '%table_cell%')
                     OR (a.candidate_id='' AND a.provenance='added' AND a.created_at>=s.detected_at)
                  )
                ORDER BY a.y1,a.x1
                """,
                (source_id,),
            ).fetchall()
        return [dict(row) for row in rows]
