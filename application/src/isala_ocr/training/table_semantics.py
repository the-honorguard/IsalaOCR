from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .json_store import read_json, write_json_atomic


FILENAME = "table_semantic_assignments.json"


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(value).casefold()))


def load_assignments(workspace: str | Path) -> dict[str, dict[str, Any]]:
    payload = read_json(Path(workspace) / FILENAME, {}) or {}
    return dict(payload.get("assignments") or {})


def save_assignment(workspace: str | Path, table_id: str, table_name: str) -> dict[str, Any]:
    path = Path(workspace) / FILENAME
    payload = read_json(path, {}) or {"schema_version": 1, "assignments": {}}
    assignments = dict(payload.get("assignments") or {})
    assignments[str(table_id)] = {"table_name": str(table_name).strip(), "source": "user"}
    payload["assignments"] = assignments
    write_json_atomic(path, payload)
    return assignments[str(table_id)]


def suggest_table_name(ocr_text: str, configured_names: list[str], fallback: str) -> tuple[str, str]:
    evidence = _tokens(ocr_text)
    scored = []
    for name in configured_names:
        keywords = _tokens(name)
        if keywords:
            scored.append((len(evidence & keywords) / len(keywords), name))
    scored.sort(reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][1], "ocr_keywords"
    return fallback, "geometry_or_fallback"
