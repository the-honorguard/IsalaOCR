"""Home/dashboard route, split out of webui.create_web_app.

``process_snapshot`` and ``pipeline_state`` stay in webui.py because
``process_snapshot`` is also used by other route groups there
(``/process/<step_key>`` and the workflow-navigation gate), and
``job_statuses`` is shared with the still-inline job routes; all three
are passed in explicitly instead of re-implemented.
"""

from __future__ import annotations

from typing import Any, Callable

from flask import Flask, render_template


def register_home_routes(
    app: Flask,
    *,
    process_snapshot: Callable[[], dict[str, Any]],
    pipeline_state: Callable[[dict[str, Any] | None], list[dict[str, Any]]],
    job_statuses: Callable[..., list[dict[str, Any]]],
) -> None:
    @app.get("/")
    def home():
        # Build the expensive workflow snapshot once. Older code rebuilt it in
        # pipeline_state() and repeated several database/filesystem lookups again.
        snapshot = process_snapshot()
        return render_template(
            "home.html",
            stages=pipeline_state(snapshot),
            jobs=job_statuses(8),
            value=snapshot["value"],
            roi_counts=snapshot["roi"],
            generic=snapshot,
        )
