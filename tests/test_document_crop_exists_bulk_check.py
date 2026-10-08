"""document() (routes_documents.py) used to call
safe_workspace_file(sample["crop_path"]).is_file() - a full symlink-resolving
realpath resolution plus a stat - once per sample on every /documents/<id>
view. Since every sample on that page shares the same source_id and
crop_path is always "crops/original/<source_id>/<field_key>.png"
(collector.py), this is now one directory scan plus an in-memory
set-membership check instead. This test locks in that the per-sample
crop_exists result stays correct for both an existing and a missing crop.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.training.db import TrainingDatabase  # noqa: E402
from isala_ocr.training.projects import ProjectManager  # noqa: E402
from isala_ocr.training.webui import create_web_app  # noqa: E402


def test_crop_exists_reflects_actual_files_per_sample(tmp_path: Path) -> None:
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
    crop_dir = workspace / "crops" / "original" / source_id
    crop_dir.mkdir(parents=True, exist_ok=True)
    (crop_dir / "field-present.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # field-missing.png is deliberately never written.

    db = TrainingDatabase(workspace / "samples.sqlite3")
    for field_key in ("field-present", "field-missing"):
        db.upsert_sample({
            "sample_id": f"{source_id}_{field_key}",
            "source_id": source_id,
            "profile": "test",
            "field_key": field_key,
            "field_label": field_key,
            "crop_path": f"crops/original/{source_id}/{field_key}.png",
            "raw_ocr": "", "raw_confidence": 0.0, "raw_variant": "original",
            "image_width": 400,
            "image_height": 400,
            "roi_x1": 0, "roi_y1": 0, "roi_x2": 10, "roi_y2": 10,
        })

    html = client.get(f"/documents/{source_id}").get_data(as_text=True)
    assert f'src="/crop/{source_id}_field-present"' in html
    assert "Crop ontbreekt" in html
    # The missing sample must not be misreported as present.
    assert f'src="/crop/{source_id}_field-missing"' not in html
