"""Read-only per-source document/output viewer routes, split out of
webui.create_web_app.

Same pattern as the other ``routes_*`` modules split out of ``webui.py``:
the handlers move here, but the helpers they call (``source_rows``,
``source_samples``, ``header_field_options``, ``source_study_info``,
the active project ``database`` proxy, ``workspace_root`` and
``safe_workspace_file``) stay in webui.py because other route groups
there also depend on them, and are passed in explicitly instead of
re-implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from flask import Flask, abort, render_template

from .json_store import read_json


def register_document_routes(
    app: Flask,
    *,
    database: Any,
    workspace_root: Callable[[], Path],
    safe_workspace_file: Callable[[str | Path], Path],
    source_rows: Callable[[], list[dict[str, Any]]],
    source_samples: Callable[[str], list[dict[str, Any]]],
    header_field_options: Callable[[], list[dict[str, Any]]],
    source_study_info: Callable[[str], tuple[dict[str, Any] | None, list[dict[str, Any]]]],
    locator_label_threshold: float,
) -> None:
    @app.get("/documents")
    def documents():
        return render_template("documents.html", sources=source_rows())

    @app.get("/documents/<source_id>")
    def document(source_id: str):
        samples = source_samples(source_id)
        if not samples:
            abort(404)
        field_options = {item["field_key"]: item for item in header_field_options()}
        fallback_count = 0
        for sample in samples:
            method = str(sample.get("extraction_method") or "")
            sample["is_fallback"] = method in {"fixed_fallback", "fixed_roi"}
            fallback_count += int(sample["is_fallback"])
            profile_field = field_options.get(str(sample.get("field_key") or ""), {})
            sample["canonical_header"] = str(profile_field.get("canonical_label") or sample.get("field_label") or "")
            sample["panel"] = str(profile_field.get("panel") or "")
            sample["crop_exists"] = safe_workspace_file(str(sample.get("crop_path") or "")).is_file()
            sample["can_train_header"] = bool(
                str(sample.get("locator_label_text") or "").strip()
                and str(sample.get("header_crop_path") or "").strip()
            )
            if sample["is_fallback"]:
                matched = str(sample.get("locator_label_text") or "").strip()
                if matched:
                    sample["fallback_reason"] = (
                        f"Beste rijheadermatch '{matched}' bleef onder de acceptatiedrempel "
                        f"van {locator_label_threshold * 100:.0f}%."
                    )
                else:
                    sample["fallback_reason"] = (
                        "Er is geen bruikbare rijheadertekst gevonden; daarom zijn de vaste profielcoördinaten gebruikt."
                    )
        study_info, study_info_fields = source_study_info(source_id)
        return render_template(
            "document.html", source_id=source_id, samples=samples,
            image_width=samples[0]["image_width"], image_height=samples[0]["image_height"],
            render_exists=(workspace_root() / "source_renders" / f"{source_id}.png").is_file(),
            study_info=study_info, study_info_fields=study_info_fields,
            extracted_output_exists=(workspace_root() / "extracted_output" / f"{source_id}.json").is_file(),
            fallback_count=fallback_count, locator_label_threshold=locator_label_threshold,
        )

    @app.get("/output-review/<source_id>")
    def output_review(source_id: str):
        path = safe_workspace_file(Path("extracted_output") / f"{source_id}.json")
        if not path.is_file():
            abort(404)
        payload = read_json(path, {})
        measurements = []
        for field_key, value in (payload.get("measurements") or {}).items():
            if isinstance(value, dict):
                measurements.append({"field_key": field_key, **value})
        source = database.get_detection_source(source_id) or {}
        return render_template(
            "output_review.html", source_id=source_id, measurements=measurements,
            generated_at=payload.get("generated_at") or "",
            image_width=int(source.get("image_width") or 1),
            image_height=int(source.get("image_height") or 1),
            render_exists=(workspace_root() / "source_renders" / f"{source_id}.png").is_file(),
        )
