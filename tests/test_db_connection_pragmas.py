from __future__ import annotations

import sqlite3
from pathlib import Path

from isala_ocr.training.db import TrainingDatabase


def test_connect_retries_transient_unable_to_open_on_wal_pragma(
    tmp_path: Path, monkeypatch
) -> None:
    """A bind-mounted Docker Desktop volume has been observed to transiently
    fail "PRAGMA journal_mode=WAL" with "unable to open database file" right
    after a burst of unrelated writes to the same project directory, even
    though the main database file itself opens fine. connect() should retry
    rather than fail the caller's whole operation over a one-off hiccup.
    """
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    calls = {"count": 0}

    class FlakyConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):  # type: ignore[override]
            if sql == "PRAGMA journal_mode=WAL":
                calls["count"] += 1
                if calls["count"] == 1:
                    raise sqlite3.OperationalError("unable to open database file")
            return super().execute(sql, *args, **kwargs)

    real_connect = sqlite3.connect

    def flaky_connect(path, timeout=30, **kwargs):
        return real_connect(path, timeout=timeout, factory=FlakyConnection, **kwargs)

    monkeypatch.setattr("isala_ocr.training.db.sqlite3.connect", flaky_connect)
    monkeypatch.setattr("isala_ocr.training.db.time.sleep", lambda _seconds: None)

    with database.connect() as db:
        assert str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    assert calls["count"] == 2


def test_connection_uses_wal_with_normal_synchronous(tmp_path: Path) -> None:
    """WAL + synchronous=NORMAL is SQLite's own recommended pairing: still
    crash-safe against corruption, but a commit no longer fsyncs on every
    single write - on a bind-mounted Docker Desktop volume (this project's
    normal deployment), the default (FULL) turned every Mapping Studio queue
    confirm/skip's commit into a multi-second fsync round-trip through the
    virtualized filesystem.
    """
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    with database.connect() as db:
        assert str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
        assert int(db.execute("PRAGMA synchronous").fetchone()[0]) == 1
