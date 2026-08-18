from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from isala_ocr.training.comparison_review_queue import PersistentComparisonReviewQueue


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pending_decisions_for_same_issue_are_coalesced(tmp_path: Path) -> None:
    queue = PersistentComparisonReviewQueue(tmp_path / "queue.json", lambda item: None)
    queue.ensure_worker = lambda: None  # type: ignore[method-assign]

    queue.enqueue(project_id="p", workspace=tmp_path / "projects" / "p", run_id="r", issue_id="i", decision="gt_check")
    queue.enqueue(project_id="p", workspace=tmp_path / "projects" / "p", run_id="r", issue_id="i", decision="model_error")

    payload = json.loads((tmp_path / "queue.json").read_text(encoding="utf-8"))
    assert len(payload["items"]) == 1
    assert payload["items"][0]["decision"] == "model_error"


def test_processing_item_is_recovered_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": [
                    {
                        "queue_id": "q1",
                        "project_id": "p",
                        "workspace": str(tmp_path / "projects" / "p"),
                        "run_id": "r",
                        "issue_id": "i",
                        "decision": "functional_ok",
                        "status": "processing",
                    }
                ],
                "completed_total": 0,
            }
        ),
        encoding="utf-8",
    )

    queue = PersistentComparisonReviewQueue(path, lambda item: None)
    queue.ensure_worker = lambda: None  # type: ignore[method-assign]
    status = queue.status(project_id="p")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert status["pending_count"] == 1
    assert payload["items"][0]["status"] == "pending"


def test_worker_applies_review_without_browser_waiting(tmp_path: Path) -> None:
    applied: list[dict] = []
    event = threading.Event()

    def handler(item: dict) -> None:
        applied.append(item)
        event.set()

    queue = PersistentComparisonReviewQueue(tmp_path / "queue.json", handler, poll_interval=0.02)
    queue.enqueue(project_id="p", workspace=tmp_path / "projects" / "p", run_id="r", issue_id="i", decision="model_error")

    assert event.wait(1.0)
    deadline = time.time() + 1.0
    while queue.status(project_id="p")["pending_count"] and time.time() < deadline:
        time.sleep(0.01)

    assert applied and applied[0]["decision"] == "model_error"
    assert queue.status(project_id="p")["pending_count"] == 0


def test_labeler_image_contains_review_queue_modules() -> None:
    dockerfile = (REPO_ROOT / "infrastructure" / "docker" / "Dockerfile.labeler").read_text(encoding="utf-8")
    assert "training/comparison_review_queue.py" in dockerfile
    assert "training/comparison_review_queue_web.py" in dockerfile


def test_web_queue_extension_reroutes_reviews_and_adds_gt_return_link() -> None:
    source = (REPO_ROOT / "application" / "src" / "isala_ocr" / "training" / "comparison_review_queue_web.py").read_text(encoding="utf-8")
    assert '@app.post("/api/comparison-review-queue")' in source
    assert '@app.get("/api/comparison-review-queue")' in source
    assert "target.pathname === '/process/table-compare'" in source
    assert "action === 'review_issue'" in source
    assert "return_to" in source
    assert "← Terug naar afwijking" in source
    assert "focus_issue" in source
