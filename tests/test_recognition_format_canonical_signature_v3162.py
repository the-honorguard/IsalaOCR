"""The Recognition-format profile distinguishes a family's canonical (most
common) signature from a less common variant - a previously unused
``canonical_signatures`` computation left both the review-priority score
(``score_format``) and the format-profile page's "allowed" flag inert
(``"allowed": True`` was hardcoded for every signature). See
``documentation/CODE_REVIEW_v3.16.0.md`` for the review that flagged this.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from flask import Flask

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.recognition_format import build_profile, score_format
from isala_ocr.training.recognition_ground_truth import EXTRACTION_METHOD
from isala_ocr.training.recognition_ground_truth_web import install_recognition_ground_truth_review


def test_canonical_signature_is_the_most_common_signature_per_family() -> None:
    labels = ["106.8", "108.2", "99.1", "50,0"]
    profile = build_profile(labels)

    # "106.8"/"108.2"/"99.1" share signature "#.#" (dot decimal); "50,0" is the
    # lone comma-decimal variant "#,#". Both are family "number".
    assert profile["signatures"] == {"#.#": 3, "#,#": 1}
    assert profile["families"] == {"number": 4}
    assert profile["canonical_signatures"] == {"number": "#.#"}


def test_score_format_flags_a_known_but_non_canonical_signature() -> None:
    profile = build_profile(["106.8", "108.2", "99.1", "50,0"])

    canonical_score, canonical_reason = score_format("101.4", 0.97, profile)
    variant_score, variant_reason = score_format("60,0", 0.97, profile)
    unseen_score, unseen_reason = score_format("1/2/2026", 0.97, profile)

    assert "wijkt af van canoniek format" not in canonical_reason
    assert "wijkt af van canoniek format" in variant_reason
    assert variant_score > canonical_score
    # An entirely unseen signature is still scored as "nieuw format", not
    # double-counted as a canonical deviation on top of that.
    assert "nieuw format" in unseen_reason
    assert "wijkt af van canoniek format" not in unseen_reason


def _sample(sample_id: str, exact_label: str) -> dict:
    return {
        "sample_id": sample_id,
        "source_id": f"source-{sample_id}",
        "profile": "profile",
        "field_key": "recognition.value",
        "field_label": "Value",
        "crop_path": f"crops/{sample_id}.png",
        "raw_ocr": exact_label,
        "raw_confidence": 0.97,
        "raw_variant": "test",
        "image_width": 100,
        "image_height": 100,
        "roi_x1": 1,
        "roi_y1": 2,
        "roi_x2": 50,
        "roi_y2": 20,
        "extraction_method": EXTRACTION_METHOD,
        "locator_confidence": 0.95,
        "locator_label_text": "value",
        "locator_version": "test",
        "crop_sha256": sample_id,
    }


def _make_app(tmp_path: Path):
    # A bare Flask app with only this installer, rather than create_web_app()'s
    # full wizard: recognition-gt-* paths are gated behind completing every
    # earlier pipeline step (detection/localization/table review), which this
    # focused test has no reason to seed just to reach the format-profile page.
    workspace = tmp_path / "workspace"
    database = TrainingDatabase(workspace / "samples.sqlite3")
    accepted = {
        "s1": "106.8",
        "s2": "108.2",
        "s3": "99.1",
        "s4": "50,0",
    }
    for sample_id, exact_label in accepted.items():
        database.upsert_sample(_sample(sample_id, exact_label))
        database.review_roi(sample_id, "correct")
        database.review(sample_id, "accepted", exact_label, "test fixture")

    app = Flask(
        "isala_ocr.training.webui",
        template_folder=str(ROOT / "application/src/isala_ocr/training/templates"),
        static_folder=str(ROOT / "application/src/isala_ocr/training/static"),
    )

    @app.context_processor
    def _base_template_stub_context():
        # base.html (which recognition_gt_formats.html extends) normally gets
        # this from create_web_app()'s own @app.context_processor, which pulls
        # in the entire wizard/gate machinery. Stub it out here so the template
        # renders without dragging in the whole app factory for this test.
        always_open: dict[str, bool] = {}

        class _AlwaysTrue(dict):
            def get(self, key, default=None):
                return True

        return {
            "app_version": "test",
            "active_model": None,
            "active_project": None,
            "available_projects": [],
            "process_steps": [],
            "workflow_gates": _AlwaysTrue(),
            "workflow_step_access": _AlwaysTrue(),
            "visible_counts": {"total": 0, "pending": 0, "accepted": 0},
            "action_duration_estimates": {},
            "detection_gate_global": always_open,
            "pipeline_gate_global": always_open,
            "recognition_gate_global": always_open,
        }

    install_recognition_ground_truth_review(app, workspace)
    return app


def test_format_profile_page_marks_the_canonical_signature_allowed_and_the_rest_variant(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    client = app.test_client()

    listing = client.get("/recognition-gt-formats")
    assert listing.status_code == 200
    listing_text = listing.get_data(as_text=True)
    # Only the canonical signature is a clickable row in the main "allowed" list.
    assert "#.#" in listing_text
    assert "#,#" not in listing_text

    detail = client.get("/recognition-gt-formats", query_string={"signature": "#,#"})
    assert detail.status_code == 200
    detail_text = detail.get_data(as_text=True)
    assert 'class="pill warn">variant</span>' in detail_text
    assert "50,0" in detail_text

    canonical_detail = client.get("/recognition-gt-formats", query_string={"signature": "#.#"})
    canonical_text = canonical_detail.get_data(as_text=True)
    assert 'class="pill ok">toegestaan</span>' in canonical_text
