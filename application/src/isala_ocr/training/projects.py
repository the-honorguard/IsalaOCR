from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .db import TrainingDatabase
from .json_store import read_json, write_json_atomic

PROJECT_CATALOG_VERSION = 1
DEFAULT_PROJECT_ID = "cmr_testcase_01"
DEFAULT_PROJECT_NAME = "CMR testcase 01"
DEFAULT_USE_CASE_ID = "philips_cmr_volume_results"

# Files/directories that belonged to the single legacy workspace and therefore
# need to move into the first project on a 3.7.x -> 3.8.x upgrade. The global
# web worker queue intentionally stays outside projects.
LEGACY_PROJECT_ITEMS = (
    "samples.sqlite3",
    "samples.sqlite3-wal",
    "samples.sqlite3-shm",
    "source_renders",
    "detection_candidate_crops",
    "collection_diagnostics",
    "collection_manifest.json",
    "generic_detection",
    "generic_detections",
    "detected_blocks",
    "locator_overlays",
    "header_crops",
    "mapping",
    "mapped_crops",
    "extracted_output",
    "mapping_materialization_manifest.json",
    "mapped_value_recognition_manifest.json",
    "header_normalization",
    "localization_datasets",
    "localization_detections",
    "localization_manifest.json",
    "localization_runs",
    "localization_predictions",
    "localization_evaluations",
    "localization_models",
    "datasets",
    "runs",
    "diagnostics",
    "crops",
    "exports",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify_project_id(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    if not text:
        raise ValueError("Projectnaam levert geen geldige project-ID op")
    return text[:64]


def load_use_case_templates(config_root: str | Path) -> list[dict[str, Any]]:
    """Discover use-case templates without hard-coding them into the UI.

    A template only describes project defaults/intent. Project data and trained
    models remain isolated below the project workspace. Invalid files are
    skipped so one experimental template cannot prevent the UI from starting.
    """
    root = Path(config_root) / "use_cases"
    result: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*.yaml")):
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(payload, dict):
                continue
            use_case_id = str(payload.get("use_case_id") or "").strip()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", use_case_id):
                continue
            result.append({
                **payload,
                "use_case_id": use_case_id,
                "name": str(payload.get("name") or use_case_id),
                "description": str(payload.get("description") or ""),
                "template_path": str(path),
            })
    if not any(item["use_case_id"] == DEFAULT_USE_CASE_ID for item in result):
        result.insert(0, {
            "schema_version": 1,
            "use_case_id": DEFAULT_USE_CASE_ID,
            "name": "Philips CMR Volume Results",
            "description": "Ingebouwde compatibiliteits-template voor de huidige testcase.",
            "template_path": "",
        })
    return sorted(result, key=lambda item: (item["use_case_id"] != DEFAULT_USE_CASE_ID, item["name"].lower()))


@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    name: str
    use_case_id: str
    workspace: Path
    input_path: str = "/input"
    archived: bool = False


class ProjectManager:
    """Manage isolated IsalaOCR project workspaces.

    The platform remains generic while every project's review data, datasets,
    mappings, gates and model metadata live below ``workspace/projects/<id>``.
    ``ISALA_PROJECT_ID`` pins background jobs to the project they were queued
    from; otherwise the globally selected active project is used.
    """

    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.projects_root = self.root / "projects"
        self.catalog_path = self.root / "projects.json"
        self.active_path = self.root / "active_project.json"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        # These two tiny JSON files are consulted by nearly every web request.
        # Cache their parsed content and invalidate by stat signature so database
        # calls do not repeatedly re-read and re-parse the same project metadata.
        self._catalog_cache: dict[str, Any] | None = None
        self._catalog_signature: tuple[int, int] | None = None
        self._active_id_cache: str | None = None
        self._active_signature: tuple[int, int] | None = None
        self._initialize()

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def _read_json(self, path: Path, default: Any) -> Any:
        return read_json(path, default)

    def _write_json_atomic(self, path: Path, payload: Any) -> None:
        write_json_atomic(path, payload)
        if path == self.catalog_path:
            self._catalog_cache = None
            self._catalog_signature = None
        elif path == self.active_path:
            self._active_id_cache = None
            self._active_signature = None

    def _catalog(self) -> dict[str, Any]:
        signature = self._file_signature(self.catalog_path)
        if self._catalog_cache is not None and signature == self._catalog_signature:
            return {
                "schema_version": int(self._catalog_cache["schema_version"]),
                "projects": [dict(item) for item in self._catalog_cache["projects"]],
            }
        payload = self._read_json(self.catalog_path, {})
        if not isinstance(payload, dict):
            payload = {}
        projects = payload.get("projects")
        if not isinstance(projects, list):
            projects = []
        normalized = {
            "schema_version": int(payload.get("schema_version") or PROJECT_CATALOG_VERSION),
            "projects": [dict(item) for item in projects if isinstance(item, dict)],
        }
        self._catalog_cache = normalized
        self._catalog_signature = signature
        return {
            "schema_version": normalized["schema_version"],
            "projects": [dict(item) for item in normalized["projects"]],
        }

    def _save_catalog(self, projects: list[dict[str, Any]]) -> None:
        payload = {
            "schema_version": PROJECT_CATALOG_VERSION,
            "updated_at": utc_now(),
            "projects": projects,
        }
        self._write_json_atomic(self.catalog_path, payload)
        self._catalog_cache = {
            "schema_version": PROJECT_CATALOG_VERSION,
            "projects": [dict(item) for item in projects],
        }
        self._catalog_signature = self._file_signature(self.catalog_path)

    def _initialize(self) -> None:
        catalog = self._catalog()
        if not catalog["projects"]:
            project_id = DEFAULT_PROJECT_ID
            project_dir = self.projects_root / project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            migrated = self._migrate_legacy_workspace(project_dir)
            now = utc_now()
            project = {
                "project_id": project_id,
                "name": DEFAULT_PROJECT_NAME,
                "use_case_id": DEFAULT_USE_CASE_ID,
                "description": "Automatisch aangemaakt bij projectmigratie." if migrated else "Eerste IsalaOCR-project.",
                "input_path": "/input",
                "created_at": now,
                "updated_at": now,
                "archived": False,
                "migrated_from_legacy_workspace": bool(migrated),
            }
            self._write_project_file(project_dir, project)
            self._save_catalog([project])
            self._write_json_atomic(self.active_path, {"project_id": project_id, "updated_at": now})
            self._active_id_cache = project_id
            self._active_signature = self._file_signature(self.active_path)
        else:
            # Ensure every catalog entry has a directory and project.json.
            changed = False
            for item in catalog["projects"]:
                project_id = slugify_project_id(str(item.get("project_id") or item.get("name") or "project"))
                if item.get("project_id") != project_id:
                    item["project_id"] = project_id
                    changed = True
                project_dir = self.projects_root / project_id
                project_dir.mkdir(parents=True, exist_ok=True)
                if not (project_dir / "project.json").is_file():
                    self._write_project_file(project_dir, item)
            if changed:
                self._save_catalog(catalog["projects"])
            if self.get_project(self._active_id_from_file(), include_archived=True) is None:
                first = next((item for item in catalog["projects"] if not bool(item.get("archived"))), catalog["projects"][0])
                self.switch(str(first["project_id"]))

    def _migrate_legacy_workspace(self, project_dir: Path) -> bool:
        migrated = False
        for name in LEGACY_PROJECT_ITEMS:
            source = self.root / name
            destination = project_dir / name
            if not source.exists() or destination.exists():
                continue
            try:
                source.replace(destination)
            except OSError:
                if source.is_dir():
                    shutil.copytree(source, destination)
                    shutil.rmtree(source)
                else:
                    shutil.copy2(source, destination)
                    source.unlink()
            migrated = True
        return migrated

    def _write_project_file(self, project_dir: Path, payload: dict[str, Any]) -> None:
        clean = {
            "project_id": str(payload["project_id"]),
            "name": str(payload.get("name") or payload["project_id"]),
            "use_case_id": str(payload.get("use_case_id") or DEFAULT_USE_CASE_ID),
            "description": str(payload.get("description") or ""),
            "input_path": str(payload.get("input_path") or "/input"),
            "created_at": str(payload.get("created_at") or utc_now()),
            "updated_at": str(payload.get("updated_at") or utc_now()),
            "archived": bool(payload.get("archived", False)),
        }
        self._write_json_atomic(project_dir / "project.json", clean)

    def list_projects(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        projects = self._catalog()["projects"]
        if not include_archived:
            projects = [item for item in projects if not bool(item.get("archived"))]
        active = self.active_project_id()
        result: list[dict[str, Any]] = []
        for item in projects:
            row = dict(item)
            row["active"] = str(row.get("project_id")) == active
            row["workspace"] = str(self.projects_root / str(row.get("project_id")))
            result.append(row)
        return sorted(result, key=lambda item: (not item["active"], str(item.get("name") or "").lower()))

    def get_project(self, project_id: str | None, *, include_archived: bool = False) -> dict[str, Any] | None:
        project_id = str(project_id or "")
        for item in self._catalog()["projects"]:
            if str(item.get("project_id")) == project_id:
                if bool(item.get("archived")) and not include_archived:
                    return None
                return dict(item)
        return None

    def _active_id_from_file(self) -> str:
        signature = self._file_signature(self.active_path)
        if self._active_id_cache is not None and signature == self._active_signature:
            return self._active_id_cache
        payload = self._read_json(self.active_path, {})
        active = str(payload.get("project_id") or "") if isinstance(payload, dict) else ""
        self._active_id_cache = active
        self._active_signature = signature
        return active

    def active_project_id(self) -> str:
        projects = self._catalog()["projects"]
        forced = str(os.environ.get("ISALA_PROJECT_ID") or "").strip()
        if forced and any(str(item.get("project_id")) == forced for item in projects):
            return forced
        active = self._active_id_from_file()
        if active and any(str(item.get("project_id")) == active for item in projects):
            return active
        projects = [item for item in projects if not bool(item.get("archived"))]
        if not projects:
            raise RuntimeError("Geen actief IsalaOCR-project beschikbaar")
        return str(projects[0]["project_id"])

    def active(self) -> ProjectContext:
        project_id = self.active_project_id()
        item = self.get_project(project_id, include_archived=True)
        if item is None:
            raise RuntimeError(f"Project niet gevonden: {project_id}")
        workspace = self.projects_root / project_id
        workspace.mkdir(parents=True, exist_ok=True)
        return ProjectContext(
            project_id=project_id,
            name=str(item.get("name") or project_id),
            use_case_id=str(item.get("use_case_id") or DEFAULT_USE_CASE_ID),
            workspace=workspace,
            input_path=str(item.get("input_path") or "/input"),
            archived=bool(item.get("archived")),
        )

    def active_workspace(self) -> Path:
        return self.active().workspace

    def switch(self, project_id: str) -> ProjectContext:
        item = self.get_project(project_id)
        if item is None:
            raise KeyError(project_id)
        self._write_json_atomic(self.active_path, {"project_id": project_id, "updated_at": utc_now()})
        self._active_id_cache = project_id
        self._active_signature = self._file_signature(self.active_path)
        return self.active()

    def create(
        self,
        *,
        name: str,
        use_case_id: str = DEFAULT_USE_CASE_ID,
        project_id: str | None = None,
        description: str = "",
        input_path: str | None = None,
        duplicate_from: str | None = None,
    ) -> ProjectContext:
        name = str(name or "").strip()
        if not name:
            raise ValueError("Projectnaam is verplicht")
        project_id = slugify_project_id(project_id or name)
        if self.get_project(project_id, include_archived=True) is not None:
            raise ValueError(f"Project-ID bestaat al: {project_id}")
        project_dir = self.projects_root / project_id
        if project_dir.exists() and any(project_dir.iterdir()):
            raise ValueError(f"Projectmap bestaat al en is niet leeg: {project_id}")
        source = None
        if duplicate_from:
            source = self.get_project(duplicate_from)
            if source is None:
                raise KeyError(duplicate_from)
            source_use_case = str(source.get("use_case_id") or DEFAULT_USE_CASE_ID)
            requested_use_case = str(use_case_id or source_use_case)
            if requested_use_case != source_use_case:
                raise ValueError(
                    "Een projectduplicaat moet dezelfde use-case houden; maak voor een andere use-case een leeg project."
                )
            use_case_id = source_use_case
            if input_path is None:
                input_path = str(source.get("input_path") or "/input")
        if input_path is None:
            input_path = f"/input/projects/{project_id}"
        input_path = str(input_path).strip().replace("\\", "/") or f"/input/projects/{project_id}"
        if input_path != "/input" and not input_path.startswith("/input/"):
            raise ValueError("Project-inputpad moet /input of een submap daarvan zijn")
        if ".." in Path(input_path).parts:
            raise ValueError("Project-inputpad mag geen '..' bevatten")
        project_dir.mkdir(parents=True, exist_ok=True)
        if duplicate_from:
            assert source is not None
            source_dir = self.projects_root / duplicate_from
            # Duplicate the complete isolated workspace, but never inherit stale
            # sqlite WAL/SHM files. This is intentionally a snapshot/experiment.
            for item in source_dir.iterdir():
                if item.name == "project.json" or item.name.endswith(("-wal", "-shm")):
                    continue
                target = project_dir / item.name
                if item.name == "samples.sqlite3" and item.is_file():
                    # SQLite commonly runs in WAL mode. Use the backup API so a
                    # duplicated project is a consistent snapshot even while the
                    # source web UI is active.
                    source_db = sqlite3.connect(item)
                    target_db = sqlite3.connect(target)
                    try:
                        source_db.backup(target_db)
                    finally:
                        target_db.close()
                        source_db.close()
                elif item.is_dir():
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
        now = utc_now()
        project = {
            "project_id": project_id,
            "name": name,
            "use_case_id": str(use_case_id or DEFAULT_USE_CASE_ID),
            "description": str(description or ""),
            "input_path": input_path,
            "created_at": now,
            "updated_at": now,
            "archived": False,
            "duplicated_from": str(duplicate_from or ""),
        }
        self._write_project_file(project_dir, project)
        catalog = self._catalog()["projects"]
        catalog.append(project)
        self._rewrite_duplicated_project_paths(project_dir, duplicate_from, project_id)
        self._save_catalog(catalog)
        self.switch(project_id)
        return self.active()

    def _rewrite_duplicated_project_paths(self, project_dir: Path, source_id: str | None, target_id: str) -> None:
        if not source_id:
            return
        old = f"/training/workspace/projects/{source_id}"
        new = f"/training/workspace/projects/{target_id}"
        database = project_dir / "samples.sqlite3"
        if database.is_file():
            # Goes through TrainingDatabase (and its LocalizationMixin) instead of a
            # bare sqlite3.connect() so the table/column knowledge lives in one place
            # and a future schema change here is felt immediately (see
            # documentation/architecture/refactor-phase2-plan.md, item 1).
            TrainingDatabase(database).rewrite_localization_paths(old, new)
        for file in project_dir.rglob("*"):
            if not file.is_file() or file.name == "samples.sqlite3" or file.suffix.lower() not in {".json", ".txt", ".yaml", ".yml"}:
                continue
            try:
                content = file.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            if old in content:
                file.write_text(content.replace(old, new), encoding="utf-8")

    def rename(self, project_id: str, name: str) -> None:
        name = str(name or "").strip()
        if not name:
            raise ValueError("Projectnaam is verplicht")
        catalog = self._catalog()["projects"]
        found = False
        for item in catalog:
            if str(item.get("project_id")) == project_id:
                item["name"] = name
                item["updated_at"] = utc_now()
                found = True
                self._write_project_file(self.projects_root / project_id, item)
                break
        if not found:
            raise KeyError(project_id)
        self._save_catalog(catalog)

    def archive(self, project_id: str, archived: bool = True) -> None:
        if project_id == self.active_project_id() and archived:
            raise ValueError("Het actieve project kan niet worden gearchiveerd; schakel eerst naar een ander project")
        catalog = self._catalog()["projects"]
        found = False
        for item in catalog:
            if str(item.get("project_id")) == project_id:
                item["archived"] = bool(archived)
                item["updated_at"] = utc_now()
                found = True
                self._write_project_file(self.projects_root / project_id, item)
                break
        if not found:
            raise KeyError(project_id)
        self._save_catalog(catalog)


def _is_platform_workspace_root(root: Path) -> bool:
    # The shipped runtime uses /training/workspace as the project catalog root.
    # Keep module-level APIs backwards compatible for callers/tests that pass an
    # arbitrary standalone workspace such as /tmp/my-run.
    return (
        (root.name == "workspace" and root.parent.name == "training")
        or (root / "projects.json").is_file()
        or (root / "active_project.json").is_file()
        or (root / "projects").is_dir()
    )


def resolve_project_workspace(workspace_root: str | Path) -> Path:
    root = Path(workspace_root).resolve()
    # If the caller already points at an isolated project directory, keep it.
    if root.parent.name == "projects" and (root / "project.json").is_file():
        return root
    if not _is_platform_workspace_root(root):
        return root
    return ProjectManager(root).active_workspace()


def resolve_project_id(workspace_root: str | Path) -> str:
    root = Path(workspace_root).resolve()
    if root.parent.name == "projects" and (root / "project.json").is_file():
        payload = json.loads((root / "project.json").read_text(encoding="utf-8-sig"))
        return str(payload.get("project_id") or root.name)
    if not _is_platform_workspace_root(root):
        return str(os.environ.get("ISALA_PROJECT_ID") or DEFAULT_PROJECT_ID)
    return ProjectManager(root).active_project_id()


def resolve_project_registry(registry_root: str | Path, workspace_root: str | Path) -> Path:
    base = Path(registry_root).resolve()
    project_id = resolve_project_id(workspace_root)
    # PowerShell actions may already pass /training/registry/projects/<id>.
    # Do not append another projects/<id> level in that case.
    if base.name == project_id and base.parent.name == "projects":
        target = base
    else:
        target = base / "projects" / project_id
    target.mkdir(parents=True, exist_ok=True)
    # First 3.8 activation/registration copies the legacy registry into the
    # migrated default project's namespace so existing recognition work survives.
    platform_base = base.parent.parent if base.name == project_id and base.parent.name == "projects" else base
    if project_id == DEFAULT_PROJECT_ID and not (target / "registry.json").exists():
        legacy_registry = platform_base / "registry.json"
        legacy_models = platform_base / "models"
        legacy_active = platform_base / "active.json"
        if legacy_registry.is_file():
            shutil.copy2(legacy_registry, target / "registry.json")
        if legacy_active.is_file():
            shutil.copy2(legacy_active, target / "active.json")
        if legacy_models.is_dir() and not (target / "models").exists():
            shutil.copytree(legacy_models, target / "models")
    return target


def project_active_recognition_dir(models_root: str | Path, workspace_root: str | Path) -> Path:
    base = Path(models_root).resolve()
    project_id = resolve_project_id(workspace_root)
    target = base / "projects" / project_id / "active-recognition"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the previously activated model for the migrated first project.
    legacy = base / "active-recognition"
    if project_id == DEFAULT_PROJECT_ID and legacy.is_dir() and not target.exists():
        shutil.copytree(legacy, target)
    return target
