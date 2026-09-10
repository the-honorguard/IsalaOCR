"""Project management routes: switching, creating, renaming, archiving.

Split out of ``webui.create_web_app`` to keep that factory function smaller.
Follows the same pattern as ``legacy_routes.register_legacy_routes``: the
handlers that only need a small, explicit set of dependencies move here and
receive those dependencies as parameters instead of closing over the whole
factory function's local scope. Anything still shared with other route
groups in ``webui.py`` (``render_management``, ``header_profile``, ...) is
passed in rather than re-implemented, so behaviour is unchanged.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from flask import Flask, flash, redirect, request, url_for

from .db import TrainingDatabase
from .mapping import ensure_default_field_definitions
from .projects import DEFAULT_USE_CASE_ID, ProjectManager


def register_project_routes(
    app: Flask,
    *,
    project_manager: ProjectManager,
    render_management: Callable[..., Any],
    header_profile: Any | None,
    use_case_ids: set[str],
    base_root: Path,
    models_root: Path,
) -> None:
    """Register ``/manage`` and ``/projects*`` routes.

    ``render_management`` and the ``project_summary`` it depends on stay in
    ``webui.py`` because a different route group (the process-step page)
    also calls ``render_management`` directly.
    """

    @app.get("/manage")
    def management_page():
        return render_management(active_tab=str(request.args.get("tab") or "projects"))

    @app.get("/projects")
    def projects_page():
        return render_management(active_tab="projects")

    def _safe_local_redirect(value: str | None, fallback: str) -> str:
        target = str(value or "").strip()
        if not target.startswith("/") or target.startswith("//"):
            return fallback
        return target

    @app.post("/projects/switch")
    def project_switch():
        project_id = str(request.form.get("project_id") or "").strip()
        try:
            context = project_manager.switch(project_id)
            if header_profile is not None and context.use_case_id == DEFAULT_USE_CASE_ID:
                ensure_default_field_definitions(TrainingDatabase(context.workspace / "samples.sqlite3"), header_profile)
            flash(f"Project actief: {context.name}", "success")
        except KeyError:
            flash("Project niet gevonden.", "error")
        return redirect(_safe_local_redirect(request.form.get("next"), url_for("home")))

    @app.post("/projects/create")
    def project_create():
        try:
            duplicate_from = str(request.form.get("duplicate_from") or "") or None
            requested_use_case = str(request.form.get("use_case_id") or DEFAULT_USE_CASE_ID)
            if requested_use_case not in use_case_ids:
                raise ValueError(f"Onbekende use-case template: {requested_use_case}")
            context = project_manager.create(
                name=str(request.form.get("name") or ""),
                project_id=str(request.form.get("project_id") or "") or None,
                use_case_id=requested_use_case,
                description=str(request.form.get("description") or ""),
                input_path=(str(request.form.get("input_path") or "").strip() or None),
                duplicate_from=duplicate_from,
            )
            if duplicate_from:
                registry_base = base_root.parent / "registry" / "projects"
                source_registry = registry_base / duplicate_from
                target_registry = registry_base / context.project_id
                if source_registry.is_dir() and not target_registry.exists():
                    shutil.copytree(source_registry, target_registry)
                    active_meta = target_registry / "active.json"
                    if active_meta.is_file():
                        try:
                            payload = json.loads(active_meta.read_text(encoding="utf-8-sig"))
                            if isinstance(payload, dict) and payload.get("path"):
                                payload["path"] = str(payload["path"]).replace(
                                    f"/models/projects/{duplicate_from}/",
                                    f"/models/projects/{context.project_id}/",
                                )
                                active_meta.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                        except (OSError, ValueError, TypeError):
                            pass
                source_active = models_root / "projects" / duplicate_from / "active-recognition"
                target_active = models_root / "projects" / context.project_id / "active-recognition"
                if source_active.is_dir() and not target_active.exists():
                    target_active.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(source_active, target_active)
            if header_profile is not None and context.use_case_id == DEFAULT_USE_CASE_ID:
                ensure_default_field_definitions(TrainingDatabase(context.workspace / "samples.sqlite3"), header_profile)
            flash(f"Project aangemaakt en geactiveerd: {context.name}", "success")
            return redirect(url_for("home"))
        except (KeyError, ValueError, OSError) as exc:
            flash(str(exc), "error")
            return redirect(url_for("management_page", tab="projects"))

    @app.post("/projects/<project_id>/rename")
    def project_rename(project_id: str):
        try:
            project_manager.rename(project_id, str(request.form.get("name") or ""))
            flash("Projectnaam bijgewerkt.", "success")
        except (KeyError, ValueError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("management_page", tab="projects"))

    @app.post("/projects/<project_id>/archive")
    def project_archive(project_id: str):
        try:
            project_manager.archive(project_id, archived=True)
            flash("Project gearchiveerd.", "success")
        except (KeyError, ValueError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("management_page", tab="projects"))

    @app.post("/projects/<project_id>/restore")
    def project_restore(project_id: str):
        try:
            project_manager.archive(project_id, archived=False)
            flash("Project hersteld uit archief.", "success")
        except (KeyError, ValueError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("management_page", tab="projects"))
