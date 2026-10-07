"""table_semantic_detect_api() (routes_table_panel_config.py) used to run a
sequential, blocking `tesseract` subprocess call (up to a 20s timeout) for
every table region with no already-persisted relation text, directly in the
request thread, and re-decoded the source render image from disk once per
region plus looked up the detection source once per region. These tests
cover the fix: the OCR fallback is cached per (source, box, render identity)
and the remaining cache misses in one request run in parallel.
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
from isala_ocr.training.table_panels import save_panel_definitions  # noqa: E402
from isala_ocr.training.webui import create_web_app  # noqa: E402

_FAKE_TESSERACT_DELAY = 0.3


class _FakeCompleted:
    def __init__(self, text: str) -> None:
        self.returncode = 0
        self.stdout = text.encode("utf-8")
        self.stderr = b""


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
    save_panel_definitions(workspace, definitions=[{"name": "Left ventricle", "hits": ["LV"]}])

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
    return client, source_id


def test_table_semantic_detect_caches_and_does_not_reinvoke_tesseract(tmp_path: Path, monkeypatch) -> None:
    client, source_id = _seed_project(tmp_path)
    calls: list[list] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _FakeCompleted(f"LV TOKEN {len(calls)}")

    monkeypatch.setattr("isala_ocr.training.routes_table_panel_config.subprocess.run", fake_run)

    response = client.post(f"/api/table-semantic-detect/{source_id}")
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["proposals"]) == 2
    assert len(calls) == 2, "each of the two regions with no relation text should get its own OCR call"

    response_again = client.post(f"/api/table-semantic-detect/{source_id}")
    assert response_again.status_code == 200
    assert len(calls) == 2, "cached OCR results must not re-invoke tesseract on an unchanged render"


def test_table_semantic_detect_runs_ocr_fallback_in_parallel(tmp_path: Path, monkeypatch) -> None:
    client, source_id = _seed_project(tmp_path)

    def slow_fake_run(args, **kwargs):
        time.sleep(_FAKE_TESSERACT_DELAY)
        return _FakeCompleted("LV")

    monkeypatch.setattr("isala_ocr.training.routes_table_panel_config.subprocess.run", slow_fake_run)

    started = time.monotonic()
    response = client.post(f"/api/table-semantic-detect/{source_id}")
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert len(response.get_json()["proposals"]) == 2
    # Two regions each needing a 0.3s fake tesseract call: sequential would
    # take >=0.6s, parallel should take well under that.
    assert elapsed < _FAKE_TESSERACT_DELAY * 1.8, (
        f"expected parallel execution (~{_FAKE_TESSERACT_DELAY}s), took {elapsed:.2f}s"
    )
