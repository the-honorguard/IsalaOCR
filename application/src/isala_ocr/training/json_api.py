"""Small shared helpers for the training webapp's JSON API routes.

Before this module existed, ``{"ok": False, "error": "..."}, <status>`` and
``request.get_json(silent=True) or {}`` were each copied independently in
dozens of route handlers across ``training/routes_*.py`` (CODE_REVIEW_v3.16.0.md,
sectie Middel: "Geen gedeelde JSON-foutrespons-helper in de Flask-routes" --
24x in ``routes_detection_review.py``, 18x in ``routes_localization_v2.py``
at review time; see also
``documentation/architecture/refactor-phase2-plan.md``, item 7).

This deliberately centralizes only the two smallest, safest-to-share pieces
-- building an error response, and reading an optional JSON body -- not a
``@json_api`` decorator wrapping whole route handlers. Each handler's
early-return validation guards carry different messages, status codes and
occasional extra response fields, and are business logic to read in place,
not boilerplate to hide behind a decorator.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify


def json_error(message: str, status: int = 400, **extra: Any):
    """Build a ``jsonify({"ok": False, "error": message, **extra}), status`` response."""
    return jsonify({"ok": False, "error": str(message), **extra}), status


def json_body(request: Any) -> dict[str, Any]:
    """Return ``request``'s parsed JSON body, or ``{}`` if absent/invalid/not a dict.

    Every existing call site already only ever calls ``.get(...)`` on the
    result, i.e. already assumed a dict; a non-dict JSON body (e.g. a bare
    JSON array) would previously have passed through ``... or {}`` unchanged
    (only a *falsy* body like ``None``/``[]``/``""`` was replaced) and then
    crashed on ``.get(...)``. Coercing any non-dict to ``{}`` here closes
    that latent crash instead of reproducing it.
    """
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}
