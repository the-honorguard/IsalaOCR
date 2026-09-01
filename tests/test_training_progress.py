from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path


def _load_progress_renderer():
    module_path = Path(__file__).resolve().parents[1] / "automation" / "training_runtime" / "training_progress.py"
    spec = importlib.util.spec_from_file_location("isala_training_progress", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TrainingProgressRenderer


TrainingProgressRenderer = _load_progress_renderer()


def test_compact_progress_collapses_batch_and_checkpoint_noise(tmp_path: Path) -> None:
    output = io.StringIO()
    renderer = TrainingProgressRenderer(tmp_path, 50, stream=output)
    renderer.record_command(["python3", "tools/train.py"])
    lines = [
        "Log path: /training/workspace/runs/example/train.log\n",
        "[2026/08/06] ppocr INFO: train dataloader has 21 iters\n",
        "[2026/08/06] ppocr INFO: valid dataloader has 1 iters\n",
        "[2026/08/06] ppocr INFO: epoch: [8/50], global_step: 150, lr: 0.000100, acc: 0.944940, norm_edit_dis: 0.993552, CTCLoss: 0.234111, NRTRLoss: 1.434562, loss: 1.697946, avg_reader_cost: 0.06588 s, avg_batch_cost: 0.14725 s, avg_samples: 5.8, ips: 39.38815 samples/s, eta: 0:04:26, max_mem_reserved: 5140 MB, max_mem_allocated: 4339 MB\n",
        "[2026/08/06] ppocr INFO: epoch: [8/50], global_step: 168, lr: 0.000099, acc: 0.984375, norm_edit_dis: 0.998264, CTCLoss: 0.178933, NRTRLoss: 1.448029, loss: 1.632242, avg_reader_cost: 0.00106 s, avg_batch_cost: 0.16773 s, avg_samples: 17.0, ips: 101.35329 samples/s, eta: 0:04:14, max_mem_reserved: 5140 MB, max_mem_allocated: 4339 MB\n",
        "eval model:: 100%|##########| 1/1 [00:00<00:00, 2.04it/s]\n",
        "[2026/08/06] ppocr INFO: cur metric, acc: 0.9999996875000976, norm_edit_dis: 1.0, fps: 470.05700877300507\n",
        "[2026/08/06] ppocr INFO: Export inference config file to /run/latest/inference.yml\n",
        "Skipping import of the encryption module\n",
        "[2026/08/06] ppocr INFO: best metric, acc: 0.9999996875000976, is_float16: False, norm_edit_dis: 1.0, fps: 470.05700877300507, best_epoch: 8\n",
    ]
    for line in lines:
        renderer.feed(line)
    renderer.finish(0)

    rendered = output.getvalue()
    assert "[1/4] Initializing PaddleX trainer" in rendered
    assert "[2/4] Dataset loaded: 21 training batches, 1 validation batch per epoch" in rendered
    assert "[3/4] Training" in rendered
    assert " 16% | epoch 8/50" in rendered
    assert "val 1.0000" in rendered
    assert "best 1.0000@8" in rendered
    assert "loss 1.6322" in rendered
    assert "ETA 00:04:14" in rendered
    assert "Export inference config" not in rendered
    assert "Skipping import of the encryption module" not in rendered
    assert rendered.count("epoch 8/50") == 1

    raw = (tmp_path / "training-console.log").read_text(encoding="utf-8")
    assert "Executing: python3 tools/train.py" in raw
    assert "Export inference config file" in raw
    assert "Skipping import of the encryption module" in raw

    progress = json.loads((tmp_path / "training-progress.json").read_text(encoding="utf-8"))
    assert progress["status"] == "completed"
    assert progress["epoch"] == 8
    assert progress["total_epochs"] == 50
    assert progress["progress_percent"] == 16.0
    assert progress["best_epoch"] == 8
    assert progress["best_accuracy"] == 0.9999996875000976
    assert progress["return_code"] == 0


def test_detailed_output_preserves_console_lines(tmp_path: Path) -> None:
    output = io.StringIO()
    renderer = TrainingProgressRenderer(tmp_path, 2, verbose=True, stream=output)
    renderer.feed("plain PaddleOCR detail\n")
    renderer.finish(1)

    rendered = output.getvalue()
    assert "plain PaddleOCR detail" in rendered
    assert "failed with exit code 1" in rendered
    progress = json.loads((tmp_path / "training-progress.json").read_text(encoding="utf-8"))
    assert progress["status"] == "failed"
    assert progress["return_code"] == 1


def test_progress_snapshot_keeps_logical_device_scope(tmp_path: Path) -> None:
    output = io.StringIO()
    renderer = TrainingProgressRenderer(tmp_path, 2, device="gpu", stream=output)
    renderer.finish(0)

    progress = json.loads((tmp_path / "training-progress.json").read_text(encoding="utf-8"))
    assert progress["device"] == "gpu"
