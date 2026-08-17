from __future__ import annotations

import json
from pathlib import Path

import cv2

from .models import DocumentResult


def write_result(
    result: DocumentResult,
    output_root: str | Path,
    overlay=None,
    include_candidates: bool = True,
) -> Path:
    root = Path(output_root)
    target = root / result.source_id
    target.mkdir(parents=True, exist_ok=True)

    json_path = target / "result.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(
            result.as_dict(include_candidates=include_candidates),
            handle,
            ensure_ascii=False,
            indent=2,
        )

    text_path = target / "result.txt"
    with text_path.open("w", encoding="utf-8") as handle:
        handle.write(f"Source: {result.source_id}\nStatus: {result.status}\nProfile: {result.profile}\n\n")
        if result.study_info is not None:
            info = result.study_info
            handle.write("Study information:\n")
            handle.write(f"Heart rate: {info.heart_rate_bpm if info.heart_rate_bpm is not None else ''} bpm\n")
            handle.write(f"BSA: {info.bsa_m2 if info.bsa_m2 is not None else ''} m²\n")
            handle.write(f"BSA method: {info.bsa_method or ''}\n")
            handle.write(f"Height: {info.height_m if info.height_m is not None else ''} m\n")
            handle.write(f"Weight: {info.weight_kg if info.weight_kg is not None else ''} kg\n")
            handle.write(f"Gender: {info.gender or ''}\n")
            handle.write(f"Raw study-info OCR: {info.raw_text}\n\n")
        for field in result.fields:
            value = "" if field.value is None else str(field.value)
            state = "OK" if field.valid else f"INVALID ({field.reason})"
            handle.write(
                f"{field.label}: {value} {field.unit or ''} | confidence={field.confidence:.3f} | {state}\n"
            )
        if result.consistency:
            handle.write("\nConsistency checks:\n")
            for check in result.consistency:
                state = "OK" if check.passed is True else ("FAILED" if check.passed is False else "NOT EVALUATED")
                handle.write(
                    f"{check.name}: {state} | observed={check.observed} expected={check.expected} "
                    f"delta={check.absolute_delta} tolerance={check.tolerance}\n"
                )

    if overlay is not None:
        cv2.imwrite(str(target / "overlay.png"), overlay)
    return target
