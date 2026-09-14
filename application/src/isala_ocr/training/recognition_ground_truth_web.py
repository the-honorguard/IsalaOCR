from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from pathlib import Path

from urllib.parse import urlencode

from flask import abort, flash, jsonify, redirect, render_template, request, url_for

from .db import TrainingDatabase
from .projects import resolve_project_workspace
from .recognition_format import _family, _signature, build_profile, load_profile, risk_label, save_profile, score_format
from .recognition_ground_truth import (
    EXTRACTION_METHOD,
    recognition_gt_counts,
    recognition_scope,
    recognition_scope_options,
    recognition_scope_preview,
)


_FORMAT_PROFILE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recognition-format")


def _rebuild_format_profile(project_root: Path) -> None:
    database = TrainingDatabase(project_root / "samples.sqlite3")
    save_profile(project_root, build_profile(database.accepted_exact_labels(EXTRACTION_METHOD)))


def _schedule_format_profile_rebuild(project_root: Path) -> None:
    _FORMAT_PROFILE_EXECUTOR.submit(_rebuild_format_profile, project_root)


def install_recognition_ground_truth_review(app, workspace: str | Path) -> None:
    workspace_root = Path(workspace)

    def current_database() -> TrainingDatabase:
        project_workspace = resolve_project_workspace(workspace_root)
        return TrainingDatabase(project_workspace / "samples.sqlite3")

    def format_profile_for_review(database: TrainingDatabase, project_root: Path) -> dict:
        """Bootstrap the profile for existing accepted GT before scoring a queue."""
        profile = load_profile(project_root)
        if profile and profile.get("canonical_signatures"):
            return profile
        if database.has_accepted_exact_label(EXTRACTION_METHOD):
            _rebuild_format_profile(project_root)
            return load_profile(project_root)
        return {}

    def source_rows(database: TrainingDatabase, status_filter: str = "", sort: str = "source") -> list[dict]:
        return database.samples_source_counts(EXTRACTION_METHOD, status_filter or None, sort)

    def source_samples(database: TrainingDatabase, source_id: str) -> list[dict]:
        return database.samples_for_source_and_method(source_id, EXTRACTION_METHOD)

    def filter_format_samples(samples: list[dict], format_signature: str) -> list[dict]:
        signature = str(format_signature or "").strip()
        if not signature:
            return samples
        return [
            sample for sample in samples
            if _signature(str(sample.get("raw_ocr") or "")) == signature
            or _signature(str(sample.get("exact_label") or "")) == signature
        ]

    def prioritize_samples(project_root: Path, samples: list[dict], sort_mode: str = "risk") -> list[dict]:
        profile = load_profile(project_root)
        for sample in samples:
            score, reason = score_format(str(sample.get("raw_ocr") or ""), float(sample.get("raw_confidence") or 0), profile)
            sample["format_risk"] = score
            sample["format_risk_label"] = risk_label(score) if int(profile.get("label_count") or 0) >= 3 else "onbekend"
            sample["format_risk_reason"] = reason
        key = lambda item: (int(item.get("roi_y1") or 0), int(item.get("roi_x1") or 0), str(item.get("sample_id") or ""))
        if sort_mode == "normal":
            return sorted(samples, key=key)
        return sorted(samples, key=lambda item: (-int(item.get("format_risk") or 0), *key(item)))

    def next_review_source_id(database: TrainingDatabase, source_id: str) -> str | None:
        sources = [item for item in source_rows(database) if int(item.get("pending") or 0) > 0]
        ids = [str(item["source_id"]) for item in sources]
        try:
            index = ids.index(str(source_id))
        except ValueError:
            index = -1
        return ids[index + 1] if index >= 0 and index + 1 < len(ids) else (ids[0] if ids else None)

    def next_format_review_source_id(database: TrainingDatabase, source_id: str, format_signature: str) -> str | None:
        sources = []
        for item in source_rows(database):
            samples = filter_format_samples(source_samples(database, item["source_id"]), format_signature)
            if any(str(sample.get("status") or "") == "pending" for sample in samples):
                sources.append(str(item["source_id"]))
        try:
            index = sources.index(str(source_id))
        except ValueError:
            index = -1
        return sources[index + 1] if index >= 0 and index + 1 < len(sources) else (sources[0] if sources else None)

    def all_samples(database: TrainingDatabase, status_filter: str = "") -> list[dict]:
        return database.samples_by_method(EXTRACTION_METHOD, status_filter or None)

    @app.before_request
    def redirect_recognition_review_process_step():
        if request.path in {"/process/recognition-gt", "/process/recognition-review", "/process/recognition-gt-studio"}:
            return redirect(url_for("recognition_gt_review_home"))
        return None

    @app.get("/recognition-gt-review")
    def recognition_gt_review_home():
        database = current_database()
        project_root = resolve_project_workspace(workspace_root)
        counts = recognition_gt_counts(database)
        format_profile_for_review(database, project_root)
        status_filter = str(request.args.get("status") or "").strip().lower()
        if status_filter not in {"pending", "accepted", "excluded", "unreadable", "no_value"}:
            status_filter = ""
        sort = str(request.args.get("sort") or "source").strip().lower()
        if sort not in {"source", "pending", "errors"}:
            sort = "source"
        return render_template(
            "recognition_gt_review.html",
            sources=source_rows(database, status_filter, sort),
            counts=counts,
            status_filter=status_filter,
            sort=sort,
            header_counts=counts,
            header_total_label="Recognition samples",
            header_pending_label="te beoordelen",
            header_accepted_label="goedgekeurd",
        )

    @app.get("/recognition-gt-formats")
    def recognition_gt_formats():
        database = current_database()
        project_root = resolve_project_workspace(workspace_root)
        profile = format_profile_for_review(database, project_root)
        rows = database.accepted_exact_label_rows(EXTRACTION_METHOD)
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for row in rows:
            label = str(row["exact_label"] or "")
            family = _family(label)
            signature = _signature(label)
            grouped[(family, signature)].append(
                {
                    "sample_id": str(row["sample_id"]),
                    "source_id": str(row["source_id"]),
                    "raw_ocr": str(row["raw_ocr"] or ""),
                    "exact_label": label,
                }
            )
        canonical = profile.get("canonical_signatures") if isinstance(profile.get("canonical_signatures"), dict) else {}
        formats = []
        for (family, signature), examples in sorted(grouped.items()):
            formats.append(
                {
                    "family": family,
                    "signature": signature,
                    "count": len(examples),
                    # The canonical signature per family is the most common one seen
                    # in approved GT (build_profile()). Every signature here already
                    # passed review, so "not allowed" only means "a less common
                    # variant of this family's usual format", not rejected/invalid.
                    "allowed": canonical.get(family) == signature,
                    "examples": examples,
                }
            )
        selected = str(request.args.get("signature") or "")
        selected_format = next((item for item in formats if item["signature"] == selected), None)
        return render_template(
            "recognition_gt_formats.html",
            formats=formats,
            selected_format=selected_format,
            format_profile=profile,
            header_counts=recognition_gt_counts(database),
            header_total_label="Recognition samples",
            header_pending_label="te beoordelen",
            header_accepted_label="goedgekeurd",
        )

    @app.route("/recognition-gt-review/<source_id>", methods=["GET", "POST"])
    def recognition_gt_review_document(source_id: str):
        database = current_database()
        project_root = resolve_project_workspace(workspace_root)
        sort_mode = str(request.values.get("sort") or "risk").strip().lower()
        if sort_mode not in {"risk", "normal"}:
            sort_mode = "risk"
        format_signature = str(request.values.get("format_signature") or "").strip()
        all_source_samples = filter_format_samples(source_samples(database, source_id), format_signature)
        format_profile_for_review(database, project_root)
        selected_sample_id = str(request.values.get("sample_id") or "").strip()
        show_all = str(request.values.get("show_all") or "").strip().lower() in {"1", "true", "yes"}
        pending_samples = [item for item in all_source_samples if str(item.get("status") or "") == "pending"]
        selected_sample = next((item for item in all_source_samples if str(item.get("sample_id")) == selected_sample_id), None)
        samples = prioritize_samples(project_root, all_source_samples if show_all else pending_samples, sort_mode)
        if selected_sample is not None and selected_sample not in samples:
            samples.insert(0, selected_sample)
        if not all_source_samples:
            abort(404)
        if request.method == "GET" and not samples:
            target = next_format_review_source_id(database, source_id, format_signature) if format_signature else next_review_source_id(database, source_id)
            if target and target != source_id:
                query = {"format_signature": format_signature} if format_signature else {}
                return redirect(url_for("recognition_gt_review_document", source_id=target, **query))

        if request.method == "POST":
            global_action = str(request.form.get("global_action") or "").strip().lower()
            changed = 0
            changed_samples: list[dict[str, str]] = []
            for sample in samples:
                sample_id = str(sample["sample_id"])
                action = str(request.form.get(f"status_{sample_id}") or "keep").strip().lower()
                exact = str(request.form.get(f"label_{sample_id}") or sample.get("raw_ocr") or "")
                notes = str(request.form.get(f"notes_{sample_id}") or "")
                if global_action == "accept_all_ocr" and str(sample.get("status") or "") == "pending":
                    exact = str(sample.get("raw_ocr") or "")
                    # A truly blank cell has nothing for a text recognizer to
                    # learn. Keep '-' / '–' / '—' as literal text, but exclude
                    # empty strings from the recognition dataset.
                    action = "accepted" if exact != "" else "excluded"
                    if action == "excluded" and not notes:
                        notes = "Lege crop: geen recognitionlabel"
                if action == "keep":
                    continue
                if action == "accepted":
                    # Recognition GT is verbatim. A lone '-', '–' or '—' is a
                    # legitimate literal label here and is NOT converted to null.
                    if exact == "":
                        database.review(sample_id, "excluded", None, notes or "Lege crop: geen recognitionlabel")
                        saved_status = "excluded"
                    else:
                        database.review(sample_id, "accepted", exact, notes, "value")
                        saved_status = "accepted"
                elif action in {"unreadable", "excluded", "pending"}:
                    database.review(sample_id, action, None, notes)
                    saved_status = action
                else:
                    abort(400)
                changed += 1
                changed_samples.append({
                    "sample_id": sample_id,
                    "status": saved_status,
                    "exact_label": exact if saved_status == "accepted" else "",
                    "notes": notes,
                })
            _schedule_format_profile_rebuild(project_root)
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" and not global_action:
                refreshed = source_samples(database, source_id)
                remaining = [item for item in refreshed if str(item.get("status") or "") == "pending"]
                return jsonify({
                    "ok": True,
                    "changed": changed_samples,
                    "remaining": len(remaining),
                    "next_source_id": (next_format_review_source_id(database, source_id, format_signature) if format_signature else next_review_source_id(database, source_id)) if not remaining else "",
                    "format_signature": format_signature,
                    "sort_mode": sort_mode,
                    "counts": {
                        "total": len(refreshed),
                        "pending": len(remaining),
                        "accepted": sum(str(item.get("status") or "") == "accepted" for item in refreshed),
                        "excluded": sum(str(item.get("status") or "") in {"unreadable", "excluded", "no_value"} for item in refreshed),
                    },
                })
            flash(f"Recognition-GT opgeslagen: {changed} wijziging(en).", "success")
            query = {"format_signature": format_signature} if format_signature else {}
            return redirect(url_for("recognition_gt_review_document", source_id=source_id, **query))

        counts = {
            "total": len(all_source_samples),
            "pending": len(pending_samples),
            "accepted": sum(str(item.get("status") or "") == "accepted" for item in all_source_samples),
        }
        return render_template(
            "recognition_gt_review_document.html",
            source_id=source_id,
            samples=samples,
            counts=counts,
            header_counts=counts,
            header_total_label="crops",
            header_pending_label="te beoordelen",
            header_accepted_label="goedgekeurd",
            recognition_scope=recognition_scope(project_root),
            recognition_scope_options=recognition_scope_options(project_root),
            recognition_scope_preview=recognition_scope_preview(project_root),
            format_profile=load_profile(project_root),
            format_signature=format_signature,
            sort_mode=sort_mode,
            selected_sample_id=selected_sample_id,
            show_all=show_all,
        )

    @app.get("/recognition-scope")
    def recognition_scope_home():
        flash("Recognition-scope beheer je nu centraal in Tabelstudio.", "success")
        return redirect(url_for("process_step", step_key="table-quality"))

    @app.post("/recognition-gt-scope")
    def recognition_gt_scope_save():
        if request.headers.get("X-Requested-With") == "recognition-scope-autosave":
            return {"ok": False, "redirect": url_for("process_step", step_key="table-quality")}, 409
        flash("Recognition-scope beheer je nu centraal in Tabelstudio.", "success")
        return redirect(url_for("process_step", step_key="table-quality"))

    @app.route("/recognition-gt-review/sample/<sample_id>", methods=["GET", "POST"])
    def recognition_gt_review_sample(sample_id: str):
        database = current_database()
        status_filter = str(request.values.get("status") or "").strip().lower()
        format_signature = str(request.values.get("format_signature") or "").strip()
        if status_filter not in {"pending", "accepted", "excluded", "unreadable", "no_value"}:
            status_filter = ""

        samples = filter_format_samples(all_samples(database, status_filter), format_signature)
        current = next((item for item in samples if item["sample_id"] == sample_id), None)
        if current is None:
            # A sample remains reviewable when it is no longer in the active
            # filter (for example after accepting a pending item).
            current = next((item for item in filter_format_samples(all_samples(database), format_signature) if item["sample_id"] == sample_id), None)
        if current is None:
            abort(404)

        if request.method == "POST":
            action = str(request.form.get("action") or "").strip().lower()
            exact = str(request.form.get("exact_label") or "")
            notes = str(request.form.get("notes") or "")
            if action == "accept_model":
                exact = str(current.get("raw_ocr") or "")
                action = "accepted"
            if action == "accepted":
                if exact == "":
                    database.review(sample_id, "excluded", None, notes or "Lege crop: geen recognitionlabel")
                else:
                    database.review(sample_id, "accepted", exact, notes, "value")
            elif action in {"unreadable", "excluded", "pending"}:
                database.review(sample_id, action, None, notes)
            else:
                abort(400)

            # Continue in the same queue. Prefer the next item, then the
            # previous one, and finally return to the overview.
            ids = [str(item["sample_id"]) for item in samples]
            index = ids.index(sample_id) if sample_id in ids else -1
            next_id = ids[index + 1] if index >= 0 and index + 1 < len(ids) else None
            previous_id = ids[index - 1] if index > 0 else None
            target = next_id or previous_id
            if target:
                query_values = {key: value for key, value in {"status": status_filter, "format_signature": format_signature}.items() if value}
                query = urlencode(query_values)
                return redirect(url_for("recognition_gt_review_sample", sample_id=target) + (f"?{query}" if query else ""))
            if format_signature:
                return redirect(url_for("recognition_gt_review_document", source_id=current["source_id"], format_signature=format_signature))
            return redirect(url_for("recognition_gt_review_home", status=status_filter) if status_filter else url_for("recognition_gt_review_home"))

        # Recompute after the fallback lookup so navigation reflects the
        # visible queue and not a stale source-page result.
        ids = [str(item["sample_id"]) for item in samples]
        index = ids.index(sample_id) if sample_id in ids else -1
        previous_id = ids[index - 1] if index > 0 else None
        next_id = ids[index + 1] if index >= 0 and index + 1 < len(ids) else None
        return render_template(
            "recognition_gt_review_sample.html",
            sample=current,
            previous_id=previous_id,
            next_id=next_id,
            status_filter=status_filter,
            counts=recognition_gt_counts(database),
            source_url=url_for("recognition_gt_review_document", source_id=current["source_id"], format_signature=format_signature) if format_signature else url_for("recognition_gt_review_document", source_id=current["source_id"]),
            format_signature=format_signature,
            header_counts=recognition_gt_counts(database),
            header_total_label="Recognition samples",
            header_pending_label="te beoordelen",
            header_accepted_label="goedgekeurd",
        )
