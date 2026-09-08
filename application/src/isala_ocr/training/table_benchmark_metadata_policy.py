from __future__ import annotations

from functools import wraps
from typing import Any


def normalize_table_benchmark_metadata(metadata: object) -> dict[str, Any]:
    """Normalize PP-Structure benchmark metadata for all detection backends.

    The generic preprocessing benchmark returns a ``runs`` list, while the
    trained table-region backend returns only its model/geometry summary.  The
    collector treats ``detect_with_benchmark`` as one contract, so callers must
    always receive an iterable ``runs`` value even when no preprocessing
    benchmark was executed.
    """
    result = dict(metadata) if isinstance(metadata, dict) else {}
    if not isinstance(result.get("runs"), list):
        result["runs"] = []

    # Keep the existing collector diagnostics meaningful for the learned path.
    if str(result.get("mode") or "").strip() == "trained_table_regions":
        result.setdefault("selected_variant", "trained_region_model")
        result.setdefault("selected_scope", "detected_regions")
    return result


def install_table_benchmark_metadata_policy() -> None:
    """Normalize ``detect_with_benchmark`` metadata before collectors consume it."""
    from ..ocr.table_structure import PPStructureTableEngine

    if getattr(PPStructureTableEngine, "_benchmark_metadata_policy_installed", False):
        return

    original_detect_with_benchmark = PPStructureTableEngine.detect_with_benchmark

    @wraps(original_detect_with_benchmark)
    def detect_with_benchmark(self, *args, **kwargs):
        regions, metadata = original_detect_with_benchmark(self, *args, **kwargs)
        return regions, normalize_table_benchmark_metadata(metadata)

    PPStructureTableEngine.detect_with_benchmark = detect_with_benchmark
    PPStructureTableEngine._benchmark_metadata_policy_installed = True
