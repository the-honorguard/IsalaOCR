from __future__ import annotations

from pathlib import Path

from isala_ocr.training.db import TrainingDatabase


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
