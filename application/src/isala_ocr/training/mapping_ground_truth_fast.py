from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import replace
from pathlib import Path

import cv2

from ..config import AppConfig
from ..dicom import hash_file
from ..image_io import load_input
from ..ocr.base import OCREngine
from ..study_info import extract_study_info
from .db import TrainingDatabase, utc_now
from .generic_detection import GENERIC_DETECTOR_VERSION, detect_generic_structure, integrate_table_regions
from .mapping import ensure_default_field_definitions
from .mapping_fast import suggest_mappings_fast
from .mapping_ground_truth import (
    CANONICAL_MAPPING_GEOMETRY_VERSION,
    _files,
    canonical_table_regions,
    mark_canonical_geometry,
)
from .projects import resolve_project_workspace
from .table_cell_ground_truth import (
    ensure_table_cell_ground_truth,
    ground_truth_review_state,
    list_ground_truth_cells,
)

LOGGER = logging.getLogger(__name__)


def _canonical_panel_regions(workspace: str | Path, source_id: str) -> list[dict[str, object]]:
    """Return semantic panel identity plus its canonical GT bounding box.

    Mapping already knows which canonical panel/table owns every cell. Older
    Mapping builds dropped that identity after reconstructing the table regions,
    leaving labels such as ``ED Volume`` or ``Cardiac Output`` ambiguous between
    LV and RV. Keep the user-defined panel name/id next to the geometry so it can
    become mapping context without changing the authoritative GT itself.
    """
    grouped: dict[str, dict[str, object]] = {}
    for cell in list_ground_truth_cells(workspace, source_id):
        panel_id = str(cell.get("panel_id") or "unassigned").strip() or "unassigned"
        panel_name = str(cell.get("panel_name") or panel_id).strip() or panel_id
        try:
            x1 = int(cell["x1"])
            y1 = int(cell["y1"])
            x2 = int(cell["x2"])
            y2 = int(cell["y2"])
        except (KeyError, TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        item = grouped.get(panel_id)
        if item is None:
            grouped[panel_id] = {
                "panel_id": panel_id,
                "panel_name": panel_name,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            }
            continue
        item["x1"] = min(int(item["x1"]), x1)
        item["y1"] = min(int(item["y1"]), y1)
        item["x2"] = max(int(item["x2"]), x2)
        item["y2"] = max(int(item["y2"]), y2)
        if panel_name and panel_name != panel_id:
            item["panel_name"] = panel_name
    return list(grouped.values())


def _panel_overlap_ratio(table: object, panel: dict[str, object]) -> float:
    box = getattr(table, "box", None)
    if box is None:
        return 0.0
    px1 = int(panel["x1"])
    py1 = int(panel["y1"])
    px2 = int(panel["x2"])
    py2 = int(panel["y2"])
    intersection_width = max(0, min(int(box.x2), px2) - max(int(box.x1), px1))
    intersection_height = max(0, min(int(box.y2), py2) - max(int(box.y1), py1))
    intersection = intersection_width * intersection_height
    if intersection <= 0:
        return 0.0
    table_area = max(1, int(box.x2 - box.x1) * int(box.y2 - box.y1))
    panel_area = max(1, (px2 - px1) * (py2 - py1))
    return intersection / max(1, min(table_area, panel_area))


def _semantic_panel_context(panel: dict[str, object]) -> str:
    values: list[str] = []
    for key in ("panel_name", "panel_id"):
        value = str(panel.get(key) or "").strip()
        if value and value.casefold() not in {item.casefold() for item in values}:
            values.append(value)
    return " | ".join(values)


def _enrich_relations_with_panel_context(
    workspace: str | Path,
    source_id: str,
    table_regions: list[object],
    relations: list[object],
) -> tuple[list[object], dict[str, str]]:
    """Attach canonical panel identity to table relation context.

    The relation scorer already understands explicit LV/RV context. This bridge
    makes the table identity that was established in Panel Setup/GT available to
    that scorer, so generic labels can be proposed for the correct functional
    field instead of forcing manual selection.
    """
    panels = _canonical_panel_regions(workspace, source_id)
    context_by_table: dict[str, str] = {}
    for table in table_regions:
        table_id = str(getattr(table, "table_id", "") or "")
        if not table_id or not panels:
            continue
        best_panel = max(panels, key=lambda panel: _panel_overlap_ratio(table, panel))
        score = _panel_overlap_ratio(table, best_panel)
        if score < 0.50:
            continue
        context = _semantic_panel_context(best_panel)
        if context:
            context_by_table[table_id] = context

    enriched: list[object] = []
    for relation in relations:
        table_id = str(
            (relation.get("table_id") if isinstance(relation, dict) else getattr(relation, "table_id", ""))
            or ""
        )
        panel_context = context_by_table.get(table_id, "")
        if not panel_context:
            enriched.append(relation)
            continue
        existing = str(
            (relation.get("context_text") if isinstance(relation, dict) else getattr(relation, "context_text", ""))
            or ""
        ).strip()
        if panel_context.casefold() in existing.casefold():
            merged = existing
        else:
            merged = f"{panel_context} | {existing}" if existing else panel_context
        if isinstance(relation, dict):
            enriched.append({**relation, "context_text": merged})
        else:
            enriched.append(replace(relation, context_text=merged))
    return enriched, context_by_table


def _redetect_source_from_canonical_gt(
    source_path: Path,
    root: Path,
    config: AppConfig,
    locator_engine: OCREngine,
    database: TrainingDatabase,
    diagnostics_root: Path,
    source_renders_root: Path,
) -> tuple[int, int]:
    """Run one real Detection/Recognition OCR pass for a single source.

    ``collect_mapping_from_canonical_gt`` normally only rebuilds suggestions
    from Detection/Recognition output that already exists (see its
    docstring); it never runs OCR itself. That makes a source permanently
    unrecoverable if the one and only run that ever populated its
    detection/detected_relations rows produced nothing: nothing else in this
    pipeline ever revisits it. This is the narrow escape hatch: it performs
    the same OCR/table-structure pass ``collector.py`` would have, for this
    one source only, and persists it exactly like a normal detection run
    would, so a source stuck at zero relations gets one real second chance
    before Mapping preparation gives up on it.

    Returns ``(ocr_token_count, relation_count)`` after persisting.
    """
    decoded = load_input(source_path, config.dicom)
    height, width = decoded.image.shape[:2]
    batches = locator_engine.recognize_many([decoded.image])
    if len(batches) != 1:
        raise RuntimeError("Generic detector did not return one OCR result for one source")
    tokens = batches[0]
    blocks, relations, detector_diagnostics = detect_generic_structure(
        decoded.source_id, decoded.image.shape, tokens
    )
    table_regions = canonical_table_regions(
        root, decoded.source_id, tokens, image_width=width, image_height=height,
    )
    blocks, relations, structural = integrate_table_regions(
        decoded.source_id, blocks, relations, table_regions
    )
    # Mapping Studio (both the label-first and ROI-first pages) resolves
    # which Table/Panel Setup panel a relation belongs to from context_text
    # alone - a relation's table_id is a per-run canonical-GT hash that
    # never matches a panel_id. Without this, a freshly redetected relation
    # has no panel context, relation_panel_id() can't resolve it, and the
    # Table Studio "Overslaan" (skip) column filter silently stops applying
    # to it (it was previously getting this from collector.py's own
    # detection run; this redetection path needs to do the same).
    relations, panel_context_by_table = _enrich_relations_with_panel_context(
        root, decoded.source_id, list(table_regions), list(relations)
    )
    blocks = mark_canonical_geometry(blocks)
    detector_diagnostics["table_structure"] = {
        "enabled": True,
        "provider": "canonical_table_cell_ground_truth",
        "engine_version": CANONICAL_MAPPING_GEOMETRY_VERSION,
        "model_inference": False,
        "active_table_model_loaded": False,
        "semantic_panel_context": panel_context_by_table,
        "error": "",
        **structural,
    }
    detector_diagnostics["block_count"] = len(blocks)
    detector_diagnostics["relation_count"] = len(relations)

    source_renders_root.mkdir(parents=True, exist_ok=True)
    render_relative = Path("source_renders") / f"{decoded.source_id}.png"
    if not cv2.imwrite(str(root / render_relative), decoded.image):
        raise RuntimeError(f"Could not save local source render: {root / render_relative}")

    block_by_id = {block.block_id: block for block in blocks}
    label_crop_ids = {
        str(relation.label_block_id)
        for relation in relations
        if relation.label_block_id and str(relation.label_block_id) in block_by_id
    }
    crop_paths: dict[str, str] = {}
    if label_crop_ids:
        source_block_dir = root / "detected_blocks" / decoded.source_id
        source_block_dir.mkdir(parents=True, exist_ok=True)
        for block_id in sorted(label_crop_ids):
            block = block_by_id[block_id]
            box = block.box.clamp(width, height)
            crop = decoded.image[box.y1:box.y2, box.x1:box.x2]
            if not crop.size:
                continue
            destination = source_block_dir / f"{block.block_id}.png"
            if cv2.imwrite(str(destination), crop):
                crop_paths[block_id] = destination.relative_to(root).as_posix()

    block_payloads: list[dict[str, object]] = []
    for block in blocks:
        payload = block.as_dict()
        payload["crop_path"] = crop_paths.get(block.block_id, "")
        block_payloads.append(payload)
    relation_payloads = [relation.as_dict() for relation in relations]

    database.replace_generic_detection(
        {
            "source_id": decoded.source_id,
            "image_width": width,
            "image_height": height,
            "render_path": render_relative.as_posix(),
            "detector_version": GENERIC_DETECTOR_VERSION,
            "token_count": detector_diagnostics.get("ocr_token_count", 0),
        },
        block_payloads,
        relation_payloads,
    )

    study_info = extract_study_info(tokens)
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    (diagnostics_root / f"{decoded.source_id}.json").write_text(
        json.dumps(
            {
                "schema_version": "2.3-canonical-gt-mapping-panel-aware",
                "source_id": decoded.source_id,
                "detector": detector_diagnostics,
                "study_info": study_info.as_dict(),
                "blocks": block_payloads,
                "relations": relation_payloads,
                "tables": [table.as_dict() for table in table_regions],
                "geometry_authority": "canonical_table_cell_ground_truth",
                "materialized_label_crops": len(crop_paths),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return int(detector_diagnostics.get("ocr_token_count", 0)), len(relations)


def collect_mapping_from_canonical_gt(
    input_path: str | Path,
    workspace: str | Path,
    config: AppConfig,
    locator_engine: OCREngine,
) -> dict[str, object]:
    """Prepare Mapping Studio from canonical GT with bounded I/O and DB work.

    Only source renders and relation-label thumbnails are materialized. Value
    crops are already generated on demand from the authoritative Pipeline-A ROI
    by the WebUI, so writing hundreds of line/token/part/semantic PNG files here
    is unnecessary and particularly expensive on Windows/Docker bind mounts.
    """
    root = resolve_project_workspace(workspace)
    # Pipeline B must consume the outputs of the preceding Detection and
    # Recognition stages.  It is a semantic mapping rebuild, not another
    # image/OCR run.  The existing detected_blocks/detected_relations rows are
    # the canonical input here; only field_mappings are regenerated. The one
    # exception is _redetect_source_from_canonical_gt() below: a source stuck
    # at zero relations gets one real OCR pass, because nothing else in this
    # pipeline ever revisits a source once canonical GT exists for it.
    database = TrainingDatabase(root / "samples.sqlite3")
    ensure_default_field_definitions(database, config.profile)
    existing_sources = database.list_detection_sources()
    if not existing_sources:
        raise RuntimeError(
            "Mapping kan niet worden opgebouwd: er is geen bestaande Detection/Recognition-output. "
            "Voer eerst de voorafgaande detectie- en recognitionstappen uit."
        )
    database.clear_all_mappings()
    total_suggestions = 0
    processed_sources = 0
    sources_without_ocr_tokens = 0
    sources_with_tokens_but_no_relations = 0
    redetected_sources = 0
    diagnostics_root = root / "generic_detections"
    source_renders_root = root / "source_renders"
    source_paths_by_id: dict[str, Path] | None = None
    for source in existing_sources:
        source_id = str(source.get("source_id") or "").strip()
        if not source_id:
            continue
        relations = database.list_detected_relations(source_id)
        relation_count = len(relations)
        redetection_attempted = False
        if relation_count <= 0 and locator_engine is not None:
            # This fast path normally never runs OCR (see the module
            # docstring); a source whose one and only Detection/Recognition
            # run produced zero relations would otherwise be stuck that way
            # forever. Give it one real, narrowly-scoped OCR pass before
            # reporting it as broken.
            if source_paths_by_id is None:
                source_paths_by_id = {
                    hash_file(candidate)[:24]: candidate
                    for candidate in _files(Path(input_path))
                }
            source_path = source_paths_by_id.get(source_id)
            if source_path is not None:
                redetection_attempted = True
                try:
                    _, relation_count = _redetect_source_from_canonical_gt(
                        source_path, root, config, locator_engine, database,
                        diagnostics_root, source_renders_root,
                    )
                except Exception:
                    LOGGER.exception(
                        "Mapping source [%s]: re-running Detection/Recognition after zero "
                        "stored relations failed; keeping the previous stored output.",
                        source_id,
                    )
                    relation_count = len(database.list_detected_relations(source_id))
                else:
                    redetected_sources += 1
                    source = database.get_detection_source(source_id) or source
                relations = database.list_detected_relations(source_id)
        if relation_count <= 0:
            token_count = int(source.get("token_count") or 0)
            block_count = int(source.get("block_count") or 0)
            if token_count <= 0:
                sources_without_ocr_tokens += 1
                if redetection_attempted:
                    hint = (
                        "de Detectie/Recognition-stap is voor deze bron opnieuw uitgevoerd, maar "
                        "vond nog steeds geen tekst; controleer de brondafbeelding zelf."
                    )
                else:
                    hint = "de Detectie/Recognition-OCR vond geen tekst voor deze bron; voer die stap opnieuw uit."
            else:
                sources_with_tokens_but_no_relations += 1
                hint = (
                    "er was wel OCR-tekst, maar geen enkel label/waarde-paar kon worden gevormd; "
                    "controleer de canonical GT-celdekking en tabel-/paneelindeling."
                )
            LOGGER.warning(
                "Mapping source [%s]: existing Detection/Recognition-output contains no relations "
                "(token_count=%d, block_count=%d); skipped. %s",
                source_id, token_count, block_count, hint,
            )
            continue
        # The mapping rebuild intentionally reuses Detection/Recognition
        # output. Reattach the user-configured table/panel identity to those
        # existing relations so a generic label (for example ``ED Volume``)
        # can resolve to the correct side on any new report layout.
        #
        # Canonical GT geometry, not Pipeline-A's detection_table_regions, is
        # the authoritative table_id space here: it's what relations.table_id
        # was actually stamped from (a per-run "canonical-<hash>" id -
        # detection_table_regions belongs to an unrelated, older detection
        # pass and its table ids never match). No OCR runs in this branch
        # ("no OCR or DICOM processing performed" below is accurate) - empty
        # tokens still yield correct table_id/box geometry for every cell,
        # just without per-cell text, which this step doesn't need.
        try:
            table_regions = canonical_table_regions(
                root, source_id, [],
                image_width=int(source.get("image_width") or 0),
                image_height=int(source.get("image_height") or 0),
            )
        except RuntimeError:
            table_regions = []
        enriched, _ = _enrich_relations_with_panel_context(
            root, source_id, table_regions, relations
        )
        contexts = {
            str(relation.get("relation_id") or ""): str(relation.get("context_text") or "")
            for relation in enriched
            if isinstance(relation, dict)
            and str(relation.get("relation_id") or "")
        }
        database.update_relation_contexts(source_id, contexts)
        suggestions = suggest_mappings_fast(database, source_id)
        processed_sources += 1
        total_suggestions += len(suggestions)
        LOGGER.info(
            "Mapping source [%s]: reused %d existing relations and created %d mapping suggestion(s); no OCR or DICOM processing performed.",
            source_id,
            relation_count,
            len(suggestions),
        )
    if not processed_sources:
        raise RuntimeError(
            "Mapping kan niet worden opgebouwd: de bestaande Detection/Recognition-output bevat geen relaties. "
            f"{sources_without_ocr_tokens} bron(nen) hadden 0 OCR-tokens (voer de Detectie/Recognition-stap "
            f"opnieuw uit); {sources_with_tokens_but_no_relations} bron(nen) hadden wel OCR-tekst maar geen "
            "label/waarde-relatie (controleer canonical GT-celdekking en tabel-/paneelindeling)."
        )
    return {
        "flow": "mapping_only_from_existing_detection_recognition_output",
        "processed_sources": processed_sources,
        "available_sources": len(existing_sources),
        "automatic_mapping_suggestions": total_suggestions,
        "redetected_sources": redetected_sources,
        "ocr_performed": redetected_sources > 0,
        "dicom_reprocessed": False,
        "mappings_reset": True,
    }

    # The code below is retained temporarily as a compatibility reference for
    # older projects, but is unreachable for the current Pipeline-B action.
    gt = ensure_table_cell_ground_truth(root)
    if gt is None:
        raise RuntimeError("Canonical table-cell Ground Truth is unavailable")
    state = ground_truth_review_state(root)
    if int(state.get("gt_cell_count") or 0) <= 0:
        raise RuntimeError(
            "Canonical table-cell Ground Truth is unavailable or contains no cells."
        )

    # Mapping Studio is a review/preview step. It may process sources whose
    # canonical geometry has been explicitly checked while other sources in
    # the same batch are still open. The training gate remains closed until
    # every source is reviewed; that gate is synchronized below by the CLI.
    open_source_count = int(state.get("open_source_count") or 0)
    if open_source_count:
        LOGGER.warning(
            "Mapping Studio: processing all %d source(s) with available canonical "
            "table structure; %d source(s) still have open GT review. Training "
            "remains gated until all sources are reviewed.",
            int(state.get("source_count") or 0),
            open_source_count,
        )

    diagnostics_root = root / "generic_detections"
    blocks_root = root / "detected_blocks"
    source_renders_root = root / "source_renders"
    # A Mapping Studio rebuild starts a clean proposal dataset. Canonical GT,
    # Recognition-GT and relation feedback remain authoritative, but all old
    # source mappings must be removed because their field semantics may have
    # been produced by an earlier mapping rule set.
    for generated_root in (diagnostics_root, blocks_root):
        if generated_root.exists():
            shutil.rmtree(generated_root)
    database = TrainingDatabase(root / "samples.sqlite3")
    database.clear_all_mappings()
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    blocks_root.mkdir(parents=True, exist_ok=True)
    source_renders_root.mkdir(parents=True, exist_ok=True)
    ensure_default_field_definitions(database, config.profile)
    all_sources = _files(Path(input_path))
    canonical_source_ids = {
        str(item.get("source_id") or "")
        for item in state.get("sources") or []
        if int(item.get("gt_count") or 0) > 0
    }
    # The input directory can contain the full archive while canonical GT only
    # covers the reviewed subset. Hash before decoding so unreviewed files do
    # not enter this source-specific mapping pass and produce misleading
    # "GT has no cells" errors.
    sources = [
        path for path in all_sources
        if hash_file(path)[:24] in canonical_source_ids
    ]
    LOGGER.info(
        "Mapping Studio: selected %d input source(s) with canonical GT out of %d available file(s).",
        len(sources), len(all_sources),
    )

    LOGGER.info(
        "Mapping Studio: canonical GT is authoritative (%d source(s), %d cell(s), revision %s); table-model inference is disabled.",
        int(state.get("source_count") or 0),
        int(state.get("gt_cell_count") or 0),
        str(gt.get("revision") or 0),
    )
    LOGGER.info(
        "Mapping Studio: fast path enabled; only relation-label thumbnails are materialized and mapping geometry is cached per source."
    )
    LOGGER.info("Mapping Studio: warming up full-page OCR only.")
    locator_engine.warmup()

    detected_sources = 0
    failed_sources = 0
    total_blocks = 0
    total_relations = 0
    total_suggestions = 0
    total_label_crops = 0

    for source_index, source in enumerate(sources, start=1):
        source_started = time.perf_counter()
        try:
            decode_started = time.perf_counter()
            LOGGER.info("Mapping source %d/%d: decoding input.", source_index, len(sources))
            decoded = load_input(source, config.dicom)
            height, width = decoded.image.shape[:2]
            decode_seconds = time.perf_counter() - decode_started

            ocr_started = time.perf_counter()
            LOGGER.info(
                "Mapping source %d/%d [%s]: full-page OCR.",
                source_index,
                len(sources),
                decoded.source_id,
            )
            batches = locator_engine.recognize_many([decoded.image])
            if len(batches) != 1:
                raise RuntimeError("Generic detector did not return one OCR result for one source")
            tokens = batches[0]
            ocr_seconds = time.perf_counter() - ocr_started

            structure_started = time.perf_counter()
            blocks, relations, detector_diagnostics = detect_generic_structure(
                decoded.source_id, decoded.image.shape, tokens
            )
            table_regions = canonical_table_regions(
                root,
                decoded.source_id,
                tokens,
                image_width=width,
                image_height=height,
            )
            gt_cell_count = sum(len(table.cells) for table in table_regions)
            LOGGER.info(
                "Mapping source %d/%d [%s]: OCR complete in %.2fs (%d token(s)); using %d canonical GT cell(s) in %d table/panel region(s).",
                source_index,
                len(sources),
                decoded.source_id,
                ocr_seconds,
                len(tokens),
                gt_cell_count,
                len(table_regions),
            )
            blocks, relations, structural = integrate_table_regions(
                decoded.source_id, blocks, relations, table_regions
            )
            relations, panel_context_by_table = _enrich_relations_with_panel_context(
                root,
                decoded.source_id,
                list(table_regions),
                list(relations),
            )
            if panel_context_by_table:
                LOGGER.info(
                    "Mapping source %d/%d [%s]: canonical panel context preserved for %d table(s): %s.",
                    source_index,
                    len(sources),
                    decoded.source_id,
                    len(panel_context_by_table),
                    ", ".join(sorted(set(panel_context_by_table.values()))),
                )
            blocks = mark_canonical_geometry(blocks)
            structure_seconds = time.perf_counter() - structure_started

            table_diagnostics = {
                "enabled": True,
                "provider": "canonical_table_cell_ground_truth",
                "engine_version": CANONICAL_MAPPING_GEOMETRY_VERSION,
                "model_inference": False,
                "active_table_model_loaded": False,
                "gt_revision": int(gt.get("revision") or 0),
                "semantic_panel_context": panel_context_by_table,
                "error": "",
                **structural,
            }
            detector_diagnostics["table_structure"] = table_diagnostics
            detector_diagnostics["block_count"] = len(blocks)
            detector_diagnostics["relation_count"] = len(relations)

            render_started = time.perf_counter()
            render_relative = Path("source_renders") / f"{decoded.source_id}.png"
            render_path = root / render_relative
            if not cv2.imwrite(str(render_path), decoded.image):
                raise RuntimeError(f"Could not save local source render: {render_path}")
            render_seconds = time.perf_counter() - render_started

            # Mapping Studio needs a detected thumbnail for relation labels. Value
            # images are served dynamically with ?mode=roi, and all other block
            # types are represented by source-image overlays. Materializing every
            # block used to produce 500-700 tiny PNG writes per source.
            crop_started = time.perf_counter()
            block_by_id = {block.block_id: block for block in blocks}
            label_crop_ids = {
                str(relation.label_block_id)
                for relation in relations
                if relation.label_block_id and str(relation.label_block_id) in block_by_id
            }
            crop_paths: dict[str, str] = {}
            if label_crop_ids:
                source_block_dir = blocks_root / decoded.source_id
                source_block_dir.mkdir(parents=True, exist_ok=True)
                for block_id in sorted(label_crop_ids):
                    block = block_by_id[block_id]
                    box = block.box.clamp(width, height)
                    crop = decoded.image[box.y1:box.y2, box.x1:box.x2]
                    if not crop.size:
                        continue
                    destination = source_block_dir / f"{block.block_id}.png"
                    if cv2.imwrite(str(destination), crop):
                        crop_paths[block_id] = destination.relative_to(root).as_posix()
            crop_seconds = time.perf_counter() - crop_started

            block_payloads: list[dict[str, object]] = []
            for block in blocks:
                payload = block.as_dict()
                payload["crop_path"] = crop_paths.get(block.block_id, "")
                block_payloads.append(payload)
            relation_payloads = [relation.as_dict() for relation in relations]

            db_started = time.perf_counter()
            database.replace_generic_detection(
                {
                    "source_id": decoded.source_id,
                    "image_width": width,
                    "image_height": height,
                    "render_path": render_relative.as_posix(),
                    "detector_version": GENERIC_DETECTOR_VERSION,
                    "token_count": detector_diagnostics.get("ocr_token_count", 0),
                },
                block_payloads,
                relation_payloads,
            )
            db_seconds = time.perf_counter() - db_started

            suggestion_started = time.perf_counter()
            suggestions = suggest_mappings_fast(database, decoded.source_id)
            suggestion_seconds = time.perf_counter() - suggestion_started

            diagnostics_started = time.perf_counter()
            study_info = extract_study_info(tokens)
            payload = {
                "schema_version": "2.3-canonical-gt-mapping-panel-aware",
                "source_id": decoded.source_id,
                "detector": detector_diagnostics,
                "study_info": study_info.as_dict(),
                "blocks": block_payloads,
                "relations": relation_payloads,
                "tables": [table.as_dict() for table in table_regions],
                "geometry_authority": "canonical_table_cell_ground_truth",
                "automatic_mapping_suggestions": len(suggestions),
                "materialized_label_crops": len(crop_paths),
                "semantic_panel_context": panel_context_by_table,
            }
            (diagnostics_root / f"{decoded.source_id}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            diagnostics_seconds = time.perf_counter() - diagnostics_started

            detected_sources += 1
            total_blocks += len(blocks)
            total_relations += len(relations)
            total_suggestions += len(suggestions)
            total_label_crops += len(crop_paths)
            total_seconds = time.perf_counter() - source_started
            LOGGER.info(
                "Mapping source %d/%d [%s]: complete in %.2fs; decode=%.2fs OCR=%.2fs structure=%.2fs render=%.2fs label-crops=%.2fs DB=%.2fs suggestions=%.2fs diagnostics=%.2fs; %d block(s), %d relation(s), %d label crop(s), %d mapping suggestion(s).",
                source_index,
                len(sources),
                decoded.source_id,
                total_seconds,
                decode_seconds,
                ocr_seconds,
                structure_seconds,
                render_seconds,
                crop_seconds,
                db_seconds,
                suggestion_seconds,
                diagnostics_seconds,
                len(blocks),
                len(relations),
                len(crop_paths),
                len(suggestions),
            )
        except Exception:
            failed_sources += 1
            LOGGER.exception("Mapping source %d/%d failed", source_index, len(sources))

    manifest = {
        "created_at": utc_now(),
        "flow": "generic_mapping_canonical_gt_fast_panel_aware",
        "detector_version": GENERIC_DETECTOR_VERSION,
        "geometry_authority": "canonical_table_cell_ground_truth",
        "geometry_version": CANONICAL_MAPPING_GEOMETRY_VERSION,
        "canonical_gt_revision": int(gt.get("revision") or 0),
        "canonical_gt_cells": int(state.get("gt_cell_count") or 0),
        "input_items": len(sources),
        "reviewed_input_items": max(0, int(state.get("source_count") or 0) - open_source_count),
        "skipped_open_gt_items": 0,
        "detected_sources": detected_sources,
        "failed_items": failed_sources,
        "detected_blocks": total_blocks,
        "proposed_relations": total_relations,
        "automatic_mapping_suggestions": total_suggestions,
        "materialized_label_crops": total_label_crops,
        "locator_engine": locator_engine.info(),
        "table_structure_engine": {
            "enabled": False,
            "provider": "canonical_table_cell_ground_truth",
            "reason": "Canonical GT is authoritative after the table-first gate; PP-Structure/RT-DETR inference is intentionally skipped.",
            "model_inference": False,
            "active_table_model_loaded": False,
        },
        "recognition_engine_reserved_for_mapping_stage": {
            "enabled": False,
            "reason": "Value recognition remains a later pipeline action after mappings are confirmed.",
        },
        "diagnostics": {
            "json_directory": "generic_detections",
            "block_crop_directory": "detected_blocks",
            "source_render_directory": "source_renders",
            "block_crop_policy": "relation_labels_only",
        },
        "privacy": {
            "source_filenames_stored": False,
            "dicom_identifiers_stored": False,
            "source_id": "first 24 hexadecimal characters of SHA-256 over source bytes",
        },
    }
    (root / "collection_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    LOGGER.info(
        "Mapping Studio preparation complete: %d/%d source(s) succeeded; failed=%d; label crops materialized=%d. No table-model inference was run.",
        detected_sources,
        len(sources),
        failed_sources,
        total_label_crops,
    )
    return manifest
