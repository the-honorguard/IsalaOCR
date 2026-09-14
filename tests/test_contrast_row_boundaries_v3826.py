from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.models import Box  # noqa: E402
from isala_ocr.ocr.table_structure import _detect_soft_row_boundaries  # noqa: E402


def _synthetic_table_with_text_noise() -> np.ndarray:
    """A 4-row table with clearly alternating row shading (light/dark bands
    every 30px, matching what a person visually reads as distinct rows) plus
    "text" inside each row: small, localized dark patches (digit-strand-sized
    strips a few scanlines tall) scattered at different row offsets so they
    never line up into a second, consistent band boundary. This reproduces
    the Detectie-lab "Probeer 3" screenshot where a magenta separator line
    landed on nearly every glyph instead of only the three real row edges.
    """
    height, width = 120, 200
    gray = np.full((height, width), 220, dtype=np.uint8)
    for band_start in (30, 90):
        gray[band_start:band_start + 30, :] = 190
    rng = np.random.default_rng(7)
    for band_start in (0, 30, 60, 90):
        for _ in range(6):
            row_offset = int(rng.integers(4, 24))
            col_start = int(rng.integers(0, width - 16))
            gray[band_start + row_offset:band_start + row_offset + 3, col_start:col_start + 14] = 60
    return gray


def test_row_boundaries_ignore_text_noise_and_find_real_row_edges():
    gray = _synthetic_table_with_text_noise()
    boundaries = _detect_soft_row_boundaries(gray, Box(0, 0, 200, 120))

    # The real row-to-row shading changes at y=30, 60 and 90. Text noise used
    # to add a spurious extra boundary at nearly every glyph (many more than
    # 3); the sustained-step check should now reject all of those.
    assert len(boundaries) <= 5, boundaries
    true_edges = (30, 60, 90)
    assert any(abs(y - edge) <= 4 for edge in true_edges for y in boundaries)
    for y in boundaries:
        assert min(abs(y - edge) for edge in true_edges) <= 6, (
            f"boundary at {y} is not close to any real row edge {true_edges} - looks like text noise"
        )


def test_row_boundaries_still_find_a_genuinely_faint_step_across_many_rows():
    """The fix must not overcorrect into never firing: a real (if subtle,
    15-unit) alternating shading step across 8 rows, each with its own text
    noise, should still be found near every true edge."""
    height, width = 200, 300
    gray = np.full((height, width), 225, dtype=np.uint8)
    for start in range(0, height, 25):
        if (start // 25) % 2 == 1:
            gray[start:start + 25, :] = 210
    rng = np.random.default_rng(11)
    for start in range(0, height, 25):
        for _ in range(5):
            row_offset = int(rng.integers(2, 22))
            col_start = int(rng.integers(0, width - 20))
            gray[start + row_offset:start + row_offset + 3, col_start:col_start + 18] = 40

    boundaries = _detect_soft_row_boundaries(gray, Box(0, 0, width, height))
    true_edges = list(range(25, height, 25))
    for edge in true_edges:
        assert any(abs(y - edge) <= 5 for y in boundaries), (
            f"missed the real (if faint) row edge at {edge}: {boundaries}"
        )


def test_row_boundaries_stay_empty_on_a_flat_region_without_any_row_shading():
    gray = np.full((80, 150), 210, dtype=np.uint8)
    rng = np.random.default_rng(3)
    for _ in range(10):
        row = int(rng.integers(0, 76))
        col = int(rng.integers(0, 136))
        gray[row:row + 3, col:col + 12] = 70  # scattered "text", no row banding at all
    assert _detect_soft_row_boundaries(gray, Box(0, 0, 150, 80)) == []
