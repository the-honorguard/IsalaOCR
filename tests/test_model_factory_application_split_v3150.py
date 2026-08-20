from pathlib import Path

import yaml

from isala_ocr.application_processing import (
    MISSING_VALUE_MARKERS,
    is_missing_value_text,
    lateral_candidate_allowed,
    schema_candidate_score,
)
from isala_ocr.training.mapping_lateral import lateral_candidate_allowed as legacy_lateral
from isala_ocr.training.mapping_semantics import schema_candidate_score as legacy_schema_score


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "application/src/isala_ocr/training/templates/base.html"
CMR_USE_CASE = ROOT / "application/config/use_cases/philips_cmr_volume_results.yaml"
GENERIC_USE_CASE = ROOT / "application/config/use_cases/generic_document.yaml"
ARCH = ROOT / "docs/architecture/model-factory-and-application-processing.md"
VERSION = ROOT / "project/VERSION"


def test_sidebar_separates_model_factory_from_optional_application_processing():
    base = BASE.read_text(encoding="utf-8")

    assert "MODEL FACTORY · DATA & GROUND TRUTH" in base
    assert "MODEL FACTORY · ITERATIE 5 → 6 → 5" in base
    assert "EINDPRODUCT · MODEL" in base
    assert "FASE 2 · APPLICATION PROCESSING · OPTIONEEL" in base
    assert '<span class="process-tab-number">A{{ loop.index }}</span>' in base
    assert "Fase 2 · Application Mapping Studio" in base


def test_application_processing_is_disabled_by_default_in_use_cases():
    for path in (CMR_USE_CASE, GENERIC_USE_CASE):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 2
        assert payload["application_processing"]["enabled_by_default"] is False
        # Compatibility keys remain until all old routes/jobs have migrated.
        assert "mapping" in payload
        assert "output" in payload


def test_semantic_helpers_live_in_application_namespace_with_legacy_shims():
    assert MISSING_VALUE_MARKERS == ("-", "–", "—")
    assert is_missing_value_text("-") is True
    assert legacy_schema_score is schema_candidate_score
    assert legacy_lateral is lateral_candidate_allowed


def test_architecture_document_preserves_existing_mapping_as_phase_two():
    text = ARCH.read_text(encoding="utf-8")
    assert "Primary product: a model bundle" in text
    assert "Optional phase 2: Application Processing" in text
    assert "Mapping Studio" in text
    assert "compatibility shims" in text


def test_architecture_split_version():
    assert VERSION.read_text(encoding="utf-8").strip() == "3.15.0"
