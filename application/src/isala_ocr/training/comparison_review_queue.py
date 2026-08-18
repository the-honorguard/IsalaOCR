from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


QUEUE_SCHEMA_VERSION = 1
MAX_RETRY_ATTEMPTS = 8
MAX_BACKOFF_SECONDS = 30.0


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersistentComparisonReviewQueue:
    """Small durable FIFO for Step-6 review decisions.

    Browser pages only enqueue decisions. A background worker applies them one at
    a time, so rapid review clicks never create concurrent writes and navigation
    does not cancel pending decisions. The JSON queue lives outside the active
    project directory and therefore also survives page changes and labeler
    restarts.
    """

    def __init__(
        self,
        path: str | Path,
        handler: Callable[[dict[str, Any]], None],
        *,
        poll_interval: float = 0.25,
    ) -> None:
        self.path = Path(path)
        self.handler = handler
        self.poll_interval = max(0.05, float(poll_interval))
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        with self._lock:
            state = self._load_locked()
            changed = False
            for item in state["items"]:
                if str(item.get("status") or "pending") == "processing":
                    item["status"] = "pending"
                    item["next_attempt_at"] = 0.0
                    changed = True
            if changed:
                self._save_locked(state)

    def _default_state(self) -> dict[str, Any]:
        return {
            "schema_version": QUEUE_SCHEMA_VERSION,
            "items": [],
            "completed_total": 0,
            "last_completed_at": "",
        }

    def _load_locked(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            payload = self._default_state()
        if not isinstance(payload, dict):
            payload = self._default_state()
        items = payload.get("items")
        if not isinstance(items, list):
            items = []
        payload["schema_version"] = QUEUE_SCHEMA_VERSION
        payload["items"] = [dict(item) for item in items if isinstance(item, dict)]
        payload["completed_total"] = int(payload.get("completed_total") or 0)
        payload["last_completed_at"] = str(payload.get("last_completed_at") or "")
        return payload

    def _save_locked(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(state, indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def ensure_worker(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="isala-comparison-review-writer",
                daemon=True,
            )
            self._thread.start()

    def enqueue(
        self,
        *,
        project_id: str,
        workspace: str | Path,
        run_id: str,
        issue_id: str,
        decision: str,
    ) -> dict[str, Any]:
        project_id = str(project_id or "").strip()
        run_id = str(run_id or "").strip()
        issue_id = str(issue_id or "").strip()
        decision = str(decision or "").strip().lower()
        if not project_id or not run_id or not issue_id:
            raise ValueError("project_id, run_id en issue_id zijn verplicht")
        if decision not in {"model_error", "functional_ok", "gt_check", "deferred", "clear"}:
            raise ValueError("Onbekende reviewbeslissing")

        now = _utcnow()
        queue_id = uuid.uuid4().hex
        with self._lock:
            state = self._load_locked()
            # If the same issue is still waiting, only the newest click matters.
            # A currently processing item is not mutated; the newer decision is
            # appended and will deterministically run afterwards.
            existing = next(
                (
                    item
                    for item in reversed(state["items"])
                    if str(item.get("project_id") or "") == project_id
                    and str(item.get("run_id") or "") == run_id
                    and str(item.get("issue_id") or "") == issue_id
                    and str(item.get("status") or "pending") == "pending"
                ),
                None,
            )
            if existing is not None:
                existing.update(
                    {
                        "decision": decision,
                        "queued_at": now,
                        "attempts": 0,
                        "last_error": "",
                        "next_attempt_at": 0.0,
                    }
                )
                queue_id = str(existing.get("queue_id") or queue_id)
            else:
                state["items"].append(
                    {
                        "queue_id": queue_id,
                        "project_id": project_id,
                        "workspace": str(Path(workspace).resolve()),
                        "run_id": run_id,
                        "issue_id": issue_id,
                        "decision": decision,
                        "status": "pending",
                        "attempts": 0,
                        "queued_at": now,
                        "next_attempt_at": 0.0,
                        "last_error": "",
                    }
                )
            self._save_locked(state)
        self.ensure_worker()
        self._wake.set()
        return {"queue_id": queue_id, **self.status(project_id=project_id)}

    def discard_pending_issue(self, *, project_id: str, run_id: str, issue_id: str) -> int:
        """Drop not-yet-processing decisions for one issue.

        Used when a synchronous canonical-GT mutation supersedes a queued review
        decision. A processing decision is intentionally left alone; the caller
        should serialize the direct mutation with the worker and run afterwards.
        """
        with self._lock:
            state = self._load_locked()
            before = len(state["items"])
            state["items"] = [
                item
                for item in state["items"]
                if not (
                    str(item.get("project_id") or "") == str(project_id)
                    and str(item.get("run_id") or "") == str(run_id)
                    and str(item.get("issue_id") or "") == str(issue_id)
                    and str(item.get("status") or "pending") in {"pending", "failed"}
                )
            ]
            removed = before - len(state["items"])
            if removed:
                self._save_locked(state)
            return removed

    def status(self, *, project_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            state = self._load_locked()
            items = state["items"]
            if project_id:
                project_id = str(project_id)
                items = [item for item in items if str(item.get("project_id") or "") == project_id]
            pending = [item for item in items if str(item.get("status") or "pending") in {"pending", "processing"}]
            failed = [item for item in items if str(item.get("status") or "") == "failed"]
            last_error = ""
            if failed:
                last_error = str(failed[-1].get("last_error") or "")
            elif pending:
                last_error = str(pending[-1].get("last_error") or "")
            return {
                "pending_count": len(pending),
                "failed_count": len(failed),
                "queued_count": len(items),
                "processing": any(str(item.get("status") or "") == "processing" for item in pending),
                "completed_total": int(state.get("completed_total") or 0),
                "last_completed_at": str(state.get("last_completed_at") or ""),
                "last_error": last_error,
            }

    def retry_failed(self, *, project_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            state = self._load_locked()
            for item in state["items"]:
                if str(item.get("status") or "") != "failed":
                    continue
                if project_id and str(item.get("project_id") or "") != str(project_id):
                    continue
                item["status"] = "pending"
                item["attempts"] = 0
                item["next_attempt_at"] = 0.0
                item["last_error"] = ""
            self._save_locked(state)
        self.ensure_worker()
        self._wake.set()
        return self.status(project_id=project_id)

    def _claim_next(self) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            state = self._load_locked()
            for item in state["items"]:
                if str(item.get("status") or "pending") != "pending":
                    continue
                try:
                    due = float(item.get("next_attempt_at") or 0.0)
                except (TypeError, ValueError):
                    due = 0.0
                if due > now:
                    continue
                item["status"] = "processing"
                item["started_at"] = _utcnow()
                self._save_locked(state)
                return dict(item)
        return None

    def _complete(self, queue_id: str) -> None:
        with self._lock:
            state = self._load_locked()
            state["items"] = [item for item in state["items"] if str(item.get("queue_id") or "") != queue_id]
            state["completed_total"] = int(state.get("completed_total") or 0) + 1
            state["last_completed_at"] = _utcnow()
            self._save_locked(state)

    def _fail(self, queue_id: str, error: BaseException, *, permanent: bool) -> None:
        with self._lock:
            state = self._load_locked()
            item = next((row for row in state["items"] if str(row.get("queue_id") or "") == queue_id), None)
            if item is None:
                return
            attempts = int(item.get("attempts") or 0) + 1
            item["attempts"] = attempts
            item["last_error"] = f"{type(error).__name__}: {error}"
            if permanent or attempts >= MAX_RETRY_ATTEMPTS:
                item["status"] = "failed"
                item["next_attempt_at"] = 0.0
            else:
                item["status"] = "pending"
                item["next_attempt_at"] = time.time() + min(
                    MAX_BACKOFF_SECONDS,
                    0.5 * (2 ** max(0, attempts - 1)),
                )
            self._save_locked(state)

    def _worker_loop(self) -> None:
        while True:
            item = self._claim_next()
            if item is None:
                self._wake.wait(self.poll_interval)
                self._wake.clear()
                continue
            queue_id = str(item.get("queue_id") or "")
            try:
                self.handler(item)
            except (KeyError, ValueError, FileNotFoundError) as exc:
                self._fail(queue_id, exc, permanent=True)
            except Exception as exc:  # transient filesystem/runtime failures are retried
                self._fail(queue_id, exc, permanent=False)
            else:
                self._complete(queue_id)
