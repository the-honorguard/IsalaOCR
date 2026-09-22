"""Shared input discovery and project-selection handling.

The WebUI, source-preview step and collectors must use the same file universe.
Keeping this here prevents helper-specific extension filters from silently
processing files that the user could not select in Step 1A.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .projects import resolve_project_workspace

IGNORED_INPUT_EXTENSIONS = frozenset({
    ".ini", ".yaml", ".yml", ".json", ".txt", ".log", ".ps1", ".cmd", ".bat", ".gitkeep",
})


def input_files(path: Path) -> list[Path]:
    """Return processable files in deterministic relative-path order."""
    if path.is_file():
        return [path] if path.suffix.lower() not in IGNORED_INPUT_EXTENSIONS else []
    if not path.is_dir():
        return []
    return sorted(
        item for item in path.rglob("*")
        if item.is_file()
        and not any(part.startswith(".") for part in item.relative_to(path).parts)
        and item.suffix.lower() not in IGNORED_INPUT_EXTENSIONS
    )


def selection_manifest_path(workspace: Path) -> Path:
    return resolve_project_workspace(workspace) / "input_selection.json"


def selected_keys(workspace: Path) -> set[str] | None:
    """Return selected relative keys, or None when no valid manifest exists."""
    manifest = selection_manifest_path(workspace)
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
        values = payload.get("selected") or []
        return {
            str(value).replace("\\", "/").lstrip("/")
            for value in values if str(value).strip()
        }
    except (OSError, TypeError, ValueError):
        return None


def selected_input_files(path: Path, workspace: Path) -> list[Path]:
    """Every processable file under ``path``, filtered by Inputselectie's manifest.

    When ``path`` already names a single file (e.g. a proefpagina rerun's own
    target, passed straight through instead of the whole input directory --
    see routes_test_pipeline.py's ``_start_rerun()``), that file itself *is*
    the selection: there is nothing left to filter against the manifest, and
    ``item.relative_to(path)`` would be nonsensical here anyway (``path``
    equals its only ``item``, so it always resolves to ``"."``, which can
    never appear in a manifest -- silently discarding the one file every
    time a manifest happens to exist). Only a directory ``path`` still goes
    through manifest filtering, matching Step 1A's own semantics.
    """
    files = input_files(path)
    if path.is_file():
        return files
    selected = selected_keys(workspace)
    if selected is None:
        return files
    return [item for item in files if item.relative_to(path).as_posix() in selected]


def input_file_key(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def input_file_source_id(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:24]


def selection_payload(selected: set[str], *, reason: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"version": 1, "selected": sorted(selected)}
    if reason:
        payload["reason"] = reason
    return payload
