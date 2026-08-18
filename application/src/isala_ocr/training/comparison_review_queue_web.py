from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from .comparison_review_queue import PersistentComparisonReviewQueue
from .projects import ProjectManager
from .table_model_comparison import review_comparison_issue


def install_comparison_review_queue(app: Flask, workspace_root: str | Path) -> PersistentComparisonReviewQueue:
    """Attach the durable Step-6 review writer to an existing Flask app."""

    base_root = Path(workspace_root).resolve()
    projects_root = (base_root / "projects").resolve()
    project_manager = ProjectManager(base_root)

    def apply_review(item: dict[str, Any]) -> None:
        target_workspace = Path(str(item.get("workspace") or "")).resolve()
        try:
            target_workspace.relative_to(projects_root)
        except ValueError as exc:
            raise ValueError("Reviewwachtrij verwijst buiten de projectworkspace") from exc
        review_comparison_issue(
            target_workspace,
            str(item.get("run_id") or ""),
            str(item.get("issue_id") or ""),
            str(item.get("decision") or ""),
        )

    queue = PersistentComparisonReviewQueue(
        base_root / "webui" / "comparison_review_queue.json",
        apply_review,
    )
    queue.ensure_worker()
    app.extensions["isala_comparison_review_queue"] = queue

    def active_project_id() -> str:
        return str(project_manager.active().project_id)

    @app.post("/api/comparison-review-queue")
    def comparison_review_queue_enqueue():
        action = str(request.form.get("comparison_action") or "review_issue").strip().lower()
        if action != "review_issue":
            return jsonify({"ok": False, "error": "Alleen reviewbeslissingen horen in deze wachtrij"}), 400
        run_id = str(request.form.get("run_id") or "").strip()[:180]
        issue_id = str(request.form.get("issue_id") or "").strip()[:120]
        decision = str(request.form.get("decision") or "").strip().lower()
        context = project_manager.active()
        try:
            status = queue.enqueue(
                project_id=context.project_id,
                workspace=context.workspace,
                run_id=run_id,
                issue_id=issue_id,
                decision=decision,
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        effective_decision = "" if decision == "clear" else decision
        labels = {
            "model_error": "Modelmisser staat in de backendwachtrij",
            "functional_ok": "Functioneel-correct oordeel staat in de backendwachtrij",
            "gt_check": "GT-controle staat in de backendwachtrij",
            "deferred": "Uitstel staat in de backendwachtrij",
            "clear": "Wissen van het oordeel staat in de backendwachtrij",
        }
        return jsonify(
            {
                "ok": True,
                "queued": True,
                "message": labels.get(decision, "Review staat in de backendwachtrij"),
                "decision": effective_decision,
                "queue": status,
            }
        ), 202

    @app.get("/api/comparison-review-queue")
    def comparison_review_queue_status():
        return jsonify({"ok": True, **queue.status(project_id=active_project_id())})

    @app.post("/api/comparison-review-queue/retry")
    def comparison_review_queue_retry():
        return jsonify({"ok": True, **queue.retry_failed(project_id=active_project_id())})

    return queue
