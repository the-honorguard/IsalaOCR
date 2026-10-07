"""quick_ocr_text_for_proposal() (webui.py, _table_panel_review_context) used
to shell out to `tesseract` (up to a 10s timeout) once per candidate table
region with no already-persisted OCR text nearby, in sequence, directly in
the panel-setup page's render path. These tests cover the fix: results are
cached per (source, box, render identity), and remaining cache misses in one
request run in parallel instead of one after another.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("flask")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.training.db import TrainingDatabase  # noqa: E402
from isala_ocr.training.projects import ProjectManager  # noqa: E402
from isala_ocr.training.webui import create_web_app  # noqa: E402

_FAKE_TESSERACT_DELAY = 0.3


class _FakeCompleted:
    def __init__(self, text: str) -> None:
        self.returncode = 0
        self.stdout = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num"
            "\tleft\ttop\twidth\theight\tconf\ttext\n"
            f"5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t95\t{text}\n"
        )
        self.stderr = ""


def _seed_project(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.14.0", encoding="utf-8")
    app = create_web_app(
        tmp_path / "training" / "workspace",
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
        config_path=ROOT / "application" / "config" / "app.yaml",
    )
    client = app.test_client()
    client.get("/")  # ensure the default project workspace exists on disk

    pm = ProjectManager(tmp_path / "training" / "workspace")
    workspace = pm.active_workspace()

    source_id = "source-a"
    render_dir = workspace / "source_renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    render_path = render_dir / f"{source_id}.png"
    import numpy as np

    image = np.full((400, 400, 3), 255, dtype="uint8")
    cv2.imwrite(str(render_path), image)

    db = TrainingDatabase(workspace / "samples.sqlite3")
    db.replace_localization_detection(
        {
            "source_id": source_id,
            "image_width": 400,
            "image_height": 400,
            "render_path": f"source_renders/{source_id}.png",
            "detector_version": "test",
            "token_count": 0,
        },
        candidates=[],
        tables=[
            {"table_id": "table-1", "x1": 0, "y1": 0, "x2": 100, "y2": 100, "confidence": 0.9, "cells": []},
            {"table_id": "table-2", "x1": 200, "y1": 200, "x2": 300, "y2": 300, "confidence": 0.9, "cells": []},
        ],
    )
    return app, client, source_id


def test_quick_ocr_results_are_cached_and_correct(tmp_path: Path, monkeypatch) -> None:
    app, client, source_id = _seed_project(tmp_path)
    calls: list[list] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _FakeCompleted(f"TOKEN-{len(calls)}")

    monkeypatch.setattr("isala_ocr.training.webui.subprocess.run", fake_run)

    response = client.get(f"/api/table-panel-review-source/{source_id}")
    assert response.status_code == 200
    payload = response.get_json()
    suggestions = payload["suggestions"]
    assert len(suggestions) == 2
    observed = {item["ocr_table_text"] for item in suggestions}
    assert observed == {"TOKEN-1", "TOKEN-2"}
    assert len(calls) == 2

    # A second request for the exact same (unchanged) proposals/render must
    # reuse the cached OCR text instead of calling tesseract again.
    response_again = client.get(f"/api/table-panel-review-source/{source_id}")
    assert response_again.status_code == 200
    assert len(calls) == 2, "cached quick-OCR results must not re-invoke tesseract"


def test_quick_ocr_cache_misses_run_in_parallel_not_sequentially(tmp_path: Path, monkeypatch) -> None:
    app, client, source_id = _seed_project(tmp_path)

    def slow_fake_run(args, **kwargs):
        time.sleep(_FAKE_TESSERACT_DELAY)
        return _FakeCompleted("SLOW-TOKEN")

    monkeypatch.setattr("isala_ocr.training.webui.subprocess.run", slow_fake_run)

    started = time.monotonic()
    response = client.get(f"/api/table-panel-review-source/{source_id}")
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    suggestions = response.get_json()["suggestions"]
    assert len(suggestions) == 2
    assert all(item["ocr_table_text"] == "SLOW-TOKEN" for item in suggestions)
    # Two proposals needing OCR, each with a 0.3s fake tesseract call: run
    # sequentially this would take >=0.6s; run in parallel it should take
    # well under that - comfortably below the 2x-delay sequential floor.
    assert elapsed < _FAKE_TESSERACT_DELAY * 1.8, (
        f"expected parallel execution (~{_FAKE_TESSERACT_DELAY}s), took {elapsed:.2f}s - "
        "looks like the quick-OCR calls ran sequentially"
    )
