from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_EPOCH = re.compile(r"epoch:\s*\[(?P<epoch>\d+)\s*/\s*(?P<total>\d+)\]", re.IGNORECASE)
_CURRENT_METRIC = re.compile(
    r"cur metric,\s*acc:\s*(?P<acc>[-+0-9.eE]+),\s*"
    r"norm_edit_dis:\s*(?P<norm>[-+0-9.eE]+),\s*fps:\s*(?P<fps>[-+0-9.eE]+)",
    re.IGNORECASE,
)
_BEST_METRIC = re.compile(
    r"best metric,\s*acc:\s*(?P<acc>[-+0-9.eE]+).*?"
    r"norm_edit_dis:\s*(?P<norm>[-+0-9.eE]+).*?"
    r"fps:\s*(?P<fps>[-+0-9.eE]+).*?best_epoch:\s*(?P<epoch>\d+)",
    re.IGNORECASE,
)
_TRAIN_BATCHES = re.compile(r"train dataloader has\s+(?P<count>\d+)\s+iters", re.IGNORECASE)
_VALID_BATCHES = re.compile(r"valid dataloader has\s+(?P<count>\d+)\s+iters", re.IGNORECASE)
_LOG_PATH = re.compile(r"Log path:\s*(?P<path>.+)$", re.IGNORECASE)

_SUPPRESSED_FRAGMENTS = (
    "Export inference config file to",
    "Skipping import of the encryption module",
    "inference model is saved to",
    "Already save model info in",
    "save model in",
    "save best model is to",
    "eval model::",
    "ppocr INFO: Architecture",
    "ppocr INFO: Eval :",
    "ppocr INFO: Global :",
    "ppocr INFO: Loss :",
    "ppocr INFO: Metric :",
    "ppocr INFO: Optimizer :",
    "ppocr INFO: PostProcess :",
    "ppocr INFO: Train :",
    "ppocr INFO: profiler_options",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_field(line: str, name: str) -> str | None:
    match = re.search(rf"(?:^|,\s*){re.escape(name)}:\s*([^,]+)", line, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _format_float(value: float | None, digits: int = 4) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _format_eta(value: str | None) -> str:
    if not value:
        return "--:--:--"
    parts = value.strip().split(":")
    if len(parts) == 3:
        return ":".join(part.zfill(2) for part in parts)
    return value.strip()


class TrainingProgressRenderer:
    """Render compact PaddleOCR progress while preserving the complete raw log."""

    def __init__(
        self,
        output_directory: Path,
        total_epochs: int,
        *,
        device: str | None = None,
        verbose: bool = False,
        stream: TextIO | None = None,
        bar_width: int = 28,
    ) -> None:
        self.output_directory = Path(output_directory)
        self.output_directory.mkdir(parents=True, exist_ok=True)
        self.total_epochs = max(1, int(total_epochs))
        self.device = str(device or "").strip().lower() or None
        self.verbose = bool(verbose)
        self.stream = stream or sys.stdout
        self.bar_width = max(10, int(bar_width))
        self.raw_log_path = self.output_directory / "training-console.log"
        self.progress_path = self.output_directory / "training-progress.json"
        self.started_monotonic = time.monotonic()
        self.started_at = _utc_now()
        self.current_epoch = 0
        self.reported_total = self.total_epochs
        self.global_step: int | None = None
        self.learning_rate: float | None = None
        self.train_accuracy: float | None = None
        self.train_norm_edit_distance: float | None = None
        self.loss: float | None = None
        self.eta: str | None = None
        self.memory_mb: int | None = None
        self.validation_accuracy: float | None = None
        self.validation_norm_edit_distance: float | None = None
        self.validation_fps: float | None = None
        self.best_accuracy: float | None = None
        self.best_norm_edit_distance: float | None = None
        self.best_fps: float | None = None
        self.best_epoch: int | None = None
        self.train_batches: int | None = None
        self.validation_batches: int | None = None
        self._last_emitted_epoch = 0
        self._training_phase_announced = False
        self._dataset_phase_announced = False
        self._error_passthrough = False
        self._raw_handle = self.raw_log_path.open("w", encoding="utf-8", newline="")
        self._write_status("starting")
        self._print("[1/4] Initializing PaddleX trainer")
        self._print(f"      Detailed log: {self.raw_log_path}")

    def record_command(self, command: list[str]) -> None:
        self._raw_handle.write("Executing: " + " ".join(command) + "\n")
        self._raw_handle.flush()

    def feed(self, raw_line: str) -> None:
        self._raw_handle.write(raw_line)
        self._raw_handle.flush()

        line = _ANSI_ESCAPE.sub("", raw_line).rstrip("\r\n")
        if self.verbose:
            self._print(line)

        if not line:
            return

        if line.startswith("Traceback (most recent call last):"):
            self._error_passthrough = True
        if self._error_passthrough:
            if not self.verbose:
                self._print(line)
            return

        log_path = _LOG_PATH.search(line)
        if log_path and not self.verbose:
            self._print(f"      PaddleOCR log: {log_path.group('path').strip()}")
            return

        train_batches = _TRAIN_BATCHES.search(line)
        if train_batches:
            self.train_batches = int(train_batches.group("count"))
            self._announce_dataset_phase_if_ready()
            self._write_status("running")
            return

        validation_batches = _VALID_BATCHES.search(line)
        if validation_batches:
            self.validation_batches = int(validation_batches.group("count"))
            self._announce_dataset_phase_if_ready()
            self._write_status("running")
            return

        epoch = _EPOCH.search(line)
        if epoch:
            incoming_epoch = int(epoch.group("epoch"))
            incoming_total = int(epoch.group("total"))
            if self.current_epoch and incoming_epoch > self.current_epoch:
                self._emit_epoch(self.current_epoch)
            self.current_epoch = incoming_epoch
            self.reported_total = incoming_total or self.total_epochs
            self.global_step = _int(_extract_field(line, "global_step"))
            self.learning_rate = _float(_extract_field(line, "lr"))
            self.train_accuracy = _float(_extract_field(line, "acc"))
            self.train_norm_edit_distance = _float(_extract_field(line, "norm_edit_dis"))
            self.loss = _float(_extract_field(line, "loss"))
            self.eta = _extract_field(line, "eta")
            memory = _extract_field(line, "max_mem_allocated")
            if memory:
                self.memory_mb = _int(memory.split()[0])
            if not self._training_phase_announced:
                self._print("[3/4] Training")
                self._training_phase_announced = True
            self._write_status("running")
            return

        current = _CURRENT_METRIC.search(line)
        if current:
            self.validation_accuracy = _float(current.group("acc"))
            self.validation_norm_edit_distance = _float(current.group("norm"))
            self.validation_fps = _float(current.group("fps"))
            self._write_status("running")
            return

        best = _BEST_METRIC.search(line)
        if best:
            self.best_accuracy = _float(best.group("acc"))
            self.best_norm_edit_distance = _float(best.group("norm"))
            self.best_fps = _float(best.group("fps"))
            self.best_epoch = _int(best.group("epoch"))
            self._emit_epoch(self.current_epoch)
            self._write_status("running")
            return

        if self.verbose:
            return

        lowered = line.lower()
        if any(fragment.lower() in lowered for fragment in _SUPPRESSED_FRAGMENTS):
            return
        if "ppocr info:" in lowered and ("    " in line or line.rstrip().endswith(":")):
            return
        if "warning" in lowered or "error" in lowered or "failed" in lowered:
            self._print(line)

    def finish(self, return_code: int) -> None:
        if self.current_epoch:
            self._emit_epoch(self.current_epoch)
        elapsed_seconds = max(0.0, time.monotonic() - self.started_monotonic)
        if return_code == 0:
            self._print("[4/4] Finalizing model artifacts")
            self._print(
                "Completed: "
                f"{self.current_epoch or self.total_epochs}/{self.reported_total or self.total_epochs} epochs | "
                f"best validation accuracy {_format_float(self.best_accuracy, 6)}"
                + (f" at epoch {self.best_epoch}" if self.best_epoch is not None else "")
                + f" | elapsed {self._format_duration(elapsed_seconds)}"
            )
            self._write_status("completed", return_code=return_code)
        else:
            self._print(
                f"Training process failed with exit code {return_code}. "
                f"See {self.raw_log_path}"
            )
            self._write_status("failed", return_code=return_code)
        self._raw_handle.close()

    def close(self) -> None:
        if not self._raw_handle.closed:
            self._raw_handle.close()

    def _announce_dataset_phase_if_ready(self) -> None:
        if self._dataset_phase_announced:
            return
        if self.train_batches is None or self.validation_batches is None:
            return
        train_label = "batch" if self.train_batches == 1 else "batches"
        validation_label = "batch" if self.validation_batches == 1 else "batches"
        self._print(
            f"[2/4] Dataset loaded: {self.train_batches} training {train_label}, "
            f"{self.validation_batches} validation {validation_label} per epoch"
        )
        self._dataset_phase_announced = True

    def _emit_epoch(self, epoch: int) -> None:
        if epoch <= 0 or epoch <= self._last_emitted_epoch:
            return
        total = max(1, self.reported_total or self.total_epochs)
        percentage = min(100, max(0, round(epoch * 100 / total)))
        filled = min(self.bar_width, round(self.bar_width * epoch / total))
        bar = "#" * filled + "-" * (self.bar_width - filled)
        validation = self.validation_accuracy
        best = self.best_accuracy
        segments = [
            f"[{bar}] {percentage:3d}%",
            f"epoch {epoch}/{total}",
            f"val {_format_float(validation)}",
            f"best {_format_float(best)}" + (f"@{self.best_epoch}" if self.best_epoch is not None else ""),
            f"loss {_format_float(self.loss)}",
            f"ETA {_format_eta(self.eta)}",
        ]
        if self.memory_mb is not None:
            segments.append(f"GPU {self.memory_mb / 1024:.1f} GB")
        self._print(" | ".join(segments))
        self._last_emitted_epoch = epoch

    def _snapshot(self, status: str, return_code: int | None = None) -> dict[str, Any]:
        total = max(1, self.reported_total or self.total_epochs)
        epoch = max(0, self.current_epoch)
        snapshot: dict[str, Any] = {
            "status": status,
            "device": self.device,
            "started_at": self.started_at,
            "updated_at": _utc_now(),
            "epoch": epoch,
            "total_epochs": total,
            "progress_percent": round(min(100.0, epoch * 100.0 / total), 2),
            "global_step": self.global_step,
            "learning_rate": self.learning_rate,
            "train_accuracy": self.train_accuracy,
            "train_norm_edit_distance": self.train_norm_edit_distance,
            "validation_accuracy": self.validation_accuracy,
            "validation_norm_edit_distance": self.validation_norm_edit_distance,
            "validation_fps": self.validation_fps,
            "best_accuracy": self.best_accuracy,
            "best_norm_edit_distance": self.best_norm_edit_distance,
            "best_fps": self.best_fps,
            "best_epoch": self.best_epoch,
            "loss": self.loss,
            "eta": self.eta,
            "memory_mb": self.memory_mb,
            "training_batches_per_epoch": self.train_batches,
            "validation_batches_per_epoch": self.validation_batches,
            "raw_log": str(self.raw_log_path),
            "compact_console": not self.verbose,
        }
        if return_code is not None:
            snapshot["return_code"] = int(return_code)
        return snapshot

    def _write_status(self, status: str, return_code: int | None = None) -> None:
        payload = self._snapshot(status, return_code)
        temporary = self.progress_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.progress_path)

    def _print(self, message: str) -> None:
        print(message, file=self.stream, flush=True)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = int(round(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
