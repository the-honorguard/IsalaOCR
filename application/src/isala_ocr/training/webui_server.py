from __future__ import annotations

import argparse

from . import webui as webui_module
from .recognition_model_factory import install_recognition_model_factory_metadata


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", default="/training/workspace")
    p.add_argument("--models", default="/models")
    p.add_argument("--output", default="/output")
    p.add_argument("--project", default="/project")
    p.add_argument("--config", default="/app/config/app.yaml")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8088)
    a = p.parse_args()
    from waitress import serve

    # Recognition is a model-training concern. Repair the legacy workflow
    # metadata before Flask captures ACTIONS/PROCESS_STEPS into its routes.
    install_recognition_model_factory_metadata(webui_module)
    # create_web_app() wires up every route itself, including recognition-GT
    # review, the comparison review queue, job cancellation and stale-job
    # reconciliation - any caller that builds the app (this server, a test, a
    # future embedding) gets the same fully-wired app without having to know
    # about those extra installers.
    app = webui_module.create_web_app(
        a.workspace,
        models_root=a.models,
        output_root=a.output,
        project_root=a.project,
        config_path=a.config,
    )
    serve(app, host=a.host, port=a.port, threads=8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
