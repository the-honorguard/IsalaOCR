from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .logging_utils import configure_logging
from .ocr.paddle import PaddleEngine
from .table_first_cli import main as table_first_legacy_main
from .training.db import TrainingDatabase
from .training.mapping_ground_truth import collect_mapping_from_canonical_gt
from .training.projects import resolve_project_workspace
from .training.table_cell_ground_truth import ensure_table_cell_ground_truth, ground_truth_review_state

LOGGER = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="isala_ocr.mapping_gt_cli",
        description="Prepare Mapping Studio from canonical table-cell Ground Truth.",
    )
    parser.add_argument("--log-level", default="INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect-mapping")
    collect.add_argument("--input", required=True)
    collect.add_argument("--workspace")
    collect.add_argument("--config", default="/app/config/app.yaml")
    collect.add_argument("--device")
    return parser


def _sync_canonical_gate(workspace: Path) -> dict[str, object]:
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
    return {**state, "ready": ready, "reason": reason}


def _collect_mapping(args: argparse.Namespace, original_argv: list[str]) -> int:
    config = load_config(args.config)
    if args.device:
        config.raw.setdefault("ocr", {})["device"] = args.device

    strategy = str(
        config.raw.get("training", {}).get("localization", {}).get("strategy") or "fusion"
    ).strip().lower()
    workspace_base = Path(
        args.workspace
        or config.raw.get("training", {}).get("workspace", "/training/workspace")
    )
    workspace = resolve_project_workspace(workspace_base)

    # Keep legacy/fusion projects untouched. Table-first projects without a
    # canonical GT also retain the old compatibility path until their GT exists.
    canonical_gt = ensure_table_cell_ground_truth(workspace) if strategy == "table_first" else None
    if strategy != "table_first" or canonical_gt is None:
        LOGGER.info("Canonical GT mapping is not active; delegating to the existing mapping runner.")
        return int(table_first_legacy_main(original_argv))

    state = _sync_canonical_gate(workspace)
    if not bool(state.get("ready")):
        raise RuntimeError(str(state.get("reason") or "Canonical table-cell Ground Truth is not ready"))

    locator_settings = dict(config.ocr)
    locator_settings.pop("active_recognition_model_dir", None)
    locator_settings["recognition_model"] = str(
        config.raw.get("training", {}).get("collection", {}).get(
            "locator_recognition_model", "PP-OCRv6_small_rec"
        )
    )
    locator_engine = PaddleEngine(locator_settings)
    manifest = collect_mapping_from_canonical_gt(
        args.input,
        workspace,
        config,
        locator_engine,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 1 if manifest.get("failed_items") else 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    args = parser.parse_args(arguments)
    configure_logging(args.log_level)
    try:
        if args.command == "collect-mapping":
            return _collect_mapping(args, arguments)
        parser.error(f"Unsupported command: {args.command}")
        return 2
    except (ConfigError, FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
