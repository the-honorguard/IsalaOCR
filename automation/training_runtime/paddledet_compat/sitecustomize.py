from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _install_replay_patch() -> None:
    # Only the actual training subprocess receives this marker. Dataset checking,
    # export and inference must keep the canonical dataset untouched.
    artifact_root = str(os.environ.get("ISALA_PADDLEDET_EVAL_ARTIFACT_DIR") or "").strip()
    if not artifact_root:
        return

    for candidate in (
        Path("/opt/paddlex-source"),
        Path("/opt/paddlex-source/paddlex/repo_manager/repos/PaddleDetection"),
        Path("/opt/isala-training"),
    ):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))

    from hard_example_replay import apply_replay_to_records
    from ppdet.data.source.coco import COCODataSet

    if getattr(COCODataSet.parse_dataset, "_isala_hard_example_replay", False):
        return

    original = COCODataSet.parse_dataset

    def parse_dataset_with_replay(self):
        original(self)
        anno_path = str(getattr(self, "anno_path", "") or "").replace("\\", "/")
        if not anno_path.endswith("instance_train.json"):
            return
        dataset_dir = Path(str(getattr(self, "dataset_dir", "") or "")).resolve()
        records = list(getattr(self, "roidbs", []) or [])
        replayed, summary = apply_replay_to_records(records, dataset_dir)
        if int(summary.get("extra_draws") or 0) <= 0:
            return
        self.roidbs = replayed

        artifact_dir = Path(artifact_root)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        marker = {
            **summary,
            "dataset": str(dataset_dir),
            "annotation": anno_path,
        }
        marker_path = artifact_dir / "hard_example_replay_runtime.json"
        marker_path.write_text(json.dumps(marker, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            "ISALA hard-example replay: "
            f"{summary['base_records']} basispanelen + {summary['extra_draws']} gewogen replay-draws "
            f"= {summary['effective_records']} trainingssamples; geen PNG/COCO-kopieen.",
            flush=True,
        )

    parse_dataset_with_replay._isala_hard_example_replay = True
    COCODataSet.parse_dataset = parse_dataset_with_replay


try:
    _install_replay_patch()
except Exception as exc:
    # Python normally treats sitecustomize failures as non-fatal. Make the
    # failure visible; table_cell_runner also verifies the runtime marker after
    # training and will fail closed when replay was expected but not applied.
    print(f"ISALA hard-example replay patch kon niet worden geinstalleerd: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
