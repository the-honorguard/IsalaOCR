"""list_detected_relations_by_source() must return exactly what
list_detected_relations(source_id) returns for each source, since
routes_mapping_studio.py's queue-start scan now reads from the bulk result
instead of calling list_detected_relations() once per source while looking
for the next one with open mapping work.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.training.db import TrainingDatabase  # noqa: E402


def _seed_relation(db: TrainingDatabase, source_id: str, index: int) -> None:
    label_block_id = f"{source_id}-label-{index}"
    value_block_id = f"{source_id}-value-{index}"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO detected_blocks(block_id, source_id, block_type, role, text,"
            " x1, y1, x2, y2, confidence, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (label_block_id, source_id, "text", "label", f"label-{index}", 0, 0, 10, 10, 0.9, "now", "now"),
        )
        conn.execute(
            "INSERT INTO detected_blocks(block_id, source_id, block_type, role, text,"
            " x1, y1, x2, y2, confidence, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (value_block_id, source_id, "text", "value", f"value-{index}", 20, 20, 30, 30, 0.9, "now", "now"),
        )
        conn.execute(
            "INSERT INTO detected_relations(relation_id, source_id, relation_type,"
            " label_block_id, value_block_id, confidence, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (f"{source_id}-rel-{index}", source_id, "table_cell", label_block_id, value_block_id, 0.9, "now", "now"),
        )


def test_bulk_relations_match_per_source_query(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    for source_id, width, height in (("src-a", 400, 400), ("src-b", 400, 400)):
        db.replace_localization_detection(
            {
                "source_id": source_id, "image_width": width, "image_height": height,
                "render_path": f"source_renders/{source_id}.png", "detector_version": "t", "token_count": 0,
            },
            candidates=[], tables=[],
        )
    for source_id in ("src-a", "src-b"):
        for index in range(2):
            _seed_relation(db, source_id, index)

    by_source = db.list_detected_relations_by_source()

    for source_id in ("src-a", "src-b", "src-c-never-seeded"):
        individual = db.list_detected_relations(source_id)
        bulk = by_source.get(source_id, [])
        assert bulk == individual, f"bulk result for {source_id!r} diverged from the per-source query"

    assert {r["relation_id"] for r in by_source["src-a"]} == {"src-a-rel-0", "src-a-rel-1"}
    assert {r["relation_id"] for r in by_source["src-b"]} == {"src-b-rel-0", "src-b-rel-1"}
    assert "src-c-never-seeded" not in by_source
