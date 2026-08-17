from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Box


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    roi: Box
    unit: str | None
    minimum: float | None
    maximum: float | None
    decimals: int | None
    allow_missing: bool
    whitelist: str | None
    panel: str | None = None
    screen_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnchorSpec:
    name: str
    expected: str
    roi: Box
    minimum_similarity: float


@dataclass(frozen=True)
class ConsistencyRuleSpec:
    name: str
    kind: str
    target: str
    left: str
    right: str
    absolute_tolerance: float
    relative_tolerance: float


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    reference_width: int
    reference_height: int
    anchors: list[AnchorSpec]
    fields: list[FieldSpec]
    consistency_rules: list[ConsistencyRuleSpec]
    dynamic_extraction: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    raw: dict[str, Any]
    path: Path
    profile_path: Path
    profile: Profile

    @property
    def ocr(self) -> dict[str, Any]:
        return self.raw.get("ocr", {})

    @property
    def preprocessing(self) -> dict[str, Any]:
        return self.raw.get("preprocessing", {})

    @property
    def output(self) -> dict[str, Any]:
        return self.raw.get("output", {})

    @property
    def privacy(self) -> dict[str, Any]:
        return self.raw.get("privacy", {})

    @property
    def dicom(self) -> dict[str, Any]:
        return self.raw.get("dicom", {})


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Top-level YAML value must be an object: {path}")
    return data


def _box(value: Any, context: str) -> Box:
    if not isinstance(value, list) or len(value) != 4:
        raise ConfigError(f"{context} must contain [x1, y1, x2, y2]")
    try:
        coords = [int(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{context} contains non-integer coordinates") from exc
    box = Box(*coords)
    if box.width <= 0 or box.height <= 0:
        raise ConfigError(f"{context} has an empty or inverted rectangle")
    return box


def load_profile(path: Path) -> Profile:
    raw = _read_yaml(path)
    reference = raw.get("reference_size", {})
    try:
        width = int(reference["width"])
        height = int(reference["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("profile.reference_size requires positive width and height") from exc
    if width <= 0 or height <= 0:
        raise ConfigError("profile.reference_size values must be positive")

    anchors: list[AnchorSpec] = []
    for index, item in enumerate(raw.get("anchors", [])):
        anchors.append(
            AnchorSpec(
                name=str(item.get("name", f"anchor_{index}")),
                expected=str(item["expected"]),
                roi=_box(item["roi"], f"anchors[{index}].roi"),
                minimum_similarity=float(item.get("minimum_similarity", 0.65)),
            )
        )

    fields: list[FieldSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(raw.get("fields", [])):
        key = str(item["key"])
        if key in seen:
            raise ConfigError(f"Duplicate field key: {key}")
        seen.add(key)
        value_range = item.get("range", [None, None])
        if not isinstance(value_range, list) or len(value_range) != 2:
            raise ConfigError(f"fields[{index}].range must contain [minimum, maximum]")
        fields.append(
            FieldSpec(
                key=key,
                label=str(item.get("label", key)),
                roi=_box(item["roi"], f"fields[{index}].roi"),
                unit=item.get("unit"),
                minimum=float(value_range[0]) if value_range[0] is not None else None,
                maximum=float(value_range[1]) if value_range[1] is not None else None,
                decimals=int(item["decimals"]) if item.get("decimals") is not None else None,
                allow_missing=bool(item.get("allow_missing", False)),
                whitelist=item.get("whitelist"),
                panel=str(item["panel"]) if item.get("panel") is not None else None,
                screen_labels=tuple(
                    str(value) for value in item.get("screen_labels", [])
                ),
            )
        )
    if not fields:
        raise ConfigError("The selected profile contains no fields")

    rules: list[ConsistencyRuleSpec] = []
    valid_kinds = {"sum", "difference", "ratio_percent"}
    for index, item in enumerate(raw.get("consistency_rules", [])):
        kind = str(item.get("kind", ""))
        if kind not in valid_kinds:
            raise ConfigError(
                f"consistency_rules[{index}].kind must be one of {sorted(valid_kinds)}"
            )
        target = str(item["target"])
        left = str(item["left"])
        right = str(item["right"])
        for field_key in (target, left, right):
            if field_key not in seen:
                raise ConfigError(
                    f"consistency_rules[{index}] references unknown field: {field_key}"
                )
        rules.append(
            ConsistencyRuleSpec(
                name=str(item.get("name", f"rule_{index}")),
                kind=kind,
                target=target,
                left=left,
                right=right,
                absolute_tolerance=float(item.get("absolute_tolerance", 5.0)),
                relative_tolerance=float(item.get("relative_tolerance", 0.10)),
            )
        )

    return Profile(
        name=str(raw.get("name", path.stem)),
        description=str(raw.get("description", "")),
        reference_width=width,
        reference_height=height,
        anchors=anchors,
        fields=fields,
        consistency_rules=rules,
        dynamic_extraction=dict(raw.get("dynamic_extraction", {}) or {}),
    )


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    raw = _read_yaml(config_path)
    profile_value = raw.get("profile")
    if not profile_value:
        raise ConfigError("app config requires 'profile'")
    profile_path = Path(str(profile_value))
    if not profile_path.is_absolute():
        profile_path = (config_path.parent / profile_path).resolve()
    return AppConfig(raw=raw, path=config_path, profile_path=profile_path, profile=load_profile(profile_path))
