"""Small read-only status/health routes, split out of webui.create_web_app.

Same pattern as routes_projects.register_project_routes: the handlers move
here, but the helpers they call (``registry_state``, ``job_statuses``,
``worker_state``) stay in webui.py because many other route groups there
also depend on them, and are passed in explicitly instead.
"""

from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify


def register_status_routes(
    app: Flask,
    *,
    database: Any,
    registry_state: Callable[[], tuple[list[dict[str, Any]], dict[str, Any] | None]],
    job_statuses: Callable[..., list[dict[str, Any]]],
    worker_state: Callable[[], dict[str, Any]],
) -> None:
    @app.get("/api/status")
    def api_status():
        # The activity dock polls this endpoint frequently. It only needs queue,
        # worker and active-model state; building the full process snapshot here
        # caused repeated database and filesystem scans every 1.5 seconds.
        _, active = registry_state()
        return jsonify({"jobs": job_statuses(), "worker": worker_state(), "active_model": active})

    @app.get("/api/jobs")
    def api_jobs():
        """Backward-compatible queue snapshot for older local clients."""
        return jsonify({"jobs": job_statuses(), "worker": worker_state()})

    @app.get("/health")
    def health():
        return {"ok": True, "counts": database.counts(), "webui": True}
