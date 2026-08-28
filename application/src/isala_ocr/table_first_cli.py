from __future__ import annotations

import sys
from pathlib import Path

from .cli import main as legacy_cli_main
from .config import load_config
from .training.db import TrainingDatabase
from .training.projects import resolve_project_workspace
from .training.table_cell_ground_truth import (
    ensure_table_cell_ground_truth,
    ground_truth_review_state,
)


VALUE_PIPELINE_COMMANDS = {
    "collect-mapping",
    "apply-mappings",
    "read-mapped-values",
    "build-dataset",
    "evaluate-recognition",
    "register-model",
    "activate-model",
    "run-application-pipeline",
}


def _argument_value(argv: list[str], name: str) -> str | None:
    try:
        index = argv.index(name)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    value = str(argv[index + 1] or "").strip()
    return value or None


def _sync_table_first_gate(argv: list[str]) -> None:
    if not argv or argv[0] not in VALUE_PIPELINE_COMMANDS:
        return

    config_path = _argument_value(argv, "--config") or "/app/config/app.yaml"
    config = load_config(config_path)
    workspace_override = _argument_value(argv, "--workspace")
    workspace_base = Path(
        workspace_override
        or config.raw.get("training", {}).get("workspace", "/training/workspace")
    )
    workspace = resolve_project_workspace(workspace_base)

    # Projects without canonical table-cell GT still use the historic field-detector
    # Detection Gate. Once canonical GT exists, table-first state is authoritative.
    if ensure_table_cell_ground_truth(workspace) is None:
        return

    state = ground_truth_review_state(workspace)
    source_count = int(state.get("source_count") or 0)
    open_source_count = int(state.get("open_source_count") or 0)
    gt_cell_count = int(state.get("gt_cell_count") or 0)
    ready = bool(source_count > 0 and gt_cell_count > 0 and open_source_count == 0)

    if ready:
        reason = (
            f"Canonical table-cell Ground Truth ready: {source_count} source(s), "
            f"{gt_cell_count} cell(s), 0 open GT source(s)."
        )
    elif source_count == 0 or gt_cell_count == 0:
        reason = "Canonical table-cell Ground Truth is missing or contains no cells."
    else:
        reason = (
            f"Canonical table-cell Ground Truth still has {open_source_count} open "
            f"source(s) out of {source_count}."
        )

    TrainingDatabase(workspace / "samples.sqlite3").set_detection_gate(
        ready,
        reason=reason,
        evaluation_id="",
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    _sync_table_first_gate(arguments)
    return legacy_cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
