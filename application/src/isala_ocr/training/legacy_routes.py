"""Small compatibility routes kept separate from the training WebUI factory."""

from __future__ import annotations

from collections.abc import Callable

from flask import Flask, redirect, url_for


def register_legacy_routes(app: Flask, process_step: Callable[[str], object]) -> None:
    """Register legacy bookmarks without adding more route logic to ``webui``."""

    def training() -> object:
        return process_step("recognition-dataset")

    def activation_redirect() -> object:
        return process_step("recognition-models")

    def models_page() -> object:
        # Keep old bookmarks working, but route model management through the
        # canonical management UI.
        return redirect(url_for("management_page", tab="models"))

    app.add_url_rule("/training", endpoint="training", view_func=training, methods=["GET"])
    app.add_url_rule("/activation", endpoint="activation_redirect", view_func=activation_redirect, methods=["GET"])
    app.add_url_rule("/models", endpoint="models_page", view_func=models_page, methods=["GET"])
