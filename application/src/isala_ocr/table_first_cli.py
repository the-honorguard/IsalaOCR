from __future__ import annotations

import sys
from pathlib import Path

from .cli import main as legacy_cli_main
from .config import load_config
from .training.projects import resolve_project_workspace
from .training.table_cell_ground_truth import (
    ensure_table_cell_ground_truth,
    sync_canonical_detection_gate,
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

    sync_canonical_detection_gate(workspace)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    _sync_table_first_gate(arguments)
    return legacy_cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
