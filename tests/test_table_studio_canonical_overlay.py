from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_table_studio_preview_embeds_and_uses_canonical_cells() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/table_studio.html").read_text(encoding="utf-8")
    script = (ROOT / "application/src/isala_ocr/training/static/table-studio-overlay.js").read_text(encoding="utf-8")

    assert 'data-cells="{{ table.cells|tojson|forceescape }}"' in template
    assert "const canonicalCells = JSON.parse(table.dataset.cells || '[]');" in script
    assert "canonicalCells.forEach((source) =>" in script
    assert "rows.forEach((row) => columns.forEach" not in script
