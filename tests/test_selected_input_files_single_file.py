"""``selected_input_files()`` (input_selection.py) must treat a single-file
``path`` as an already-final selection, not filter it against Inputselectie's
manifest.

Bug this guards against: when ``path`` names one specific file (e.g. a
proefpagina rerun's own target -- see routes_test_pipeline.py's
``_start_rerun()``, which passes the rerun's exact DICOM copy straight
through instead of the whole input directory), the pre-fix code still ran
``item.relative_to(path)`` against every one of ``input_files(path)``'s
results. Since ``path`` and its only ``item`` are the same file, that always
resolved to ``"."`` -- which can never appear in a manifest -- so any run
that happened to have an ``input_selection.json`` on disk silently produced
zero selected files for a single-file ``path``, even though the manifest was
completely irrelevant to a request that already named its one file.
"""

from __future__ import annotations

import json
from pathlib import Path

from isala_ocr.training.input_selection import selected_input_files


def test_single_file_path_is_returned_regardless_of_manifest_content(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "input" / "test_abc123_original.dcm"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fake-dicom-bytes")

    # A manifest exists but does not mention this file at all -- exactly the
    # situation after a proefpagina rerun passes its own file straight
    # through instead of registering it in the shared manifest.
    (workspace / "input_selection.json").write_text(
        json.dumps({"version": 1, "selected": ["some_other_file.dcm"]}), encoding="utf-8",
    )

    result = selected_input_files(target, workspace)

    assert result == [target], "a single-file path is already the whole selection"


def test_single_file_path_returned_when_no_manifest_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "input" / "test_abc123_original.dcm"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fake-dicom-bytes")

    assert selected_input_files(target, workspace) == [target]


def test_directory_path_still_filters_by_manifest(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    input_root = tmp_path / "input"
    input_root.mkdir()
    kept = input_root / "kept.dcm"
    kept.write_bytes(b"kept")
    dropped = input_root / "dropped.dcm"
    dropped.write_bytes(b"dropped")

    (workspace / "input_selection.json").write_text(
        json.dumps({"version": 1, "selected": ["kept.dcm"]}), encoding="utf-8",
    )

    result = selected_input_files(input_root, workspace)

    assert result == [kept], "directory selection must still respect the manifest"
