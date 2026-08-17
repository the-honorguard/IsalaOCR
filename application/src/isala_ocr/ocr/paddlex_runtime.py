from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


_RUNTIME_DIRS = ("temp", "locks", "func_ret")


def prepare_paddlex_runtime(settings: dict[str, Any]) -> Path:
    """Prepare PaddleX's cache before importing PaddleOCR/PaddleX.

    PaddleX resolves its cache paths at import time and always needs writable
    ``temp``, ``locks`` and ``func_ret`` directories, even when all official
    model weights are already available locally. Preparing and probing the
    cache before the import avoids a partially initialized PaddleX module.
    """

    model_root = Path(str(settings.get("model_root", "/models/paddlex")))
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(model_root)
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

    allow_downloads = bool(settings.get("allow_downloads", False))
    if not allow_downloads:
        if not model_root.exists() or not any(model_root.iterdir()):
            raise RuntimeError(
                f"Offline model cache is empty: {model_root}. Run model preparation first."
            )

    try:
        model_root.mkdir(parents=True, exist_ok=True)
        for name in _RUNTIME_DIRS:
            (model_root / name).mkdir(parents=True, exist_ok=True)
        # A real write probe catches read-only bind mounts before PaddleX is
        # imported. That prevents the misleading follow-up error about PDX
        # already being initialized.
        with tempfile.NamedTemporaryFile(dir=model_root / "temp", prefix="isalaocr_"):
            pass
    except OSError as exc:
        raise RuntimeError(
            "PaddleX runtime cache is not writable at "
            f"{model_root}. The Docker models mount must be writable at runtime; "
            "remove ':ro' from the ./models:/models volume mapping."
        ) from exc

    return model_root
