"""Bounded legacy ``pkg_resources`` compatibility for PaddleDetection.

PaddleDetection still imports ``pkg_resources`` in its model-zoo loader, while
new setuptools installations can omit that deprecated module.  IsalaOCR adds
this runtime directory only to the localization/PaddleDetection subprocess
PYTHONPATH, so this compatibility surface does not affect the normal app or OCR
recognition environments.
"""
from __future__ import annotations

import builtins
import importlib.metadata
import importlib.util
import os
from pathlib import Path
from typing import Any, Iterator

try:
    from packaging.requirements import Requirement as _PackagingRequirement
    from packaging.version import parse as parse_version
except Exception:  # pragma: no cover
    _PackagingRequirement = None
    parse_version = lambda value: str(value)

__isala_compat__ = True


# PaddleX launches PaddleDetection with the root-owned PaddleDetection source
# checkout as its working directory. During inline COCO evaluation PaddleDetection
# writes relative artifacts such as ``bbox.json``. Redirect only those known
# artifact names to the writable localization run directory selected by IsalaOCR.
_EVAL_TARGET_DIR = os.environ.get("ISALA_PADDLEDET_EVAL_ARTIFACT_DIR", "").strip()
_EVAL_ARTIFACT_NAMES = frozenset({"bbox.json", "mask.json", "segm.json", "keypoint.json"})
_REAL_OPEN = builtins.open


def _redirect_eval_artifact(file: Any) -> Any:
    if not _EVAL_TARGET_DIR or isinstance(file, int):
        return file
    try:
        raw = os.fspath(file)
    except TypeError:
        return file
    raw_text = os.fsdecode(raw) if isinstance(raw, bytes) else str(raw)
    candidate = Path(raw_text)
    if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name not in _EVAL_ARTIFACT_NAMES:
        return file
    target_dir = Path(_EVAL_TARGET_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / candidate.name
    return os.fsencode(target) if isinstance(raw, bytes) else str(target)


def _isala_open(file: Any, *args: Any, **kwargs: Any):
    return _REAL_OPEN(_redirect_eval_artifact(file), *args, **kwargs)


if _EVAL_TARGET_DIR:
    builtins.open = _isala_open


class DistributionNotFound(LookupError):
    pass


class VersionConflict(RuntimeError):
    pass


class Requirement:
    @staticmethod
    def parse(value: str):
        if _PackagingRequirement is None:
            return str(value)
        return _PackagingRequirement(str(value))


class Distribution:
    def __init__(self, name: str):
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise DistributionNotFound(name) from exc
        self._distribution = distribution
        self.project_name = str(distribution.metadata.get("Name") or name)
        self.version = str(distribution.version)
        self.location = str(Path(distribution.locate_file(".")).resolve())
        self.key = self.project_name.lower().replace("_", "-")

    def __str__(self) -> str:
        return f"{self.project_name} {self.version}"


def get_distribution(dist: str) -> Distribution:
    return Distribution(str(dist))


def _package_root(package_or_requirement) -> Path:
    package_name = str(package_or_requirement).strip()
    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
        if separator in package_name:
            package_name = package_name.split(separator, 1)[0].strip()
            break
    try:
        spec = importlib.util.find_spec(package_name)
    except (ImportError, AttributeError, ValueError) as exc:
        raise ModuleNotFoundError(f"Package resource root not found: {package_name}") from exc
    if spec is None:
        raise ModuleNotFoundError(f"Package resource root not found: {package_name}")
    if spec.submodule_search_locations:
        locations = list(spec.submodule_search_locations)
        if not locations:
            raise FileNotFoundError(f"Package has no filesystem location: {package_name}")
        return Path(locations[0])
    if spec.origin:
        return Path(spec.origin).parent
    raise FileNotFoundError(f"Package has no filesystem location: {package_name}")


def resource_filename(package_or_requirement, resource_name: str) -> str:
    return str((_package_root(package_or_requirement) / resource_name).resolve())


def resource_exists(package_or_requirement, resource_name: str) -> bool:
    return (_package_root(package_or_requirement) / resource_name).exists()


def resource_string(package_or_requirement, resource_name: str) -> bytes:
    return (_package_root(package_or_requirement) / resource_name).read_bytes()


def resource_stream(package_or_requirement, resource_name: str):
    return (_package_root(package_or_requirement) / resource_name).open("rb")


def resource_listdir(package_or_requirement, resource_name: str) -> list[str]:
    root = _package_root(package_or_requirement) / resource_name
    return [path.name for path in root.iterdir()]


def iter_entry_points(group: str, name: str | None = None) -> Iterator[importlib.metadata.EntryPoint]:
    entries = importlib.metadata.entry_points()
    selected = entries.select(group=group) if hasattr(entries, "select") else entries.get(group, ())
    for entry in selected:
        if name is None or entry.name == name:
            yield entry


def require(requirements):
    if isinstance(requirements, str):
        requirements = [requirements]
    result = []
    for requirement in requirements:
        parsed = Requirement.parse(str(requirement))
        name = getattr(parsed, "name", str(requirement).split("=", 1)[0])
        result.append(get_distribution(name))
    return result


def declare_namespace(_name: str) -> None:
    return None
