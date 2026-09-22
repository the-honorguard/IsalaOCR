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
from .mapping_ground_truth_fast import _configured_panel_regions
from .test_pipeline_sources import test_pipeline_source_ids


def _overlap_ratio(region: dict[str, int], panel: dict[str, object]) -> float:
    """Fraction of ``region`` covered by ``panel`` (0..1)."""
    px1, py1, px2, py2 = int(panel["x1"]), int(panel["y1"]), int(panel["x2"]), int(panel["y2"])
    ix1, iy1 = max(region["x1"], px1), max(region["y1"], py1)
    ix2, iy2 = min(region["x2"], px2), min(region["y2"], py2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area = max(1, (region["x2"] - region["x1"]) * (region["y2"] - region["y1"]))
    return inter / area


def _back_link(
    workspace_root: Path, source_id: str, *, default_url: str, default_label: str
) -> tuple[str, str]:
    """Where a source's detail pages' "back" link should go.

    A proefpagina source must always lead back to the proefpagina itself
    directly, not through a training-review hop it has been deliberately
    filtered out of (see test_pipeline_sources.py) or even through this
    source's own Datablok page first -- every one of these detail pages
    (Tabellen, Cellen, Identificatie, and Datablok itself) shares this so a
    proefpagina visit never bounces through an extra page before reaching the
    proefpagina again. For a real training source, ``default_url``/
    ``default_label`` keep each page's own, already-correct hop (sub-pages go
    up to that source's Datablok view; Datablok itself goes to the full list).
    """
    if source_id in test_pipeline_source_ids(workspace_root):
        return f"/test-pipeline?source_id={source_id}", "← Proefpagina"
    return default_url, default_label


def _located_windows(
    workspace_root: Path, localization: dict[str, Any], image_width: int, image_height: int
) -> list[dict[str, Any]]:
    """Every table region Pipeline A located, numbered top-to-bottom and matched
    to its configured Table/Panel Setup name (see ``output_review_tables``).
    Shared with the cell-detection view so both agree on the same windows.
    """
    windows = [
        {
            "x1": int(item.get("x1") or 0), "y1": int(item.get("y1") or 0),
            "x2": int(item.get("x2") or 0), "y2": int(item.get("y2") or 0),
        }
        for item in (localization.get("tables") or [])
        if isinstance(item, dict)
    ]
    windows.sort(key=lambda region: region["y1"])
    for index, region in enumerate(windows, start=1):
        region["window_index"] = index
    panels = _configured_panel_regions(workspace_root, image_width, image_height)
    for region in windows:
        best_panel = max(panels, key=lambda panel: _overlap_ratio(region, panel)) if panels else None
        region["table_label"] = (
            str(best_panel["panel_name"])
            if best_panel is not None and _overlap_ratio(region, best_panel) >= 0.50
            else "Onbekend"
        )
    return windows


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
        back_url, back_label = _back_link(
            workspace_root(), source_id, default_url="/process/value-review", default_label="← Alle datablokken"
        )
        return render_template(
            "output_review.html", source_id=source_id, measurements=measurements,
            generated_at=payload.get("generated_at") or "",
            image_width=int(source.get("image_width") or 1),
            image_height=int(source.get("image_height") or 1),
            render_exists=(workspace_root() / "source_renders" / f"{source_id}.png").is_file(),
            identification_exists=(workspace_root() / "generic_detections" / f"{source_id}.json").is_file(),
            tables_exists=(workspace_root() / "localization_detections" / f"{source_id}.json").is_file(),
            cells_exists=(workspace_root() / "localization_detections" / f"{source_id}.json").is_file(),
            back_url=back_url, back_label=back_label,
        )

    @app.get("/output-review/<source_id>/tabellen")
    def output_review_tables(source_id: str):
        """Show which tables were located, and which configured table name each got.

        Nothing else: no cell content, no row/column structure, no mapping
        outcome. Just window -> label, using the same mechanism as Table/Panel
        Setup (``table_panel_profile.json``, geometric overlap against the
        located regions) rather than the old, fragile per-relation text guess.
        """
        localization_path = safe_workspace_file(Path("localization_detections") / f"{source_id}.json")
        if not localization_path.is_file():
            abort(404)
        localization = read_json(localization_path, {})
        source = database.get_detection_source(source_id) or {}
        image_width = int(localization.get("image_width") or source.get("image_width") or 1)
        image_height = int(localization.get("image_height") or source.get("image_height") or 1)
        located_tables = _located_windows(workspace_root(), localization, image_width, image_height)
        back_url, back_label = _back_link(
            workspace_root(), source_id,
            default_url=f"/output-review/{source_id}", default_label="← Datablok",
        )

        return render_template(
            "output_tables.html", source_id=source_id,
            located_tables=located_tables,
            image_width=image_width, image_height=image_height,
            render_exists=(workspace_root() / "source_renders" / f"{source_id}.png").is_file(),
            cells_exists=bool(localization.get("tables")),
            back_url=back_url, back_label=back_label,
        )

    @app.get("/output-review/<source_id>/cellen")
    def output_review_cells(source_id: str):
        """Show the actual row/column grid per window, like GT Studio (Stap 7-9).

        The previous version of this page plotted Pipeline A's cell boxes flat
        across the whole page -- geometrically correct, but not what "cell
        detection" means in this project: GT Studio, Celdetector trainen and
        Tabelstudio all work from row/column grid structure, not a scattered
        box list. ``localization_detections`` already carries that same grid
        (each cell has ``row_index``/``column_index`` from the active, trained
        table-cell detector); this fills in each cell's text from the OCR
        blocks Pipeline B produced (by center-point containment) when that
        stage has run, and renders one real grid per window instead of one
        global scatter.
        """
        localization_path = safe_workspace_file(Path("localization_detections") / f"{source_id}.json")
        if not localization_path.is_file():
            abort(404)
        localization = read_json(localization_path, {})
        source = database.get_detection_source(source_id) or {}
        image_width = int(localization.get("image_width") or source.get("image_width") or 1)
        image_height = int(localization.get("image_height") or source.get("image_height") or 1)
        windows = _located_windows(workspace_root(), localization, image_width, image_height)

        mapping_path = safe_workspace_file(Path("generic_detections") / f"{source_id}.json")
        mapping_payload = read_json(mapping_path, {}) if mapping_path.is_file() else {}
        blocks = [
            block for block in (mapping_payload.get("blocks") or [])
            if isinstance(block, dict) and block.get("block_type") == "semantic" and str(block.get("text") or "").strip()
        ]

        located_tables = [item for item in (localization.get("tables") or []) if isinstance(item, dict)]
        for window in windows:
            table = next(
                (item for item in located_tables if item.get("x1") == window["x1"] and item.get("y1") == window["y1"]),
                {},
            )
            rows: dict[int, dict[int, dict[str, Any]]] = {}
            for cell in table.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                cx1, cy1 = int(cell.get("x1") or 0), int(cell.get("y1") or 0)
                cx2, cy2 = int(cell.get("x2") or 0), int(cell.get("y2") or 0)
                texts = [
                    block["text"].strip() for block in blocks
                    if cx1 <= (block["x1"] + block["x2"]) / 2 <= cx2
                    and cy1 <= (block["y1"] + block["y2"]) / 2 <= cy2
                ]
                row_index = int(cell.get("row_index") or 0)
                column_index = int(cell.get("column_index") or 0)
                rows.setdefault(row_index, {})[column_index] = {
                    "text": " ".join(texts),
                    "confidence": float(cell.get("confidence") or 0),
                    "x1": cx1, "y1": cy1, "x2": cx2, "y2": cy2,
                }
            column_count = max((max(cols) for cols in rows.values()), default=-1) + 1
            grid = [
                [rows[row_index].get(col) for col in range(column_count)]
                for row_index in sorted(rows)
            ]
            window["grid"] = grid
            window["cell_count"] = sum(1 for row in rows.values() for _ in row)
            window["has_text"] = bool(blocks)

        back_url, back_label = _back_link(
            workspace_root(), source_id,
            default_url=f"/output-review/{source_id}/tabellen", default_label="← Tabelherkenning",
        )
        return render_template(
            "output_cells.html", source_id=source_id, windows=windows,
            image_width=image_width, image_height=image_height,
            render_exists=(workspace_root() / "source_renders" / f"{source_id}.png").is_file(),
            back_url=back_url, back_label=back_label,
        )

    @app.get("/output-review/<source_id>/identificatie")
    def output_review_identification(source_id: str):
        """Show every within-window box and the text used to identify its side.

        Debugging aid for the deployment ("fusion") mapping path: the boxes a
        source's confirmed measurements came from are only a fraction of what
        was actually detected. This renders every candidate relation's value
        box plus the label text and context text used to decide which table
        (and therefore which canonical field) it belongs to, so a rejected
        candidate's cause is visible directly on the image instead of only in
        the raw JSON.

        Scoped to relations that actually fall inside a located table window
        (Pipeline A's regions): the page-wide generic OCR pass also treats
        scan parameters, patient info and DICOM-viewer chrome (Flip Angle,
        Scan Nr, HR, BSA, ...) as label/value "relations", since it has no
        notion of "this is a table" -- those were never eligible for mapping
        anyway (see mapping.py's own geometry gate), so showing them here
        just buries the ones that matter.
        """
        localization_path = safe_workspace_file(Path("localization_detections") / f"{source_id}.json")
        localization = read_json(localization_path, {}) if localization_path.is_file() else {}
        source = database.get_detection_source(source_id) or {}
        image_width = int(localization.get("image_width") or source.get("image_width") or 1)
        image_height = int(localization.get("image_height") or source.get("image_height") or 1)
        windows = _located_windows(workspace_root(), localization, image_width, image_height) if localization else []

        path = safe_workspace_file(Path("generic_detections") / f"{source_id}.json")
        if not path.is_file():
            abort(404)
        payload = read_json(path, {})
        blocks_by_id = {
            str(block.get("block_id") or ""): block
            for block in (payload.get("blocks") or [])
            if isinstance(block, dict)
        }
        boxes = []
        for relation in payload.get("relations") or []:
            if not isinstance(relation, dict):
                continue
            value_block = blocks_by_id.get(str(relation.get("value_block_id") or ""))
            if value_block is None:
                continue
            vx1, vy1 = int(value_block.get("x1") or 0), int(value_block.get("y1") or 0)
            vx2, vy2 = int(value_block.get("x2") or 0), int(value_block.get("y2") or 0)
            if windows:
                center_x, center_y = (vx1 + vx2) / 2, (vy1 + vy2) / 2
                if not any(w["x1"] <= center_x <= w["x2"] and w["y1"] <= center_y <= w["y2"] for w in windows):
                    continue
            label_block = blocks_by_id.get(str(relation.get("label_block_id") or ""))
            context_text = str(relation.get("context_text") or "")
            context_lower = context_text.casefold()
            if "right ventricle" in context_lower or "rechter ventrikel" in context_lower or "rechts" in context_lower:
                side = "right"
            elif "left ventricle" in context_lower or "linker ventrikel" in context_lower or "links" in context_lower:
                side = "left"
            else:
                side = "unknown"
            boxes.append({
                "x1": vx1, "y1": vy1, "x2": vx2, "y2": vy2,
                "label_text": str((label_block or {}).get("text") or ""),
                "value_text": str(value_block.get("text") or ""),
                "context_text": context_text,
                "has_table_id": bool(str(relation.get("table_id") or "")),
                "side": side,
            })
        back_url, back_label = _back_link(
            workspace_root(), source_id, default_url=f"/output-review/{source_id}", default_label="← Datablok",
        )
        return render_template(
            "output_identification.html", source_id=source_id, boxes=boxes,
            image_width=image_width, image_height=image_height,
            render_exists=(workspace_root() / "source_renders" / f"{source_id}.png").is_file(),
            back_url=back_url, back_label=back_label,
        )
