from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "automation" / "training_runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from hard_example_replay import apply_replay_to_records, replay_training_counts  # noqa: E402


def _scalar_image_id(value) -> int:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        value = value[0]
    return int(value)


def test_replay_reuses_panel_record_without_creating_dataset_copies(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "manifest.json").write_text(
        json.dumps({
            "hard_example_replay": {
                "strategy": "dynamic_panel_weighted_replay",
                "selected_extra_draws": 2,
                "panels": [
                    {"file_name": "a.png", "replay_count": 2, "error_streak": 2}
                ],
            }
        }),
        encoding="utf-8",
    )
    records = [
        {"im_file": str(dataset / "a.png"), "im_id": [1], "gt_bbox": [[1, 2, 3, 4]]},
        {"im_file": str(dataset / "b.png"), "im_id": [2], "gt_bbox": [[5, 6, 7, 8]]},
    ]

    replayed, summary = apply_replay_to_records(records, dataset)

    assert summary["base_records"] == 2
    assert summary["extra_draws"] == 2
    assert summary["effective_records"] == 4
    assert len(replayed) == 4
    assert [Path(str(item["im_file"])).name for item in replayed].count("a.png") == 3
    assert [Path(str(item["im_file"])).name for item in replayed].count("b.png") == 1
    assert len({_scalar_image_id(item["im_id"]) for item in replayed}) == 4
    assert replayed[2]["isala_hard_example_replay"] is True
    assert replayed[2]["gt_bbox"] == records[0]["gt_bbox"]
    assert not list(dataset.glob("*hard*"))


def test_effective_training_count_includes_replay_draws(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "manifest.json").write_text(
        json.dumps({
            "hard_example_replay": {
                "strategy": "dynamic_panel_weighted_replay",
                "panels": [
                    {"file_name": "a.png", "replay_count": 1},
                    {"file_name": "b.png", "replay_count": 2},
                ],
            }
        }),
        encoding="utf-8",
    )

    counts = replay_training_counts(dataset, base_images=18)

    assert counts == {
        "base_train_images": 18,
        "hard_example_replay_draws": 3,
        "effective_train_images": 21,
    }


def test_paddledetection_training_hook_is_fail_closed() -> None:
    hook = (RUNTIME / "paddledet_compat" / "sitecustomize.py").read_text(encoding="utf-8")
    runner = (RUNTIME / "table_cell_runner.py").read_text(encoding="utf-8")

    assert "ISALA_PADDLEDET_EVAL_ARTIFACT_DIR" in hook
    assert "COCODataSet.parse_dataset" in hook
    assert "apply_replay_to_records" in hook
    assert "hard_example_replay_runtime.json" in hook
    assert "geen PNG/COCO-kopieen" in hook
    assert "hard_example_replay_runtime.json" in runner
    assert "Hard-example replay was gepland" in runner
    assert "applied != replay_draws" in runner
