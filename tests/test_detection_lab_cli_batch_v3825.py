from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.detection_lab_cli import _parse_source_ids  # noqa: E402


def test_parse_source_ids_splits_and_strips_a_comma_separated_batch():
    """"Alle afbeeldingen draaien" submits every source as one comma-separated
    --source-id value (see detection_lab_cli.py._run) instead of one job per
    source, so the model loads once and the batch keeps running server-side
    even if the browser tab that started it closes."""
    assert _parse_source_ids("aaa111, bbb222 ,ccc333") == ["aaa111", "bbb222", "ccc333"]


def test_parse_source_ids_accepts_a_single_id_unchanged():
    assert _parse_source_ids("aaa111") == ["aaa111"]


def test_parse_source_ids_ignores_empty_segments():
    assert _parse_source_ids("aaa111,,bbb222,") == ["aaa111", "bbb222"]


@pytest.mark.parametrize("raw", ["", "   ", ",,,"])
def test_parse_source_ids_rejects_nothing_usable(raw):
    with pytest.raises(ValueError):
        _parse_source_ids(raw)


def test_parse_source_ids_rejects_any_invalid_id_in_the_batch():
    with pytest.raises(ValueError):
        _parse_source_ids("aaa111,not valid!,ccc333")
