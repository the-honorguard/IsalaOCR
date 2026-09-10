from __future__ import annotations

import hashlib
import io
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import threading
import traceback
import uuid
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import cv2
from flask import Flask, Response, abort, flash, g, has_request_context, jsonify, redirect, render_template, request, send_file, stream_with_context, url_for

from ..config import load_config
from .db import TrainingDatabase, VALID_OCR_CONTENT_FILTERS
from .header_normalization import (
    build_header_normalization_model, canonical_screen_label, load_header_aliases,
)
from .dynamic_locator import normalize_for_matching
from .mapping import (
    build_mapping_output_preview, ensure_default_field_definitions,
    resolve_value_roi_box, suggest_mappings,
)
from .generic_detection import normalize_text
from .mapping_lateral import field_lateral_side, field_lateral_suffix, relation_lateral_side
from .relation_feedback import RELATION_FEEDBACK_REASONS
from .localization_dataset import (
    derived_detection_gate_state, localization_dataset_preview, localization_dataset_image_path, localization_evaluation_details,
    save_localization_split_config,
)
from .table_quality import table_first_quality
from .table_panels import load_panel_profile
from .table_cell_training import active_table_cell_model, table_cell_training_state
from .source_preview import prepare_source_renders
from .legacy_routes import register_legacy_routes
from .routes_detection_candidate import register_detection_candidate_routes
from .routes_home import register_home_routes
from .routes_jobs import register_job_routes
from .routes_documents import register_document_routes
from .routes_field_mapping_config import register_field_mapping_config_routes
from .routes_media import register_media_routes
from .routes_projects import register_project_routes
from .routes_roi_review import register_roi_review_routes
from .routes_sample_review import register_sample_review_routes
from .routes_status import register_status_routes
from .routes_table_panel_config import register_table_panel_config_routes
from .routes_table_panel_review import register_table_panel_review_routes
from .routes_value_review import register_value_review_routes
from .input_selection import input_file_key, input_file_source_id, input_files, selection_manifest_path, selection_payload
from .json_store import read_json as _read_json
from .table_cell_ground_truth import (
    add_ground_truth_cell, delete_ground_truth_cell, ensure_table_cell_ground_truth,
    ground_truth_counts, ground_truth_review_state, list_ground_truth_cells, list_ground_truth_sources,
    set_ground_truth_source_review_completed, update_ground_truth_cell,
)
from .table_region_ground_truth import list_table_regions, list_table_region_sources
from .table_semantics import load_assignments as load_table_semantic_assignments, suggest_table_name
from .table_model_comparison import (
    add_comparison_fp_to_ground_truth, review_comparison_issue, table_cell_comparison_state,
)
from .recognition_ground_truth import (
    recognition_gt_counts, recognition_scope_preview, save_recognition_scope,
    save_table_studio_roles, table_studio_roles, table_studio_rows,
)
from .projects import (
    DEFAULT_PROJECT_ID, DEFAULT_USE_CASE_ID, ProjectManager, load_use_case_templates,
    project_active_recognition_dir, resolve_project_registry,
)
DETECTION_REVIEW_REASONS = {
    "too_small": "Te klein",
    "too_large": "Te groot",
    "misplaced": "Verkeerd geplaatst",
    "false_positive": "Geen veld / false positive",
    "merged_fields": "Meerdere velden/cellen samengevoegd",
    "split_field": "Eén veld opgesplitst",
    "table_geometry_error": "Tabel/cel fout",
    "other": "Andere reden",
}
DETECTION_RELEVANCE_REASONS = {
    "date_time": "Datum/tijd",
    "ui_element": "UI-element",
    "reference_value": "Referentiewaarde",
    "graph_annotation": "Grafiekannotatie",
    "technical_overlay": "Technische overlay",
    "study_info_out_of_scope": "Patiënt-/studiegegeven buiten huidige scope",
    "other_out_of_scope": "Ander correct veld buiten huidige scope",
}

ACTIONS = {
    "1": "ALLE modellen en trainingsimages voorbereiden",
    "2": "Celdetectie uitvoeren",
    "60": "Volledige actieve DICOM-verwerkingspipeline",
    "5": "Localization-dataset bouwen (COCO)",
    "6": "Localization-dataset valideren",
    "7": "Field detector trainen op NVIDIA GPU",
    "8": "Field detector trainen op CPU",
    "9": "Huidige field detector evalueren",
    "10": "Baseline en getrainde field detector vergelijken",
    "11": "Field detector registreren en activeren",
    "12": "Fallback-detectie uitvoeren met actief field model",
    "13": "Detectiekwaliteitsrapport maken",
    "14": "Inference OCR- en tabelmodellen installeren",
    "15": "CPU detector / PicoDet-S stack installeren",
    "16": "GPU OCR-recognition stack installeren",
    "17": "GPU PaddleDetection / PicoDet-S stack installeren",
    "18": "PP-OCRv6 pretrained trainingsgewicht installeren",
    "19": "Voorbereidingsstatus opnieuw controleren",
    "30": "Inference-modelbestanden downloaden",
    "31": "CPU detector basisimage downloaden",
    "32": "GPU OCR basisimage downloaden",
    "33": "GPU detector basisimage downloaden",
    "34": "PP-OCRv6 pretrained gewicht downloaden",
    "35": "Inference runtime installeren",
    "36": "CPU detector stack bouwen",
    "37": "GPU OCR-recognition stack bouwen",
    "38": "GPU PaddleDetection stack bouwen",
    "39": "Pretrained gewicht installeren",
    "40": "Alle voorbereidingsdownloads parallel uitvoeren",
    "41": "Alle voorbereidingscomponenten installeren/bouwen",
    "42": "Inference-installatie controleren",
    "43": "CPU detector-installatie controleren",
    "44": "GPU OCR-installatie controleren",
    "45": "GPU PaddleDetection-installatie controleren",
    "46": "Pretrained gewicht controleren",
    "47": "Alle voorbereidingsinstallaties controleren",
    "48": "Table-cell trainingsdataset bouwen",
    "49": "Table-cell trainingsdataset valideren",
    "50": "Wireless table-cell detector trainen op GPU",
    "51": "Wireless table-cell detector trainen op CPU",
    "52": "Getraind table-cell model activeren",
    "53": "Stap 6 volledig uitvoeren (dataset, training, activatie en nieuwe celdetectie)",
    "54": "Tabelregio-dataset bouwen",
    "55": "Tabelregio-detector trainen op GPU",
    "56": "Tabelregio-detector trainen op CPU",
    "57": "Tabelregio-detector activeren",
    "60": "Stap 4 volledig uitvoeren (dataset, training en activatie)",
    "59": "Alleen tabelregio’s detecteren voor beoordeling",
    "20": "Mappinggegevens voorbereiden na detectiepoort",
    "21": "Nieuwe raster/celkaders toepassen op de bevestigde mappings",
    "22": "Waarden uit het nieuwe raster uitlezen",
    "58": "Nieuw raster toepassen en waarden uitlezen",
    "24": "Recognition-dataset bouwen en valideren",
    "25": "Recognition-dataset valideren",
    "26": "Recognition-model trainen",
    "27": "Recognition-model evalueren en vergelijken",
    "28": "Recognition-model registreren/activeren",
    # Backwards-compatible worker aliases kept for existing queued jobs.
    "107": "Legacy recognition-dataset bouwen",
    "108": "Legacy recognition-dataset valideren",
    "109": "Legacy baseline evalueren",
    "110": "Legacy recognition GPU-training",
    "111": "Legacy recognition CPU-training",
    "112": "Legacy recognition-model exporteren",
    "113": "Legacy custom recognition evalueren",
    "114": "Legacy recognition-modellen vergelijken",
    "115": "Legacy recognition-model registreren",
    "116": "Legacy recognition-model activeren",
}

# Approximate wall-clock durations shown next to workflow actions. These are
# deliberately ranges rather than promises: first-time downloads/builds, cache
# state, dataset size and GPU/CPU speed can change runtime substantially.
ACTION_DURATION_ESTIMATES = {
    "1": {"label": "± 20–60 min", "detail": "Volledige voorbereiding; eerste run en downloads kunnen langer duren."},
    "2": {"label": "± 2–10 min", "detail": "Afhankelijk van aantal bronnen/panelen en preprocessing-varianten."},
    "60": {"label": "± 1–5 min", "detail": "DICOM door actieve tabel-, mapping- en recognition-modellen naar één datablok."},
    "5": {"label": "± 10–60 sec", "detail": "Afhankelijk van het aantal gereviewde bronnen."},
    "6": {"label": "± 10–30 sec", "detail": "Dataset- en PaddleDetection-validatie."},
    "7": {"label": "± 5–20 min", "detail": "GPU-training; afhankelijk van dataset en GPU."},
    "8": {"label": "± 30–120 min", "detail": "CPU-training; sterk hardware-afhankelijk."},
    "9": {"label": "± 1–5 min", "detail": "Evaluatie over de vaste split."},
    "10": {"label": "± 1–5 min", "detail": "Baseline en getraind model vergelijken."},
    "11": {"label": "± 10–30 sec", "detail": "Model kopiëren, registreren en activeren."},
    "12": {"label": "± 2–10 min", "detail": "Afhankelijk van aantal bronnen."},
    "13": {"label": "± 5–30 sec", "detail": "Rapportage over bestaande evaluatieresultaten."},
    "14": {"label": "± 10–30 min", "detail": "Eerste keer; met gevulde caches meestal veel sneller."},
    "15": {"label": "± 5–20 min", "detail": "CPU detector/PicoDet stack installeren of bouwen."},
    "16": {"label": "± 10–30 min", "detail": "GPU OCR-recognition stack installeren of bouwen."},
    "17": {"label": "± 10–30 min", "detail": "GPU PaddleDetection stack installeren of bouwen."},
    "18": {"label": "± 1–5 min", "detail": "Pretrained recognition-gewicht installeren."},
    "19": {"label": "± 5–20 sec", "detail": "Alleen lokale status en aanwezige artifacts controleren."},
    "20": {"label": "± 10–60 sec", "detail": "Mappingvoorstellen opbouwen uit bestaande detecties."},
    "21": {"label": "± 10–60 sec", "detail": "Actuele raster/celkaders toepassen op bevestigde mappings."},
    "22": {"label": "± 1–10 min", "detail": "Afhankelijk van aantal crops en actief recognition-model."},
    "58": {"label": "± 2–11 min", "detail": "Nieuwe raster/celkaders toepassen en daarna de waarden uitlezen."},
    "24": {"label": "± 10–60 sec", "detail": "Recognition-dataset opbouwen uit goedgekeurde waarden."},
    "25": {"label": "± 10–30 sec", "detail": "Recognition-dataset valideren."},
    "26": {"label": "± 10–45 min", "detail": "Recognition-training; afhankelijk van dataset en GPU."},
    "27": {"label": "± 1–10 min", "detail": "Recognition-model evalueren op de vaste testset."},
    "28": {"label": "± 10–30 sec", "detail": "Recognition-model registreren/activeren."},
    "30": {"label": "± 2–10 min", "detail": "Netwerksnelheid en bestaande modelcache bepalen de duur."},
    "31": {"label": "± 1–5 min", "detail": "Basisimage downloaden; met Docker-cache vaak korter."},
    "32": {"label": "± 2–10 min", "detail": "GPU OCR basisimage downloaden; met cache vaak korter."},
    "33": {"label": "± 2–10 min", "detail": "GPU detector basisimage downloaden; met cache vaak korter."},
    "34": {"label": "± 1–5 min", "detail": "Pretrained gewicht downloaden; met cache vaak korter."},
    "35": {"label": "± 5–20 min", "detail": "Inference runtime bouwen/installeren; Docker-cache kan dit sterk verkorten."},
    "36": {"label": "± 5–20 min", "detail": "CPU detector stack bouwen; Docker-cache kan dit sterk verkorten."},
    "37": {"label": "± 10–30 min", "detail": "GPU OCR stack bouwen; Docker-cache kan dit sterk verkorten."},
    "38": {"label": "± 10–30 min", "detail": "GPU PaddleDetection stack bouwen; Docker-cache kan dit sterk verkorten."},
    "39": {"label": "± 10–60 sec", "detail": "Lokaal pretrained gewicht installeren."},
    "40": {"label": "± 5–20 min", "detail": "Downloads lopen parallel; netwerksnelheid/cache bepalen de duur."},
    "41": {"label": "± 15–45 min", "detail": "Alle install/build-componenten; met Docker-cache vaak sneller."},
    "42": {"label": "± 10–60 sec", "detail": "Inference/table runtime controleren."},
    "43": {"label": "± 10–60 sec", "detail": "CPU detector-installatie controleren."},
    "44": {"label": "± 10–60 sec", "detail": "GPU OCR-installatie controleren."},
    "45": {"label": "± 10–60 sec", "detail": "GPU PaddleDetection-installatie controleren."},
    "46": {"label": "± 5–20 sec", "detail": "Pretrained gewicht controleren."},
    "47": {"label": "± 30–90 sec", "detail": "Alle voorbereidingscomponenten controleren."},
    "48": {"label": "± 10–60 sec", "detail": "Table-cell COCO-dataset bouwen uit de canonieke Ground Truth."},
    "49": {"label": "± 10–30 sec", "detail": "Table-cell dataset valideren."},
    "50": {"label": "± 8–20 min", "detail": "Huidig small-reviewed profiel op GPU; dataset/GPU bepalen de werkelijke duur."},
    "51": {"label": "± 1–4 uur", "detail": "CPU-alternatief; sterk hardware- en dataset-afhankelijk."},
    "52": {"label": "± 10–30 sec", "detail": "Bestaand getraind table-cell model activeren; er wordt niet opnieuw getraind."},
    "53": {"label": "± 10–30 min", "detail": "Dataset bouwen → valideren → trainen → activeren → nieuwe celdetectie."},
    "54": {"label": "± 10–60 sec", "detail": "Volledige bronbeelden met Stap-2 tabelregio-GT naar COCO omzetten."},
    "55": {"label": "± 5–20 min", "detail": "PicoDet-S tabelregio-detector trainen op GPU."},
    "56": {"label": "± 30–120 min", "detail": "PicoDet-S tabelregio-detector trainen op CPU."},
    "57": {"label": "± 10–30 sec", "detail": "Een bestaand tabelregio-model als voorste detectorlaag activeren."},
    "60": {"label": "± 5–20 min", "detail": "Tabelregio-dataset bouwen → GPU-trainen → activeren."},
    # Legacy aliases remain annotated because older queued/retry jobs can surface in the UI.
    "107": {"label": "± 10–60 sec", "detail": "Legacy recognition-dataset bouwen."},
    "108": {"label": "± 10–30 sec", "detail": "Legacy recognition-dataset valideren."},
    "109": {"label": "± 1–5 min", "detail": "Legacy baseline-evaluatie."},
    "110": {"label": "± 10–45 min", "detail": "Legacy recognition GPU-training."},
    "111": {"label": "± 1–4 uur", "detail": "Legacy recognition CPU-training."},
    "112": {"label": "± 1–5 min", "detail": "Legacy recognition-model exporteren."},
    "113": {"label": "± 1–10 min", "detail": "Legacy custom recognition evalueren."},
    "114": {"label": "± 1–10 min", "detail": "Legacy recognition-modellen vergelijken."},
    "115": {"label": "± 10–30 sec", "detail": "Legacy recognition-model registreren."},
    "116": {"label": "± 10–30 sec", "detail": "Legacy recognition-model activeren."},
}

PROCESS_STEPS = [
    {"key": "detection-models","index":1,"group":"detection","title":"Voorbereiding","subtitle":"Controleer of PP-StructureV3 en de inference/table-modelcache beschikbaar zijn.","action_ids":["14","19","30","35","42"],"requirements":["Docker Desktop actief","Inference OCR + tabelmodellen lokaal beschikbaar","Tabelregio’s en tabelnamen worden in Stap 2 gedefinieerd","Geen detector-training nodig voor de table-first proef"]},
    {"key": "input-selection","index":"1A","group":"input","title":"Inputselectie","subtitle":"Bepaal welke bronafbeeldingen onderdeel worden van deze verwerkingsronde.","action_ids":[],"requirements":["Voorbereiding afgerond","Bestanden in de projectmap input","Alle gewenste afbeeldingen expliciet geselecteerd"]},
    {"key": "panel-setup","index":2,"group":"detection","title":"Tabelregio’s selecteren","subtitle":"Beoordeel per lezing de volledige tabelregio’s in de fullscreen reviewer en sla ze op als Ground Truth.","action_ids":[],"requirements":["Minimaal één bronpreview","Per lezing alle volledige tabellen omkaderen","Tabeldefinities en tabelregio-GT opslaan"]},
    {"key": "table-region-model","index":3,"group":"detection","title":"Tabelregio-model trainen","subtitle":"Train eerst een model dat volledige tabelregio’s automatisch leert vinden uit de GT van Stap 2.","action_ids":["54","55","56","57","60"],"requirements":["Tabelregio-GT opgeslagen in Stap 2","Dataset gebouwd en gevalideerd vóór training","Regio-model geactiveerd vóór de volgende detectie"]},
    {"key": "detect-candidates","index":4,"group":"detection","title":"Tabelregio’s detecteren en beoordelen","subtitle":"Draai alleen het actieve tabelregio-model. Beoordeel daarna de gevonden regio’s voordat er cellen worden gedetecteerd.","action_ids":["59"],"requirements":["Voorbereiding afgerond","Tabelregio-model getraind en geactiveerd","Bronnen in input"]},
    {"key": "detection-review","index":5,"group":"detection","title":"GT Studio","subtitle":"Beoordeel de celdetectie per bron en leg de canonieke cel-GT vast voor de celdetector.","action_ids":[],"requirements":["Tabelregio’s en cellen gedetecteerd","Bronrender","Per bron GT controleren en goedkeuren"]},
    {"key": "table-model","index":6,"group":"detection","title":"Celdetector trainen","subtitle":"Bouw uit de reviewcorrecties trainingsdata, train/activeer de celdetector en gebruik het nieuwe model in de volgende detectieronde.","action_ids":["48","49","50","51","52","53"],"requirements":["Afgeronde GT-review","Positieve functionele cellen","Dataset gebouwd en gevalideerd vóór training"]},
    {"key": "table-compare","index":None,"group":"tables","title":"Detectorafwijkingen reviewen","subtitle":"Optionele technische vergelijking van een nieuwe detectorrun met de vaste Ground Truth.","action_ids":[],"requirements":["Canonieke Ground Truth uit Stap 5","Table-cell dataset uit Stap 6","Nieuwe detectierun uit Stap 4"]},
    {"key": "table-quality","index":8,"group":"tables","title":"Tabelstudio","subtitle":"Maak vanuit de getrainde celdetector het rij-kolomraster en bepaal welke bezette rastercellen naar Recognition gaan.","action_ids":[],"requirements":["Celdetector getraind en opnieuw gedraaid","Goedgekeurde celposities"]},

    {"key": "recognition-gt-studio","index":10,"group":"value","title":"Recognition GT Studio","subtitle":"Controleer de Recognition-tekst uit de bestaande cellen en keur de trainingsvoorbeelden goed.","action_ids":[],"requirements":["Tabelstudio afgerond","Recognition-samples beschikbaar"]},

    # The previous loose field/PicoDet workflow is intentionally parked. Routes,
    # artifacts and jobs stay available so nothing is deleted, but they are no
    # longer part of the primary table-first sequence.
    {"key": "localization-dataset","index":None,"group":"fallback","title":"Losse box-detector trainen","subtitle":"Geparkeerde fallback: bouw/valideer de oude localization-dataset en train PicoDet.","action_ids":["5","6","7","8"],"requirements":["Alleen gebruiken als table-first coverage onvoldoende blijkt"]},
    {"key": "localization-evaluate","index":None,"group":"fallback","title":"Box-detector evalueren","subtitle":"Geparkeerde fallback-evaluatie voor een getrainde field detector.","action_ids":["9","10"],"requirements":["Getrainde fallback-detector"]},
    {"key": "localization-register","index":None,"group":"fallback","title":"Box-detector activeren","subtitle":"Activeer een fallback-detector alleen wanneer de table-first pipeline daar aantoonbaar baat bij heeft.","action_ids":["11"],"requirements":["Geslaagde fallback-evaluatie"]},
    {"key": "redetect","index":None,"group":"fallback","title":"Detecteren met fallback-model","subtitle":"Legacy/fallback detectierun met een actief field-detector-model.","action_ids":["12"],"requirements":["Actief fallback-model"]},
    {"key": "detection-report","index":None,"group":"fallback","title":"Box-detector kwaliteitsrapport","subtitle":"Legacy/fallback Detection Gate rapport.","action_ids":["13"],"requirements":["Localization-evaluatie"]},

    {"key": "mapping","index":13,"group":"value","title":"Mapping Studio","subtitle":"Pas pas ná Recognition optioneel functionele betekenis toe op betrouwbare cellen.","action_ids":["20"],"requirements":["Recognition-output","Betrouwbare celgeometrie","Functioneel veldschema"]},
    {"key": "apply-mapping","index":14,"group":"value","title":"Application output","subtitle":"Pas de actuele raster/celkaders toe en lees daarna automatisch de waarden uit met het actieve recognition-model.","action_ids":["58"],"requirements":["Bevestigde mappings","Actuele raster/celgeometrie","Actief recognition-model"]},
    {"key": "value-review","index":15,"group":"value","title":"Waarden beoordelen","subtitle":"Beoordeel uitsluitend OCR-inhoud; raster- en celgeometrie wordt hier niet meer aangepast.","action_ids":[],"requirements":["Uitgelezen waarden"]},
    {"key": "recognition-dataset","index":11,"group":"value","title":"Recognition Model Factory","subtitle":"Bouw, train, beoordeel en activeer het Recognition-model vanuit één pagina.","action_ids":["24","26","27","28"],"requirements":["Goedgekeurde Recognition-GT-samples"]},
    {"key": "recognition-output-review","index":12,"group":"value","title":"Recognition Model Review","subtitle":"Controleer de modeluitvoer alleen-lezen tegen de vaste Recognition-GT.","action_ids":[],"requirements":["Recognition Model Factory afgerond","Vaste Recognition-testset"]},
    {"key": "recognition-train","index":None,"group":"value","title":"Recognition-model trainen · legacy","subtitle":"Legacy-route; gebruik de gecombineerde Recognition Model Factory.","action_ids":["26"],"requirements":["Gevalideerde recognition-dataset"]},
    {"key": "recognition-evaluate","index":None,"group":"value","title":"Recognition-model beoordelen · legacy","subtitle":"Legacy-route; gebruik de gecombineerde Recognition Model Factory.","action_ids":["27"],"requirements":["Getraind/exporteerbaar recognition-model"]},
    {"key": "recognition-models","index":None,"group":"value","title":"Recognition-model activeren · legacy","subtitle":"Legacy-route; gebruik de gecombineerde Recognition Model Factory.","action_ids":["28"],"requirements":["Recognition-evaluatie"]},
    {"key": "artifacts","index":None,"group":"system","title":"Data & modellen","subtitle":"Beheer datasets, modellen, evaluaties en trainingsruns.","action_ids":[],"requirements":[]},
    {"key": "system-checks","index":None,"group":"system","title":"Systeemcontroles","subtitle":"Controleer Docker, caches, permissies, database en beide pipelines.","action_ids":[],"requirements":[]},
    {"key": "maintenance","index":None,"group":"system","title":"Onderhoud","subtitle":"Veilige opruim- en herstelacties.","action_ids":[],"requirements":[]},
]
PROCESS_STEP_BY_KEY = {step["key"]: step for step in PROCESS_STEPS}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _latest_file(root: Path, name: str) -> Path | None:
    candidates = [p for p in root.glob(f"**/{name}") if p.is_file()]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _optional_confidence(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    parsed = float(value)
    if parsed < 0 or parsed > 1:
        raise ValueError("Confidence must be between 0 and 1")
    return parsed


def _filter_args() -> dict[str, str | None]:
    if not request.args:
        return {
            "status": "pending", "field": None, "min_confidence": None,
            "max_confidence": "0.8", "ocr_content": "text",
        }
    return {
        "status": request.args.get("status") or None,
        "field": request.args.get("field") or None,
        "min_confidence": request.args.get("min_confidence") or None,
        "max_confidence": request.args.get("max_confidence") or None,
        "ocr_content": request.args.get("ocr_content") or "all",
    }


def create_web_app(
    workspace: str | Path,
    *,
    models_root: str | Path = "/models",
    output_root: str | Path = "/output",
    project_root: str | Path = "/project",
    config_path: str | Path = "/app/config/app.yaml",
) -> Flask:
    base_root = Path(workspace).resolve()
    models = Path(models_root).resolve()
    output = Path(output_root).resolve()
    project = Path(project_root).resolve()
    base_root.mkdir(parents=True, exist_ok=True)
    project_manager = ProjectManager(base_root)
    use_case_templates = load_use_case_templates(Path(config_path).resolve().parent)
    use_case_ids = {str(item.get("use_case_id")) for item in use_case_templates}

    def workspace_root() -> Path:
        return project_manager.active_workspace()

    class ActiveProjectDatabase:
        """Lazy per-project database proxy.

        The previous implementation constructed a new TrainingDatabase for every
        method lookup. Besides opening SQLite repeatedly, that also reran schema
        initialization on every web request. Keep exactly one initialized handle
        for the active project and rotate it only when the project changes.
        """

        def __init__(self) -> None:
            self._project_id: str | None = None
            self._database: TrainingDatabase | None = None

        @property
        def path(self) -> Path:
            if self._database is not None and self._project_id == project_manager.active_project_id():
                return self._database.path
            return project_manager.active_workspace() / "samples.sqlite3"

        def invalidate(self) -> None:
            self._project_id = None
            self._database = None

        def _db(self) -> TrainingDatabase:
            context = project_manager.active()
            path = context.workspace / "samples.sqlite3"
            if self._database is None or self._project_id != context.project_id or self._database.path != path:
                db = TrainingDatabase(path)
                if header_profile is not None and context.use_case_id == DEFAULT_USE_CASE_ID:
                    ensure_default_field_definitions(db, header_profile)
                self._project_id = context.project_id
                self._database = db
            return self._database

        def __getattr__(self, name: str):
            return getattr(self._db(), name)

    database = ActiveProjectDatabase()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=os.environ.get("ISALA_WEBUI_SECRET", "local-only-isalaocr"),
        # Static URLs carry ?v=<app version>, so they can be cached aggressively
        # without stale CSS/JS after an upgrade. Dynamic image routes override
        # max_age explicitly and are unaffected.
        SEND_FILE_MAX_AGE_DEFAULT=31536000,
    )
    app_version = (project / "VERSION").read_text(encoding="utf-8").strip() if (project / "VERSION").is_file() else "unknown"

    def request_cached(key: str, factory):
        """Memoize expensive helpers for the lifetime of one HTTP request."""
        if not has_request_context():
            return factory()
        cache = getattr(g, "_isala_request_cache", None)
        if cache is None:
            cache = {}
            g._isala_request_cache = cache
        if key not in cache:
            cache[key] = factory()
        return cache[key]

    try:
        loaded_config = load_config(config_path)
        header_profile = loaded_config.profile
    except Exception:
        loaded_config = None
        header_profile = None
    if header_profile is not None:
        ensure_default_field_definitions(database._db(), header_profile)

    def localization_settings() -> dict[str, Any]:
        if loaded_config is None:
            return {}
        return dict(loaded_config.raw.get("training", {}).get("localization", {}) or {})

    def localization_strategy() -> str:
        return str(localization_settings().get("strategy") or "fusion").strip().lower()

    def localization_gate_thresholds() -> dict[str, Any]:
        return dict(localization_settings().get("gate", {}) or {})

    def table_first_thresholds() -> dict[str, float]:
        settings = dict(localization_settings().get("table_first", {}) or {})
        return {
            "minimum_direct_coverage": float(settings.get("minimum_direct_coverage", 0.95)),
            "maximum_false_candidate_rate": float(settings.get("maximum_false_candidate_rate", 0.10)),
            "maximum_adjustment_rate": float(settings.get("maximum_adjustment_rate", 0.25)),
        }

    def table_panel_state() -> dict[str, Any]:
        profile = load_panel_profile(workspace_root())
        definitions = list(profile.get("definitions") or [])
        panels = list(profile.get("panels") or [])
        positioned_ids = {str(item.get("panel_id") or "") for item in panels}
        missing_definitions = [
            item for item in definitions if str(item.get("panel_id") or "") not in positioned_ids
        ]
        # When project-wide panel names are configured, every named panel must
        # have geometry before the table pipeline is considered configured.
        configured = bool(panels) and (not definitions or not missing_definitions)
        updated_at = str(profile.get("updated_at") or "")
        sources = database.list_detection_sources() if configured else []
        current = False
        if configured and sources and updated_at:
            try:
                profile_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if profile_time.tzinfo is None:
                    profile_time = profile_time.replace(tzinfo=timezone.utc)
                current = all(
                    bool(str(item.get("detected_at") or "")) and
                    datetime.fromisoformat(str(item.get("detected_at")).replace("Z", "+00:00")) >= profile_time
                    for item in sources
                )
            except (TypeError, ValueError):
                current = False
        return {
            "profile": profile,
            "configured": configured,
            "definitions_configured": bool(definitions),
            "definition_count": len(definitions),
            "panel_count": len(panels),
            "missing_panel_count": len(missing_definitions),
            "missing_definitions": missing_definitions,
            "detection_current": current,
            "needs_rerun": configured and bool(sources) and not current,
        }

    def _record_webui_error(scope: str, exc: BaseException, *, target_workspace: Path | None = None) -> str:
        """Persist a local diagnostic without letting diagnostics break the UI again."""
        reference = f"webui-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        try:
            root = Path(target_workspace).resolve() if target_workspace is not None else workspace_root()
            root.mkdir(parents=True, exist_ok=True)
            log_path = root / "webui_errors.log"
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{_utcnow()}] {reference} {scope}\n")
                handle.write(f"{type(exc).__name__}: {exc}\n")
                handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                handle.write("\n")
        except Exception:
            pass
        return reference

    def _path_signature(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    _detection_gate_cache: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    _detection_gate_cache_lock = threading.Lock()

    def _detection_gate_signature(root: Path) -> tuple[Any, ...]:
        db_path = root / "samples.sqlite3"
        pointer = root / "localization_datasets" / "latest.txt"
        dataset_id = ""
        try:
            dataset_id = pointer.read_text(encoding="utf-8-sig").strip() if pointer.is_file() else ""
        except OSError:
            dataset_id = ""
        manifest = root / "localization_datasets" / dataset_id / "manifest.json" if dataset_id else root / ".no-localization-manifest"
        return (
            _path_signature(db_path),
            _path_signature(Path(str(db_path) + "-wal")),
            _path_signature(pointer),
            dataset_id,
            _path_signature(manifest),
        )

    def _safe_detection_gate(
        target_workspace: Path | None = None, *, target_db: TrainingDatabase | None = None
    ) -> dict[str, Any]:
        """Derived gate state must never be able to take down the web interface.

        v3.9.1 moved the derived gate into the global template context. That made a
        malformed/legacy evaluation capable of turning every HTML route into a 500.
        Pipeline B remains fail-closed, but the UI stays available and exposes a
        diagnostic reference.
        """
        root = Path(target_workspace).resolve() if target_workspace is not None else workspace_root()
        try:
            return derived_detection_gate_state(root, thresholds=localization_gate_thresholds())
        except Exception as exc:
            reference = _record_webui_error("derived_detection_gate_state", exc, target_workspace=root)
            fallback: dict[str, Any] = {}
            try:
                fallback_db = target_db if target_db is not None else TrainingDatabase(root / "samples.sqlite3")
                fallback = fallback_db.detection_gate()
            except Exception:
                fallback = {}
            return {
                **fallback,
                "ready": False,
                "state": "error",
                "reason": (
                    "Detection Gate kon niet veilig worden herberekend. Pipeline B blijft geblokkeerd; "
                    f"diagnostiek: {reference}."
                ),
                "evaluation_id": str(fallback.get("evaluation_id") or ""),
                "model_id": "",
                "failures": [f"{type(exc).__name__}: {exc}"],
                "fingerprint_current": False,
                "calculation_error": {
                    "reference": reference,
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }

    def current_detection_gate() -> dict[str, Any]:
        # Fingerprinting the localization ground truth can be relatively expensive.
        # Cache it across requests and invalidate on SQLite WAL/database or dataset changes.
        def load() -> dict[str, Any]:
            root = workspace_root()
            key = str(root)
            signature = _detection_gate_signature(root)
            with _detection_gate_cache_lock:
                cached = _detection_gate_cache.get(key)
                if cached is not None and cached[0] == signature:
                    return dict(cached[1])
            result = _safe_detection_gate(root)
            with _detection_gate_cache_lock:
                _detection_gate_cache[key] = (signature, dict(result))
                while len(_detection_gate_cache) > 8:
                    _detection_gate_cache.pop(next(iter(_detection_gate_cache)))
            return result

        return request_cached("current_detection_gate", load)

    def navigation_detection_gate() -> dict[str, Any]:
        """Cheap persisted gate state for navigation chrome only.

        Gate-sensitive routes still call current_detection_gate(), which derives and
        fingerprints the authoritative state before allowing Pipeline B.
        """
        def load() -> dict[str, Any]:
            try:
                return database.detection_gate()
            except Exception:
                return {"ready": False, "state": "unknown"}
        return request_cached("navigation_detection_gate", load)

    def canonical_gt_quality_state() -> dict[str, Any]:
        """Canonical-GT readiness after the first reviewed table-cell dataset.

        Once canonical GT exists, new Step-3 candidates are model predictions,
        not a second Ground-Truth review queue.  Their differences belong in
        Step 7.  Reusing detection_candidates.review_completed here made every
        retraining round reopen hundreds of invisible Step-4 candidates.
        """
        review = ground_truth_review_state(workspace_root())
        sources = []
        for item in review.get("sources") or []:
            gt_count = int(item.get("gt_count") or 0)
            sources.append({
                "source_id": str(item.get("source_id") or ""),
                "review_completed": bool(item.get("review_completed")),
                "candidate_total": gt_count,
                "pending": 0 if bool(item.get("review_completed")) else 1,
                "correct": gt_count,
                "adjusted": 0, "rejected": 0, "reconstructed": 0, "manual_added": 0,
                "direct_coverage": 1.0 if gt_count else 0.0,
                "structural_coverage": 1.0 if gt_count else 0.0,
            })
        source_count = int(review.get("source_count") or 0)
        open_sources = int(review.get("open_source_count") or 0)
        gt_cells = int(review.get("gt_cell_count") or 0)
        ready = bool(source_count and gt_cells and open_sources == 0)
        if not source_count or not gt_cells:
            state = "no_ground_truth"
            title = "Canonieke Ground Truth ontbreekt"
            summary = "Er is nog geen bruikbare canonieke table-cell Ground Truth."
            next_step = "Ga naar Stap 5 en leg de gewenste cellen vast."
        elif open_sources:
            state = "canonical_gt_needs_review"
            title = "Ground Truth-controle nog niet afgerond"
            summary = (
                f"{open_sources} van {source_count} bronafbeelding(en) moeten nog expliciet als GT-gecontroleerd worden gemarkeerd. "
                "Nieuwe modelpredictions tellen hier niet als open kandidaten; die beoordeel je in Stap 7."
            )
            next_step = "Open Stap 5 · GT Studio, controleer de bron en kies GT goedkeuren."
        else:
            state = "canonical_gt_ready"
            title = "Canonieke Ground Truth is volledig gecontroleerd"
            summary = (
                f"Alle {source_count} bronafbeeldingen zijn als GT-gecontroleerd gemarkeerd; de canonieke GT bevat {gt_cells} cellen. "
                "Een nieuwe Stap-4-run wijzigt deze status niet. Modelverschillen worden uitsluitend in Stap 7 beoordeeld."
            )
            next_step = "Gebruik Stap 7 voor de actuele modelvergelijking of Stap 6 voor een volgende trainingsdataset."
        return {
            "strategy": "table_first", "canonical_ground_truth": True,
            "ready": ready, "state": state, "tone": "success" if ready else "warning",
            "title": title, "summary": summary, "reason": summary, "next_step": next_step,
            "sources": sources,
            "totals": {
                "candidate_total": gt_cells, "pending": open_sources, "correct": gt_cells,
                "adjusted": 0, "rejected": 0, "reconstructed": 0, "manual_added": 0,
                "desired_total": gt_cells, "detected_desired": gt_cells,
                "direct_coverage": 1.0 if gt_cells else 0.0,
                "structural_coverage": 1.0 if gt_cells else 0.0,
                "fallback_need": 0.0, "adjustment_rate": 0.0, "false_candidate_rate": 0.0,
                "source_count": source_count, "completed_source_count": source_count - open_sources,
                "open_source_count": open_sources,
            },
            "thresholds": table_first_thresholds(),
        }


    def current_table_first_quality() -> dict[str, Any]:
        def load() -> dict[str, Any]:
            # After the first frozen dataset, Step 4 is canonical GT management.
            # Do not reopen the raw candidate-review gate on every new model run.
            if ensure_table_cell_ground_truth(workspace_root()) is not None:
                return canonical_gt_quality_state()
            panel_state = table_panel_state()
            if not panel_state.get("configured"):
                return {
                    "strategy": "table_first", "ready": False, "state": "panels_missing", "tone": "warning",
                    "title": "Stel eerst de table-panels in",
                    "reason": "De table-pipeline heeft nog geen door jou gekozen resultaatpanelen.",
                    "summary": "Stel in Stap 2 de volledige tabelregio’s in voordat Stap 3 draait.",
                    "next_step": "Open Stap 2 · Tabelregio’s selecteren.",
                    "sources": [], "totals": {}, "thresholds": table_first_thresholds(),
                }
            if panel_state.get("needs_rerun"):
                return {
                    "strategy": "table_first", "ready": False, "state": "panel_detection_stale", "tone": "warning",
                    "title": "Voer de table-detectie opnieuw uit",
                    "reason": "Het panelprofiel is nieuwer dan de huidige cell-detectie.",
                    "summary": "Voer Stap 4 opnieuw uit na een wijziging in Stap 2.",
                    "next_step": "Voer Stap 4 · Tabelregio’s en cellen detecteren opnieuw uit.",
                    "sources": [], "totals": {}, "thresholds": table_first_thresholds(),
                }
            try:
                return table_first_quality(database, **table_first_thresholds())
            except Exception as exc:
                reference = _record_webui_error("table_first_quality", exc)
                return {
                    "strategy": "table_first", "ready": False, "state": "error", "tone": "warning",
                    "title": "Table-first status kon niet worden berekend",
                    "reason": f"Diagnostiek: {reference}.",
                    "summary": f"Diagnostiek: {reference}.",
                    "next_step": "Open Stap 5 en controleer of de panelgerichte tabelanalyse/reviewdata aanwezig is.",
                    "sources": [], "totals": {}, "thresholds": table_first_thresholds(),
                }
        return request_cached("current_table_first_quality", load)

    def table_review_counts(source_id: str | None = None, quality: dict[str, Any] | None = None) -> dict[str, int]:
        """Review counters scoped to the current table-first detection pass.

        Legacy/manual field-detector annotations are intentionally preserved in
        SQLite, but they must not inflate the new table-cell experiment after a
        fresh Step-2 run. table_first_quality only counts manual additions created
        after the current source's detected_at timestamp.
        """
        quality = quality or current_table_first_quality()
        items = quality.get("sources") or []
        if source_id is not None:
            items = [item for item in items if str(item.get("source_id")) == str(source_id)]
        def total(key: str) -> int:
            return sum(int(item.get(key) or 0) for item in items)
        candidate_total = total("candidate_total")
        correct = total("correct")
        adjusted = total("adjusted")
        rejected = total("rejected")
        irrelevant = total("irrelevant")
        added = total("added")
        pending = total("pending")
        relevant = total("detected_desired")
        positive = relevant + added
        reviewed = correct + adjusted + rejected
        return {
            "correct": correct, "adjusted": adjusted, "rejected": rejected,
            "relevant": relevant, "irrelevant": irrelevant, "added": added,
            "candidate_total": candidate_total, "candidate_reviewed": reviewed,
            "pending": pending, "positive": positive, "negative": rejected,
            "ignored": rejected, "persistent": added,
            "total_reviews": reviewed + added,
        }

    def canonical_table_gt_mode() -> bool:
        return localization_strategy() == "table_first" and ensure_table_cell_ground_truth(workspace_root()) is not None

    def step4_review_counts(source_id: str | None = None) -> dict[str, int]:
        if canonical_table_gt_mode():
            return ground_truth_counts(workspace_root(), source_id)
        return table_review_counts(source_id) if localization_strategy() == "table_first" else database.detection_review_counts(source_id)

    def current_pipeline_gate() -> dict[str, Any]:
        """Authoritative geometry gate for the currently selected localization strategy."""
        if localization_strategy() == "table_first":
            quality = current_table_first_quality()
            return {
                **quality,
                "gate_label": "TABLE-FIRST CHECK",
                "evaluation_id": "",
            }
        gate = current_detection_gate()
        return {**gate, "gate_label": "DETECTION GATE"}

    def current_recognition_gate() -> dict[str, Any]:
        counts = recognition_gt_counts(database)
        accepted = int(counts.get("accepted") or 0)
        ready = accepted > 0
        summary = (
            f"{accepted} goedgekeurde Recognition-GT-samples beschikbaar. Alleen deze samples worden in de Recognition Dataset opgenomen."
            if ready else "Er zijn nog geen goedgekeurde Recognition-GT-samples beschikbaar."
        )
        return {
            "ready": ready,
            "state": "recognition_gt_ready" if ready else "recognition_gt_missing",
            "tone": "success" if ready else "warning",
            "gate_label": "RECOGNITION GT CHECK",
            "reason": summary,
            "summary": summary,
            "next_step": "Bouw de Recognition Dataset uit de goedgekeurde samples." if ready else "Open Recognition GT Studio en keur eerst minimaal één sample goed.",
        }

    def navigation_pipeline_gate() -> dict[str, Any]:
        if localization_strategy() == "table_first":
            # The table quality helper uses bulk aggregate SQL only and is cheap
            # enough for navigation chrome; request_cached keeps it single-shot.
            return current_pipeline_gate()
        return {**navigation_detection_gate(), "gate_label": "DETECTION GATE"}

    def header_model_path() -> Path:
        return workspace_root() / "header_normalization" / "model.json"
    locator_label_threshold = (
        float(header_profile.dynamic_extraction.get("label_match_threshold", 0.72))
        if header_profile is not None else 0.72
    )

    def load_field_ranges() -> dict[str, tuple[float | None, float | None]]:
        try:
            import yaml
            config_file = Path(config_path)
            config_payload = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            profile_file = Path(str(config_payload.get("profile", "")))
            if not profile_file.is_absolute():
                profile_file = config_file.parent / profile_file
            profile_payload = yaml.safe_load(profile_file.read_text(encoding="utf-8")) or {}
            result = {}
            for field in profile_payload.get("fields", []):
                limits = field.get("range") or [None, None]
                result[str(field.get("key"))] = (limits[0], limits[1])
            return result
        except Exception:
            return {}

    field_ranges = load_field_ranges()

    def value_in_configured_range(sample: dict[str, Any]) -> bool:
        limits = field_ranges.get(str(sample.get("field_key")))
        if limits is None:
            return False
        match = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(sample.get("raw_ocr", "")))
        if match is None:
            return False
        try:
            value = float(match.group(0).replace(",", "."))
        except ValueError:
            return False
        minimum, maximum = limits
        return (minimum is None or value >= float(minimum)) and (maximum is None or value <= float(maximum))

    jobs_root = base_root / "webui" / "jobs"
    for name in ("pending", "running", "completed", "failed", "status", "logs"):
        (jobs_root / name).mkdir(parents=True, exist_ok=True)

    def enqueue_job(
        action_id: str,
        options: dict[str, Any] | None = None,
        *,
        action_name: str | None = None,
    ) -> dict[str, Any]:
        if action_id not in ACTIONS:
            raise ValueError(f"Unknown action: {action_id}")
        job_id = f"job-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        payload = {
            "job_id": job_id,
            "action_id": action_id,
            "action_name": str(action_name or ACTIONS[action_id]),
            "project_id": project_manager.active_project_id(),
            "project_name": project_manager.active().name,
            "options": options or {},
            "status": "pending",
            "progress_percent": 0,
            "progress_mode": "indeterminate",
            "progress_label": "In wachtrij",
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        temporary = jobs_root / "pending" / f"{job_id}.json.tmp"
        final = jobs_root / "pending" / f"{job_id}.json"
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(final)
        (jobs_root / "status" / f"{job_id}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return payload

    def enqueue_artifact_delete_job(
        kind: str, artifact_id: str, *, cascade: bool = False, replacement_dataset_id: str = ""
    ) -> dict[str, Any]:
        kind = str(kind or "").strip().lower()
        artifact_id = str(artifact_id or "").strip()
        if kind not in {"dataset", "model", "evaluation", "run"}:
            raise ValueError("Onbekend artifacttype")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", artifact_id):
            raise ValueError("Ongeldig artifact-ID")
        replacement_dataset_id = str(replacement_dataset_id or "").strip()
        if replacement_dataset_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", replacement_dataset_id):
            raise ValueError("Ongeldig vervangend dataset-ID")
        for item in job_statuses(1000, job_type="artifact_delete"):
            if str(item.get("status") or "") not in {"pending", "running"}:
                continue
            options = item.get("options") if isinstance(item.get("options"), dict) else {}
            if str(options.get("kind") or "") == kind and str(options.get("id") or "") == artifact_id:
                return item
        job_id = f"job-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        payload = {
            "job_id": job_id,
            "job_type": "artifact_delete",
            "action_id": "",
            "action_name": f"Verwijder {kind}: {artifact_id}",
            "project_id": project_manager.active_project_id(),
            "project_name": project_manager.active().name,
            "options": {
                "kind": kind,
                "id": artifact_id,
                "cascade": bool(cascade),
                "replacement_dataset_id": replacement_dataset_id,
            },
            "status": "pending",
            "progress_percent": 0,
            "progress_mode": "indeterminate",
            "progress_label": "Verwijderen in wachtrij",
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        temporary = jobs_root / "pending" / f"{job_id}.json.tmp"
        final = jobs_root / "pending" / f"{job_id}.json"
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(final)
        (jobs_root / "status" / f"{job_id}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return payload

    def safe_workspace_file(relative: str | Path) -> Path:
        root = workspace_root()
        path = (root / relative).resolve()
        if path != root and root not in path.parents:
            abort(404)
        return path

    _render_image_cache: dict[str, tuple[tuple[int, int], Any]] = {}
    _render_image_cache_lock = threading.Lock()

    def cached_render_image(path: Path) -> Any:
        """Decode a recent source render once and reuse it for crop endpoints."""
        try:
            stat = path.stat()
        except OSError:
            return None
        signature = (stat.st_mtime_ns, stat.st_size)
        key = str(path)
        with _render_image_cache_lock:
            cached = _render_image_cache.get(key)
            if cached is not None and cached[0] == signature:
                return cached[1]
            import cv2
            image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if image is None:
                return None
            _render_image_cache.pop(key, None)
            _render_image_cache[key] = (signature, image)
            while len(_render_image_cache) > 2:
                _render_image_cache.pop(next(iter(_render_image_cache)))
            return image

    def source_rows() -> list[dict[str, Any]]:
        with database.connect() as db:
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
        result=[]
        for row in rows:
            item=dict(row)
            item["render_exists"]=(workspace_root()/"source_renders"/f"{item['source_id']}.png").is_file()
            result.append(item)
        return result

    def source_samples(source_id: str) -> list[dict[str, Any]]:
        with database.connect() as db:
            rows=db.execute(
                "SELECT * FROM samples WHERE source_id=? ORDER BY roi_y1, roi_x1, field_key",
                (source_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def source_study_info(source_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        diagnostics = _read_json(workspace_root() / "collection_diagnostics" / f"{source_id}.json", {})
        info = diagnostics.get("study_info") if isinstance(diagnostics, dict) else None
        if not isinstance(info, dict):
            return None, []
        rows = [
            {"key": "heart_rate_bpm", "label": "Hartfrequentie", "value": info.get("heart_rate_bpm"), "unit": "bpm"},
            {"key": "bsa_m2", "label": "BSA", "value": info.get("bsa_m2"), "unit": "m²"},
            {"key": "bsa_method", "label": "BSA-methode", "value": info.get("bsa_method"), "unit": ""},
            {"key": "height_m", "label": "Lengte", "value": info.get("height_m"), "unit": "m"},
            {"key": "weight_kg", "label": "Gewicht", "value": info.get("weight_kg"), "unit": "kg"},
            {"key": "gender", "label": "Geslacht", "value": info.get("gender"), "unit": ""},
        ]
        raw_values = info.get("raw_values") if isinstance(info.get("raw_values"), dict) else {}
        confidence = info.get("field_confidence") if isinstance(info.get("field_confidence"), dict) else {}
        validity = info.get("valid") if isinstance(info.get("valid"), dict) else {}
        for row in rows:
            row["raw"] = raw_values.get(row["key"], "")
            row["confidence"] = confidence.get(row["key"])
            row["valid"] = validity.get(row["key"], row["value"] is not None)
        return info, rows

    def roi_review_counts() -> dict[str, int]:
        with database.connect() as db:
            rows = db.execute(
                "SELECT roi_review_status, COUNT(*) AS amount FROM samples WHERE extraction_method<>'mapped_generic_stale' GROUP BY roi_review_status"
            ).fetchall()
        counts = {"pending": 0, "correct": 0, "incorrect": 0, "deferred": 0}
        for row in rows:
            counts[str(row["roi_review_status"])] = int(row["amount"])
        counts["total"] = sum(counts.values())
        return counts

    def header_review_counts() -> dict[str, int]:
        counts = database.header_review_counts()
        counts["reviewed"] = counts.get("accepted", 0) + counts.get("rejected", 0)
        counts["open"] = counts.get("pending", 0) + counts.get("deferred", 0)
        counts["unavailable"] = max(0, database.counts().get("total", 0) - counts.get("total", 0))
        return counts

    def header_field_options() -> list[dict[str, Any]]:
        if header_profile is None:
            return []
        return [
            {
                "field_key": field.key,
                "field_label": field.label,
                "panel": field.panel,
                "canonical_label": canonical_screen_label(field),
            }
            for field in header_profile.fields
        ]

    def header_model_info() -> dict[str, Any] | None:
        payload = _read_json(header_model_path())
        if not isinstance(payload, dict):
            return None
        payload = dict(payload)
        payload["path"] = str(header_model_path().relative_to(workspace_root()))
        payload["active_alias_fields"] = len(load_header_aliases(header_model_path(), header_profile)) if header_profile else 0
        return payload

    def header_review_samples(
        status: str = "pending",
        *,
        source_id: str = "",
        sample_id: str = "",
        extraction_method: str = "all",
    ) -> list[dict[str, Any]]:
        rows = database.list_header_samples(status=status, limit=2000)
        if source_id:
            rows = [row for row in rows if str(row.get("source_id") or "") == source_id]
        if sample_id:
            rows = [row for row in rows if str(row.get("sample_id") or "") == sample_id]
        if extraction_method == "fallback":
            rows = [row for row in rows if str(row.get("extraction_method") or "") in {"fixed_fallback", "fixed_roi"}]
        elif extraction_method == "dynamic":
            rows = [row for row in rows if str(row.get("extraction_method") or "").startswith("dynamic_")]
        fields = {item["field_key"]: item for item in header_field_options()}
        for row in rows:
            target_key = str(row.get("header_target_field_key") or row.get("field_key") or "")
            target = fields.get(target_key) or fields.get(str(row.get("field_key") or ""))
            row["target_field_key"] = target_key
            row["target_canonical_label"] = target.get("canonical_label") if target else row.get("field_label")
            raw_header_text = str(row.get("locator_label_text") or "")
            row["raw_header_text"] = raw_header_text
            row["normalized_header_text"] = normalize_for_matching(raw_header_text)
            row["display_exact_label"] = str(row.get("header_exact_label") or row["target_canonical_label"] or "")
            row["default_review_status"] = (
                "accepted" if str(row.get("header_review_status") or "pending") == "pending"
                else str(row.get("header_review_status"))
            )
        return rows

    def value_review_counts() -> dict[str, int]:
        """Return value-review counts for the current mapped application output."""
        with database.connect() as db:
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

    def value_source_rows() -> list[dict[str, Any]]:
        """Group only current mapped samples for the value-review step."""
        with database.connect() as db:
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

    def value_source_samples(source_id: str) -> list[dict[str, Any]]:
        with database.connect() as db:
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

    def latest_dataset() -> str | None:
        pointer=workspace_root()/"datasets"/"latest.txt"
        if not pointer.is_file(): return None
        try: return pointer.read_text(encoding="utf-8").strip().lstrip("\ufeff") or None
        except OSError: return None

    def latest_progress(device: str | None = None) -> dict[str, Any] | None:
        path=_latest_file(workspace_root()/"runs", "training-progress.json")
        payload=_read_json(path) if path else None
        if isinstance(payload,dict):
            requested_device = str(device or "").strip().lower()
            recorded_device = str(payload.get("device") or "").strip().lower()
            if requested_device and recorded_device != requested_device:
                return None
            payload["path"]=str(path.relative_to(workspace_root()))
        return payload

    def latest_comparison() -> dict[str, Any] | None:
        path=_latest_file(workspace_root()/"runs", "comparison.json")
        payload=_read_json(path) if path else None
        if isinstance(payload,dict): payload["path"]=str(path.relative_to(workspace_root()))
        return payload

    _registry_state_cache: dict[str, tuple[tuple[Any, ...], list[dict[str, Any]], dict[str, Any] | None]] = {}
    _registry_state_cache_lock = threading.Lock()

    def registry_state() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        def load() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
            registry_root = resolve_project_registry(base_root.parent / "registry", base_root)
            registry_file = registry_root / "registry.json"
            active_file = registry_root / "active.json"
            signature = (_path_signature(registry_file), _path_signature(active_file))
            key = str(registry_root)
            with _registry_state_cache_lock:
                cached = _registry_state_cache.get(key)
                if cached is not None and cached[0] == signature:
                    return [dict(item) for item in cached[1]], dict(cached[2]) if cached[2] is not None else None
            index = _read_json(registry_file, {"models": []})
            active = _read_json(active_file)
            items = list(reversed(index.get("models", []))) if isinstance(index, dict) else []
            active_item = active if isinstance(active, dict) else None
            with _registry_state_cache_lock:
                _registry_state_cache[key] = (signature, [dict(item) for item in items], dict(active_item) if active_item is not None else None)
                while len(_registry_state_cache) > 8:
                    _registry_state_cache.pop(next(iter(_registry_state_cache)))
            return items, active_item
        return request_cached("registry_state", load)


    def latest_dataset_info() -> dict[str, Any] | None:
        dataset_id = latest_dataset()
        if not dataset_id:
            return None
        directory = workspace_root() / "datasets" / dataset_id
        manifest = _read_json(directory / "manifest.json", {})
        if not isinstance(manifest, dict):
            manifest = {}
        return {
            "dataset_id": dataset_id,
            "path": str(directory.relative_to(workspace_root())) if directory.exists() else f"datasets/{dataset_id}",
            "exists": directory.is_dir(),
            "manifest": manifest,
            "original_samples": manifest.get("original_samples", {}),
            "samples": manifest.get("samples_including_augmentation", {}),
            "field_counts": manifest.get("field_counts", {}),
            "created_at": manifest.get("created_at"),
        }

    def latest_validation() -> dict[str, Any] | None:
        path = _latest_file(workspace_root() / "runs", "charset_report.json")
        payload = _read_json(path) if path else None
        if isinstance(payload, dict):
            payload["path"] = str(path.relative_to(workspace_root()))
            return payload
        return None

    def latest_evaluations() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Return latest baseline/custom evaluations after one runs-tree scan."""
        candidates = [p for p in (workspace_root() / "runs").glob("**/evaluation.json") if p.is_file()]

        def latest_for(kind: str) -> dict[str, Any] | None:
            matches = [p for p in candidates if f"evaluation-{kind}" in p.parent.name.lower()]
            if not matches:
                return None
            path = max(matches, key=lambda p: p.stat().st_mtime)
            payload = _read_json(path)
            if isinstance(payload, dict):
                payload["path"] = str(path.relative_to(workspace_root()))
                return payload
            return None

        return latest_for("baseline"), latest_for("custom")

    def latest_export_info() -> dict[str, Any] | None:
        candidates = [p for p in (workspace_root() / "runs").glob("**/exported") if p.is_dir()]
        if not candidates:
            return None
        directory = max(candidates, key=lambda p: p.stat().st_mtime)
        files = [p for p in directory.rglob("*") if p.is_file()]
        return {
            "path": str(directory.relative_to(workspace_root())),
            "file_count": len(files),
            "total_bytes": sum(p.stat().st_size for p in files),
            "updated_at": datetime.fromtimestamp(directory.stat().st_mtime, timezone.utc).isoformat(),
        }

    def preparation_info() -> dict[str, Any]:
        status_file = models / "preparation_status.json"
        host_status = _read_json(status_file, {}) if status_file.is_file() else {}
        host_components = host_status.get("components", {}) if isinstance(host_status, dict) else {}
        if not isinstance(host_components, dict):
            host_components = {}
        inventory = host_status.get("inventory", {}) if isinstance(host_status, dict) else {}
        if not isinstance(inventory, dict):
            inventory = {}

        checked_at_raw = str(host_status.get("checked_at") or "") if isinstance(host_status, dict) else ""
        snapshot_age_seconds: float | None = None
        if checked_at_raw:
            try:
                checked_at = datetime.fromisoformat(checked_at_raw.replace("Z", "+00:00"))
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
                snapshot_age_seconds = max(0.0, (datetime.now(timezone.utc) - checked_at.astimezone(timezone.utc)).total_seconds())
            except ValueError:
                snapshot_age_seconds = None
        # preparation_status.json is a host-side inventory snapshot. A WebUI or
        # Docker restart does not change the model inventory, so a three-minute
        # wall-clock expiry made a valid preparation look broken on every later
        # restart. The explicit preparation/check actions remain the authority
        # when files, images or the runtime actually change.
        status_fresh = snapshot_age_seconds is not None and snapshot_age_seconds <= 86400.0

        definitions = [
            ("inference", "Inference OCR + tabelmodellen", "PP-OCRv6 en PP-Structure modelcache voor offline inferentie.", "14", "30", "35", "42"),
            ("cpu_detection", "CPU detector / PicoDet-S", "CPU training stack en PicoDet-S localization-baseline.", "15", "31", "36", "43"),
            ("gpu_recognition", "GPU OCR-recognition", "NVIDIA recognition-training image zonder PaddleDetection.", "16", "32", "37", "44"),
            ("gpu_detection", "GPU PaddleDetection / PicoDet-S", "NVIDIA detector-image met PaddleDetection.", "17", "33", "38", "45"),
            ("pretrained", "PP-OCRv6 pretrained gewicht", "Officieel medium recognition-gewicht voor fine-tuning.", "18", "34", "39", "46"),
        ]

        def normalized_phase(raw: Any) -> dict[str, Any]:
            expected = [str(item) for item in raw.get("expected", [])] if isinstance(raw, dict) and isinstance(raw.get("expected"), list) else []
            if not status_fresh:
                return {
                    "ready": None,
                    "state": "unknown",
                    "detail": "Status is verouderd; actuele host-inventarisatie wordt uitgevoerd.",
                    "expected": expected,
                }
            if not isinstance(raw, dict):
                return {"ready": None, "state": "unknown", "detail": "Nog niet gecontroleerd", "expected": []}
            ready = raw.get("ready")
            state = str(raw.get("state") or ("ready" if ready is True else "missing" if ready is False else "unknown"))
            if state not in {"ready", "missing", "unknown"}:
                state = "unknown"
            return {
                "ready": ready if isinstance(ready, bool) else None,
                "state": state,
                "detail": str(raw.get("detail") or ""),
                "expected": expected,
            }

        components = []
        for key, title, description, full_id, download_id, install_id, check_id in definitions:
            raw = host_components.get(key, {}) if isinstance(host_components, dict) else {}
            if not isinstance(raw, dict):
                raw = {}
            download = normalized_phase(raw.get("download"))
            install = normalized_phase(raw.get("install"))
            components.append({
                "key": key,
                "title": str(raw.get("title") or title),
                "description": str(raw.get("description") or description),
                "files": [str(item) for item in raw.get("files", [])] if isinstance(raw.get("files"), list) else [],
                "download": download,
                "install": install,
                "full_action_id": str(raw.get("full_action_id") or full_id),
                "download_action_id": str(raw.get("download_action_id") or download_id),
                "install_action_id": str(raw.get("install_action_id") or install_id),
                "check_action_id": str(raw.get("check_action_id") or check_id),
                "ready": download["ready"] is True and install["ready"] is True,
                "model_entries": (
                    [
                        {"name": "PP-OCRv6 small detection", "purpose": "Tekstgebieden detecteren"},
                        {"name": "PP-OCRv6 small recognition", "purpose": "Tekst in gevonden gebieden herkennen"},
                        {"name": "PP-StructureV3 layout", "purpose": "Document- en schermindeling herkennen"},
                        {"name": "PP-StructureV3 table", "purpose": "Tabelstructuur herkennen"},
                        {"name": "PP-StructureV3 cell", "purpose": "Celgeometrie binnen tabellen herkennen"},
                        {"name": "PP-OCRv6 medium baseline", "purpose": "Baseline voor Recognition-vergelijking"},
                    ] if key == "inference" else []
                ),
            })

        all_downloads_ready = all(item["download"]["ready"] is True for item in components)
        all_installs_ready = all(item["install"]["ready"] is True for item in components)
        all_ready = all_downloads_ready and all_installs_ready
        unknown_count = sum(
            1 for item in components for phase in (item["download"], item["install"])
            if phase["state"] == "unknown"
        )
        return {
            "ready": all_ready,
            "model_file_count": int(inventory.get("model_file_count") or 0),
            "weight_file_count": int(inventory.get("weight_file_count") or 0),
            "model_bytes": int(inventory.get("model_bytes") or 0),
            "components": components,
            "component_count": len(components),
            "ready_count": sum(item["ready"] for item in components),
            "download_ready_count": sum(item["download"]["ready"] is True for item in components),
            "install_ready_count": sum(item["install"]["ready"] is True for item in components),
            "unknown_count": unknown_count,
            "all_downloads_ready": all_downloads_ready,
            "all_installs_ready": all_installs_ready,
            "all_ready": all_ready,
            "status_checked_at": host_status.get("checked_at") if isinstance(host_status, dict) else None,
            "status_fresh": status_fresh,
            "status_stale": not status_fresh,
            "snapshot_age_seconds": snapshot_age_seconds,
            "training_image_version": host_status.get("training_image_version") if isinstance(host_status, dict) else None,
            "status_snapshot_exists": status_file.is_file(),
        }

    def preparation_for_current_strategy() -> dict[str, Any]:
        """Return preparation status scoped to what the active workflow actually needs.

        In table-first mode only the inference/table component is a prerequisite.
        Keeping the global 5-component counters here made a fully ready table pipeline
        look like a detector-training setup and was especially confusing on Step 1.
        """
        prep = dict(preparation_info())
        if localization_strategy() != "table_first":
            return prep

        components = [
            item for item in prep.get("components", [])
            if item.get("key") == "inference"
        ]
        all_downloads_ready = bool(components) and all(
            item.get("download", {}).get("ready") is True for item in components
        )
        all_installs_ready = bool(components) and all(
            item.get("install", {}).get("ready") is True for item in components
        )
        all_ready = all_downloads_ready and all_installs_ready
        prep.update({
            "components": components,
            "component_count": len(components),
            "ready_count": sum(bool(item.get("ready")) for item in components),
            "download_ready_count": sum(
                item.get("download", {}).get("ready") is True for item in components
            ),
            "install_ready_count": sum(
                item.get("install", {}).get("ready") is True for item in components
            ),
            "unknown_count": sum(
                1
                for item in components
                for phase in (item.get("download", {}), item.get("install", {}))
                if phase.get("state") == "unknown"
            ),
            "all_downloads_ready": all_downloads_ready,
            "all_installs_ready": all_installs_ready,
            "all_ready": all_ready,
            "ready": all_ready,
            "scope": "table_first",
            "scope_label": "Table pipeline",
        })
        return prep

    def input_source_count() -> int:
        input_root = Path("/input")
        if not input_root.is_dir():
            return 0
        ignored = {".ini", ".yaml", ".yml", ".json", ".txt", ".log", ".gitkeep"}
        return sum(
            1 for item in input_root.rglob("*")
            if item.is_file() and item.suffix.lower() not in ignored and item.name != ".gitkeep"
        )

    def mapped_sample_state() -> dict[str, int]:
        return database.mapped_sample_counts()

    def current_localization_dataset(localization_datasets: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Resolve the localization dataset from latest.txt, the canonical pointer.

        The database ordering is useful for history, but it must never disagree
        with training preflight about which immutable loc-* dataset is current.
        """
        pointer = workspace_root() / "localization_datasets" / "latest.txt"
        if not pointer.is_file():
            return None
        try:
            dataset_id = pointer.read_text(encoding="utf-8-sig").strip()
        except OSError:
            return None
        if not dataset_id:
            return None
        for item in localization_datasets:
            if str(item.get("dataset_id") or "") == dataset_id:
                return item
        dataset_root = workspace_root() / "localization_datasets" / dataset_id
        manifest = _read_json(dataset_root / "manifest.json", None)
        if not isinstance(manifest, dict):
            return {
                "dataset_id": dataset_id,
                "path": f"localization_datasets/{dataset_id}",
                "image_count": 0,
                "annotation_count": 0,
                "negative_image_count": 0,
                "splits": {},
                "manifest": {},
            }
        return {
            "dataset_id": dataset_id,
            "path": str(manifest.get("path") or f"localization_datasets/{dataset_id}"),
            "image_count": int(manifest.get("image_count") or 0),
            "annotation_count": int(manifest.get("annotation_count") or 0),
            "negative_image_count": int(manifest.get("negative_image_count") or 0),
            "splits": manifest.get("splits") if isinstance(manifest.get("splits"), dict) else {},
            "manifest": manifest,
            "created_at": manifest.get("created_at"),
        }

    def localization_dataset_readiness_state(
        localization_datasets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Read only the files required to determine localization training readiness."""
        datasets = localization_datasets if localization_datasets is not None else database.list_localization_datasets()
        loc_dataset = current_localization_dataset(datasets)
        validation = None
        paddlex_validation = None
        ready_marker = None
        split_current = False
        dataset_id = str(loc_dataset.get("dataset_id") or "") if loc_dataset else ""
        if loc_dataset:
            dataset_root = workspace_root() / str(loc_dataset.get("path") or "")
            validation = _read_json(dataset_root / "validation.json", None)
            paddlex_validation = _read_json(
                dataset_root / "paddlex_validation" / "isala_paddlex_validation.json", None
            )
            ready_marker = _read_json(dataset_root / "training_ready.json", None)
            manifest = _read_json(dataset_root / "manifest.json", {})
            source_splits = manifest.get("source_splits") if isinstance(manifest, dict) else None
            split_manifest_ready = isinstance(source_splits, dict) and bool(source_splits)
            split_current = split_manifest_ready and not (
                workspace_root() / "localization_split_pending.flag"
            ).is_file()
        app_valid = bool(
            validation
            and validation.get("status") == "ok"
            and str(validation.get("dataset_id") or "") == dataset_id
        )
        paddlex_dataset_id = ""
        if isinstance(paddlex_validation, dict):
            try:
                paddlex_dataset_id = Path(str(paddlex_validation.get("dataset") or "").rstrip("/\\")).name
            except (TypeError, ValueError):
                paddlex_dataset_id = ""
        paddlex_valid = bool(
            paddlex_validation
            and (paddlex_validation.get("status") == "ok" or paddlex_validation.get("ok") is True)
            and paddlex_dataset_id == dataset_id
        )
        ready_marker_valid = bool(
            ready_marker
            and ready_marker.get("status") == "ok"
            and ready_marker.get("ready") is True
            and str(ready_marker.get("dataset_id") or "") == dataset_id
        )
        training_ready = bool(loc_dataset is not None and app_valid and paddlex_valid and split_current)
        return {
            "localization_dataset": loc_dataset,
            "localization_validation": validation,
            "localization_paddlex_validation": paddlex_validation,
            "localization_training_ready_marker": ready_marker,
            "localization_ready_marker_valid": ready_marker_valid,
            "localization_dataset_id": dataset_id,
            "localization_app_valid": app_valid,
            "localization_paddlex_valid": paddlex_valid,
            "localization_split_current": split_current,
            "localization_training_ready": training_ready,
        }

    def process_snapshot() -> dict[str, Any]:
        """Lean workflow snapshot for the overview page.

        Keep this deliberately limited to fields rendered by home.html/pipeline_state;
        expensive artifact scans and schema lists belong to their dedicated pages.
        """
        _, active = registry_state()
        dataset = latest_dataset_info()
        validation = latest_validation()
        baseline, custom = latest_evaluations()
        progress = latest_progress()
        prep = preparation_info()
        roi = roi_review_counts()
        value = value_review_counts()
        detection_sources = database.list_detection_sources()
        region_sources = list_table_region_sources(workspace_root()) if localization_strategy() == "table_first" else []
        region_by_source = {str(item.get("source_id") or ""): item for item in region_sources}
        region_gt_complete = bool(detection_sources) and all(
            bool(region_by_source.get(str(source.get("source_id") or ""), {}).get("review_completed"))
            and bool(region_by_source.get(str(source.get("source_id") or ""), {}).get("region_count"))
            for source in detection_sources
        )
        detection_reviews = step4_review_counts()
        localization_datasets = database.list_localization_datasets()
        localization_evaluations = database.list_localization_evaluations()
        localization_models = database.list_localization_models()
        active_localization_model = database.active_localization_model()
        detection_gate = current_detection_gate() if localization_strategy() != "table_first" else {"ready": False, "state": "parked", "reason": "Losse box-detector staat geparkeerd in table-first mode."}
        pipeline_gate = current_pipeline_gate()
        table_quality_state = current_table_first_quality() if localization_strategy() == "table_first" else None
        table_model_state = table_cell_training_state(workspace_root()) if localization_strategy() == "table_first" else {}
        panel_state = table_panel_state() if localization_strategy() == "table_first" else {"configured": True, "detection_current": True, "panel_count": 0}
        input_state = input_selection_state()
        mapping = database.mapping_counts()
        mapped = mapped_sample_state()
        loc_state = localization_dataset_readiness_state(localization_datasets)
        loc_dataset = loc_state["localization_dataset"]
        localization_training_ready = bool(loc_state["localization_training_ready"])
        loc_baseline = next((item for item in localization_evaluations if item.get("kind") == "baseline"), None)
        loc_trained = next((item for item in localization_evaluations if item.get("kind") == "trained"), None)
        loc_comparison = _read_json(workspace_root() / "localization_evaluations" / "latest_comparison.json", None)
        inference_component = next((item for item in prep.get("components", []) if item.get("key") == "inference"), {})
        preparation_ready = bool(inference_component.get("ready")) if localization_strategy() == "table_first" else bool(prep["ready"])
        readiness = {
            "detection-models": preparation_ready,
            # A saved checkbox manifest alone is not enough: Step 2 needs the
            # selected input to have gone through the initial source scan so a
            # real source render is available for drawing table regions.
            "input-selection": bool(input_state.get("has_manifest"))
                and bool(input_state.get("selected"))
                and bool(detection_sources),
            # Step 2 is complete when every selected source has saved region
            # GT. The old project-wide panel profile is not this workflow's
            # source of truth anymore.
            "panel-setup": region_gt_complete,
            # Region GT is the input to Step 3; completion requires an
            # explicitly activated trained region model.
            "table-region-model": bool(_read_json(workspace_root() / "table_region_models" / "active.json", None)),
            "detect-candidates": bool(detection_sources) and all(
                bool(database.list_detection_table_geometry(str(source.get("source_id") or "")).get("regions"))
                for source in detection_sources
            ),
            "detection-review": (
                canonical_table_gt_mode()
                or bool(detection_reviews.get("candidate_total", 0) > 0)
                or (bool(detection_sources) and all(
                    bool(database.list_detection_table_geometry(str(source.get("source_id") or "")).get("regions"))
                    for source in detection_sources
                ))
            ),
            "table-quality": bool((table_model_state.get("active_model") or {}).get("model_id")),
            "table-model": bool((table_model_state.get("active_model") or {}).get("model_id")),
            "table-compare": bool((table_model_state.get("active_model") or {}).get("model_id")) and bool(table_model_state.get("dataset")) and bool(panel_state.get("detection_current")),
            "localization-dataset": bool(localization_models),
            "localization-evaluate": loc_baseline is not None or loc_trained is not None,
            "localization-compare": loc_comparison is not None,
            "localization-register": active_localization_model is not None,
            "redetect": active_localization_model is not None,
            "detection-report": bool(localization_evaluations),
            "mapping": pipeline_gate.get("ready", False) and mapping.get("confirmed", 0) > 0,
            "apply-mapping": mapped.get("total", 0) > 0,
            "value-extract": mapped.get("recognized", 0) > 0,
            "value-review": value.get("total", 0) > 0 and value.get("pending", 0) == 0,
            "recognition-gt-studio": int(recognition_gt_counts(database).get("accepted") or 0) > 0,
            "recognition-dataset": dataset is not None and bool(dataset.get("exists")),
            "recognition-train": progress is not None,
            "recognition-evaluate": baseline is not None or custom is not None,
            "recognition-models": active is not None,
            "recognition-output-review": baseline is not None and custom is not None,
            "system-checks": True,
            "maintenance": True,
        }
        return {
            "active": active, "dataset": dataset, "validation": validation,
            "baseline": baseline, "custom": custom, "progress": progress,
            "preparation": prep, "readiness": readiness, "roi": roi, "value": value,
            "detection_sources": detection_sources, "detection_reviews": detection_reviews,
            "localization_dataset": loc_dataset,
            "localization_training_ready": localization_training_ready,
            "localization_evaluations": localization_evaluations,
            "localization_baseline": loc_baseline, "localization_trained": loc_trained,
            "localization_comparison": loc_comparison, "localization_models": localization_models,
            "active_localization_model": active_localization_model,
            "detection_gate": detection_gate, "pipeline_gate": pipeline_gate,
            "table_quality": table_quality_state, "table_model": table_model_state, "table_panels": panel_state, "mapping": mapping, "mapped": mapped,
        }

    def worker_state() -> dict[str, Any]:
        payload = _read_json(jobs_root / "worker.json", {})
        if not isinstance(payload, dict):
            payload = {}
        heartbeat = str(payload.get("heartbeat_at") or payload.get("started_at") or "")
        age_seconds: float | None = None
        if heartbeat:
            try:
                parsed = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                age_seconds = max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
            except ValueError:
                age_seconds = None
        payload["online"] = age_seconds is not None and age_seconds <= 15
        payload["heartbeat_age_seconds"] = age_seconds
        return payload

    _job_file_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
    _job_file_cache_lock = threading.Lock()

    def _cached_job_payload(path: Path, fallback_status: str = "pending") -> dict[str, Any] | None:
        signature = _path_signature(path)
        if signature is None:
            return None
        key = str(path)
        with _job_file_cache_lock:
            cached = _job_file_cache.get(key)
            if cached is not None and cached[0] == signature:
                return dict(cached[1])
        payload = _read_json(path)
        if not isinstance(payload, dict):
            return None
        payload = dict(payload)
        payload["job_id"] = str(payload.get("job_id") or path.stem)
        payload.setdefault("status", fallback_status)
        with _job_file_cache_lock:
            _job_file_cache[key] = (signature, dict(payload))
            if len(_job_file_cache) > 4096:
                for stale_key in list(_job_file_cache)[:1024]:
                    _job_file_cache.pop(stale_key, None)
        return payload

    def job_statuses(
        limit: int = 20, *, action_ids: set[str] | None = None, job_type: str | None = None
    ) -> list[dict[str, Any]]:
        # status/ is canonical. Cache parsed JSON by file signature so frequent UI
        # polling mostly performs cheap stat() calls instead of reparsing history.
        merged: dict[str, dict[str, Any]] = {}
        status_root = jobs_root / "status"
        status_paths = list(status_root.glob("*.json"))
        for path in status_paths:
            payload = _cached_job_payload(path)
            if payload is not None:
                merged[str(payload["job_id"])] = payload

        # Compatibility fallback for legacy jobs without a canonical status file.
        # Parsed legacy files are cached too, so keeping this compatibility is cheap.
        for folder, fallback_status in (
            ("pending", "pending"), ("running", "running"),
            ("completed", "completed"), ("failed", "failed"),
        ):
            for path in (jobs_root / folder).glob("*.json"):
                if path.stem in merged:
                    continue
                payload = _cached_job_payload(path, fallback_status)
                if payload is not None:
                    merged[str(payload["job_id"])] = payload

        active_project_id = project_manager.active_project_id()
        items = [
            item for item in merged.values()
            if str(item.get("project_id") or DEFAULT_PROJECT_ID) == active_project_id
        ]
        if action_ids is not None:
            wanted = {str(action_id) for action_id in action_ids}
            items = [item for item in items if str(item.get("action_id") or "") in wanted]
        if job_type is not None:
            items = [item for item in items if str(item.get("job_type") or "") == str(job_type)]
        # Queue order is based on creation time. Using updated_at made older
        # jobs jump around whenever their worker status/log snapshot changed.
        items.sort(key=lambda x: (str(x.get("created_at") or ""), str(x.get("job_id") or "")), reverse=True)
        items = items[:max(0, int(limit))]

        needs_training_progress = any(
            str(item.get("status") or "") == "running" and str(item.get("action_id") or "") == "26"
            for item in items
        )
        progress_by_device: dict[str, dict[str, Any] | None] = {}
        if needs_training_progress:
            for item in items:
                if str(item.get("status") or "") != "running" or str(item.get("action_id") or "") != "26":
                    continue
                options = item.get("options") if isinstance(item.get("options"), dict) else {}
                device = str(options.get("device") or "").strip().lower()
                if device not in progress_by_device:
                    progress_by_device[device] = latest_progress(device)
        log_root = jobs_root / "logs"
        for item in items:
            status = str(item.get("status", "pending"))
            default_percent = 100.0 if status in {"completed", "failed"} else 0.0
            try:
                percent = float(item.get("progress_percent") if item.get("progress_percent") is not None else default_percent)
            except (TypeError, ValueError):
                percent = default_percent
            progress_mode = str(item.get("progress_mode") or ("determinate" if status in {"completed", "failed"} else "indeterminate"))
            label = str(item.get("progress_label") or {
                "pending": "In wachtrij",
                "running": "Wordt uitgevoerd · live uitvoer actief",
                "completed": "Voltooid",
                "failed": "Mislukt",
            }.get(status, status))
            options = item.get("options") if isinstance(item.get("options"), dict) else {}
            device = str(options.get("device") or "").strip().lower()
            progress = progress_by_device.get(device)
            if status == "running" and str(item.get("action_id")) == "26" and isinstance(progress, dict):
                percent = float(progress.get("progress_percent") or percent)
                progress_mode = "determinate"
                epoch = progress.get("epoch")
                total = progress.get("total_epochs")
                if epoch is not None and total is not None:
                    label = f"Epoch {epoch}/{total} · ETA {progress.get('eta') or '--'}"
            stdout_path = log_root / f"{item['job_id']}.log"
            if status == "running" and progress_mode != "determinate" and stdout_path.is_file():
                try:
                    log_tail = stdout_path.read_text(encoding="utf-8-sig", errors="replace")[-65536:]
                    stages = re.findall(r"(?m)^\s*\[(\d+)\s*/\s*(\d+)\]\s*(.+?)\s*$", log_tail)
                    if stages:
                        current_raw, total_raw, stage_label = stages[-1]
                        current_stage, total_stages = int(current_raw), int(total_raw)
                        if total_stages > 0:
                            percent = current_stage / total_stages * 100.0
                            progress_mode = "determinate"
                            label = stage_label.strip().rstrip(".")
                except OSError:
                    pass
            item["progress_percent"] = max(0.0, min(100.0, percent))
            item["progress_mode"] = progress_mode
            item["progress_label"] = label
            stderr_path = log_root / f"{item['job_id']}.log.err"
            worker_log_path = log_root / f"{item['job_id']}.worker.log"
            item["stdout_bytes"] = stdout_path.stat().st_size if stdout_path.is_file() else 0
            item["stderr_bytes"] = stderr_path.stat().st_size if stderr_path.is_file() else 0
            item["worker_log_bytes"] = worker_log_path.stat().st_size if worker_log_path.is_file() else 0
            item["has_log"] = any(value > 0 for value in (
                item["stdout_bytes"], item["stderr_bytes"], item["worker_log_bytes"]
            ))
        return items

    def localization_readiness_payload() -> dict[str, Any]:
        """Small canonical localization state used by both legacy and React clients."""
        state = localization_dataset_readiness_state()
        dataset = state.get("localization_dataset") or {}
        validation = state.get("localization_validation") or {}
        marker = state.get("localization_training_ready_marker") or {}
        splits = dataset.get("splits") if isinstance(dataset, dict) else {}
        if not isinstance(splits, dict):
            splits = {}

        def split_images(name: str) -> int:
            item = splits.get(name) or {}
            try:
                return int(item.get("images") or 0) if isinstance(item, dict) else 0
            except (TypeError, ValueError):
                return 0

        train_images = split_images("train")
        if train_images <= 0:
            training_profile = {
                "name": "onbekend", "epochs": 0, "batch_size": 0, "learning_rate": 0.0,
                "warmup_steps": 0, "eval_interval": 0, "steps_per_epoch": 0,
                "estimated_optimizer_steps": 0, "sanity_check": False, "warning": "",
            }
        elif train_images <= 32:
            steps_per_epoch = max(1, (train_images + 1) // 2)
            training_profile = {
                "name": "kleine dataset", "epochs": 150, "batch_size": 2, "learning_rate": 0.005,
                "warmup_steps": 20, "eval_interval": 5, "steps_per_epoch": steps_per_epoch,
                "estimated_optimizer_steps": steps_per_epoch * 150, "sanity_check": True,
                "warning": f"Slechts {train_images} onafhankelijke trainingsbeelden; eerst wordt automatisch een 2-beeld sanity-overfit check uitgevoerd.",
            }
        elif train_images <= 128:
            steps_per_epoch = max(1, (train_images + 7) // 8)
            training_profile = {
                "name": "middelgrote dataset", "epochs": 100, "batch_size": 8, "learning_rate": 0.02,
                "warmup_steps": 50, "eval_interval": 5, "steps_per_epoch": steps_per_epoch,
                "estimated_optimizer_steps": steps_per_epoch * 100, "sanity_check": False, "warning": "",
            }
        else:
            steps_per_epoch = max(1, (train_images + 15) // 16)
            training_profile = {
                "name": "standaard", "epochs": 80, "batch_size": 16, "learning_rate": 0.08,
                "warmup_steps": 100, "eval_interval": 1, "steps_per_epoch": steps_per_epoch,
                "estimated_optimizer_steps": steps_per_epoch * 80, "sanity_check": False, "warning": "",
            }

        blockers: list[dict[str, str]] = []
        if not state.get("localization_dataset"):
            blockers.append({
                "code": "dataset_missing",
                "message": "Er is nog geen localization-dataset gebouwd.",
                "next_step": "Rond bronbeelden af in Detection Review en kies daarna Dataset bouwen.",
            })
        else:
            if not bool(state.get("localization_split_current")):
                blockers.append({
                    "code": "dataset_stale",
                    "message": "De review- of splitindeling is gewijzigd sinds deze dataset is gebouwd.",
                    "next_step": "Bouw de dataset opnieuw zodat de actuele reviews en split worden vastgelegd.",
                })
            if not bool(state.get("localization_app_valid")):
                blockers.append({
                    "code": "app_validation_missing",
                    "message": "De IsalaOCR-validatie voor deze dataset ontbreekt of is niet meer geldig.",
                    "next_step": "Voer Dataset valideren uit.",
                })
            if not bool(state.get("localization_paddlex_valid")):
                blockers.append({
                    "code": "paddlex_validation_missing",
                    "message": "De PaddleX/PaddleDetection-validatie voor deze dataset ontbreekt of is niet meer geldig.",
                    "next_step": "Voer Dataset valideren uit; die controleert ook PaddleX/PaddleDetection.",
                })

        return {
            "dataset_id": str(state.get("localization_dataset_id") or ""),
            "dataset_present": bool(state.get("localization_dataset")),
            "dataset_created_at": str(dataset.get("created_at") or "") if isinstance(dataset, dict) else "",
            "image_count": int(dataset.get("image_count") or 0) if isinstance(dataset, dict) else 0,
            "annotation_count": int(dataset.get("annotation_count") or 0) if isinstance(dataset, dict) else 0,
            "negative_image_count": int(dataset.get("negative_image_count") or 0) if isinstance(dataset, dict) else 0,
            "splits": {
                "train": split_images("train"),
                "val": split_images("val"),
                "test": split_images("test"),
            },
            "app_valid": bool(state.get("localization_app_valid")),
            "paddlex_valid": bool(state.get("localization_paddlex_valid")),
            "split_current": bool(state.get("localization_split_current")),
            "ready_marker_valid": bool(state.get("localization_ready_marker_valid")),
            "training_ready": bool(state.get("localization_training_ready")),
            "validated_at": str(marker.get("validated_at") or validation.get("validated_at") or ""),
            "validation_totals": (validation.get("totals") if isinstance(validation, dict) and isinstance(validation.get("totals"), dict) else {}),
            # Old validation artifacts may omit warnings/errors or contain null.
            # Keep the browser contract stable: these fields are always arrays.
            "warnings": (validation.get("warnings") if isinstance(validation, dict) and isinstance(validation.get("warnings"), list) else []),
            "errors": (validation.get("errors") if isinstance(validation, dict) and isinstance(validation.get("errors"), list) else []),
            "blockers": blockers,
            "next_step": blockers[0]["next_step"] if blockers else "Dataset is trainingsklaar.",
            "models": database.list_localization_models(),
            "training_profile": training_profile,
        }

    def localization_workbench_payload() -> dict[str, Any]:
        """Complete Step 4 state for the React client.

        The browser owns presentation state; this endpoint only exposes canonical
        backend state and the exact dataset preview used by the builder.
        """
        preview = localization_dataset_preview(workspace_root())
        relevant = {"5", "6", "7", "8"}
        jobs = job_statuses(20, action_ids=relevant)
        active_job = next(
            (item for item in jobs if str(item.get("status") or "") in {"pending", "running"}),
            None,
        )
        project_state = project_manager.active()
        return {
            "schema_version": 1,
            "generated_at": _utcnow(),
            "project": {
                "project_id": project_state.project_id,
                "name": project_state.name,
                "use_case_id": project_state.use_case_id,
            },
            "readiness": localization_readiness_payload(),
            "preview": preview,
            "jobs": jobs,
            "active_job": active_job,
            "worker": worker_state(),
        }

    def _localization_selection_path() -> Path:
        return workspace_root() / "localization_artifact_selection.json"

    _dir_size_cache: dict[str, tuple[float, int]] = {}

    def _dir_size(path: Path) -> int:
        key = str(path)
        now = time.monotonic()
        cached = _dir_size_cache.get(key)
        if cached is not None and now - cached[0] < 30.0:
            return cached[1]
        total = 0
        if not path.exists():
            _dir_size_cache.pop(key, None)
            return 0
        try:
            for item in path.rglob("*"):
                if item.is_file():
                    try:
                        total += item.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        _dir_size_cache[key] = (now, total)
        return total

    def _safe_workspace_tree(path: Path, *, parent: Path) -> Path:
        target = path.resolve()
        allowed = parent.resolve()
        try:
            target.relative_to(allowed)
        except ValueError as exc:
            raise ValueError(f"Unsafe artifact path outside workspace: {target}") from exc
        return target

    def localization_artifact_selection() -> dict[str, Any]:
        root = workspace_root()
        stored = _read_json(_localization_selection_path(), {})
        if not isinstance(stored, dict):
            stored = {}
        datasets = database.list_localization_datasets()
        models_list = database.list_localization_models()
        evaluations = database.list_localization_evaluations()
        current_dataset_id = ""
        pointer = root / "localization_datasets" / "latest.txt"
        try:
            current_dataset_id = pointer.read_text(encoding="utf-8-sig").strip() if pointer.is_file() else ""
        except OSError:
            current_dataset_id = ""
        dataset_ids = {str(item.get("dataset_id") or "") for item in datasets}
        model_ids = {str(item.get("model_id") or "") for item in models_list}
        evaluation_ids = {str(item.get("evaluation_id") or "") for item in evaluations}
        active = database.active_localization_model()
        evaluation_dataset_id = str(stored.get("evaluation_dataset_id") or current_dataset_id)
        if evaluation_dataset_id not in dataset_ids:
            evaluation_dataset_id = current_dataset_id if current_dataset_id in dataset_ids else (str(datasets[0].get("dataset_id") or "") if datasets else "")
        evaluation_model_id = str(stored.get("evaluation_model_id") or "")
        if evaluation_model_id not in model_ids:
            active_id = str((active or {}).get("model_id") or "")
            evaluation_model_id = active_id if active_id in model_ids else (str(models_list[0].get("model_id") or "") if models_list else "")
        baseline_evaluation_id = str(stored.get("baseline_evaluation_id") or "")
        trained_evaluation_id = str(stored.get("trained_evaluation_id") or "")
        if baseline_evaluation_id not in evaluation_ids:
            baseline_evaluation_id = ""
        if trained_evaluation_id not in evaluation_ids:
            trained_evaluation_id = ""
        selected_model = next((item for item in models_list if str(item.get("model_id") or "") == evaluation_model_id), None)
        return {
            "evaluation_dataset_id": evaluation_dataset_id,
            "evaluation_model_id": evaluation_model_id,
            "baseline_evaluation_id": baseline_evaluation_id,
            "trained_evaluation_id": trained_evaluation_id,
            "current_dataset_id": current_dataset_id,
            "selected_model": selected_model,
            "updated_at": str(stored.get("updated_at") or ""),
        }

    def save_localization_artifact_selection(payload: dict[str, Any]) -> dict[str, Any]:
        current = localization_artifact_selection()
        datasets = {str(item.get("dataset_id") or ""): item for item in database.list_localization_datasets()}
        models_list = {str(item.get("model_id") or ""): item for item in database.list_localization_models()}
        evaluations = {str(item.get("evaluation_id") or ""): item for item in database.list_localization_evaluations()}
        result = {
            "evaluation_dataset_id": str(payload.get("evaluation_dataset_id", current.get("evaluation_dataset_id") or "") or ""),
            "evaluation_model_id": str(payload.get("evaluation_model_id", current.get("evaluation_model_id") or "") or ""),
            "baseline_evaluation_id": str(payload.get("baseline_evaluation_id", current.get("baseline_evaluation_id") or "") or ""),
            "trained_evaluation_id": str(payload.get("trained_evaluation_id", current.get("trained_evaluation_id") or "") or ""),
            "updated_at": _utcnow(),
        }
        if result["evaluation_dataset_id"] and result["evaluation_dataset_id"] not in datasets:
            raise ValueError("Onbekende localization-dataset")
        if result["evaluation_model_id"] and result["evaluation_model_id"] not in models_list:
            raise ValueError("Onbekend field-detector-model")
        for key in ("baseline_evaluation_id", "trained_evaluation_id"):
            if result[key] and result[key] not in evaluations:
                raise ValueError("Onbekende localization-evaluatie")
        selected_model = models_list.get(result["evaluation_model_id"])
        if selected_model:
            result["model"] = {
                "model_id": str(selected_model.get("model_id") or ""),
                "path": str(selected_model.get("path") or ""),
                "device": str(selected_model.get("device") or "gpu"),
                "dataset_id": str(selected_model.get("dataset_id") or ""),
            }
        path = _localization_selection_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
        return localization_artifact_selection()

    def select_localization_work_dataset(dataset_id: str) -> dict[str, Any]:
        dataset_id = str(dataset_id or "").strip()
        datasets = {str(item.get("dataset_id") or ""): item for item in database.list_localization_datasets()}
        if dataset_id not in datasets:
            raise ValueError("Onbekende localization-dataset")
        root = workspace_root() / "localization_datasets"
        dataset_dir = root / dataset_id
        if not (dataset_dir / "manifest.json").is_file():
            raise ValueError("Datasetmap of manifest ontbreekt")

        manifest = _read_json(dataset_dir / "manifest.json", {})
        source_splits = manifest.get("source_splits") if isinstance(manifest, dict) else {}
        eligible = {
            str(item.get("source_id") or "")
            for item in database.list_detection_sources()
            if bool(item.get("review_completed"))
        }
        split_compatible = bool(source_splits) and set(map(str, source_splits.keys())) == eligible
        if split_compatible:
            targets = {
                name: sum(1 for split in source_splits.values() if str(split) == name)
                for name in ("train", "val", "test")
            }
            save_localization_split_config(
                workspace_root(), mode="counts", targets=targets,
                overrides={str(source_id): str(split) for source_id, split in source_splits.items()},
            )

        root.mkdir(parents=True, exist_ok=True)
        temp = root / "latest.txt.tmp"
        temp.write_text(dataset_id, encoding="ascii")
        temp.replace(root / "latest.txt")
        pending = workspace_root() / "localization_split_pending.flag"
        if split_compatible:
            pending.unlink(missing_ok=True)
        else:
            pending.write_text(_utcnow() + "\n", encoding="utf-8")
        save_localization_artifact_selection({"evaluation_dataset_id": dataset_id})
        return localization_readiness_payload()

    def localization_artifacts_payload() -> dict[str, Any]:
        root = workspace_root()
        selection = localization_artifact_selection()
        current_dataset_id = str(selection.get("current_dataset_id") or "")
        models_list = database.list_localization_models()
        evaluations = database.list_localization_evaluations()
        model_by_id = {str(item.get("model_id") or ""): item for item in models_list}
        dataset_rows: list[dict[str, Any]] = []
        for item in database.list_localization_datasets():
            dataset_id = str(item.get("dataset_id") or "")
            path = root / str(item.get("path") or f"localization_datasets/{dataset_id}")
            validation = _read_json(path / "validation.json", {}) if path.is_dir() else {}
            paddlex = _read_json(path / "paddlex_validation" / "isala_paddlex_validation.json", {}) if path.is_dir() else {}
            dataset_rows.append({
                **item,
                "current": dataset_id == current_dataset_id,
                "selected_for_evaluation": dataset_id == str(selection.get("evaluation_dataset_id") or ""),
                "validation_ok": bool(isinstance(validation, dict) and validation.get("status") == "ok"),
                "paddlex_ok": bool(isinstance(paddlex, dict) and (paddlex.get("status") == "ok" or paddlex.get("ok") is True)),
                "model_count": sum(1 for model in models_list if str(model.get("dataset_id") or "") == dataset_id),
                "evaluation_count": sum(1 for ev in evaluations if str(ev.get("dataset_id") or "") == dataset_id),
                "size_bytes": _dir_size(path),
            })
        model_rows: list[dict[str, Any]] = []
        for item in models_list:
            model_id = str(item.get("model_id") or "")
            model_path = Path(str(item.get("path") or ""))
            run_dir = None
            try:
                relative = model_path.resolve().relative_to(root.resolve())
                parts = relative.parts
                if len(parts) >= 2 and parts[0] == "localization_runs":
                    run_dir = root / parts[0] / parts[1]
            except (OSError, ValueError):
                pass
            model_rows.append({
                **item,
                "selected_for_evaluation": model_id == str(selection.get("evaluation_model_id") or ""),
                "evaluation_count": sum(1 for ev in evaluations if str(ev.get("model_id") or "") == model_id),
                "run_id": run_dir.name if run_dir else "",
                "size_bytes": _dir_size(run_dir) if run_dir else 0,
            })
        eval_rows: list[dict[str, Any]] = []
        for item in evaluations:
            evaluation_id = str(item.get("evaluation_id") or "")
            path = root / "localization_evaluations" / evaluation_id
            eval_rows.append({
                **item,
                "selected": evaluation_id in {
                    str(selection.get("baseline_evaluation_id") or ""),
                    str(selection.get("trained_evaluation_id") or ""),
                },
                "size_bytes": _dir_size(path),
            })
        run_rows: list[dict[str, Any]] = []
        runs_root = root / "localization_runs"
        registered_run_ids = {str(item.get("run_id") or "") for item in model_rows if item.get("run_id")}
        if runs_root.is_dir():
            for run_dir in sorted((p for p in runs_root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
                metadata = _read_json(run_dir / "isala_localization_run.json", {})
                registration = _read_json(run_dir / "isala_model_registration.json", {})
                run_rows.append({
                    "run_id": run_dir.name,
                    "model_id": str((registration or {}).get("model_id") or ""),
                    "dataset_id": str((registration or {}).get("dataset_id") or Path(str((metadata or {}).get("dataset") or "")).name),
                    "status": str((metadata or {}).get("status") or ("registered" if run_dir.name in registered_run_ids else "incomplete")),
                    "registered": run_dir.name in registered_run_ids,
                    "size_bytes": _dir_size(run_dir),
                    "created_at": str((metadata or {}).get("completed_at") or ""),
                })
        delete_jobs = []
        for job in job_statuses(1000, job_type="artifact_delete"):
            if str(job.get("status") or "") not in {"pending", "running"}:
                continue
            options = job.get("options") if isinstance(job.get("options"), dict) else {}
            delete_jobs.append({
                "job_id": str(job.get("job_id") or ""),
                "status": str(job.get("status") or "pending"),
                "progress_label": str(job.get("progress_label") or ""),
                "kind": str(options.get("kind") or ""),
                "id": str(options.get("id") or ""),
            })
        project_state = project_manager.active()
        return {
            "schema_version": 3,
            "generated_at": _utcnow(),
            "project": {
                "project_id": project_state.project_id,
                "name": project_state.name,
                "use_case_id": project_state.use_case_id,
            },
            "selection": selection,
            "datasets": dataset_rows,
            "models": model_rows,
            "evaluations": eval_rows,
            "runs": run_rows,
            "active_model": database.active_localization_model(),
            "gate": current_detection_gate(),
            "worker": worker_state(),
            "delete_jobs": delete_jobs,
        }

    def _remove_evaluation_artifact(evaluation_id: str) -> None:
        root = workspace_root()
        evaluation = database.get_localization_evaluation(evaluation_id)
        if evaluation is None:
            raise ValueError("Onbekende localization-evaluatie")
        path = _safe_workspace_tree(root / "localization_evaluations" / evaluation_id, parent=root / "localization_evaluations")
        if path.is_dir():
            shutil.rmtree(path)
        database.delete_localization_evaluation(evaluation_id)
        comparison = _read_json(root / "localization_evaluations" / "latest_comparison.json", {})
        if isinstance(comparison, dict) and evaluation_id in {
            str(comparison.get("baseline_evaluation_id") or ""), str(comparison.get("trained_evaluation_id") or "")
        }:
            (root / "localization_evaluations" / "latest_comparison.json").unlink(missing_ok=True)
        selection = localization_artifact_selection()
        updates: dict[str, str] = {}
        if str(selection.get("baseline_evaluation_id") or "") == evaluation_id:
            updates["baseline_evaluation_id"] = ""
        if str(selection.get("trained_evaluation_id") or "") == evaluation_id:
            updates["trained_evaluation_id"] = ""
        if updates:
            save_localization_artifact_selection(updates)

    def artifact_delete_plan(kind: str, artifact_id: str, *, replacement_dataset_id: str = "") -> dict[str, Any]:
        root = workspace_root()
        kind = str(kind or "").strip().lower()
        artifact_id = str(artifact_id or "").strip()
        if kind not in {"dataset", "model", "evaluation", "run"}:
            raise ValueError("Onbekend artifacttype")
        if not artifact_id:
            raise ValueError("Artifact-ID ontbreekt")
        result: dict[str, Any] = {
            "kind": kind, "id": artifact_id, "dependency_count": 0,
            "requires_cascade": False, "current": False, "replacement_dataset_id": "",
        }
        if kind == "evaluation":
            if database.get_localization_evaluation(artifact_id) is None:
                raise ValueError("Onbekende localization-evaluatie")
            return result
        if kind == "model":
            model = database.get_localization_model(artifact_id)
            if model is None:
                raise ValueError("Onbekend field-detector-model")
            if int(model.get("active") or 0):
                raise ValueError("Het actieve field-detector-model kan niet worden verwijderd. Activeer eerst een ander model.")
            dependencies = [
                ev for ev in database.list_localization_evaluations()
                if str(ev.get("model_id") or "") == artifact_id
            ]
            result["dependency_count"] = len(dependencies)
            result["requires_cascade"] = bool(dependencies)
            return result
        if kind == "dataset":
            datasets = {str(item.get("dataset_id") or ""): item for item in database.list_localization_datasets()}
            if artifact_id not in datasets:
                raise ValueError("Onbekende localization-dataset")
            models_for_dataset = [
                model for model in database.list_localization_models()
                if str(model.get("dataset_id") or "") == artifact_id
            ]
            active_refs = [model for model in models_for_dataset if int(model.get("active") or 0)]
            if active_refs:
                active_ids = ", ".join(str(model.get("model_id") or "") for model in active_refs)
                raise ValueError(f"Deze dataset hoort bij het actieve field-detector-model ({active_ids}); activeer eerst een ander model.")
            evaluations_for_dataset = [
                ev for ev in database.list_localization_evaluations()
                if str(ev.get("dataset_id") or "") == artifact_id
            ]
            dependency_count = len(models_for_dataset) + len(evaluations_for_dataset)
            result["dependency_count"] = dependency_count
            result["requires_cascade"] = dependency_count > 0
            selection = localization_artifact_selection()
            is_current = str(selection.get("current_dataset_id") or "") == artifact_id
            result["current"] = is_current
            if is_current:
                alternatives = [dataset_id for dataset_id in datasets if dataset_id != artifact_id]
                if not alternatives:
                    raise ValueError("Dit is de enige werkdataset. Bouw of bewaar eerst een andere dataset voordat je deze verwijdert.")
                replacement = str(replacement_dataset_id or "").strip()
                if replacement and replacement not in alternatives:
                    raise ValueError("De gekozen vervangende werkdataset bestaat niet meer.")
                result["replacement_dataset_id"] = replacement
                result["replacement_candidates"] = alternatives
                if not replacement:
                    raise ValueError("Dit is de huidige werkdataset. Kies eerst een vervangende werkdataset.")
            return result
        path = _safe_workspace_tree(root / "localization_runs" / artifact_id, parent=root / "localization_runs")
        if not path.is_dir():
            raise ValueError("Onbekende localization-run")
        registration = _read_json(path / "isala_model_registration.json", {})
        model_id = str((registration or {}).get("model_id") or "")
        if model_id and database.get_localization_model(model_id):
            return artifact_delete_plan("model", model_id, replacement_dataset_id=replacement_dataset_id)
        return result

    def delete_localization_artifact(kind: str, artifact_id: str, *, cascade: bool = False, replacement_dataset_id: str = "") -> dict[str, Any]:
        root = workspace_root()
        kind = str(kind or "").strip().lower()
        artifact_id = str(artifact_id or "").strip()
        if not artifact_id:
            raise ValueError("Artifact-ID ontbreekt")
        if kind == "evaluation":
            _remove_evaluation_artifact(artifact_id)
        elif kind == "model":
            model = database.get_localization_model(artifact_id)
            if model is None:
                raise ValueError("Onbekend field-detector-model")
            if int(model.get("active") or 0):
                raise ValueError("Het actieve field-detector-model kan niet worden verwijderd. Activeer eerst een ander model.")
            dependencies = [ev for ev in database.list_localization_evaluations() if str(ev.get("model_id") or "") == artifact_id]
            if dependencies and not cascade:
                raise ValueError(f"Model wordt gebruikt door {len(dependencies)} evaluatie(s); verwijder die eerst of gebruik cascade")
            for ev in dependencies:
                _remove_evaluation_artifact(str(ev.get("evaluation_id") or ""))
            path = Path(str(model.get("path") or ""))
            run_dir = None
            try:
                relative = path.resolve().relative_to(root.resolve())
                if len(relative.parts) >= 2 and relative.parts[0] == "localization_runs":
                    run_dir = _safe_workspace_tree(root / relative.parts[0] / relative.parts[1], parent=root / "localization_runs")
            except (OSError, ValueError):
                run_dir = None
            database.delete_localization_model(artifact_id)
            if run_dir and run_dir.is_dir():
                shutil.rmtree(run_dir)
            selection = localization_artifact_selection()
            if str(selection.get("evaluation_model_id") or "") == artifact_id:
                save_localization_artifact_selection({"evaluation_model_id": ""})
        elif kind == "dataset":
            datasets = {str(item.get("dataset_id") or ""): item for item in database.list_localization_datasets()}
            dataset = datasets.get(artifact_id)
            if dataset is None:
                raise ValueError("Onbekende localization-dataset")
            selection = localization_artifact_selection()
            is_current = str(selection.get("current_dataset_id") or "") == artifact_id
            models_for_dataset = [model for model in database.list_localization_models() if str(model.get("dataset_id") or "") == artifact_id]
            active_refs = [model for model in models_for_dataset if int(model.get("active") or 0)]
            if active_refs:
                active_ids = ", ".join(str(model.get("model_id") or "") for model in active_refs)
                raise ValueError(f"Deze dataset hoort bij het actieve field-detector-model ({active_ids}); activeer eerst een ander model.")
            evaluations_for_dataset = [ev for ev in database.list_localization_evaluations() if str(ev.get("dataset_id") or "") == artifact_id]
            dependency_count = len(models_for_dataset) + len(evaluations_for_dataset)
            if dependency_count and not cascade:
                raise ValueError(f"Dataset heeft {dependency_count} afhankelijke model/evaluatie-artifact(s); verwijder die eerst of gebruik cascade")
            if is_current:
                alternatives = [dataset_id for dataset_id in datasets if dataset_id != artifact_id]
                replacement = str(replacement_dataset_id or "").strip()
                if not alternatives:
                    raise ValueError("Dit is de enige werkdataset. Bouw of bewaar eerst een andere dataset voordat je deze verwijdert.")
                if not replacement:
                    raise ValueError("Dit is de huidige werkdataset. Kies eerst een andere werkdataset of bevestig verwijderen met een vervangende werkdataset.")
                if replacement not in alternatives:
                    raise ValueError("De gekozen vervangende werkdataset bestaat niet meer.")
                select_localization_work_dataset(replacement)
                selection = localization_artifact_selection()
            if cascade:
                for model in list(models_for_dataset):
                    delete_localization_artifact("model", str(model.get("model_id") or ""), cascade=True)
                for ev in list(evaluations_for_dataset):
                    if database.get_localization_evaluation(str(ev.get("evaluation_id") or "")) is not None:
                        _remove_evaluation_artifact(str(ev.get("evaluation_id") or ""))
            path = _safe_workspace_tree(root / str(dataset.get("path") or f"localization_datasets/{artifact_id}"), parent=root / "localization_datasets")
            if path.is_dir():
                shutil.rmtree(path)
            database.delete_localization_dataset_record(artifact_id)
            if str(selection.get("evaluation_dataset_id") or "") == artifact_id:
                save_localization_artifact_selection({"evaluation_dataset_id": ""})
        elif kind == "run":
            path = _safe_workspace_tree(root / "localization_runs" / artifact_id, parent=root / "localization_runs")
            if not path.is_dir():
                raise ValueError("Onbekende localization-run")
            registration = _read_json(path / "isala_model_registration.json", {})
            model_id = str((registration or {}).get("model_id") or "")
            if model_id and database.get_localization_model(model_id):
                return delete_localization_artifact("model", model_id, cascade=cascade)
            shutil.rmtree(path)
        else:
            raise ValueError("Onbekend artifacttype")
        return localization_artifacts_payload()

    def localization_quality_payload() -> dict[str, Any]:
        selection = localization_artifact_selection()
        dataset_id = str(selection.get("evaluation_dataset_id") or "")
        model_id = str(selection.get("evaluation_model_id") or "")
        evaluations = database.list_localization_evaluations()
        localization_models = database.list_localization_models()
        baseline_id = str(selection.get("baseline_evaluation_id") or "")
        trained_id = str(selection.get("trained_evaluation_id") or "")
        baseline = next((item for item in evaluations if baseline_id and str(item.get("evaluation_id") or "") == baseline_id), None)
        if baseline is None:
            baseline = next((
                item for item in evaluations
                if str(item.get("kind") or "") == "baseline"
                and (not dataset_id or str(item.get("dataset_id") or "") == dataset_id)
            ), None)
        trained = next((item for item in evaluations if trained_id and str(item.get("evaluation_id") or "") == trained_id), None)
        if trained is None:
            trained = next((
                item for item in evaluations
                if str(item.get("kind") or "") == "trained"
                and (not dataset_id or str(item.get("dataset_id") or "") == dataset_id)
                and (not model_id or str(item.get("model_id") or "") == model_id)
            ), None)
        comparison = _read_json(workspace_root() / "localization_evaluations" / "latest_comparison.json", None)
        if isinstance(comparison, dict):
            expected = {
                str((baseline or {}).get("evaluation_id") or ""),
                str((trained or {}).get("evaluation_id") or ""),
            }
            actual = {
                str(comparison.get("baseline_evaluation_id") or ""),
                str(comparison.get("trained_evaluation_id") or ""),
            }
            if "" in expected or expected != actual:
                comparison = None
        diagnostics = _read_json(workspace_root() / "localization_diagnostics" / "latest_trained.json", None)
        if isinstance(diagnostics, dict) and (
            (model_id and str(diagnostics.get("model_id") or "") != model_id)
            or (dataset_id and str(diagnostics.get("dataset_id") or "") != dataset_id)
            or (
                trained
                and str((trained or {}).get("predictions_path") or "")
                and str(diagnostics.get("predictions_path") or "") != str((trained or {}).get("predictions_path") or "")
            )
        ):
            diagnostics = None
        relevant = {"9", "10", "11", "13"}
        jobs = job_statuses(20, action_ids=relevant)
        project_state = project_manager.active()
        return {
            "schema_version": 3,
            "generated_at": _utcnow(),
            "project": {
                "project_id": project_state.project_id,
                "name": project_state.name,
                "use_case_id": project_state.use_case_id,
            },
            "gate": current_detection_gate(),
            "thresholds": localization_gate_thresholds(),
            "selection": selection,
            "datasets": database.list_localization_datasets(),
            "baseline": baseline,
            "trained": trained,
            "evaluations": evaluations,
            "comparison": comparison,
            "diagnostics": diagnostics,
            "active_model": database.active_localization_model(),
            "models": localization_models,
            "jobs": jobs,
            "worker": worker_state(),
        }

    def localization_event_signature() -> str:
        """Cheap filesystem signature for SSE invalidation events.

        We deliberately do not serialize the full workbench on every heartbeat.
        When files or job status snapshots change, the React client refetches its
        canonical workbench state once.
        """
        root = workspace_root()
        localization_root = root / "localization_datasets"
        pointer = localization_root / "latest.txt"
        dataset_id = ""
        try:
            dataset_id = pointer.read_text(encoding="utf-8-sig").strip() if pointer.is_file() else ""
        except OSError:
            dataset_id = ""
        dataset_root = localization_root / dataset_id if dataset_id else localization_root
        paths = [
            pointer,
            root / "localization_split_config.json",
            root / "localization_split_pending.flag",
            dataset_root / "manifest.json",
            dataset_root / "validation.json",
            dataset_root / "training_ready.json",
            dataset_root / "paddlex_validation" / "isala_paddlex_validation.json",
            root / "detection_gate.json",
            root / "localization_evaluations" / "latest_comparison.json",
            root / "localization_evaluations" / "quality_report.json",
            root / "localization_diagnostics" / "latest_trained.json",
            root / "localization_runs" / "latest.txt",
            root / "localization_artifact_selection.json",
            jobs_root / "worker.json",
        ]
        parts: list[str] = [project_manager.active_project_id(), dataset_id]
        for path in paths:
            try:
                stat = path.stat()
                parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
            except OSError:
                parts.append(f"{path.name}:missing")
        for path in sorted((root / "localization_evaluations").glob("*/evaluation.json")):
            try:
                stat = path.stat()
                parts.append(f"evaluation:{path.parent.name}:{stat.st_mtime_ns}:{stat.st_size}")
            except OSError:
                continue
        for path in sorted((jobs_root / "status").glob("*.json")):
            try:
                stat = path.stat()
                parts.append(f"job:{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
            except OSError:
                continue
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def pipeline_state(snapshot: dict[str, Any] | None = None) -> list[dict[str,Any]]:
        snapshot = snapshot or process_snapshot()
        reviews = snapshot["detection_reviews"]
        loc_dataset = snapshot.get("localization_dataset")
        loc_validation = snapshot.get("localization_validation")
        loc_baseline = snapshot.get("localization_baseline")
        loc_trained = snapshot.get("localization_trained")
        loc_comparison = snapshot.get("localization_comparison")
        active_loc = snapshot.get("active_localization_model")
        gate = snapshot.get("pipeline_gate") or snapshot.get("detection_gate") or {}
        table_quality_state = snapshot.get("table_quality") or {}
        active_table_model = ((snapshot.get("table_model") or {}).get("active_model") or {})
        detail = {
            "detection-models": f"{snapshot['preparation']['model_file_count']} modelbestanden lokaal",
            "panel-setup": (
                f"{int((snapshot.get('table_panels') or {}).get('panel_count') or 0)} panel(en) ingesteld"
                if (snapshot.get('table_panels') or {}).get('configured') else "nog geen panelen ingesteld"
            ),
            "detect-candidates": (
                f"{len(snapshot['detection_sources'])} bron(nen), "
                f"{reviews.get('candidate_total', 0)} " + ("table-cell kandidaten" if localization_strategy() == "table_first" else "kandidaat-ROI's")
            ),
            "detection-review": (
                f"{reviews.get('positive', 0)} bevestigd, "
                f"{reviews.get('rejected', 0)} afgewezen, {reviews.get('pending', 0)} open"
            ),
            "table-quality": "raster en Recognition-scope na nieuwe detectierun beoordelen",
            "table-model": (
                str(active_table_model.get('model_id') or 'reviewdata nog niet als actief table-model ingezet')
            ),
            "table-region-model": (
                f"actief regio-model · {len(list_table_region_sources(workspace_root()))} lezing(en) met GT"
                if _read_json(workspace_root() / "table_region_models" / "active.json", None)
                else f"{len(list_table_region_sources(workspace_root()))} lezing(en) met GT · model nog niet actief"
            ),
            "table-compare": (
                "nieuwe Stap-4-run klaar voor vergelijking" if active_table_model else "eerst een getraind tablecelmodel activeren en Stap 4 uitvoeren"
            ),
            "localization-dataset": (
                (f"{loc_dataset.get('image_count', 0)} beelden · {loc_dataset.get('annotation_count', 0)} boxen · "
                 f"validatie={'OK' if snapshot.get('localization_training_ready') else 'open'} · "
                 f"{len(snapshot['localization_models'])} detector(en)")
                if loc_dataset else "nog niet gebouwd"
            ),
            "localization-evaluate": (
                "getrainde detector geëvalueerd" if loc_trained else
                ("baseline geëvalueerd" if loc_baseline else "nog niet geëvalueerd")
            ),
            "localization-compare": (
                "vergelijking aanwezig" if loc_comparison else "nog niet vergeleken"
            ),
            "localization-register": (
                str(active_loc.get('model_id') or active_loc.get('model_name')) if active_loc else "geen actieve field detector"
            ),
            "redetect": (
                "actieve field detector beschikbaar" if active_loc else "eerst detector activeren"
            ),
            "detection-report": (
                ("PASS · Pipeline B ontgrendeld" if gate.get('ready') else f"GATE DICHT · {gate.get('reason') or 'kwaliteit nog onvoldoende'}")
            ),
            "mapping": (
                f"{snapshot['mapping'].get('confirmed', 0)} bevestigd, {snapshot['mapping'].get('suggested', 0)} voorgesteld"
                if gate.get('ready') else f"geblokkeerd · {gate.get('gate_label') or 'Pipeline A'}"
            ),
            "apply-mapping": f"{snapshot['mapped'].get('total', 0)} actuele raster/celkaders toegepast",
            "value-extract": f"{snapshot['mapped'].get('recognized', 0)} actuele rasterwaarden uitgelezen",
            "value-review": f"{snapshot['value'].get('accepted', 0)} goedgekeurd, {snapshot['value'].get('pending', 0)} open",
            "recognition-dataset": snapshot['dataset']['dataset_id'] if snapshot['dataset'] else "nog niet gebouwd",
            "recognition-train": f"{float(snapshot['progress'].get('progress_percent', 0)):.1f}%" if snapshot['progress'] else "nog geen recognition-training",
            "recognition-evaluate": (
                "custom evaluatie aanwezig" if snapshot['custom'] else
                ("baseline evaluatie aanwezig" if snapshot['baseline'] else "nog niet geëvalueerd")
            ),
            "recognition-models": snapshot['active'].get('model_id') if snapshot['active'] else "geen actief recognition-model",
            "recognition-output-review": f"{snapshot['value'].get('accepted', 0)}/{snapshot['value'].get('total', 0)} resultaten beoordeeld" if snapshot['value'].get('total', 0) else "nog geen uitvoerreview",
            "system-checks": "runtime-, model- en opslagcontroles",
            "maintenance": "veilige herstel- en opruimacties",
        }
        return [
            {**step, "name": step["title"], "complete": bool(snapshot["readiness"].get(step["key"])), "detail": detail.get(step["key"], "")}
            for step in PROCESS_STEPS
            if not (localization_strategy() == "table_first" and step.get("group") == "fallback")
        ]

    def query_samples(filters: dict[str,str|None], *, limit:int, offset:int=0, exclude_sample_id:str|None=None):
        ocr_content=str(filters.get("ocr_content") or "all")
        if ocr_content not in VALID_OCR_CONTENT_FILTERS: abort(400)
        try:
            min_confidence=_optional_confidence(filters.get("min_confidence"))
            max_confidence=_optional_confidence(filters.get("max_confidence"))
        except ValueError: abort(400)
        return database.list_samples(
            status=filters.get("status"), field_key=filters.get("field"),
            min_confidence=min_confidence, max_confidence=max_confidence,
            ocr_content=ocr_content, roi_review_status="correct",
            exclude_sample_id=exclude_sample_id, limit=limit, offset=offset,
        )

    @app.context_processor
    def common_context():
        _, active = registry_state()
        active_project = request_cached("active_project", project_manager.active)
        available_projects = request_cached("available_projects", project_manager.list_projects)
        pipeline_gate = navigation_pipeline_gate()
        recognition_gate = current_recognition_gate()
        workflow_step_access = workflow_navigation_access()
        workflow_gates = {
            # The first GT/Table menu is the entry point and must remain open.
            "gt_workflow": True,
            # Recognition GT may only be opened after the canonical table gate.
            "recognition_preparation": bool(workflow_step_access.get("recognition-gt-studio")),
            # Recognition dataset/model work requires approved Recognition GT.
            "recognition_factory": bool(workflow_step_access.get("recognition-dataset")),
            # The bundle is available only after a model has been activated.
            "model_bundle": bool(active),
            # Application processing is downstream of the active bundle.
            "application": bool(workflow_step_access.get("mapping")),
        }
        return {
            "app_version": app_version,
            "active_model": active,
            "process_steps": PROCESS_STEPS,
            "detection_gate_global": (navigation_detection_gate() if localization_strategy() != "table_first" else {"ready": False, "state": "parked"}),
            "pipeline_gate_global": navigation_pipeline_gate(),
            "recognition_gate_global": recognition_gate,
            "workflow_gates": workflow_gates,
            "workflow_step_access": workflow_step_access,
            "localization_strategy": localization_strategy(),
            "active_project": active_project,
            "available_projects": available_projects,
            "action_duration_estimates": ACTION_DURATION_ESTIMATES,
        }


    def project_summary(item: dict[str, Any]) -> dict[str, Any]:
        project_id = str(item.get("project_id") or "")
        project_workspace = project_manager.projects_root / project_id
        db = TrainingDatabase(project_workspace / "samples.sqlite3")
        if header_profile is not None and str(item.get("use_case_id") or "") == DEFAULT_USE_CASE_ID:
            ensure_default_field_definitions(db, header_profile)
        detection = db.detection_review_counts()
        mappings = db.mapping_counts()
        loc_models = db.list_localization_models()
        return {
            **item,
            "source_count": len(db.list_detection_sources()),
            "candidate_count": int(detection.get("candidate_total") or 0),
            "positive_count": int(detection.get("positive") or 0),
            "negative_count": int(detection.get("negative") or detection.get("ignored") or 0),
            "open_count": int(detection.get("pending") or 0),
            "mapping_count": int(mappings.get("confirmed") or 0),
            "active_localization_model": db.active_localization_model(),
            "localization_model_count": len(loc_models),
            "gate": _safe_detection_gate(project_workspace, target_db=db),
        }

    @app.errorhandler(500)
    def internal_server_error(error):
        original = getattr(error, "original_exception", None) or error
        reference = _record_webui_error("unhandled_http_500", original)
        message = str(original).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        error_type = type(original).__name__.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body = f"""<!doctype html><html lang='nl'><head><meta charset='utf-8'><title>IsalaOCR fout</title>
<style>body{{font-family:system-ui,sans-serif;max-width:900px;margin:48px auto;padding:0 24px}}code{{background:#f3f4f6;padding:2px 5px;border-radius:4px}}.ref{{font-family:ui-monospace,monospace}}</style></head>
<body><h1>IsalaOCR webinterface-fout</h1><p>De interface blijft fail-closed; er is niets automatisch geactiveerd of verwerkt.</p>
<p><strong>{error_type}</strong>: {message}</p><p>Diagnostiek: <code class='ref'>{reference}</code></p>
<p>De volledige traceback staat in <code>training/workspace/projects/&lt;project&gt;/webui_errors.log</code>.</p></body></html>"""
        return Response(body, status=500, mimetype="text/html")

    def render_management(*, active_tab: str = "projects"):
        tab = "models" if str(active_tab).strip().lower() == "models" else "projects"
        return render_template(
            "management.html",
            active_tab=tab,
            projects=[project_summary(item) for item in project_manager.list_projects(include_archived=True)],
            use_cases=use_case_templates,
        )

    register_project_routes(
        app,
        project_manager=project_manager,
        render_management=render_management,
        header_profile=header_profile,
        use_case_ids=use_case_ids,
        base_root=base_root,
        models_root=models,
    )

    register_home_routes(
        app,
        process_snapshot=process_snapshot,
        pipeline_state=pipeline_state,
        job_statuses=job_statuses,
    )


    @app.route("/test-pipeline", methods=["GET", "POST"])
    def test_pipeline():
        """Small end-to-end proving ground for a future one-click pipeline.

        Keep this route deliberately separate from the training workflow: an
        uploaded image is stored in the active project's configured input
        directory and only that image is selected for the first worker step.
        Later orchestration can extend the same page without changing the
        existing review/training contracts.
        """
        allowed_extensions = {".dcm"}
        source_id = str(request.args.get("source_id") or "").strip()[:80]
        job_id = str(request.args.get("job_id") or "").strip()[:80]
        error = ""
        uploaded_name = ""
        active_table_model = active_table_cell_model(workspace_root()) or {}
        active_table_model_id = str(active_table_model.get("model_id") or "generic-ppstructure")
        active_table_model_name = str(
            active_table_model.get("model_name") or "Generieke PP-Structure baseline"
        )
        _, active_recognition_model = registry_state()
        table_model_state = table_cell_training_state(workspace_root()) or {}
        latest_table_dataset = table_model_state.get("dataset") or {}

        if request.method == "POST":
            upload = request.files.get("image")
            original_name = str(upload.filename or "").strip() if upload else ""
            suffix = Path(original_name).suffix.lower()
            if request.content_length and request.content_length > 25 * 1024 * 1024:
                error = "De upload is te groot; gebruik maximaal 25 MB per afbeelding."
            elif upload is None or not original_name:
                error = "Kies eerst een DICOM-bestand."
            elif suffix not in allowed_extensions:
                error = "Gebruik een DICOM-bestand met de extensie .dcm."
            else:
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_name).name).strip("._")
                safe_name = (safe_name or "upload")[:120]
                if Path(safe_name).suffix.lower() not in allowed_extensions:
                    error = "De bestandsnaam bevat geen ondersteunde afbeeldings-extensie."
                else:
                    try:
                        input_root = Path(project_manager.active().input_path).resolve()
                        allowed_root = Path("/input").resolve()
                        if allowed_root != input_root and allowed_root not in input_root.parents:
                            raise ValueError("Het actieve project-inputpad valt buiten /input.")
                        input_root.mkdir(parents=True, exist_ok=True)
                        stored_name = f"test_{uuid.uuid4().hex[:12]}_{safe_name}"
                        destination = (input_root / stored_name).resolve()
                        if input_root not in destination.parents:
                            raise ValueError("Ongeldig uploadpad.")
                        upload.save(destination)
                        relative_key = destination.relative_to(allowed_root).as_posix()
                        file_bytes = destination.read_bytes()
                        source_id = hashlib.sha256(file_bytes).hexdigest()[:24]
                        input_selection_path().parent.mkdir(parents=True, exist_ok=True)
                        payload = selection_payload({relative_key}, reason="test-pipeline-upload")
                        payload["updated_at"] = _utcnow()
                        input_selection_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
                        job = enqueue_job("60", {
                            "table_model_id": "active" if active_table_model else "generic-ppstructure",
                            "mapping_profile_id": str(request.form.get("mapping_profile_id") or "").strip(),
                        })
                        job_id = str(job["job_id"])
                        uploaded_name = safe_name
                    except (OSError, ValueError) as exc:
                        error = f"Upload kon niet worden klaargezet: {exc}"

        output = None
        if source_id:
            output_path = safe_workspace_file(Path("extracted_output") / f"{source_id}.json")
            if output_path.is_file():
                output = _read_json(output_path, None)
        jobs = job_statuses(20)
        current_job = next((item for item in jobs if str(item.get("job_id") or "") == job_id), None)
        mapping_profiles = database.list_mapping_profiles()
        if error:
            return render_template(
                "test_pipeline.html", source_id=source_id, job_id=job_id,
                current_job=current_job, output=output, error=error,
                active_table_model_id=active_table_model_id, active_table_model_name=active_table_model_name,
                active_table_model=active_table_model,
                active_recognition_model=active_recognition_model or {},
                latest_table_dataset=latest_table_dataset,
                mapping_profiles=mapping_profiles,
            ), 400
        return render_template(
            "test_pipeline.html", source_id=source_id, job_id=job_id,
            current_job=current_job, output=output, uploaded_name=uploaded_name,
            active_table_model_id=active_table_model_id, active_table_model_name=active_table_model_name,
            active_table_model=active_table_model,
            active_recognition_model=active_recognition_model or {},
            latest_table_dataset=latest_table_dataset,
            mapping_profiles=mapping_profiles,
        )

    def _table_panel_review_context(requested_source_id: str = "", panel_state: dict[str, Any] | None = None) -> dict[str, Any]:
        panel_state = panel_state or table_panel_state()
        sources = [dict(item) for item in database.list_detection_sources()]
        selected_source_id = str(requested_source_id or (panel_state.get("profile") or {}).get("reference_source_id") or "")
        selected = next((item for item in sources if str(item.get("source_id")) == selected_source_id), None)
        if selected is None and sources:
            selected = sources[0]
            selected_source_id = str(selected.get("source_id") or "")

        region_ground_truth = list_table_regions(workspace_root(), selected_source_id) if selected_source_id else []
        table_review_sources = []
        for source_item in sources:
            source_key = str(source_item.get("source_id") or "")
            saved_regions = list_table_regions(workspace_root(), source_key) if source_key else []
            table_review_sources.append({
                "source_id": source_key,
                "region_count": len(saved_regions),
                "review_completed": bool(saved_regions),
            })

        suggestions: list[dict[str, Any]] = []
        detection_info: dict[str, Any] = {}
        if selected is not None:
            try:
                geometry = database.list_detection_table_geometry(selected_source_id)
                suggestions = [{**dict(item), "kind": "selected_table_region", "variant": "selected"} for item in geometry.get("regions", [])]
            except Exception:
                suggestions = []
            diagnostic_path = safe_workspace_file(Path("localization_detections") / f"{selected_source_id}.json")
            if diagnostic_path.is_file():
                try:
                    diagnostic_payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
                    benchmark = diagnostic_payload.get("preprocessing_benchmark")
                    benchmark_suggestions = benchmark.get("panel_suggestions") if isinstance(benchmark, dict) else None
                    if isinstance(benchmark_suggestions, list):
                        suggestions.extend(dict(item) for item in benchmark_suggestions if isinstance(item, dict))
                except (OSError, ValueError, TypeError):
                    pass

            unique_suggestions: list[dict[str, Any]] = []
            for item in suggestions:
                try:
                    x1, y1, x2, y2 = (float(item.get(key) or 0) for key in ("x1", "y1", "x2", "y2"))
                except (TypeError, ValueError):
                    continue
                area = max(1.0, (x2 - x1) * (y2 - y1))
                duplicate = False
                for existing in unique_suggestions:
                    ex1, ey1, ex2, ey2 = (float(existing.get(key) or 0) for key in ("x1", "y1", "x2", "y2"))
                    ix = max(0.0, min(x2, ex2) - max(x1, ex1))
                    iy = max(0.0, min(y2, ey2) - max(y1, ey1))
                    inter = ix * iy
                    existing_area = max(1.0, (ex2 - ex1) * (ey2 - ey1))
                    union = area + existing_area - inter
                    if (inter / max(1.0, min(area, existing_area))) >= 0.80 or (inter / max(1.0, union)) >= 0.50:
                        duplicate = True
                        break
                if not duplicate:
                    unique_suggestions.append(item)
            suggestions = unique_suggestions

            diagnostic_path = safe_workspace_file(Path("localization_detections") / f"{selected_source_id}.json")
            if diagnostic_path.is_file():
                try:
                    diagnostic_payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
                    benchmark = diagnostic_payload.get("preprocessing_benchmark") or {}
                    runs = benchmark.get("runs") if isinstance(benchmark, dict) else []
                    detection_info = {
                        "source_id": selected_source_id,
                        "batch_id": str(diagnostic_payload.get("detection_batch_id") or ""),
                        "started_at": str(diagnostic_payload.get("detection_started_at") or diagnostic_payload.get("detected_at") or ""),
                        "detector_version": str(diagnostic_payload.get("detector_version") or ""),
                        "engine": str(((diagnostic_payload.get("table_structure_engine") or {}).get("pipeline") or "")),
                        "device": str(((diagnostic_payload.get("table_structure_engine") or {}).get("device") or "")),
                        "selected_variant": str((benchmark.get("selected_variant") or "") if isinstance(benchmark, dict) else ""),
                        "selected_scope": str((benchmark.get("selected_scope") or "") if isinstance(benchmark, dict) else ""),
                        "selected_score": benchmark.get("selected_score") if isinstance(benchmark, dict) else None,
                        "region_model": str((benchmark.get("region_model") or benchmark.get("table_region_model") or "") if isinstance(benchmark, dict) else ""),
                        "detection_mode": str((benchmark.get("mode") or "") if isinstance(benchmark, dict) else ""),
                        "table_count": int(diagnostic_payload.get("table_count") or 0),
                        "cell_count": int(diagnostic_payload.get("table_cell_count") or 0),
                        "suggestion_count": len(suggestions),
                        "runs": [
                            {key: item.get(key) for key in ("variant", "scope", "score", "table_count", "cell_count", "row_count", "multi_cell_rows")}
                            for item in runs if isinstance(item, dict)
                        ],
                    }
                except (OSError, ValueError, TypeError):
                    detection_info = {}

        definitions = list((panel_state.get("profile") or {}).get("definitions") or [])
        ocr_blocks = database.list_detected_blocks(selected_source_id) if selected_source_id else []

        def quick_ocr_text_for_proposal(proposal: dict[str, Any]) -> str:
            """OCR only the upper part of a proposed table for type matching.

            Table-first detection deliberately does not persist OCR values. This
            small, on-demand pass reads likely headers only, so table type
            matching can use stable labels without turning Pipeline A into value
            extraction.
            """
            if selected is None:
                return ""
            render_value = str(selected.get("render_path") or f"source_renders/{selected_source_id}.png")
            render_path = safe_workspace_file(Path(render_value))
            if not render_path.is_file():
                return ""
            try:
                x1, y1, x2, y2 = (int(float(proposal[key])) for key in ("x1", "y1", "x2", "y2"))
            except (KeyError, TypeError, ValueError):
                return ""
            image = cv2.imread(str(render_path))
            if image is None:
                return ""
            height, width = image.shape[:2]
            x1, x2 = max(0, min(width, x1)), max(0, min(width, x2))
            y1, y2 = max(0, min(height, y1)), max(0, min(height, y2))
            if x2 <= x1 or y2 <= y1:
                return ""
            header_bottom = min(y2, y1 + max(80, int((y2 - y1) * 0.35)))
            crop = image[y1:header_bottom, x1:x2]
            if crop.size == 0:
                return ""
            try:
                tesseract = str((loaded_config.ocr if loaded_config else {}).get("tesseract", {}).get("executable", "tesseract"))
                with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
                    if not cv2.imwrite(image_file.name, crop):
                        return ""
                    completed = subprocess.run(
                        [tesseract, image_file.name, "stdout", "--psm", "6", "-l", "eng", "tsv"],
                        check=False, capture_output=True, text=True, timeout=10,
                    )
                if completed.returncode != 0:
                    return ""
                tokens = []
                for row in csv.DictReader(io.StringIO(completed.stdout), delimiter="\t"):
                    text = str(row.get("text") or "").strip()
                    if text:
                        tokens.append(text)
            except Exception:
                return ""
            return " | ".join(tokens)

        def table_text_for_proposal(proposal: dict[str, Any]) -> str:
            try:
                x1, y1, x2, y2 = (float(proposal[key]) for key in ("x1", "y1", "x2", "y2"))
            except (KeyError, TypeError, ValueError):
                return ""
            texts: list[str] = []
            for block in ocr_blocks:
                text = str(block.get("text") or block.get("normalized_text") or block.get("context_text") or "").strip()
                if not text:
                    continue
                try:
                    bx1, by1, bx2, by2 = (float(block[key]) for key in ("x1", "y1", "x2", "y2"))
                except (KeyError, TypeError, ValueError):
                    continue
                overlap_x = max(0.0, min(x2, bx2) - max(x1, bx1))
                overlap_y = max(0.0, min(y2, by2) - max(y1, by1))
                block_area = max(1.0, (bx2 - bx1) * (by2 - by1))
                center_inside = x1 <= (bx1 + bx2) / 2 <= x2 and y1 <= (by1 + by2) / 2 <= y2
                if center_inside or (overlap_x * overlap_y) / block_area >= 0.35:
                    texts.append(text)
            return " | ".join(dict.fromkeys(texts))

        def definition_text_score(definition: dict[str, Any], observed: str) -> tuple[float, str]:
            observed_normalized = normalize_for_matching(observed)
            if not observed_normalized:
                return 0.0, ""
            candidates = [str(definition.get("name") or "")]
            candidates.extend(str(hit) for hit in (definition.get("hits") or definition.get("aliases") or []) if str(hit).strip())
            best_score, best_hit = 0.0, ""
            observed_parts = set(observed_normalized.split())
            for candidate in candidates:
                normalized = normalize_for_matching(candidate)
                if not normalized:
                    continue
                if normalized in observed_normalized:
                    score = 1.0
                else:
                    candidate_parts = set(normalized.split())
                    token_score = len(candidate_parts & observed_parts) / max(1, len(candidate_parts))
                    score = max(token_score * 0.92, SequenceMatcher(None, normalized, observed_normalized).ratio() * 0.8)
                if score > best_score:
                    best_score, best_hit = score, candidate
            return best_score, best_hit

        for proposal in suggestions:
            observed_text = table_text_for_proposal(proposal)
            if not observed_text:
                observed_text = quick_ocr_text_for_proposal(proposal)
            scored = sorted(
                ((definition_text_score(definition, observed_text)[0], definition, definition_text_score(definition, observed_text)[1]) for definition in definitions),
                key=lambda item: item[0], reverse=True,
            )
            if scored and scored[0][0] >= 0.68 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
                proposal["suggested_panel_id"] = str(scored[0][1].get("panel_id") or "")
                proposal["suggested_panel_name"] = str(scored[0][1].get("name") or "")
                proposal["suggestion_score"] = round(scored[0][0], 3)
                proposal["suggestion_basis"] = f"snelle OCR-hit: {scored[0][2]}"
            proposal["ocr_table_text"] = observed_text

        return {
            "panel_state": panel_state,
            "sources": sources,
            "source": selected,
            "source_id": selected_source_id,
            "region_ground_truth": region_ground_truth,
            "table_review_sources": table_review_sources,
            "suggestions": suggestions,
            "detection_info": detection_info,
        }

    register_table_panel_review_routes(
        app,
        table_panel_review_context=_table_panel_review_context,
    )

    @app.route("/process/<step_key>", methods=["GET", "POST"])
    def process_step(step_key: str):
        legacy_step_aliases = {
            "localization-validate": "localization-dataset",
            "localization-train": "localization-dataset",
            "localization-compare": "localization-evaluate",
        }
        if step_key in legacy_step_aliases:
            if request.method != "GET":
                abort(405)
            return redirect(url_for("process_step", step_key=legacy_step_aliases[step_key]))
        if step_key == "value-extract" and request.method == "GET":
            return redirect(url_for("process_step", step_key="apply-mapping"))
        step = PROCESS_STEP_BY_KEY.get(step_key)
        if step is None:
            abort(404)
        if step_key == "detection-review" and request.method == "GET":
            return redirect(url_for("detection_review_index"))

        if step_key == "input-selection":
            if request.method == "POST":
                selected = {
                    str(value).strip().replace("\\", "/")
                    for value in request.form.getlist("selected_file")
                    if str(value).strip()
                }
                available = {str(item["key"]) for item in input_selection_state()["files"]}
                selected &= available
                payload = selection_payload(selected)
                payload["updated_at"] = _utcnow()
                input_selection_path().parent.mkdir(parents=True, exist_ok=True)
                input_selection_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
                flash(f"Inputselectie opgeslagen: {len(selected)} van {len(available)} afbeeldingen geselecteerd.", "success")
                if request.form.get("open_panel") == "1":
                    return redirect(url_for("process_step", step_key="panel-setup"))
                if request.form.get("start_processing") == "1":
                    if loaded_config is None:
                        flash("Bronpreview kan niet worden voorbereid: de actieve configuratie ontbreekt.", "error")
                        return redirect(url_for("process_step", step_key="input-selection"))
                    try:
                        result = prepare_source_renders("/input", workspace_root(), loaded_config)
                        flash(f"{result['sources']} volledige bronpreview(s) voorbereid. Stap 2 voor tabelregio’s is nu beschikbaar.", "success")
                        return redirect(url_for("process_step", step_key="panel-setup"))
                    except Exception as exc:
                        _record_webui_error("source_render_prepare", exc)
                        flash(f"Bronpreview voorbereiden mislukt: {type(exc).__name__}: {exc}", "error")
                        return redirect(url_for("process_step", step_key="input-selection"))
                return redirect(url_for("process_step", step_key="input-selection"))
            selection = input_selection_state()
            existing_sources = {str(item["source_id"]) for item in database.list_detection_sources()}
            for item in selection["files"]:
                item["processed"] = item["source_id"] in existing_sources
                if item["processed"]:
                    item["preview_url"] = url_for("source_render", source_id=item["source_id"])
                elif Path(item["key"]).suffix.lower() in {".dcm", ".dicom", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
                    item["preview_url"] = url_for("input_preview", relative_path=item["key"])
            return render_template(
                "input_selection.html", step=step, selection=selection,
                header_counts={
                    "total": selection["total"],
                    "pending": selection["new"],
                    "accepted": selection["selected"],
                },
                header_total_label="afbeeldingen", header_pending_label="nieuw",
                header_accepted_label="geselecteerd",
            )

        header_status_filter = str(request.args.get("header_status", "pending")).strip().lower()
        if header_status_filter not in {"all", "pending", "accepted", "rejected", "deferred"}:
            abort(400)
        header_source_filter = str(request.args.get("source_id", "")).strip()[:160]
        header_sample_filter = str(request.args.get("sample_id", "")).strip()[:260]
        header_method_filter = str(request.args.get("extraction_method", "all")).strip().lower()
        if header_method_filter not in {"all", "fallback", "dynamic"}:
            abort(400)

        if request.method == "POST":
            if step_key == "table-quality":
                roles = dict(table_studio_roles(workspace_root()))
                rows = dict(table_studio_rows(workspace_root()))
                table_ids = {str(value) for value in request.form.getlist("table_definition") if str(value)}
                for table_id in table_ids:
                    roles[table_id] = {}
                    rows[table_id] = []
                for value in request.form.getlist("table_role"):
                    table_id, separator, remainder = str(value).partition("|")
                    column, separator2, role = remainder.partition("|")
                    if not separator or not separator2 or not column.isdigit():
                        continue
                    if role in {"label", "value", "unit", "header", "skip"}:
                        roles.setdefault(table_id, {})[column] = role
                for value in request.form.getlist("table_row"):
                    table_id, separator, row = str(value).partition("|")
                    if separator and row.isdigit():
                        rows.setdefault(table_id, []).append(int(row))
                save_table_studio_roles(workspace_root(), roles, rows=rows)
                recognition_tables = {
                    table_id: {
                        "rows": rows.get(table_id, []),
                        "columns": sorted(
                            int(column) for column, role in table_roles.items()
                            if role in {"label", "value", "unit", "header"}
                        ),
                    }
                    for table_id, table_roles in roles.items()
                }
                save_recognition_scope(workspace_root(), recognition_tables)
                included = sum(len(item["rows"]) * len(item["columns"]) for item in recognition_tables.values())
                flash(f"Tabeldefinitie en Recognition-scope opgeslagen ({included} rasterposities geselecteerd).", "success")
                return redirect(url_for("process_step", step_key=step_key, source_id=request.form.get("source_id", "")))
            if step_key == "table-compare":
                action = str(request.form.get("comparison_action") or "").strip().lower()
                if action not in {"review_issue", "add_prediction_to_gt", "apply_functional_suggestions"}:
                    abort(400)
                run_id = str(request.form.get("run_id") or "").strip()[:180]
                issue_id = str(request.form.get("issue_id") or "").strip()[:80]
                reference = str(request.form.get("reference_run_id") or "").strip()
                candidate = str(request.form.get("candidate_run_id") or "").strip()
                if action == "apply_functional_suggestions":
                    state = table_cell_comparison_state(
                        workspace_root(),
                        reference_run_id=reference or None,
                        candidate_run_id=candidate or run_id or None,
                    )
                    active_run = str((state.get("candidate") or {}).get("run_id") or "")
                    allowed_ids = set((state.get("functional_suggestions") or {}).get("issue_ids") or [])
                    requested_ids = {
                        str(value).strip()[:80]
                        for value in request.form.getlist("issue_id")
                        if str(value).strip()
                    }
                    selected_ids = sorted(allowed_ids.intersection(requested_ids))
                    if not state.get("ready") or not state.get("review_writable") or run_id != active_run:
                        flash("De veilige suggesties horen bij de nieuwste, schrijfbare detectierun.", "error")
                    elif not selected_ids:
                        flash("Er zijn geen geldige, nog open functionele suggesties om toe te passen.", "warning")
                    else:
                        for suggested_issue_id in selected_ids:
                            review_comparison_issue(workspace_root(), run_id, suggested_issue_id, "functional_ok")
                        flash(
                            f"{len(selected_ids)} veilige geometrieën als functioneel correct gemarkeerd. "
                            "Ground Truth en trainingsfeedback zijn niet gewijzigd.",
                            "success",
                        )
                    parameters = {}
                    if reference:
                        parameters["reference"] = reference
                    if candidate:
                        parameters["candidate"] = candidate
                    return redirect(url_for("process_step", step_key=step_key, **parameters))
                wants_json = (
                    request.headers.get("X-Requested-With") == "XMLHttpRequest"
                    or request.accept_mimetypes.best == "application/json"
                )
                effective_decision = ""
                promoted: dict[str, Any] | None = None
                error_message = ""
                message = ""
                if action == "add_prediction_to_gt":
                    try:
                        promoted = add_comparison_fp_to_ground_truth(workspace_root(), run_id, issue_id)
                    except (KeyError, ValueError, FileNotFoundError) as exc:
                        error_message = f"Prediction kon niet aan de Ground Truth worden toegevoegd: {exc}"
                    else:
                        effective_decision = "gt_added"
                        suffix = " (bestond al in GT)" if promoted.get("already_present") else ""
                        message = (
                            "Prediction toegevoegd aan de canonieke Ground Truth" + suffix +
                            ". De huidige table-cell trainingsdataset is nu verouderd; bouw hem in Stap 5 opnieuw."
                        )
                else:
                    decision = str(request.form.get("decision") or "").strip().lower()
                    try:
                        review_comparison_issue(workspace_root(), run_id, issue_id, decision)
                    except (KeyError, ValueError) as exc:
                        error_message = f"Vervolg-review kon niet worden opgeslagen: {exc}"
                    else:
                        effective_decision = "" if decision == "clear" else decision
                        labels = {
                            "model_error": "Modelmisser bevestigd",
                            "functional_ok": "Geometrie functioneel correct bevonden",
                            "gt_check": "Gemarkeerd voor Ground Truth-controle",
                            "gt_added": "Prediction toegevoegd aan Ground Truth",
                            "deferred": "Beoordeling uitgesteld",
                            "clear": "Beoordeling gewist",
                        }
                        message = labels.get(decision, "Vervolg-review opgeslagen")

                if wants_json:
                    if error_message:
                        return jsonify({"ok": False, "error": error_message}), 409
                    state = table_cell_comparison_state(
                        workspace_root(),
                        reference_run_id=reference or None,
                        candidate_run_id=candidate or run_id or None,
                    )
                    return jsonify({
                        "ok": True,
                        "message": message,
                        "decision": effective_decision,
                        "already_present": bool((promoted or {}).get("already_present")),
                        "counts": {
                            "open_issue_count": int(state.get("open_issue_count") or 0),
                            "reviewed_issue_count": int(state.get("reviewed_issue_count") or 0),
                            "issue_count": int(state.get("issue_count") or 0),
                        },
                    })

                if error_message:
                    flash(error_message, "error")
                else:
                    flash(message, "success")
                parameters = {}
                if reference:
                    parameters["reference"] = reference
                if candidate:
                    parameters["candidate"] = candidate
                return redirect(url_for("process_step", step_key=step_key, **parameters))
            if step_key == "localization-dataset":
                split_action = str(request.form.get("split_action") or "save").strip().lower()
                try:
                    if split_action == "auto":
                        plan = save_localization_split_config(workspace_root(), mode="auto", overrides={})
                        flash(
                            f"Veilige automatische split toegepast: {plan['counts']['train']} train / "
                            f"{plan['counts']['val']} val / {plan['counts']['test']} test.",
                            "success",
                        )
                    elif split_action == "save":
                        targets = {
                            "train": int(request.form.get("split_train") or 0),
                            "val": int(request.form.get("split_val") or 0),
                            "test": int(request.form.get("split_test") or 0),
                        }
                        source_ids = request.form.getlist("split_source_id")
                        choices = request.form.getlist("split_choice")
                        overrides = {
                            str(source_id): str(choice)
                            for source_id, choice in zip(source_ids, choices)
                            if str(choice) in {"train", "val", "test"}
                        }
                        plan = save_localization_split_config(
                            workspace_root(), mode="counts", targets=targets, overrides=overrides
                        )
                        flash(
                            f"Dataset-split opgeslagen: {plan['counts']['train']} train / "
                            f"{plan['counts']['val']} val / {plan['counts']['test']} test. "
                            "Bouw de localization-dataset opnieuw om deze verdeling vast te leggen.",
                            "success",
                        )
                    else:
                        abort(400)
                except (TypeError, ValueError) as exc:
                    flash(f"Dataset-split kon niet worden opgeslagen: {exc}", "error")
                return redirect(url_for("process_step", step_key=step_key))
            if step_key != "header-normalization":
                abort(405)
            if header_profile is None:
                flash("Het actieve profiel kon niet worden geladen; normalisatietraining is niet beschikbaar.", "error")
                return redirect(url_for("process_step", step_key=step_key))

            action = str(request.form.get("header_action", "save")).strip().lower()
            sample_ids = request.form.getlist("header_sample_id")
            saved = 0
            rejected = 0
            for sample_id in sample_ids:
                current = database.get(sample_id)
                if current is None:
                    continue
                selected = str(request.form.get(f"header_status_{sample_id}", "accepted")).strip().lower()
                if action == "accept_visible":
                    selected = "accepted"
                target = str(
                    request.form.get(
                        f"header_target_{sample_id}",
                        current.get("header_target_field_key") or current.get("field_key") or "",
                    )
                ).strip()
                exact = str(request.form.get(f"header_exact_{sample_id}", ""))
                notes = str(request.form.get(f"header_notes_{sample_id}", ""))
                try:
                    database.review_header(sample_id, selected, target, exact, notes)
                    saved += 1
                    rejected += int(selected == "rejected")
                except ValueError as exc:
                    flash(f"Rijheader {sample_id} kon niet worden opgeslagen: {exc}", "error")

            trained_payload: dict[str, Any] | None = None
            if action in {"train", "train_redetect"}:
                trained_payload = build_header_normalization_model(
                    database.header_training_rows(), header_profile, header_model_path()
                )
                if trained_payload.get("included_example_count", 0) > 0:
                    flash(
                        f"Normalisatiemodel opgebouwd met {trained_payload.get('included_example_count', 0)} "
                        f"beoordeelde voorbeelden en {trained_payload.get('learned_alias_count', 0)} geleerde aliassen.",
                        "success",
                    )
                else:
                    flash(
                        "Het model is opgeslagen, maar bevat nog geen bruikbare bevestigde rijheaders.",
                        "warning",
                    )
                if trained_payload.get("conflicts"):
                    flash(
                        f"{len(trained_payload['conflicts'])} dubbelzinnige alias(sen) zijn uit veiligheid niet geactiveerd.",
                        "warning",
                    )

            queued_job: dict[str, Any] | None = None
            if action == "train_redetect":
                queued_job = enqueue_job("2")
                flash(
                    "Nieuwe normalisatie is actief. DICOM-detectie is opnieuw in de wachtrij geplaatst.",
                    "success",
                )
            elif action in {"save", "accept_visible"}:
                flash(
                    f"{saved} rijheaderbeoordeling(en) opgeslagen"
                    + (f"; {rejected} uitgesloten" if rejected else "")
                    + ".",
                    "success",
                )

            parameters = {"header_status": header_status_filter}
            if header_source_filter:
                parameters["source_id"] = header_source_filter
            if header_sample_filter:
                parameters["sample_id"] = header_sample_filter
            if header_method_filter != "all":
                parameters["extraction_method"] = header_method_filter
            if queued_job:
                parameters["job_id"] = str(queued_job["job_id"])
            return redirect(url_for("process_step", step_key=step_key, **parameters))

        if step_key == "panel-setup":
            panel_state = table_panel_state()
            context = _table_panel_review_context(str(request.args.get("source_id") or ""), panel_state)
            region_sources = list_table_region_sources(workspace_root())
            region_total = sum(int(item.get("region_count") or 0) for item in region_sources)
            expected_sources = database.list_detection_sources()
            region_by_source = {str(item.get("source_id") or ""): item for item in region_sources}
            region_pending = sum(
                1 for item in expected_sources
                if not bool(region_by_source.get(str(item.get("source_id") or ""), {}).get("review_completed"))
                or not bool(region_by_source.get(str(item.get("source_id") or ""), {}).get("region_count"))
            )
            return render_template(
                "table_panel_setup.html", step=step, panel_state=panel_state,
                panel_profile=panel_state.get("profile") or {}, sources=context["sources"], source=context["source"],
                source_id=context["source_id"], suggestions=context["suggestions"],
                detection_info=context["detection_info"],
                region_ground_truth=context["region_ground_truth"],
                table_review_sources=context["table_review_sources"],
                header_counts={
                    "total": region_total,
                    "pending": region_pending,
                    "accepted": region_total,
                },
                header_total_label="regio’s", header_pending_label="lezingen open", header_accepted_label="opgeslagen",
            )

        if step_key == "table-region-model":
            region_sources = list_table_region_sources(workspace_root())
            dataset = None
            latest_pointer = workspace_root() / "table_region_datasets" / "latest.txt"
            try:
                dataset_id = latest_pointer.read_text(encoding="ascii").strip()
            except OSError:
                dataset_id = ""
            if dataset_id:
                dataset = _read_json(workspace_root() / "table_region_datasets" / dataset_id / "manifest.json", None)
            reviewed_sources = [item for item in region_sources if item.get("review_completed")]
            return render_template(
                "table_region_training.html", step=step,
                region_sources=region_sources, reviewed_sources=reviewed_sources,
                dataset=dataset,
                header_counts={
                    "total": sum(int(item.get("region_count") or 0) for item in reviewed_sources),
                    "pending": max(0, len(sources := database.list_detection_sources()) - len(reviewed_sources)),
                    "accepted": int((dataset or {}).get("annotation_count") or 0),
                },
                header_total_label="tabelregio’s", header_pending_label="lezingen open",
                header_accepted_label="trainingskaders",
            )

        if step_key == "table-quality":
            quality = current_table_first_quality()
            preview = recognition_scope_preview(workspace_root())
            semantic_assignments = load_table_semantic_assignments(workspace_root())
            # The persisted table raster is authoritative here. Do not rebuild
            # rows and columns by clustering canonical GT cells.
            studio_source_id = str(preview.get("source_id") or "")
            geometry = database.list_detection_table_geometry(studio_source_id) if studio_source_id else {"regions": [], "cells": []}
            profile = load_panel_profile(workspace_root())
            reference_width = float(profile.get("reference_width") or 0)
            reference_height = float(profile.get("reference_height") or 0)
            named_tables: dict[str, dict[str, Any]] = {}
            for region in geometry.get("regions", []):
                center_x = (float(region.get("x1") or 0) + float(region.get("x2") or 0)) / 2
                center_y = (float(region.get("y1") or 0) + float(region.get("y2") or 0)) / 2
                for panel in profile.get("panels") or []:
                    if (
                        float(panel.get("x1") or 0) * reference_width <= center_x <= float(panel.get("x2") or 0) * reference_width
                        and float(panel.get("y1") or 0) * reference_height <= center_y <= float(panel.get("y2") or 0) * reference_height
                    ):
                        named_tables[str(region.get("table_id") or "")] = panel
                        break
            table_groups: dict[str, list[dict[str, Any]]] = {}
            for cell in geometry.get("cells", []):
                raw_table_id = str(cell.get("table_id") or "")
                panel = named_tables.get(raw_table_id) or {}
                table_id = str(panel.get("panel_id") or raw_table_id or "__default__")
                table_groups.setdefault(table_id, []).append({
                    **cell, "panel_id": table_id,
                    "panel_name": str(panel.get("name") or table_id),
                })

            def indexed_cells(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
                """Use persisted row/column indices; infer only for legacy records.

                Older canonical GT records store exact boxes but predate the
                optional row_index/column_index fields. Tabelstudio needs
                stable visual grouping, so infer the indices from box centers
                without changing the canonical GT file.
                """
                usable = [dict(cell) for cell in cells]
                if all("row_index" in item and "column_index" in item for item in usable):
                    return usable
                heights = [
                    max(1, int(item.get("y2") or 0) - int(item.get("y1") or 0))
                    for item in usable
                ]
                widths = [
                    max(1, int(item.get("x2") or 0) - int(item.get("x1") or 0))
                    for item in usable
                ]
                row_tolerance = max(6.0, (sum(heights) / max(1, len(heights))) * 0.75)
                column_tolerance = max(8.0, (sum(heights) / max(1, len(heights))) * 1.5)

                def cluster(items: list[dict[str, Any]], center_key: str, tolerance: float) -> list[list[dict[str, Any]]]:
                    groups: list[list[dict[str, Any]]] = []
                    for item in sorted(items, key=lambda value: float(value[center_key])):
                        center = float(item[center_key])
                        if not groups:
                            groups.append([item])
                            continue
                        previous_center = sum(float(value[center_key]) for value in groups[-1]) / len(groups[-1])
                        if center - previous_center <= tolerance:
                            groups[-1].append(item)
                        else:
                            groups.append([item])
                    return groups

                for item in usable:
                    item["_center_y"] = (int(item.get("y1") or 0) + int(item.get("y2") or 0)) / 2
                    item["_center_x"] = (int(item.get("x1") or 0) + int(item.get("x2") or 0)) / 2
                rows = cluster(usable, "_center_y", row_tolerance)
                columns = cluster(usable, "_center_x", column_tolerance)
                for row_index, row in enumerate(rows):
                    for item in row:
                        item["row_index"] = row_index
                for column_index, column in enumerate(columns):
                    for item in column:
                        item["column_index"] = column_index
                for item in usable:
                    item.pop("_center_y", None)
                    item.pop("_center_x", None)
                return usable

            def axis_groups(cells: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
                groups: dict[int, list[dict[str, Any]]] = {}
                for cell in cells:
                    groups.setdefault(int(cell.get(key, -1)), []).append(cell)
                result = [
                    {"index": index, "cells": sorted(items, key=lambda item: int(item.get("column_index" if key == "row_index" else "row_index", -1))),
                     "x1": min(int(item.get("x1") or 0) for item in items), "y1": min(int(item.get("y1") or 0) for item in items),
                     "x2": max(int(item.get("x2") or 0) for item in items), "y2": max(int(item.get("y2") or 0) for item in items)}
                    for index, items in sorted(groups.items()) if index >= 0
                ]
                if key == "column_index":
                    # Adjacent raster columns share one boundary. Detection
                    # boxes can overlap by a few pixels; never expose that
                    # overlap as a semantic column boundary in the Studio.
                    for left, right in zip(result, result[1:]):
                        left_center = (left["x1"] + left["x2"]) / 2
                        right_center = (right["x1"] + right["x2"]) / 2
                        boundary = round((left_center + right_center) / 2)
                        boundary = max(left["x1"] + 1, min(boundary, right["x2"] - 1))
                        left["x2"] = boundary
                        right["x1"] = boundary
                return result
            def table_record(table_id: str, cells: list[dict[str, Any]]) -> dict[str, Any]:
                cells = indexed_cells(cells)
                padding = 16
                fallback_name = str(cells[0].get("table_name") or cells[0].get("panel_name") or ("Tabel zonder profiel" if table_id == "__default__" else table_id))
                relations = database.list_detected_relations(studio_source_id)
                ocr_parts = []
                bounds = (min(int(item.get("x1") or 0) for item in cells), min(int(item.get("y1") or 0) for item in cells), max(int(item.get("x2") or 0) for item in cells), max(int(item.get("y2") or 0) for item in cells))
                for relation in relations:
                    cx = (int(relation.get("label_x1") or 0) + int(relation.get("label_x2") or 0)) / 2
                    cy = (int(relation.get("label_y1") or 0) + int(relation.get("label_y2") or 0)) / 2
                    if bounds[0] <= cx <= bounds[2] and bounds[1] <= cy <= bounds[3]:
                        for key in ("context_text", "label_text", "header_text", "column_header"):
                            value = str(relation.get(key) or "").strip()
                            if value and value not in ocr_parts:
                                ocr_parts.append(value)
                saved = semantic_assignments.get(table_id) or {}
                suggested_name, suggestion_source = suggest_table_name(
                    " | ".join(ocr_parts),
                    [str(item.get("name") or "") for item in profile.get("panels") or [] if str(item.get("name") or "").strip()],
                    fallback_name,
                )
                return {"table_id": table_id, "table_name": str(saved.get("table_name") or suggested_name), "table_name_source": str(saved.get("source") or suggestion_source), "ocr_header_text": " | ".join(ocr_parts), "cells": cells, "rows": axis_groups(cells, "row_index"), "columns": axis_groups(cells, "column_index"), "crop": {"x1": max(0, bounds[0] - padding), "y1": max(0, bounds[1] - padding), "x2": bounds[2] + padding, "y2": bounds[3] + padding}}
            studio = {
                "source_id": str(preview.get("source_id") or ""),
                "tables": [table_record(table_id, cells) for table_id, cells in sorted(table_groups.items())],
            }
            if str(request.args.get("view") or "").strip().lower() == "geometry":
                return render_template(
                    "table_structure.html",
                    step=step, table_quality=quality, studio=studio,
                    header_counts={
                        "total": int((quality.get("totals") or {}).get("desired_total", 0)),
                        "pending": int((quality.get("totals") or {}).get("pending", 0)),
                        "accepted": int((quality.get("totals") or {}).get("detected_desired", 0)),
                    },
                    header_total_label="doelcellen", header_pending_label="te reviewen",
                    header_accepted_label="direct gevonden",
                )
            roles = table_studio_roles(workspace_root())
            configured_rows = table_studio_rows(workspace_root())
            studio_tables = [
                {
                    **table,
                    "rows": [
                        {
                            **row,
                            "active": (
                                table["table_id"] not in configured_rows
                                or int(row["index"]) in configured_rows.get(table["table_id"], [])
                            ),
                        }
                        for row in table["rows"]
                    ],
                    "columns": [
                        {
                            **column,
                            "role": roles.get(table["table_id"], {}).get(str(column["index"]), ""),
                        }
                        for column in table["columns"]
                    ],
                }
                for table in studio["tables"]
                if table["table_id"] != "__default__"
            ]
            return render_template(
                "table_studio.html",
                step=step, table_quality=quality, studio=studio,
                studio_tables=studio_tables,
                table_roles=roles,
                table_rows=configured_rows,
                role_options=[
                    ("", "Niet ingesteld"),
                    ("label", "Label"), ("value", "Waarde"),
                    ("unit", "Eenheid"), ("header", "Koptekst"), ("skip", "Overslaan"),
                ],
                header_counts={
                    "total": len(studio_tables),
                    "pending": sum(1 for table in studio_tables for column in table["columns"] if not column["role"]),
                    "accepted": sum(1 for table in studio_tables for column in table["columns"] if column["role"]),
                },
                header_total_label="tabellen", header_pending_label="kolommen open",
                header_accepted_label="rollen gekozen",
            )

        if step_key == "table-model":
            model_state = table_cell_training_state(workspace_root())
            preview = model_state.get("preview") or {}
            dataset = model_state.get("dataset") or {}
            validation = dataset.get("validation") if isinstance(dataset, dict) else {}
            validation = validation if isinstance(validation, dict) else {}
            latest_model = model_state.get("latest_model") or {}
            evaluation = latest_model.get("evaluation") if isinstance(latest_model, dict) else {}
            evaluation = evaluation if isinstance(evaluation, dict) else {}
            dataset_current = bool(model_state.get("dataset_current"))
            build_ready = bool(preview.get("ready"))
            validate_ready = bool(dataset and dataset_current)
            train_ready = bool(validate_ready and validation.get("valid"))
            model_for_current_dataset = bool(
                latest_model.get("model_id") and dataset.get("dataset_id")
                and str(latest_model.get("dataset_id") or "") == str(dataset.get("dataset_id") or "")
            )
            active_is_latest = bool(
                model_for_current_dataset and (model_state.get("active_model") or {}).get("model_id")
                and str((model_state.get("active_model") or {}).get("model_id") or "") == str(latest_model.get("model_id") or "")
            )
            needs_training = bool(train_ready and not model_for_current_dataset)
            activate_ready = bool(model_for_current_dataset and not active_is_latest)
            needs_redetect = bool(model_for_current_dataset and active_is_latest)
            reasons = {
                "build": "" if build_ready else "Rond eerst de tabelreview af en zorg dat er positieve functionele cellen zijn.",
                "validate": "" if validate_ready else ("De review is gewijzigd sinds de laatste dataset. Bouw de dataset opnieuw." if dataset else "Bouw eerst de table-cell dataset."),
                "train": "" if train_ready else ("Valideer eerst de actuele table-cell dataset." if validate_ready else "Bouw eerst een actuele dataset uit de huidige reviewcorrecties."),
                "activate": "" if activate_ready else ("Dit model is al actief." if active_is_latest else "Train eerst een model op de actuele dataset."),
            }
            return render_template(
                "table_model_training.html", step=step, model_state=model_state, preview=preview,
                dataset=dataset, validation=validation, latest_model=latest_model, evaluation=evaluation,
                build_ready=build_ready, validate_ready=validate_ready, train_ready=train_ready,
                needs_training=needs_training, model_for_current_dataset=model_for_current_dataset,
                activate_ready=activate_ready, needs_redetect=needs_redetect, reasons=reasons,
                header_counts={
                    "total": int(preview.get("annotation_count") or 0),
                    "pending": 0 if dataset_current else (1 if dataset else 0),
                    "accepted": len(model_state.get("models") or []),
                },
                header_total_label="reviewcellen", header_pending_label="dataset verouderd",
                header_accepted_label="getrainde modellen",
            )

        if step_key == "table-compare":
            comparison = table_cell_comparison_state(
                workspace_root(),
                reference_run_id=str(request.args.get("reference") or "").strip() or None,
                candidate_run_id=str(request.args.get("candidate") or "").strip() or None,
            )
            candidate_metrics = ((comparison.get("candidate") or {}).get("metrics") or {}) if comparison.get("ready") else {}
            return render_template(
                "table_model_comparison.html",
                step=step, comparison=comparison,
                header_counts={
                    "total": int(candidate_metrics.get("gt_total") or 0),
                    "pending": int(comparison.get("open_issue_count") or 0),
                    "accepted": int(comparison.get("reviewed_issue_count") or 0),
                },
                header_total_label="GT-cellen", header_pending_label="afwijkingen open",
                header_accepted_label="afwijkingen beoordeeld",
            )

        if step_key == "localization-dataset":
            return render_template("react_localization_workbench.html", step=step)

        if step_key in {"localization-evaluate", "localization-register", "detection-report"}:
            return render_template("react_localization_quality.html", step=step)

        # Region predictions get their own review surface.  Keeping this out
        # of Panel Setup prevents newly detected boxes from being confused
        # with the manually accepted region GT used to train the model.
        if step_key == "detect-candidates" and localization_strategy() == "table_first":
            sources = [dict(item) for item in database.list_detection_sources()]
            requested_source_id = str(request.args.get("source_id") or "").strip()
            source = next((item for item in sources if str(item.get("source_id") or "") == requested_source_id), None)
            if source is None and sources:
                source = sources[0]
            source_id = str((source or {}).get("source_id") or "")
            geometry = database.list_detection_table_geometry(source_id) if source_id else {"regions": [], "cells": []}
            context = _table_panel_review_context(source_id)
            review_sources = []
            for item in sources:
                item_source_id = str(item.get("source_id") or "")
                item["region_count"] = len(database.list_detection_table_geometry(item_source_id).get("regions", [])) if item_source_id else 0
                review_sources.append(item)
            return render_template(
                "table_region_review.html", step=step, sources=review_sources, source=source,
                source_id=source_id, regions=geometry.get("regions", []),
                panel_profile=load_panel_profile(workspace_root()),
                ocr_contexts=database.list_detected_relations(source_id) if source_id else [],
                ground_truth_regions=list_table_regions(workspace_root(), source_id) if source_id else [],
                detection_info=context.get("detection_info") or {},
                header_counts={
                    "total": len(geometry.get("regions", [])), "pending": len(geometry.get("regions", [])),
                    "accepted": len(list_table_regions(workspace_root(), source_id)) if source_id else 0,
                },
                header_total_label="modelregio’s", header_pending_label="te beoordelen", header_accepted_label="oude GT",
            )

        if step_key == "artifacts":
            return render_management(active_tab="models")

        # Most process pages only display a handful of counters. Building the
        # full workflow snapshot here used to scan recognition runs, localization
        # artifacts, mappings, datasets and registries on every navigation. Load
        # only the state this specific page actually renders.
        state: dict[str, Any] = {}
        header_counts = None

        if step_key == "detection-models":
            state["preparation"] = preparation_for_current_strategy()
            state["panel_state"] = table_panel_state()
            state["input_file_count"] = input_source_count()
            state["registered_source_count"] = len(database.list_detection_sources())
        elif step_key in {"detect-candidates", "detection-review"}:
            detection_sources = database.list_detection_sources()
            detection_reviews = step4_review_counts()
            state.update(
                detection_sources=detection_sources,
                detection_reviews=detection_reviews,
                input_selection=input_selection_state(),
                panel_state=(table_panel_state() if localization_strategy() == "table_first" else {"configured": True, "detection_current": True}),
            )
            if step_key == "detect-candidates" and localization_strategy() == "table_first":
                state["table_model"] = table_cell_training_state(workspace_root())
            header_counts = {
                "total": int(detection_reviews.get("candidate_total", 0)) + int(detection_reviews.get("added", 0)),
                "pending": int(detection_reviews.get("pending", 0)),
                "accepted": int(detection_reviews.get("positive", 0)),
            }
        elif step_key == "redetect":
            evaluations = database.list_localization_evaluations()
            state.update(
                detection_gate=current_detection_gate(),
                localization_baseline=next((item for item in evaluations if item.get("kind") == "baseline"), None),
                localization_trained=next((item for item in evaluations if item.get("kind") == "trained"), None),
                active_localization_model=database.active_localization_model(),
            )
        elif step_key == "mapping":
            mapping = database.mapping_counts()
            state.update(detection_gate=current_pipeline_gate(), mapping=mapping)
            header_counts = {
                "total": mapping.get("relations", 0),
                "pending": mapping.get("suggested", 0),
                "accepted": mapping.get("confirmed", 0),
            }
        elif step_key in {"apply-mapping", "value-extract"}:
            mapped = mapped_sample_state()
            state.update(detection_gate=current_pipeline_gate(), mapped=mapped)
            header_counts = {
                "total": mapped.get("total", 0),
                "pending": max(0, mapped.get("total", 0) - mapped.get("roi_correct", 0)),
                "accepted": mapped.get("roi_correct", 0),
            }
        elif step_key == "value-review":
            value = value_review_counts()
            outputs = []
            for source in database.list_detection_sources():
                current_source = str(source.get("source_id") or "")
                output_path = workspace_root() / "extracted_output" / f"{current_source}.json"
                payload = _read_json(output_path, {}) if output_path.is_file() else {}
                measurements = payload.get("measurements") if isinstance(payload, dict) else {}
                if isinstance(measurements, dict) and measurements:
                    outputs.append({
                        "source_id": current_source,
                        "measurement_count": len(measurements),
                        "generated_at": payload.get("generated_at") or "",
                    })
            state.update(detection_gate=current_pipeline_gate(), value=value, outputs=outputs)
            header_counts = value
        elif step_key.startswith("recognition-"):
            _, active = registry_state()
            recognition_baseline, recognition_custom = latest_evaluations()
            state.update(
                detection_gate=current_recognition_gate(),
                pipeline_gate=current_pipeline_gate(),
                dataset=latest_dataset_info(),
                active=active,
                recognition_baseline=recognition_baseline,
                recognition_custom=recognition_custom,
                recognition_comparison=latest_comparison(),
            )
        elif step.get("group") == "value":
            state["detection_gate"] = current_pipeline_gate()

        return render_template(
            "process_step.html",
            step=step,
            actions={action_id: ACTIONS[action_id] for action_id in step["action_ids"]},
            header_counts=header_counts,
            header_total_label=("GT-cellen" if step_key == "detection-review" and canonical_table_gt_mode() else "kandidaten" if step.get("group") == "detection" else "relaties" if step_key == "mapping" else "waarden" if step_key == "value-review" else "ROI's"),
            header_pending_label=("open" if step_key == "detection-review" and canonical_table_gt_mode() else "te reviewen" if step.get("group") == "detection" else "voorgesteld" if step_key == "mapping" else "open"),
            header_accepted_label=("canonieke GT" if step_key == "detection-review" and canonical_table_gt_mode() else "ground truth" if step.get("group") == "detection" else "bevestigd" if step_key == "mapping" else "goedgekeurd"),
            **state,
        )


    def detection_review_source_rows() -> list[dict[str, Any]]:
        sources = database.list_detection_sources()
        table_counts = database.detection_table_counts_by_source()
        canonical_sources = {
            str(item["source_id"]): item
            for item in list_ground_truth_sources(workspace_root())
        } if canonical_table_gt_mode() else {}
        if localization_strategy() == "table_first":
            quality = current_table_first_quality()
            candidate_counts = {
                str(item["source_id"]): table_review_counts(str(item["source_id"]), quality)
                for item in sources
            }
        else:
            candidate_counts = database.detection_review_counts_by_source()
        result: list[dict[str, Any]] = []
        for source in sources:
            source_id = str(source["source_id"])
            gt_source = canonical_sources.get(source_id)
            geometry = table_counts.get(source_id, {"regions": 0, "cells": 0})
            is_canonical_gt = gt_source is not None
            counts = ground_truth_counts(workspace_root(), source_id) if is_canonical_gt else candidate_counts.get(source_id, {})
            result.append({
                **source,
                "review_completed": bool(gt_source.get("review_completed", False)) if gt_source else bool(source.get("review_completed", False)),
                "review_completed_at": gt_source.get("review_completed_at") if gt_source else source.get("review_completed_at"),
                "review_counts": counts,
                "table_region_count": int(geometry.get("regions", 0)),
                "table_cell_count": int(geometry.get("cells", 0)),
                "render_exists": safe_workspace_file(str(source.get("render_path") or "")).is_file(),
                "gt_mode": is_canonical_gt,
            })
        return result

    register_table_panel_config_routes(
        app,
        database=database,
        workspace_root=workspace_root,
        safe_workspace_file=safe_workspace_file,
    )

    @app.post("/api/table-region-redetect")
    def table_region_redetect_api():
        source_id = str((request.get_json(silent=True) or {}).get("source_id") or "").strip()
        if not source_id:
            return jsonify({"error": "source_id is verplicht"}), 400
        payload = enqueue_job("59", action_name="Tabelregio’s opnieuw detecteren voor beoordeling")
        return jsonify({"ok": True, "job": payload, "message": "Nieuwe voorspelling gestart; bestaande handmatige GT blijft bewaard."}), 202

    @app.post("/api/table-region-detect")
    def table_region_detect_api():
        if loaded_config is None:
            return jsonify({"error": "De actieve configuratie ontbreekt"}), 409
        try:
            result = prepare_source_renders("/input", workspace_root(), loaded_config)
        except Exception as exc:
            _record_webui_error("source_render_prepare_for_table_detection", exc)
            return jsonify({"error": f"Bronrenders konden niet worden voorbereid: {type(exc).__name__}: {exc}"}), 500
        payload = enqueue_job("59", action_name="Tabelregio’s detecteren voor beoordeling")
        return jsonify({"ok": True, "job": payload, "sources": result.get("sources", 0), "message": "Bronrenders voorbereid; alleen tabelregio-detectie gestart."}), 202

    @app.post("/api/table-region-detect-source")
    def table_region_detect_source_api():
        if loaded_config is None:
            return jsonify({"error": "De actieve configuratie ontbreekt"}), 409
        source_id = str((request.get_json(silent=True) or {}).get("source_id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", source_id):
            return jsonify({"error": "Ongeldig source_id"}), 400
        try:
            prepare_source_renders("/input", workspace_root(), loaded_config)
        except Exception as exc:
            _record_webui_error("source_render_prepare_for_single_table_detection", exc)
            return jsonify({"error": f"Bronrenders konden niet worden voorbereid: {type(exc).__name__}: {exc}"}), 500
        payload = enqueue_job(
            "59",
            {"source_id": source_id},
            action_name="Alleen huidige bron · tabelregio’s detecteren",
        )
        return jsonify({"ok": True, "job": payload, "message": f"Alleen bron {source_id} opnieuw op tabelregio’s detecteren gestart."}), 202

    @app.get("/detection-review")
    def detection_review_index():
        rows = detection_review_source_rows()
        gt_mode = canonical_table_gt_mode()
        completed_source_count = sum(1 for row in rows if bool(row.get("review_completed")))
        open_source_count = max(0, len(rows) - completed_source_count)
        return render_template(
            "detection_review_index.html",
            sources=rows, gt_mode=gt_mode,
            completed_source_count=completed_source_count, open_source_count=open_source_count,
            header_counts={
                "total": sum(int(row["review_counts"].get("positive", 0)) for row in rows) if gt_mode else sum(int(row["review_counts"].get("candidate_total", 0)) + int(row["review_counts"].get("added", 0)) for row in rows),
                "pending": 0 if gt_mode else sum(int(row["review_counts"].get("pending", 0)) for row in rows),
                "accepted": sum(int(row["review_counts"].get("positive", 0)) for row in rows),
            },
            review_counts_global={"negative": sum(int(row["review_counts"].get("negative", 0)) for row in rows)},
            header_total_label=("GT-cellen" if gt_mode else "kandidaten"),
            header_pending_label=("open" if gt_mode else "onbeoordeeld"),
            header_accepted_label=("canonieke GT" if gt_mode else "positief"),
        )

    @app.get("/detection-review/<source_id>")
    def detection_review_studio(source_id: str):
        source = database.get_detection_source(source_id)
        if source is None:
            abort(404)
        canonical_gt_sources = {
            str(item.get("source_id") or ""): item
            for item in list_ground_truth_sources(workspace_root())
        } if canonical_table_gt_mode() else {}
        gt_source = canonical_gt_sources.get(source_id)
        gt_mode = gt_source is not None
        if gt_mode:
            source = {
                **source,
                "review_completed": bool(gt_source.get("review_completed", False)),
                "review_completed_at": gt_source.get("review_completed_at"),
            }
        # New sources remain detector-review sources until a reviewer explicitly
        # creates canonical GT. Their model output is never discarded or mistaken
        # for Ground Truth.
        candidates = [] if gt_mode else database.list_detection_candidates(source_id, include_rejected=True)
        annotations = database.list_detection_annotations(source_id, active_only=True, include_ignored=True)
        geometry = database.list_detection_table_geometry(source_id)
        preprocessing_benchmark: dict[str, Any] = {"enabled": False}
        if localization_strategy() == "table_first":
            diagnostic_path = safe_workspace_file(Path("localization_detections") / f"{source_id}.json")
            if diagnostic_path.is_file():
                try:
                    diagnostic_payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
                    raw_benchmark = diagnostic_payload.get("preprocessing_benchmark")
                    if isinstance(raw_benchmark, dict):
                        preprocessing_benchmark = raw_benchmark
                except (OSError, ValueError, TypeError):
                    pass

        # Structural review assist: infer stable row/column bounds from all Paddle
        # cells. This powers Smart Fit and conservative missing-cell suggestions.
        cell_by_id = {str(item.get("cell_id")): item for item in geometry.get("cells", [])}
        tables_for_assist: dict[str, dict[str, Any]] = {}
        if localization_strategy() == "table_first":
            from statistics import median
            grouped: dict[str, list[dict[str, Any]]] = {}
            for cell in geometry.get("cells", []):
                grouped.setdefault(str(cell.get("table_id") or ""), []).append(cell)
            for table_id, cells in grouped.items():
                rows: dict[int, list[dict[str, Any]]] = {}
                columns: dict[int, list[dict[str, Any]]] = {}
                for cell in cells:
                    rows.setdefault(int(cell.get("row_index", -1)), []).append(cell)
                    columns.setdefault(int(cell.get("column_index", -1)), []).append(cell)
                multi_rows = {idx: items for idx, items in rows.items() if len(items) >= 2}
                # The structure view must expose every geometrically inferred
                # column, including sparse columns and columns containing a
                # merged cell.  Coverage thresholds are useful for conservative
                # missing-cell suggestions, but must not hide real columns from
                # the structural review.
                canonical_columns = sorted(idx for idx in columns if idx >= 0)
                column_bounds = {
                    idx: [int(round(median([int(c["x1"]) for c in items]))), int(round(median([int(c["x2"]) for c in items])))]
                    for idx, items in columns.items() if idx in canonical_columns
                }
                row_bounds = {
                    idx: [int(round(median([int(c["y1"]) for c in items]))), int(round(median([int(c["y2"]) for c in items])))]
                    for idx, items in rows.items() if idx >= 0
                }
                suggestions: list[dict[str, Any]] = []
                for row_idx, row_cells in multi_rows.items():
                    present = {int(c.get("column_index", -1)) for c in row_cells}
                    for col_idx in canonical_columns:
                        if col_idx in present or col_idx not in column_bounds or row_idx not in row_bounds:
                            continue
                        x1, x2 = column_bounds[col_idx]; y1, y2 = row_bounds[row_idx]
                        if x2 - x1 >= 4 and y2 - y1 >= 4:
                            suggestions.append({
                                "table_id": table_id, "row_index": row_idx, "column_index": col_idx,
                                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                            })
                tables_for_assist[table_id] = {
                    "canonical_columns": canonical_columns,
                    "column_bounds": column_bounds,
                    "row_bounds": row_bounds,
                    "table_bounds": [
                        min(int(cell["x1"]) for cell in cells), min(int(cell["y1"]) for cell in cells),
                        max(int(cell["x2"]) for cell in cells), max(int(cell["y2"]) for cell in cells),
                    ] if cells else [0, 0, 0, 0],
                    "row_count": len(row_bounds),
                    "column_count": len(canonical_columns),
                    "cell_count": len(cells),
                    "suggestions": suggestions,
                }
        # In legacy detector mode, detached reviewed annotations remain first-class
        # ground truth. In table-first mode, only manual cells added after the
        # current Step-2 detection pass belong to this experiment; older field-box
        # ground truth stays preserved in SQLite but is intentionally hidden here.
        if gt_mode:
            manual_annotations = [
                {
                    **item,
                    "annotation_id": str(item.get("gt_id") or ""),
                    "training_role": "positive",
                    "provenance": str(item.get("provenance") or "canonical_gt"),
                    "candidate_id": "",
                }
                for item in list_ground_truth_cells(workspace_root(), source_id)
            ]
        elif localization_strategy() == "table_first":
            detected_at = str(source.get("detected_at") or "")
            manual_annotations = [
                item for item in annotations
                if not str(item.get("candidate_id") or "")
                and str(item.get("provenance") or "") == "added"
                and (not detected_at or str(item.get("created_at") or "") >= detected_at)
            ]
        else:
            manual_annotations = [item for item in annotations if not str(item.get("candidate_id") or "")]
        for item in candidates:
            status = str(item.get("review_status") or "pending")
            if status == "adjusted":
                item["display_x1"] = int(item.get("corrected_x1") or item["x1"])
                item["display_y1"] = int(item.get("corrected_y1") or item["y1"])
                item["display_x2"] = int(item.get("corrected_x2") or item["x2"])
                item["display_y2"] = int(item.get("corrected_y2") or item["y2"])
            else:
                item["display_x1"] = int(item["x1"]); item["display_y1"] = int(item["y1"])
                item["display_x2"] = int(item["x2"]); item["display_y2"] = int(item["y2"])
            item["review_status"] = status
            item["relevance_status"] = str(item.get("relevance_status") or ("unreviewed" if status == "pending" else "relevant"))
            item["reason_label"] = DETECTION_REVIEW_REASONS.get(str(item.get("reason_code") or ""), "")
            item["relevance_reason_label"] = DETECTION_RELEVANCE_REASONS.get(str(item.get("relevance_reason") or ""), "")
            if localization_strategy() == "table_first":
                cell_id = ""
                for ref in item.get("source_refs") or []:
                    parts = str(ref).split(":")
                    if len(parts) >= 4 and parts[0] == "table" and parts[2] == "cell":
                        cell_id = parts[3]; break
                cell = cell_by_id.get(cell_id) or {}
                item["table_id"] = str(cell.get("table_id") or "")
                item["cell_id"] = cell_id
                item["row_index"] = int(cell.get("row_index", -1))
                item["column_index"] = int(cell.get("column_index", -1))
                assist = tables_for_assist.get(item["table_id"], {})
                rb = (assist.get("row_bounds") or {}).get(item["row_index"])
                cb = (assist.get("column_bounds") or {}).get(item["column_index"])
                item["smart_box"] = [cb[0], rb[0], cb[1], rb[1]] if rb and cb else None
        counts = step4_review_counts(source_id)
        # The canonical GT Studio is the full source-review editor. Keep the
        # compact React page available only as an explicit compatibility view.
        if request.args.get("view", "legacy").strip().lower() != "legacy":
            studio_sources = (
                [
                    {"source_id": str(item["source_id"]), "review_completed": bool(item.get("review_completed"))}
                    for item in database.list_detection_sources()
                ]
                if gt_mode else
                [
                    {"source_id": str(item["source_id"]), "review_completed": bool(item.get("review_completed"))}
                    for item in database.list_detection_sources()
                ]
            )
            return render_template(
                "gt_studio.html", source=source, source_id=source_id,
                candidates=candidates, manual_annotations=manual_annotations,
                sources=studio_sources, gt_mode=gt_mode,
            )
        return render_template(
            "detection_review_studio.html",
            source=source, source_id=source_id, candidates=candidates, gt_mode=gt_mode,
            manual_annotations=manual_annotations,
            table_regions=geometry["regions"], table_cells=geometry["cells"],
            table_assist=tables_for_assist,
            preprocessing_benchmark=preprocessing_benchmark, panel_state=table_panel_state(),
            reconstructed_suggestions=[] if gt_mode else [item for table in tables_for_assist.values() for item in table.get("suggestions", [])],
            reasons=DETECTION_REVIEW_REASONS, relevance_reasons=DETECTION_RELEVANCE_REASONS, review_counts=counts,
            sources=(
                [
                    {"source_id": str(item["source_id"]), "review_completed": bool(item.get("review_completed"))}
                    for item in database.list_detection_sources()
                ]
                if gt_mode else
                [
                    {"source_id": str(item["source_id"]), "review_completed": bool(item.get("review_completed"))}
                    for item in database.list_detection_sources()
                ]
            ),
            header_counts={
                "total": int(counts.get("positive", 0)) if gt_mode else int(counts.get("candidate_total", 0)) + int(counts.get("added", 0)),
                "pending": 0 if gt_mode else int(counts.get("pending", 0)),
                "accepted": int(counts.get("positive", 0)),
            },
            header_total_label=("GT-cellen" if gt_mode else "kandidaten"), header_pending_label=("open" if gt_mode else "te reviewen"), header_accepted_label="ground truth",
        )

    @app.post("/api/detection-review/<source_id>/<candidate_id>")
    def detection_review_candidate_api(source_id: str, candidate_id: str):
        payload = request.get_json(silent=True) or {}
        status = str(payload.get("status") or "").strip().lower()
        reason = str(payload.get("reason_code") or "").strip().lower()
        relevance_status = str(payload.get("relevance_status") or "relevant").strip().lower()
        relevance_reason = str(payload.get("relevance_reason") or "").strip().lower()
        notes = str(payload.get("notes") or "")[:2000]
        box_payload = payload.get("box")
        corrected_box = None
        if isinstance(box_payload, list) and len(box_payload) == 4:
            corrected_box = tuple(int(round(float(value))) for value in box_payload)
        try:
            item = database.review_detection_candidate(
                source_id=source_id, candidate_id=candidate_id, review_status=status,
                corrected_box=corrected_box, reason_code=reason,
                relevance_status=relevance_status, relevance_reason=relevance_reason, notes=notes,
            )
        except KeyError:
            return jsonify({"ok": False, "error": "Kandidaat niet gevonden"}), 404
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "candidate": item, "counts": step4_review_counts(source_id)})

    @app.post("/api/detection-review/<source_id>/batch")
    def detection_review_batch_api(source_id: str):
        payload = request.get_json(silent=True) or {}
        raw_ids = payload.get("candidate_ids")
        if not isinstance(raw_ids, list):
            return jsonify({"ok": False, "error": "candidate_ids moet een lijst zijn"}), 400
        candidate_ids = []
        seen = set()
        for raw in raw_ids:
            candidate_id = str(raw or "").strip()
            if candidate_id and candidate_id not in seen:
                candidate_ids.append(candidate_id); seen.add(candidate_id)
        if not candidate_ids:
            return jsonify({"ok": False, "error": "Selecteer minimaal één kandidaat"}), 400
        if len(candidate_ids) > 2000:
            return jsonify({"ok": False, "error": "Maximaal 2000 kandidaten per batch"}), 400
        operation = str(payload.get("operation") or "").strip().lower()
        if operation not in {"confirm", "reject", "irrelevant", "relevant"}:
            return jsonify({"ok": False, "error": "Onbekende batchactie"}), 400
        reason = str(payload.get("reason_code") or "").strip().lower()
        relevance_reason = str(payload.get("relevance_reason") or "").strip().lower()
        notes = str(payload.get("notes") or "")[:2000]
        if reason and reason not in DETECTION_REVIEW_REASONS:
            return jsonify({"ok": False, "error": "Onbekende detectiereden"}), 400
        if relevance_reason and relevance_reason not in DETECTION_RELEVANCE_REASONS:
            return jsonify({"ok": False, "error": "Onbekende relevantieregel"}), 400
        current = {str(item["candidate_id"]): item for item in database.list_detection_candidates(source_id, include_rejected=True)}
        missing = [candidate_id for candidate_id in candidate_ids if candidate_id not in current]
        if missing:
            return jsonify({"ok": False, "error": f"Kandidaat niet gevonden: {missing[0]}"}), 404
        updated = []
        try:
            for candidate_id in candidate_ids:
                candidate = current[candidate_id]
                current_status = str(candidate.get("review_status") or "pending")
                preserve_adjusted = current_status == "adjusted"
                corrected_box = None
                if preserve_adjusted:
                    corrected_box = (
                        int(candidate.get("corrected_x1") or candidate["x1"]),
                        int(candidate.get("corrected_y1") or candidate["y1"]),
                        int(candidate.get("corrected_x2") or candidate["x2"]),
                        int(candidate.get("corrected_y2") or candidate["y2"]),
                    )
                if operation == "reject":
                    status, relevance, scope_reason = "rejected", "unreviewed", ""
                    review_reason = reason
                elif operation == "irrelevant":
                    status = "adjusted" if preserve_adjusted else "correct"
                    relevance, scope_reason = "irrelevant", relevance_reason
                    review_reason = str(candidate.get("reason_code") or "") if preserve_adjusted else ""
                elif operation == "relevant":
                    status = "adjusted" if preserve_adjusted else "correct"
                    relevance, scope_reason = "relevant", ""
                    review_reason = str(candidate.get("reason_code") or "") if preserve_adjusted else ""
                else:
                    status = "adjusted" if preserve_adjusted else "correct"
                    relevance, scope_reason = "relevant", ""
                    review_reason = str(candidate.get("reason_code") or "") if preserve_adjusted else ""
                updated.append(database.review_detection_candidate(
                    source_id=source_id, candidate_id=candidate_id, review_status=status,
                    corrected_box=corrected_box, reason_code=review_reason,
                    relevance_status=relevance, relevance_reason=scope_reason,
                    notes=notes if notes else str(candidate.get("review_notes") or ""),
                ))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "updated": len(updated), "candidates": updated, "counts": step4_review_counts(source_id)})

    @app.post("/api/detection-review/<source_id>/complete")
    def detection_review_complete_api(source_id: str):
        payload = request.get_json(silent=True) or {}
        completed = bool(payload.get("completed", True))
        try:
            if canonical_table_gt_mode():
                source = set_ground_truth_source_review_completed(workspace_root(), source_id, completed)
            else:
                source = database.set_detection_source_review_completed(source_id, completed)
        except (KeyError, FileNotFoundError):
            return jsonify({"ok": False, "error": "Bron niet gevonden"}), 404
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc), "counts": step4_review_counts(source_id)}), 409
        return jsonify({
            "ok": True,
            "completed": bool(source.get("review_completed")),
            "review_completed_at": source.get("review_completed_at"),
            "counts": step4_review_counts(source_id),
        })

    @app.post("/api/detection-review/<source_id>/manual")
    def detection_review_manual_api(source_id: str):
        payload = request.get_json(silent=True) or {}
        box_payload = payload.get("box")
        if not isinstance(box_payload, list) or len(box_payload) != 4:
            return jsonify({"ok": False, "error": "box moet vier coördinaten bevatten"}), 400
        try:
            box = tuple(int(round(float(value))) for value in box_payload)
            if canonical_table_gt_mode():
                gt = add_ground_truth_cell(workspace_root(), source_id, box)
                item = {**gt, "annotation_id": gt["gt_id"], "training_role": "positive", "provenance": gt.get("provenance", "manual_gt")}
            else:
                item = database.add_detection_annotation(
                    source_id=source_id, box=box,
                    reason_code=str(payload.get("reason_code") or "other"),
                    notes=str(payload.get("notes") or "")[:2000],
                )
        except KeyError:
            return jsonify({"ok": False, "error": "Bron niet gevonden"}), 404
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "annotation": item, "counts": step4_review_counts(source_id)})

    @app.post("/api/detection-review/<source_id>/<candidate_id>/promote-to-gt")
    def detection_review_promote_candidate_to_gt_api(source_id: str, candidate_id: str):
        """Promote one reviewed table-cell proposal to canonical GT."""
        candidate = database.get_detection_candidate(source_id, candidate_id)
        if candidate is None:
            return jsonify({"ok": False, "error": "Kandidaat niet gevonden"}), 404
        box = (
            int(candidate.get("corrected_x1") or candidate["x1"]),
            int(candidate.get("corrected_y1") or candidate["y1"]),
            int(candidate.get("corrected_x2") or candidate["x2"]),
            int(candidate.get("corrected_y2") or candidate["y2"]),
        )
        try:
            gt = add_ground_truth_cell(workspace_root(), source_id, box, provenance="step7_prediction_gt")
            database.review_detection_candidate(
                source_id=source_id, candidate_id=candidate_id, review_status="correct",
                relevance_status="relevant", reason_code="", relevance_reason="",
                notes="Promoted to canonical GT",
            )
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        item = {**gt, "annotation_id": gt["gt_id"], "training_role": "positive", "provenance": gt.get("provenance", "step7_prediction_gt")}
        return jsonify({"ok": True, "annotation": item, "counts": ground_truth_counts(workspace_root(), source_id)})

    @app.post("/api/detection-review/<source_id>/accept-unreviewed")
    def detection_review_accept_unreviewed_api(source_id: str):
        return jsonify({
            "ok": False,
            "error": "Impliciet accepteren is uitgeschakeld. Alleen expliciet beoordeelde crops worden trainingsdata.",
        }), 410

    @app.post("/api/detection-review/accept-all-unreviewed")
    def detection_review_accept_all_unreviewed_api():
        return jsonify({
            "ok": False,
            "error": "Impliciet accepteren is uitgeschakeld. Onbeoordeelde kandidaten worden bewust genegeerd.",
        }), 410

    @app.patch("/api/detection-review/<source_id>/manual/<annotation_id>")
    def detection_review_update_manual_api(source_id: str, annotation_id: str):
        payload = request.get_json(silent=True) or {}
        box_payload = payload.get("box")
        if not isinstance(box_payload, list) or len(box_payload) != 4:
            return jsonify({"ok": False, "error": "box moet vier coördinaten bevatten"}), 400
        try:
            box = tuple(int(round(float(value))) for value in box_payload)
            if canonical_table_gt_mode():
                gt = update_ground_truth_cell(workspace_root(), source_id, annotation_id, box)
                item = {**gt, "annotation_id": gt["gt_id"], "training_role": "positive", "provenance": gt.get("provenance", "canonical_gt")}
            else:
                item = database.update_manual_detection_annotation(annotation_id, box=box)
                if str(item.get("source_id") or "") != source_id:
                    return jsonify({"ok": False, "error": "Handmatige annotatie hoort bij een andere bron"}), 409
        except KeyError:
            return jsonify({"ok": False, "error": "Handmatige annotatie niet gevonden"}), 404
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({
            "ok": True,
            "annotation": item,
            "counts": step4_review_counts(source_id),
        })

    @app.delete("/api/detection-review/<source_id>/manual/<annotation_id>")
    def detection_review_delete_manual_api(source_id: str, annotation_id: str):
        try:
            if canonical_table_gt_mode():
                delete_ground_truth_cell(workspace_root(), source_id, annotation_id)
            else:
                database.delete_manual_detection_annotation(annotation_id)
        except KeyError:
            return jsonify({"ok": False, "error": "Ground Truth-cel niet gevonden" if canonical_table_gt_mode() else "Handmatige annotatie niet gevonden"}), 404
        return jsonify({"ok": True, "counts": step4_review_counts(source_id)})

    register_detection_candidate_routes(
        app,
        database=database,
        safe_workspace_file=safe_workspace_file,
        cached_render_image=cached_render_image,
    )


    @app.get("/detections")
    def generic_detections():
        gate = current_pipeline_gate()
        if not gate.get("ready"):
            return render_template("mapping_blocked.html", gate=gate), 423
        mapping = database.mapping_counts()
        return render_template(
            "generic_detections.html",
            sources=database.list_detection_sources(),
            mapping=mapping,
            header_counts={"total": mapping.get("relations", 0), "pending": mapping.get("suggested", 0), "accepted": mapping.get("confirmed", 0)},
            header_total_label="relaties", header_pending_label="voorgesteld", header_accepted_label="bevestigd",
        )

    @app.get("/detections/<source_id>")
    def generic_detection_document(source_id: str):
        gate = current_pipeline_gate()
        if not gate.get("ready"):
            return render_template("mapping_blocked.html", gate=gate), 423
        source = database.get_detection_source(source_id)
        if source is None:
            abort(404)
        role = str(request.args.get("role", "candidates")).strip().lower()
        if role not in {"candidates", "semantic", "all", "table", "label", "value", "header", "unit", "unknown"}:
            abort(400)
        blocks = database.list_detected_blocks(
            source_id,
            role=None if role in {"candidates", "semantic", "all", "table"} else role,
            semantic_only=(role in {"candidates", "semantic"}),
        )
        if role == "candidates":
            blocks = [item for item in blocks if item.get("role") in {"label", "value"}]
        elif role == "table":
            blocks = [item for item in database.list_detected_blocks(source_id) if item.get("block_type") in {"table", "table_cell"}]
        relations = database.list_detected_relations(source_id)
        value_preview_needed = any(
            item.get("role") == "value" and item.get("block_type") in {"semantic", "table_cell"}
            for item in blocks
        )
        source_annotations = database.list_detection_annotations(source_id, active_only=True) if value_preview_needed else []
        source_candidates = database.list_detection_candidates(source_id) if value_preview_needed else []
        for block in blocks:
            block["crop_exists"] = bool(block.get("crop_path")) and safe_workspace_file(str(block.get("crop_path") or "")).is_file()
            block["display_x1"] = int(block["x1"]); block["display_y1"] = int(block["y1"])
            block["display_x2"] = int(block["x2"]); block["display_y2"] = int(block["y2"])
            block["geometry_source"] = "detected"
            if block.get("role") == "value" and block.get("block_type") in {"semantic", "table_cell"}:
                try:
                    preview_box, preview_diag = resolve_value_roi_box(
                        database, str(block["block_id"]), int(source["image_width"]), int(source["image_height"]),
                        block=block, annotations=source_annotations, candidates=source_candidates,
                    )
                    block["display_x1"], block["display_y1"], block["display_x2"], block["display_y2"] = preview_box.to_list()
                    block["geometry_source"] = str(preview_diag.get("geometry_source") or "refined")
                except (KeyError, ValueError):
                    pass
        mapping_counts = database.mapping_counts()
        return render_template(
            "generic_detection.html",
            source=source,
            source_id=source_id,
            blocks=blocks,
            relations=relations,
            role_filter=role,
            field_definitions=database.list_field_definitions(active_only=True),
            header_counts={"total": len(relations), "pending": max(0, len(relations) - mapping_counts.get("confirmed", 0)), "accepted": mapping_counts.get("confirmed", 0)},
            header_total_label="relaties", header_pending_label="open", header_accepted_label="bevestigd",
        )

    @app.get("/detected-block/<block_id>")
    def detected_block_crop(block_id: str):
        if not current_pipeline_gate().get("ready"):
            abort(423, description="Pipeline A geometry gate is gesloten")
        block = database.get_detected_block(block_id)
        if block is None:
            abort(404)
        mode = str(request.args.get("mode") or "detected").strip().lower()
        if mode == "roi" and str(block.get("role") or "") == "value":
            source = database.get_detection_source(str(block["source_id"]))
            if source is None:
                abort(404)
            render = safe_workspace_file(str(source.get("render_path") or ""))
            if not render.is_file():
                abort(404)
            import cv2
            image = cached_render_image(render)
            if image is None:
                abort(404)
            height, width = image.shape[:2]
            try:
                box, _ = resolve_value_roi_box(database, block_id, width, height)
            except (KeyError, ValueError):
                abort(404)
            crop = image[box.y1:box.y2, box.x1:box.x2]
            if crop.size == 0:
                abort(404)
            ok, encoded = cv2.imencode(".png", crop)
            if not ok:
                abort(500)
            return Response(encoded.tobytes(), mimetype="image/png", headers={"Cache-Control": "no-store"})
        if not str(block.get("crop_path") or ""):
            abort(404)
        path = safe_workspace_file(str(block["crop_path"]))
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/png", max_age=0)

    def _first_open_mapping_source(sources: list[dict[str, Any]]) -> str | None:
        """Return the first source that still needs Mapping Studio review."""
        for item in sources:
            source_id = str(item.get("source_id") or "")
            if not source_id:
                continue
            relations = [
                relation for relation in database.list_detected_relations(source_id)
                if str(relation.get("relation_type") or "") == "table_cell"
                and str(relation.get("label_text") or "").strip()
            ]
            if not relations:
                continue
            mappings = {
                str(mapping.get("relation_id") or ""): mapping
                for mapping in database.list_mappings(source_id)
            }
            if any(str(mappings.get(str(relation.get("relation_id")), {}).get("status") or "") != "confirmed" for relation in relations):
                return source_id
        return None

    @app.get("/mapping")
    def mapping_index():
        sources = database.list_detection_sources()
        if not sources:
            return render_template("mapping_empty.html")
        requested = str(request.args.get("source_id") or "").strip()
        valid_source_ids = {str(item["source_id"]) for item in sources}
        if requested in valid_source_ids:
            source_id = requested
        else:
            source_id = _first_open_mapping_source(sources) or str(sources[0]["source_id"])
        return redirect(url_for("label_mapping_studio", source_id=source_id))

    @app.get("/mapping-labels")
    def label_mapping_index():
        sources = database.list_detection_sources()
        if not sources:
            return render_template("mapping_empty.html")
        requested = str(request.args.get("source_id") or "").strip()
        valid_source_ids = {str(item["source_id"]) for item in sources}
        if requested in valid_source_ids:
            source_id = requested
        else:
            source_id = _first_open_mapping_source(sources) or str(sources[0]["source_id"])
        return redirect(url_for("label_mapping_studio", source_id=source_id))

    @app.post("/mapping/<source_id>/relation-feedback")
    def mapping_relation_feedback(source_id: str):
        if database.get_detection_source(source_id) is None:
            abort(404)
        payload = request.get_json(silent=True) or request.form
        relation_id = str(payload.get("relation_id") or "").strip()
        feedback_action = str(payload.get("action") or "reject").strip().lower()
        if not relation_id:
            return jsonify({"ok": False, "error": "relation_id ontbreekt"}), 400
        try:
            if feedback_action == "restore":
                database.clear_relation_feedback(source_id, relation_id)
                result = {
                    "ok": True,
                    "status": "proposed",
                    "reason_code": "",
                    "reason_label": "",
                    "reason_detail": "",
                }
            elif feedback_action == "reject":
                reason_code = str(payload.get("reason_code") or "").strip().lower()
                reason_detail = str(payload.get("reason_detail") or "").strip()
                feedback = database.record_relation_feedback(
                    source_id=source_id,
                    relation_id=relation_id,
                    verdict="rejected",
                    reason_code=reason_code,
                    reason_detail=reason_detail,
                )
                result = {
                    "ok": True,
                    "status": "rejected",
                    "reason_code": feedback["reason_code"],
                    "reason_label": RELATION_FEEDBACK_REASONS.get(feedback["reason_code"], feedback["reason_code"]),
                    "reason_detail": feedback["reason_detail"],
                }
            else:
                return jsonify({"ok": False, "error": "Onbekende feedbackactie"}), 400
        except (KeyError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        result["stats"] = database.relation_feedback_stats()
        return jsonify(result)

    @app.route("/mapping-labels/<source_id>", methods=["GET", "POST"])
    def label_mapping_studio(source_id: str):
        """Label-first Mapping Studio, independent of ROI review."""
        source = database.get_detection_source(source_id)
        if source is None:
            abort(404)
        fields = database.list_field_definitions(active_only=True)
        all_relations = [
            item for item in database.list_detected_relations(source_id)
            if str(item.get("relation_type") or "") == "table_cell"
            and str(item.get("label_text") or "").strip()
        ]
        column_roles = table_studio_roles(workspace_root())
        active_rows = table_studio_rows(workspace_root())
        panel_profile = load_panel_profile(workspace_root())
        panel_by_id = {
            str(panel.get("panel_id") or ""): panel
            for panel in panel_profile.get("panels") or []
            if str(panel.get("panel_id") or "")
        }

    def workflow_navigation_access() -> dict[str, bool]:
        """Return which primary workflow step may be opened next.

        A step is navigable only when every preceding primary step is complete.
        The current incomplete step remains open so the user can finish it.
        Fallback, system and maintenance routes are intentionally excluded.
        """
        sequence = [
            "detection-models", "input-selection", "panel-setup", "table-region-model",
            "detect-candidates", "detection-review", "table-model", "table-compare", "table-quality",
            "recognition-gt-studio", "recognition-dataset", "recognition-output-review",
            "mapping", "apply-mapping", "value-review",
        ] if localization_strategy() == "table_first" else [
            step["key"] for step in PROCESS_STEPS
            if step.get("group") in {"detection", "value"}
            and step.get("index") is not None
        ]
        readiness = request_cached("workflow_readiness", lambda: process_snapshot().get("readiness", {}))
        access: dict[str, bool] = {}
        previous_complete = True
        for key in sequence:
            access[key] = previous_complete
            previous_complete = bool(readiness.get(key))
        return access

    @app.before_request
    def enforce_primary_workflow_gate():
        """Prevent bypassing the sidebar gates through a hand-typed URL."""
        if request.method != "GET":
            return None
        path_to_step = {
            "/mapping": "mapping",
            "/process/value-review": "value-review",
            "/recognition-gt-review": "recognition-gt-studio",
            "/recognition-scope": "recognition-gt-studio",
        }
        step_key = path_to_step.get(request.path)
        if step_key is None and request.path.startswith("/mapping-labels"):
            step_key = "mapping"
        if step_key is None and request.path.startswith("/recognition-gt-"):
            step_key = "recognition-gt-studio"
        if step_key is None and request.path.startswith("/process/"):
            candidate = request.path.removeprefix("/process/").strip("/")
            if candidate in PROCESS_STEP_BY_KEY:
                step_key = candidate
        if not step_key:
            return None
        access = workflow_navigation_access()
        if step_key not in access:
            return None
        if access.get(step_key):
            return None
        sequence = list(access)
        target = next((key for key in sequence if access.get(key)), "detection-models")
        flash("Deze stap is nog vergrendeld. Rond eerst de vorige stap af.", "warning")
        if target == "recognition-gt-studio":
            return redirect(url_for("recognition_gt_review_home"))
        if target == "mapping":
            return redirect(url_for("mapping_index"))
        return redirect(url_for("process_step", step_key=target))
        geometry = database.list_detection_table_geometry(source_id)
        image_width = float(source.get("image_width") or panel_profile.get("reference_width") or 0)
        image_height = float(source.get("image_height") or panel_profile.get("reference_height") or 0)
        raw_table_panels: dict[str, str] = {}
        for region in geometry.get("regions", []):
            center_x = (float(region.get("x1") or 0) + float(region.get("x2") or 0)) / 2
            center_y = (float(region.get("y1") or 0) + float(region.get("y2") or 0)) / 2
            for panel_id, panel in panel_by_id.items():
                if (
                    float(panel.get("x1") or 0) * image_width <= center_x <= float(panel.get("x2") or 0) * image_width
                    and float(panel.get("y1") or 0) * image_height <= center_y <= float(panel.get("y2") or 0) * image_height
                ):
                    raw_table_panels[str(region.get("table_id") or "")] = panel_id
                    break
        raster_rows: dict[str, dict[int, tuple[int, int]]] = {}
        for cell in geometry.get("cells", []):
            panel_id = raw_table_panels.get(str(cell.get("table_id") or ""), "")
            if not panel_id:
                continue
            row_index = int(cell.get("row_index") or 0)
            y1, y2 = int(cell.get("y1") or 0), int(cell.get("y2") or 0)
            previous = raster_rows.setdefault(panel_id, {}).get(row_index)
            raster_rows[panel_id][row_index] = (
                min(y1, previous[0]) if previous else y1,
                max(y2, previous[1]) if previous else y2,
            )

        def relation_panel_id(relation: dict[str, Any]) -> str:
            parts = [part.strip() for part in str(relation.get("context_text") or "").split("|")]
            # Panel context is persisted as human-readable name plus optional
            # id. Older mapping runs only persisted the name, so do not assume
            # that the id is always the second token. The selected Table/Panel
            # remains the semantic disambiguator for generic labels such as
            # ``ED Volume``; no report-specific label is hardcoded here.
            normalized_parts = {normalize_text(part) for part in parts if part}
            for panel_id, panel in panel_by_id.items():
                panel_name = normalize_text(str(panel.get("name") or ""))
                if normalize_text(panel_id) in normalized_parts or (
                    panel_name and panel_name in normalized_parts
                ):
                    return panel_id
            return ""

        def relation_raster_row(relation: dict[str, Any], panel_id: str) -> int:
            rows = raster_rows.get(panel_id) or {}
            if not rows:
                return int(relation.get("row_index") or -1)
            center_y = (int(relation.get("label_y1") or 0) + int(relation.get("label_y2") or 0)) / 2
            containing = [index for index, (y1, y2) in rows.items() if y1 <= center_y <= y2]
            if containing:
                return containing[0]
            return min(rows, key=lambda index: abs(((rows[index][0] + rows[index][1]) / 2) - center_y))

        relations = []
        for relation in all_relations:
            panel_id = relation_panel_id(relation)
            value_column = str(int(relation.get("value_column_index") or 0))
            raster_row = relation_raster_row(relation, panel_id)
            configured = panel_id in column_roles
            if configured and column_roles.get(panel_id, {}).get(value_column) != "value":
                continue
            if panel_id in active_rows and raster_row not in set(active_rows[panel_id]):
                continue
            panel = panel_by_id.get(panel_id) or {}
            relations.append({
                **relation,
                "panel_id": panel_id,
                "panel_name": str(panel.get("name") or panel_id or "Tabel"),
                "raster_row_index": raster_row,
                "table_configured": configured,
            })
        relations.sort(key=lambda item: (
            str(item.get("panel_name") or ""),
            int(item.get("raster_row_index") or -1),
            int(item.get("value_column_index") or -1),
            str(item.get("label_text") or "").casefold(),
        ))
        relations_by_id = {str(item["relation_id"]): item for item in relations}

        def generic_field_options() -> list[dict[str, Any]]:
            options: list[dict[str, Any]] = []
            seen: set[str] = set()
            for field in fields:
                family = field_lateral_suffix(field) or str(field.get("field_key") or "")
                if not family or family in seen:
                    continue
                seen.add(family)
                display_name = str(field.get("display_name") or family)
                group_name = str(field.get("group_name") or "")
                prefix = f"{group_name} "
                if prefix and display_name.casefold().startswith(prefix.casefold()):
                    display_name = display_name[len(prefix):]
                options.append({"family": family, "display_name": display_name})
            return options

        field_options = generic_field_options()

        if request.method == "POST":
            action = str(request.form.get("label_mapping_action") or "save").strip().lower()
            if action == "rebuild":
                job = enqueue_job("20")
                flash("Mappingvoorstellen opnieuw opgebouwd; controleer de nieuwe voorstellen zodra de taak gereed is.", "success")
                return redirect(url_for("label_mapping_studio", source_id=source_id, job_id=job["job_id"]))
            if action != "save":
                abort(400)
            assignments = [
                {
                    "relation_id": relation_id,
                    "field_key": str(request.form.get(f"field_{relation_id}") or "").strip(),
                    "notes": "label-first mapping",
                }
                for relation_id in request.form.getlist("relation_id")
                if relation_id in relations_by_id
            ]
            resolution_error = ""
            for assignment in assignments:
                selected = assignment["field_key"]
                if not selected.startswith("family:"):
                    continue
                family = selected.removeprefix("family:")
                relation = relations_by_id[assignment["relation_id"]]
                side = relation_lateral_side(relation)
                candidates = [
                    field for field in fields
                    if (field_lateral_suffix(field) or str(field.get("field_key") or "")) == family
                    and (not side or not field_lateral_side(field) or field_lateral_side(field) == side)
                ]
                if len(candidates) != 1:
                    resolution_error = f"Kan algemene veldnaam '{family}' niet eenduidig koppelen aan de gekozen tabel/panel."
                    break
                assignment["field_key"] = str(candidates[0]["field_key"])
            if resolution_error:
                flash(f"Labelmappings niet opgeslagen: {resolution_error}", "error")
                return redirect(url_for("label_mapping_studio", source_id=source_id))
            try:
                result = database.sync_relation_mappings(source_id, assignments)
            except (KeyError, ValueError) as exc:
                flash(f"Labelmappings niet opgeslagen: {exc}", "error")
            else:
                flash(
                    f"{result['saved']} labelmapping(s) opgeslagen, {result['removed']} verwijderd.",
                    "success",
                )
            return redirect(url_for("label_mapping_studio", source_id=source_id))

        mappings = database.list_mappings(source_id)
        mappings_by_relation = {
            str(item["relation_id"]): item
            for item in mappings
            if str(item.get("relation_id") or "")
        }
        relation_groups: list[dict[str, Any]] = []
        for relation in relations:
            panel_id = str(relation.get("panel_id") or relation.get("table_id") or "")
            if not relation_groups or relation_groups[-1]["panel_id"] != panel_id:
                relation_groups.append({
                    "panel_id": panel_id,
                    "panel_name": str(relation.get("panel_name") or "Tabel"),
                    "relations": [],
                })
            relation_groups[-1]["relations"].append(relation)
        return render_template(
            "mapping_labels_studio.html",
            source=source,
            source_id=source_id,
            sources=database.list_detection_sources(),
            relations=relations,
            relation_groups=relation_groups,
            mappings_by_relation=mappings_by_relation,
            fields=fields,
            field_options=field_options,
            table_roles_configured=bool(column_roles),
            header_counts={
                "total": len(relations),
                "pending": sum(
                    1 for relation in relations
                    if str(mappings_by_relation.get(str(relation["relation_id"]), {}).get("status") or "") != "confirmed"
                ),
                "accepted": sum(
                    1 for relation in relations
                    if str(mappings_by_relation.get(str(relation["relation_id"]), {}).get("status") or "") == "confirmed"
                ),
            },
            header_total_label="labels",
            header_pending_label="te koppelen",
            header_accepted_label="gekoppeld",
        )

    def input_selection_path() -> Path:
        return selection_manifest_path(workspace_root())

    def input_selection_state() -> dict[str, Any]:
        root = Path("/input")
        files = []
        for path in input_files(root):
            try:
                relative = input_file_key(path, root)
                files.append({
                    "key": relative,
                    "name": path.name,
                    "directory": str(path.parent.relative_to(root)).replace(".", ""),
                    "size": path.stat().st_size,
                    "source_id": input_file_source_id(path),
                })
            except (OSError, ValueError):
                continue
        saved = _read_json(input_selection_path(), {}) or {}
        selected = {str(item) for item in (saved.get("selected") or []) if str(item)}
        has_manifest = input_selection_path().is_file()
        for item in files:
            item["selected"] = item["key"] in selected if has_manifest else True
            item["is_new"] = item["key"] not in selected if has_manifest else False
        return {
            "files": files,
            "selected": sum(1 for item in files if item["selected"]),
            "total": len(files),
            "new": sum(1 for item in files if item["is_new"]),
            "has_manifest": has_manifest,
            "updated_at": saved.get("updated_at", ""),
        }

    @app.route("/mapping/<source_id>", methods=["GET", "POST"])
    def mapping_studio(source_id: str):
        source = database.get_detection_source(source_id)
        if source is None:
            abort(404)
        relations = database.list_detected_relations(source_id)
        relations_by_id = {str(item["relation_id"]): item for item in relations}
        fields = database.list_field_definitions(active_only=True)
        pipeline_a_annotations: list[dict[str, Any]] | None = None
        pipeline_a_candidates: list[dict[str, Any]] | None = None
        value_blocks_cache: dict[str, dict[str, Any]] | None = None

        def resolve_mapping_roi(value_block_id: str) -> tuple[Any, dict[str, Any]]:
            nonlocal pipeline_a_annotations, pipeline_a_candidates, value_blocks_cache
            if pipeline_a_annotations is None:
                pipeline_a_annotations = database.list_detection_annotations(source_id, active_only=True)
                pipeline_a_candidates = database.list_detection_candidates(source_id)
                if value_blocks_cache is None:
                    value_blocks_cache = {
                        str(item["block_id"]): item
                        for item in database.list_detected_blocks(source_id, role="value", semantic_only=True)
                    }
            block = (value_blocks_cache or {}).get(str(value_block_id))
            return resolve_value_roi_box(
                database, str(value_block_id), int(source["image_width"]), int(source["image_height"]),
                block=block, annotations=pipeline_a_annotations, candidates=pipeline_a_candidates,
            )
        if request.method == "POST":
            action = str(request.form.get("mapping_action") or "save").strip().lower()
            saved = 0
            if action in {"save", "save_apply"}:
                posted_relation_ids = [
                    str(value) for value in request.form.getlist("relation_id")
                    if str(value) in relations_by_id
                ]
                desired = {
                    relation_id: str(request.form.get(f"field_{relation_id}") or "").strip()
                    for relation_id in posted_relation_ids
                }
                selected_fields = [field_key for field_key in desired.values() if field_key]
                duplicate_fields = sorted({
                    field_key for field_key in selected_fields
                    if selected_fields.count(field_key) > 1
                })
                if duplicate_fields:
                    names = {str(item["field_key"]): str(item.get("display_name") or item["field_key"]) for item in fields}
                    labels = ", ".join(names.get(key, key) for key in duplicate_fields)
                    flash(
                        f"Niet opgeslagen: hetzelfde functionele veld is meerdere keren geselecteerd ({labels}).",
                        "error",
                    )
                    return redirect(url_for("mapping_studio", source_id=source_id))

                assignments = [
                    {
                        "relation_id": relation_id,
                        "field_key": field_key,
                        "notes": str(request.form.get(f"notes_{relation_id}") or ""),
                    }
                    for relation_id, field_key in desired.items()
                ]
                try:
                    for assignment in assignments:
                        if not assignment["field_key"]:
                            continue
                        relation = relations_by_id[assignment["relation_id"]]
                        resolve_mapping_roi(str(relation["value_block_id"]))
                    sync_result = database.sync_relation_mappings(source_id, assignments)
                except (KeyError, ValueError) as exc:
                    flash(f"Mappings niet opgeslagen: {exc}", "error")
                    return redirect(url_for("mapping_studio", source_id=source_id))
                saved = int(sync_result["saved"])
                removed = int(sync_result["removed"])
                changed = saved + removed
                if changed:
                    flash(
                        f"{saved} mapping(s) opgeslagen, {removed} verwijderd. Gewijzigde ROI's zijn gemarkeerd als verouderd tot 'Mapping toepassen' opnieuw is uitgevoerd.",
                        "success",
                    )
                else:
                    flash("Geen mappingwijzigingen om op te slaan.", "success")
                if action == "save_apply":
                    job = enqueue_job("21", {"source_id": source_id})
                    return redirect(url_for("mapping_studio", source_id=source_id, job_id=job["job_id"]))
            elif action == "confirm_suggestions":
                selected = set(request.form.getlist("mapping_id"))
                candidates = database.list_mappings(source_id, status="suggested")
                for item in candidates:
                    if str(item["mapping_id"]) not in selected:
                        continue
                    try:
                        resolve_mapping_roi(str(item["value_block_id"]))
                    except (KeyError, ValueError):
                        continue
                    database.upsert_mapping(
                        source_id=source_id,
                        field_key=str(item["field_key"]),
                        relation_id=str(item.get("relation_id") or ""),
                        label_block_id=str(item.get("label_block_id") or ""),
                        value_block_id=str(item["value_block_id"]),
                        unit_block_id=str(item.get("unit_block_id") or ""),
                        status="confirmed",
                        mapping_confidence=float(item.get("mapping_confidence") or 0),
                        notes=str(item.get("notes") or "") + " confirmed_by_user",
                        profile_id=str(item.get("profile_id") or ""),
                    )
                    saved += 1
                flash(f"{saved} voorgestelde mapping(s) bevestigd.", "success")
            elif action == "suggest":
                suggestions = suggest_mappings(database, source_id)
                flash(f"{len(suggestions)} nieuwe mappings voorgesteld op basis van aliassen en context.", "success")
            elif action == "regenerate":
                job = enqueue_job("20")
                flash("De vorige Mapping-dataset wordt gewist en opnieuw opgebouwd met de actuele tabelstructuur en OCR.", "success")
                return redirect(url_for("mapping_studio", source_id=source_id, job_id=job["job_id"]))
            elif action == "custom":
                field_key = str(request.form.get("custom_field_key") or "").strip()
                label_block_id = str(request.form.get("custom_label_block_id") or "").strip()
                value_block_id = str(request.form.get("custom_value_block_id") or "").strip()
                if not field_key or not value_block_id:
                    flash("Kies minimaal een functioneel veld en een waardeblok.", "error")
                else:
                    try:
                        resolve_mapping_roi(value_block_id)
                    except (KeyError, ValueError) as exc:
                        flash(f"Kan niet mappen zonder geldige Pipeline-A ROI: {exc}", "error")
                        return redirect(url_for("mapping_studio", source_id=source_id))
                    database.upsert_mapping(
                        source_id=source_id,
                        field_key=field_key,
                        relation_id="",
                        label_block_id=label_block_id,
                        value_block_id=value_block_id,
                        status="confirmed",
                        mapping_confidence=1.0,
                        notes="manual block mapping",
                    )
                    flash("Handmatige mapping opgeslagen.", "success")
            elif action == "delete":
                mapping_id = str(request.form.get("mapping_id_single") or "").strip()
                if mapping_id:
                    database.delete_mapping(mapping_id)
                    flash("Mapping verwijderd.", "success")
            else:
                abort(400)
            return redirect(url_for("mapping_studio", source_id=source_id))

        mappings = database.list_mappings(source_id)
        mappings_by_relation = {
            str(item["relation_id"]): item for item in mappings if str(item.get("relation_id") or "")
        }
        confirmed_fields = {str(item["field_key"]) for item in mappings if item["status"] == "confirmed"}
        label_blocks = database.list_detected_blocks(source_id, role="label", semantic_only=True)
        value_blocks = database.list_detected_blocks(source_id, role="value", semantic_only=True)
        value_blocks_cache = {str(item["block_id"]): item for item in value_blocks}
        fields_by_key = {str(item["field_key"]): item for item in fields}
        feedback_by_relation = database.feedback_for_relations(source_id, relations)
        feedback_stats = database.relation_feedback_stats()
        for relation in relations:
            try:
                roi_box, roi_diag = resolve_mapping_roi(str(relation["value_block_id"]))
                relation["pipeline_a_roi_ready"] = True
                relation["pipeline_a_roi"] = roi_box.to_list()
                relation["pipeline_a_geometry_source"] = str(roi_diag.get("geometry_source") or "")
                relation["pipeline_a_match_score"] = float(roi_diag.get("pipeline_a_match_score") or 0)
            except (KeyError, ValueError):
                relation["pipeline_a_roi_ready"] = False
                relation["pipeline_a_roi"] = []
                relation["pipeline_a_geometry_source"] = ""
                relation["pipeline_a_match_score"] = 0.0
        # Pipeline B receives only relations backed by relevant, reviewed
        # Pipeline-A geometry. Out-of-scope/ignored regions are intentionally
        # absent from Mapping Studio instead of appearing as disabled noise.
        hidden_relation_count = sum(1 for relation in relations if not relation.get("pipeline_a_roi_ready"))
        relations = [relation for relation in relations if relation.get("pipeline_a_roi_ready")]
        allowed_value_block_ids = {str(relation.get("value_block_id") or "") for relation in relations}
        value_blocks = [block for block in value_blocks if str(block.get("block_id") or "") in allowed_value_block_ids]
        visible_relation_ids = {str(relation.get("relation_id") or "") for relation in relations}
        mappings = [
            item for item in mappings
            if not str(item.get("relation_id") or "") or str(item.get("relation_id") or "") in visible_relation_ids
        ]
        mappings_by_relation = {
            str(item["relation_id"]): item for item in mappings if str(item.get("relation_id") or "")
        }
        confirmed_fields = {str(item["field_key"]) for item in mappings if item["status"] == "confirmed"}
        preview_relations = {
            str(item["relation_id"]): {
                "relation_id": str(item["relation_id"]),
                "label_text": str(item.get("label_text") or ""),
                "value_text": str(item.get("value_text") or ""),
                "confidence": float(item.get("confidence") or 0),
                "relation_type": str(item.get("relation_type") or ""),
                "table_id": str(item.get("table_id") or ""),
                "row_index": int(item.get("row_index", -1)),
                "value_column_index": int(item.get("value_column_index", -1)),
                "label_x1": int(item.get("label_x1") or 0),
                "label_y1": int(item.get("label_y1") or 0),
                "label_x2": int(item.get("label_x2") or 0),
                "label_y2": int(item.get("label_y2") or 0),
                "value_x1": int(item.get("value_x1") or 0),
                "value_y1": int(item.get("value_y1") or 0),
                "value_x2": int(item.get("value_x2") or 0),
                "value_y2": int(item.get("value_y2") or 0),
                "pipeline_a_roi_ready": bool(item.get("pipeline_a_roi_ready")),
                "pipeline_a_roi": item.get("pipeline_a_roi") or [],
                "pipeline_a_geometry_source": str(item.get("pipeline_a_geometry_source") or ""),
                "pipeline_a_match_score": float(item.get("pipeline_a_match_score") or 0),
            }
            for item in relations
        }
        preview_fields = {
            key: {
                "field_key": key,
                "display_name": item.get("display_name") or key,
                "group_name": item.get("group_name") or "",
                "data_type": item.get("data_type") or "text",
                "preferred_unit": item.get("preferred_unit") or "",
                "minimum_value": item.get("minimum_value"),
                "maximum_value": item.get("maximum_value"),
            }
            for key, item in fields_by_key.items()
        }
        initial_preview = None
        for relation in relations:
            current = mappings_by_relation.get(str(relation["relation_id"]))
            if current and str(current.get("field_key") or "") in fields_by_key:
                initial_preview = build_mapping_output_preview(relation, fields_by_key[str(current["field_key"])])
                break
        return render_template(
            "mapping_studio.html",
            source=source,
            source_id=source_id,
            sources=database.list_detection_sources(),
            relations=relations,
            mappings=mappings,
            mappings_by_relation=mappings_by_relation,
            confirmed_fields=confirmed_fields,
            fields=fields,
            label_blocks=label_blocks,
            value_blocks=value_blocks,
            preview_relations=preview_relations,
            preview_fields=preview_fields,
            initial_preview=initial_preview,
            feedback_by_relation=feedback_by_relation,
            feedback_stats=feedback_stats,
            feedback_reasons=RELATION_FEEDBACK_REASONS,
            hidden_relation_count=hidden_relation_count,
            header_counts={"total": len(relations), "pending": sum(item["status"] == "suggested" for item in mappings), "accepted": sum(item["status"] == "confirmed" for item in mappings)},
            header_total_label="relaties", header_pending_label="voorgesteld", header_accepted_label="bevestigd",
        )

    register_field_mapping_config_routes(app, database=database)

    register_media_routes(
        app,
        database=database,
        safe_workspace_file=safe_workspace_file,
        loaded_config=loaded_config,
    )

    register_document_routes(
        app,
        database=database,
        workspace_root=workspace_root,
        safe_workspace_file=safe_workspace_file,
        source_rows=source_rows,
        source_samples=source_samples,
        header_field_options=header_field_options,
        source_study_info=source_study_info,
        locator_label_threshold=locator_label_threshold,
    )

    register_roi_review_routes(
        app,
        database=database,
        workspace_root=workspace_root,
        source_rows=source_rows,
        source_samples=source_samples,
        roi_review_counts=roi_review_counts,
    )

    register_value_review_routes(
        app,
        database=database,
        filter_args=_filter_args,
        query_samples=query_samples,
        value_source_rows=value_source_rows,
        value_source_samples=value_source_samples,
        value_in_configured_range=value_in_configured_range,
        value_review_counts=value_review_counts,
    )

    register_sample_review_routes(
        app,
        database=database,
        filter_args=_filter_args,
        query_samples=query_samples,
        value_review_counts=value_review_counts,
    )

    register_legacy_routes(app, process_step)

    register_job_routes(
        app,
        jobs_root=jobs_root,
        job_statuses=job_statuses,
        worker_state=worker_state,
        enqueue_job=enqueue_job,
        current_recognition_gate=current_recognition_gate,
        project_manager=project_manager,
        actions=ACTIONS,
        utcnow=_utcnow,
    )

    register_status_routes(
        app,
        database=database,
        registry_state=registry_state,
        job_statuses=job_statuses,
        worker_state=worker_state,
    )

    @app.get("/api/localization-readiness")
    def api_localization_readiness():
        """Backward-compatible readiness endpoint for legacy screens."""
        return jsonify(localization_readiness_payload())

    @app.get("/api/v2/preparation")
    def api_v2_preparation():
        return jsonify({"ok": True, "preparation": preparation_for_current_strategy()})

    @app.get("/api/v2/localization/workbench")
    def api_v2_localization_workbench():
        response = jsonify(localization_workbench_payload())
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/v2/localization/quality")
    def api_v2_localization_quality():
        response = jsonify(localization_quality_payload())
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/v2/localization/quality/details")
    def api_v2_localization_quality_details():
        evaluation_id = str(request.args.get("evaluation_id") or "").strip()
        if not evaluation_id:
            return jsonify({"ok": False, "error": "Kies eerst een getrainde evaluatie."}), 400
        evaluation = database.get_localization_evaluation(evaluation_id)
        if evaluation is None or str(evaluation.get("kind") or "") != "trained":
            return jsonify({"ok": False, "error": "De gekozen getrainde evaluatie bestaat niet meer."}), 404
        predictions_path = str(evaluation.get("predictions_path") or "").strip()
        if not predictions_path:
            return jsonify({
                "ok": False,
                "error": "Deze evaluatie bevat geen bewaarde voorspellingen. Voer Nieuwe evaluatie uitvoeren opnieuw uit om visuele diagnostiek te maken.",
            }), 409
        try:
            confidence = float(request.args.get("threshold") or (evaluation.get("metrics") or {}).get("minimum_confidence") or 0.25)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Ongeldige confidence-threshold."}), 400
        confidence = max(0.0, min(1.0, confidence))
        split = str(request.args.get("split") or evaluation.get("split") or "test").strip().lower()
        if split not in {"train", "val", "test"}:
            return jsonify({"ok": False, "error": "Split moet train, val of test zijn."}), 400
        try:
            iou_threshold = float(request.args.get("iou") or request.args.get("iou_threshold") or (evaluation.get("metrics") or {}).get("iou_threshold") or 0.75)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Ongeldige IoU-drempel."}), 400
        iou_threshold = max(0.05, min(0.95, iou_threshold))
        try:
            details = localization_evaluation_details(
                workspace_root(), predictions_path,
                model_id=str(evaluation.get("model_id") or ""),
                dataset_id=str(evaluation.get("dataset_id") or ""),
                minimum_confidence=confidence,
                iou_threshold=iou_threshold,
                canonical_iou_threshold=float((evaluation.get("metrics") or {}).get("iou_threshold") or 0.75),
                split=split,
            )
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        except Exception as exc:
            # This is a localhost-only diagnostic endpoint. Never turn a useful
            # visualization failure into an opaque HTTP 500: surface the concrete
            # exception while keeping the page alive so the reviewer knows what to fix.
            traceback.print_exc()
            return jsonify({
                "ok": False,
                "error": f"Visuele diagnostiek kon niet worden opgebouwd: {type(exc).__name__}: {exc}",
            }), 500
        response = jsonify({"ok": True, "evaluation_id": evaluation_id, "details": details})
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/v2/localization/quality/image/<dataset_id>/<source_id>")
    def api_v2_localization_quality_image(dataset_id: str, source_id: str):
        split = str(request.args.get("split") or "test").strip().lower()
        if split not in {"train", "val", "test"}:
            abort(400)
        try:
            path = localization_dataset_image_path(
                workspace_root(), dataset_id=dataset_id, source_id=source_id, split=split
            )
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            abort(404)
        response = send_file(path, conditional=True, max_age=3600)
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response

    @app.get("/api/v2/localization/artifacts")
    def api_v2_localization_artifacts():
        response = jsonify(localization_artifacts_payload())
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.post("/api/v2/localization/selection")
    def api_v2_localization_selection():
        payload = request.get_json(silent=True) or {}
        try:
            selection = save_localization_artifact_selection(payload)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "selection": selection, "quality": localization_quality_payload()})

    @app.post("/api/v2/localization/datasets/select")
    def api_v2_localization_select_dataset():
        payload = request.get_json(silent=True) or {}
        try:
            readiness = select_localization_work_dataset(str(payload.get("dataset_id") or ""))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "readiness": readiness, "artifacts": localization_artifacts_payload()})

    @app.post("/api/v2/localization/artifacts/delete")
    def api_v2_localization_delete_artifact():
        payload = request.get_json(silent=True) or {}
        kind = str(payload.get("kind") or "")
        artifact_id = str(payload.get("id") or "")
        cascade = bool(payload.get("cascade"))
        replacement_dataset_id = str(payload.get("replacement_dataset_id") or "")
        try:
            plan = artifact_delete_plan(
                kind, artifact_id, replacement_dataset_id=replacement_dataset_id
            )
            if bool(plan.get("requires_cascade")) and not cascade:
                if str(plan.get("kind") or kind) == "model":
                    raise ValueError(
                        f"Model wordt gebruikt door {int(plan.get('dependency_count') or 0)} evaluatie(s); "
                        "verwijder die eerst of gebruik cascade"
                    )
                raise ValueError(
                    f"Dataset heeft {int(plan.get('dependency_count') or 0)} afhankelijke model/evaluatie-artifact(s); "
                    "verwijder die eerst of gebruik cascade"
                )
            job = enqueue_artifact_delete_job(
                kind, artifact_id, cascade=cascade, replacement_dataset_id=replacement_dataset_id
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({
            "ok": True,
            "queued": True,
            "job_id": str(job.get("job_id") or ""),
            "status": str(job.get("status") or "pending"),
            "plan": plan,
        }), 202

    @app.post("/api/v2/localization/split")
    def api_v2_localization_split():
        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "save").strip().lower()
        try:
            if action == "auto":
                plan = save_localization_split_config(workspace_root(), mode="auto", overrides={})
            elif action == "save":
                raw_targets = payload.get("targets") if isinstance(payload.get("targets"), dict) else {}
                targets = {
                    "train": int(raw_targets.get("train") or 0),
                    "val": int(raw_targets.get("val") or 0),
                    "test": int(raw_targets.get("test") or 0),
                }
                raw_overrides = payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {}
                overrides = {
                    str(source_id): str(split)
                    for source_id, split in raw_overrides.items()
                    if str(split) in {"train", "val", "test"}
                }
                plan = save_localization_split_config(
                    workspace_root(), mode="counts", targets=targets, overrides=overrides
                )
            else:
                return jsonify({"ok": False, "error": "Onbekende splitactie"}), 400
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "plan": plan, "workbench": localization_workbench_payload()})

    @app.post("/api/v2/jobs")
    def api_v2_create_job():
        payload = request.get_json(silent=True) or {}
        action_id = str(payload.get("action_id") or "").strip()
        if action_id not in ACTIONS:
            return jsonify({"ok": False, "error": "Onbekende taak"}), 400
        if action_id in {"24", "25", "26", "27", "28"} and not current_recognition_gate().get("ready"):
            gate = current_recognition_gate()
            return jsonify({"ok": False, "error": f"Recognition is vergrendeld: {gate.get('reason') or 'goedgekeurde Recognition-GT ontbreekt'}."}), 423
        # Prevent double-submit races from a reactive UI. Existing jobs remain
        # selectable in the terminal dock and the client can retry after they finish.
        existing = next((
            item for item in job_statuses(20, action_ids={action_id})
            if str(item.get("status") or "") in {"pending", "running"}
        ), None)
        if existing is not None:
            return jsonify({"ok": False, "error": "Deze taak draait al.", "job": existing}), 409
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        if action_id == "2" and options.get("table_model_id") is not None:
            table_model_id = str(options.get("table_model_id") or "").strip()
            if table_model_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", table_model_id):
                return jsonify({"ok": False, "error": "Ongeldig table-cell model-ID"}), 400
            options = {**options, "table_model_id": table_model_id}
        if action_id in {"9", "10", "11"}:
            # Persist resolved defaults so the non-interactive PowerShell worker
            # sees exactly the same dataset/model selection as the React client.
            # A fresh evaluate+compare run intentionally resets manual evaluation
            # pinning so the newly produced pair becomes visible immediately.
            if action_id == "9":
                save_localization_artifact_selection({"baseline_evaluation_id": "", "trained_evaluation_id": ""})
            else:
                save_localization_artifact_selection({})
        if action_id == "26":
            device = str(options.get("device") or "gpu").strip().lower()
            if device not in {"cpu", "gpu"}:
                return jsonify({"ok": False, "error": "Ongeldig device"}), 400
            options = {**options, "device": device}
        job = enqueue_job(action_id, options)
        return jsonify({"ok": True, "job": job}), 202

    @app.get("/api/v2/events")
    def api_v2_events():
        """SSE invalidation stream for reactive screens.

        It sends tiny invalidation messages rather than complete snapshots. The
        client then refetches only the state it owns, so no page navigation or
        full HTML refresh is necessary.
        """
        @stream_with_context
        def event_stream():
            last_signature = ""
            last_heartbeat = time.monotonic()
            yield "event: connected\ndata: {\"scope\":\"all\"}\n\n"
            while True:
                signature = localization_event_signature()
                if signature != last_signature:
                    last_signature = signature
                    data = json.dumps({
                        "scope": "all",
                        "at": _utcnow(),
                    }, ensure_ascii=False)
                    yield f"event: invalidate\ndata: {data}\n\n"
                    last_heartbeat = time.monotonic()
                elif time.monotonic() - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()
                time.sleep(1.0)

        response = Response(event_stream(), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Connection"] = "keep-alive"
        return response

    return app
