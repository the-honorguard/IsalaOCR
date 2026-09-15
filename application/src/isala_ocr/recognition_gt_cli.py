from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .config import ConfigError, load_config
from .logging_utils import configure_logging
from .ocr.recognition import PaddleRecognitionEngine
from .training.projects import resolve_project_workspace
from .training.recognition_ground_truth import materialize_recognition_ground_truth

LOGGER = logging.getLogger(__name__)


def _baseline_engine(config) -> PaddleRecognitionEngine:
    settings = dict(config.ocr)
    collection = config.raw.get("training", {}).get("collection", {})
    if isinstance(collection, dict):
        baseline_name = str(collection.get("locator_recognition_model") or "").strip()
        if baseline_name:
            settings["recognition_model"] = baseline_name
    # Recognition GT must be bootstrapped by a generic/pretrained recognizer,
    # not by whichever project-specific custom model happens to be active.
    settings.pop("active_recognition_model_dir", None)
    settings.pop("recognition_model_dir", None)
    return PaddleRecognitionEngine(settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build neutral recognition GT from canonical table-cell geometry")
    parser.add_argument("--workspace", default="/training/workspace")
    parser.add_argument("--config", default="/app/config/app.yaml")
    parser.add_argument("--no-ocr", action="store_true", help="Only materialize crops; do not create baseline OCR suggestions")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    try:
        config = load_config(args.config)
        workspace = resolve_project_workspace(Path(args.workspace))
        engine = None if args.no_ocr else _baseline_engine(config)
        summary = materialize_recognition_ground_truth(workspace, recognition_engine=engine)
    except (ConfigError, FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
