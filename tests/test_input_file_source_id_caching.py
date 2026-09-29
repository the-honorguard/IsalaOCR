from __future__ import annotations

import os
import time
from pathlib import Path
from unittest import mock

from isala_ocr.training import input_selection


def _reset_cache():
    input_selection._source_id_cache.clear()


def test_unchanged_file_is_hashed_only_once(tmp_path: Path) -> None:
    """input_selection_state() (webui.py) calls this once per /input file on
    every single page render, so re-hashing every file's full content each
    time made every page in the app slow, not just Mapping Studio's queue.
    An unchanged file (same mtime + size) must reuse the cached digest."""
    _reset_cache()
    path = tmp_path / "scan.dcm"
    path.write_bytes(b"unchanged content")

    first = input_selection.input_file_source_id(path)
    with mock.patch.object(Path, "open", side_effect=AssertionError("must not re-read an unchanged file")):
        second = input_selection.input_file_source_id(path)

    assert first == second
    assert len(first) == 24


def test_modified_file_is_rehashed(tmp_path: Path) -> None:
    """A real content change must never be masked by the cache."""
    _reset_cache()
    path = tmp_path / "scan.dcm"
    path.write_bytes(b"first version")
    first = input_selection.input_file_source_id(path)

    # Force a distinct mtime regardless of filesystem timestamp resolution.
    path.write_bytes(b"second, different version")
    later = time.time() + 5
    os.utime(path, (later, later))

    second = input_selection.input_file_source_id(path)
    assert first != second


def test_cache_is_keyed_per_file_not_shared_across_paths(tmp_path: Path) -> None:
    _reset_cache()
    path_a = tmp_path / "a.dcm"
    path_b = tmp_path / "b.dcm"
    path_a.write_bytes(b"content a")
    path_b.write_bytes(b"content b")

    assert input_selection.input_file_source_id(path_a) != input_selection.input_file_source_id(path_b)


def test_warm_cache_hashes_every_file_once_upfront(tmp_path: Path) -> None:
    """warm_input_file_source_id_cache() lets create_web_app() pre-hash every
    /input file in a background thread right after startup, so the first
    real page render doesn't pay for it. After warming, looking up any of
    those files' ids must not touch the filesystem again."""
    _reset_cache()
    for name in ("a.dcm", "b.dcm", "c.dcm"):
        (tmp_path / name).write_bytes(name.encode())

    input_selection.warm_input_file_source_id_cache(tmp_path)

    with mock.patch.object(Path, "open", side_effect=AssertionError("must not re-read an already-warmed file")):
        ids = {path.name: input_selection.input_file_source_id(path) for path in tmp_path.iterdir()}
    assert len(set(ids.values())) == 3


def test_warm_cache_skips_unreadable_files(tmp_path: Path) -> None:
    """A file that disappears or errors mid-scan must not abort the whole
    warm-up; the rest of /input should still get cached."""
    _reset_cache()
    good = tmp_path / "good.dcm"
    good.write_bytes(b"content")
    missing = tmp_path / "missing.dcm"

    real_source_id = input_selection.input_file_source_id

    def flaky(path: Path):
        if path == missing:
            raise OSError("vanished mid-scan")
        return real_source_id(path)

    with mock.patch.object(input_selection, "input_files", return_value=[missing, good]), \
            mock.patch.object(input_selection, "input_file_source_id", side_effect=flaky):
        input_selection.warm_input_file_source_id_cache(tmp_path)

    assert input_selection.input_file_source_id(good) == real_source_id(good)
