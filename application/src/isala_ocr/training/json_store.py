"""Small, consistent JSON persistence primitives used by the training WebUI.

All writes go through a sibling temporary file before replacement so a worker
or browser refresh cannot observe a half-written manifest.  Readers are
deliberately tolerant because these files are user-editable workflow state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def read_json(path: str | Path, default: T | None = None) -> Any:
    """Read UTF-8 JSON, returning ``default`` for missing/invalid files."""

    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, TypeError, ValueError):
        return default


def read_json_object(path: str | Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read a JSON object and reject arrays/scalars at the boundary."""

    fallback = default if default is not None else {}
    payload = read_json(path, fallback)
    return payload if isinstance(payload, dict) else fallback


def write_json_atomic(path: str | Path, payload: Any, *, allow_nan: bool = True) -> Path:
    """Atomically replace ``path`` with formatted, UTF-8 JSON."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=allow_nan),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target
