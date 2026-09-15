"""Optional, non-destructive Recognition format profiling."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


PROFILE_FILENAME = "recognition_format_profile.json"


def _family(value: str) -> str:
    text = str(value or "")
    stripped = text.strip()
    if not stripped:
        return "empty"
    if stripped in {"-", "–", "—"}:
        return "dash"
    if re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", stripped):
        return "date"
    if re.search(r"\d\s*\.\.\.\s*\d", stripped):
        return "range"
    if "%" in stripped:
        return "percentage"
    if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?(?:\s+.*)?", stripped):
        return "number_unit" if re.search(r"\s+[A-Za-zµ/%²]+", stripped) else "number"
    return "text"


def _signature(value: str) -> str:
    """Preserve formatting markers while abstracting numeric/letter content."""
    text = str(value or "")
    text = re.sub(r"\d+", "#", text)
    text = re.sub(r"[A-Z]", "A", text)
    text = re.sub(r"[a-z]", "a", text)
    return text


def build_profile(labels: Iterable[str]) -> dict[str, Any]:
    signatures = Counter()
    families = Counter()
    family_signatures: dict[str, Counter] = {}
    total = 0
    for label in labels:
        text = str(label or "")
        if not text:
            continue
        signatures[_signature(text)] += 1
        family = _family(text)
        families[family] += 1
        family_signatures.setdefault(family, Counter())[_signature(text)] += 1
        total += 1
    canonical_signatures = {
        family: counts.most_common(1)[0][0]
        for family, counts in family_signatures.items()
        if counts
    }
    return {
        "version": 1,
        "label_count": total,
        "signatures": dict(signatures),
        "families": dict(families),
        "canonical_signatures": canonical_signatures,
        "family_signatures": {family: dict(counts) for family, counts in family_signatures.items()},
    }


def profile_path(project_root: str | Path) -> Path:
    return Path(project_root) / PROFILE_FILENAME


def load_profile(project_root: str | Path) -> dict[str, Any]:
    path = profile_path(project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_profile(project_root: str | Path, profile: dict[str, Any]) -> None:
    destination = profile_path(project_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(profile, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def score_format(value: str, confidence: float, profile: dict[str, Any]) -> tuple[int, str]:
    """Return a review-priority score; this never changes the OCR label."""
    if not profile or int(profile.get("label_count") or 0) < 3:
        return 0, "Nog te weinig format-GT"
    signatures = profile.get("signatures") if isinstance(profile.get("signatures"), dict) else {}
    families = profile.get("families") if isinstance(profile.get("families"), dict) else {}
    canonical_signatures = profile.get("canonical_signatures") if isinstance(profile.get("canonical_signatures"), dict) else {}
    signature = _signature(value)
    family = _family(value)
    score = 0
    reasons: list[str] = []
    if signature not in signatures:
        score += 45
        reasons.append("nieuw format")
    else:
        if int(signatures.get(signature) or 0) == 1:
            score += 12
            reasons.append("zeldzaam format")
        canonical_signature = canonical_signatures.get(family)
        if canonical_signature and canonical_signature != signature:
            score += 15
            reasons.append("wijkt af van canoniek format")
    if family not in families:
        score += 35
        reasons.append("onbekend type")
    confidence_score = max(0, min(40, round((0.85 - max(0.0, min(1.0, float(confidence)))) * 100)))
    if confidence_score >= 10:
        score += confidence_score
        reasons.append("lage confidence")
    return min(100, score), ", ".join(reasons) if reasons else "past bij bekende formats"


def risk_label(score: int) -> str:
    if score >= 65:
        return "hoog"
    if score >= 30:
        return "middel"
    return "laag"
