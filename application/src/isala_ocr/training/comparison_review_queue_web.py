from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from .comparison_review_queue import PersistentComparisonReviewQueue
from .json_api import json_error
from .projects import ProjectManager
from .table_model_comparison import review_comparison_issue


_GLOBAL_REVIEW_QUEUE_UI = r"""
<style>
#isala-review-write-queue{position:fixed;right:18px;bottom:18px;z-index:12000;min-width:250px;max-width:min(420px,calc(100vw - 36px));padding:10px 12px;border:1px solid var(--line,#334155);border-radius:10px;background:rgba(10,18,26,.96);box-shadow:0 12px 36px rgba(0,0,0,.35);font-size:12px;line-height:1.35;backdrop-filter:blur(8px)}
#isala-review-write-queue[hidden]{display:none}#isala-review-write-queue .rq-head{display:flex;align-items:center;justify-content:space-between;gap:12px}#isala-review-write-queue .rq-title{display:flex;align-items:center;gap:7px;font-weight:700}#isala-review-write-queue .rq-dot{width:8px;height:8px;border-radius:50%;background:#45d7a0;box-shadow:0 0 0 3px rgba(69,215,160,.12)}#isala-review-write-queue.is-busy .rq-dot{background:#f0b84b;box-shadow:0 0 0 3px rgba(240,184,75,.12)}#isala-review-write-queue.is-failed{border-color:#a94d57}#isala-review-write-queue.is-failed .rq-dot{background:#ff6378;box-shadow:0 0 0 3px rgba(255,99,120,.12)}#isala-review-write-queue .rq-detail{display:block;margin-top:4px;color:var(--muted,#94a3b8)}#isala-review-write-queue button{margin-top:7px;padding:5px 8px;font-size:11px}.isala-return-to-review{white-space:nowrap}
</style>
<div id="isala-review-write-queue" hidden aria-live="polite" aria-label="Review-opslag wachtrij">
  <div class="rq-head"><span class="rq-title"><span class="rq-dot"></span>Review-opslag</span><strong id="isala-review-write-queue-count">0</strong></div>
  <span class="rq-detail" id="isala-review-write-queue-detail">Alle beoordelingen opgeslagen.</span>
  <button type="button" class="ghost" id="isala-review-write-queue-retry" hidden>Opnieuw proberen</button>
</div>
<script>
(() => {
  if (window.__ISALA_PERSISTENT_REVIEW_QUEUE_INSTALLED__) return;
  window.__ISALA_PERSISTENT_REVIEW_QUEUE_INSTALLED__ = true;
  const nativeFetch = window.fetch.bind(window);
  const queueBox = document.getElementById('isala-review-write-queue');
  const queueCount = document.getElementById('isala-review-write-queue-count');
  const queueDetail = document.getElementById('isala-review-write-queue-detail');
  const retryButton = document.getElementById('isala-review-write-queue-retry');
  let queuePollTimer = null;
  let hideTimer = null;

  const validLocalReturn = value => typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && value.startsWith('/process/table-compare');

  function renderQueue(payload) {
    if (!queueBox) return;
    const pending = Number(payload?.pending_count || 0);
    const failed = Number(payload?.failed_count || 0);
    queueBox.classList.toggle('is-busy', pending > 0);
    queueBox.classList.toggle('is-failed', failed > 0);
    retryButton.hidden = failed === 0;
    if (failed > 0) {
      clearTimeout(hideTimer);
      queueBox.hidden = false;
      queueCount.textContent = `${failed} fout`;
      queueDetail.textContent = payload?.last_error ? `Opslaan geblokkeerd · ${payload.last_error}` : 'Een review kon niet worden opgeslagen.';
      return;
    }
    if (pending > 0) {
      clearTimeout(hideTimer);
      queueBox.hidden = false;
      queueCount.textContent = String(pending);
      queueDetail.textContent = payload?.processing ? `${pending} beoordeling(en) verwerken…` : `${pending} beoordeling(en) in backendwachtrij`;
      return;
    }
    queueCount.textContent = '✓';
    queueDetail.textContent = 'Alle beoordelingen opgeslagen.';
    if (!queueBox.hidden) {
      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => { queueBox.hidden = true; }, 1800);
    }
  }

  function scheduleQueuePoll(active) {
    clearTimeout(queuePollTimer);
    // This widget is injected on every page, not just the review screen, so
    // it kept polling every second globally even though the queue is empty
    // (no pending/failed items) the overwhelming majority of the time - it
    // only needs to be that responsive while a write is actually in flight.
    // Mirrors the activity dock's own backoff (schedulePoll in app.js).
    const delay = document.hidden ? 30000 : (active ? 1000 : 15000);
    queuePollTimer = setTimeout(pollQueue, delay);
  }

  async function pollQueue() {
    let active = false;
    try {
      const response = await nativeFetch(`/api/comparison-review-queue?_=${Date.now()}`, {cache: 'no-store'});
      if (response.ok) {
        const payload = await response.json();
        renderQueue(payload);
        active = Number(payload?.pending_count || 0) > 0 || Number(payload?.failed_count || 0) > 0;
      }
    } catch (_) {
    } finally {
      scheduleQueuePoll(active);
    }
  }

  retryButton?.addEventListener('click', async () => {
    retryButton.disabled = true;
    try {
      const response = await nativeFetch('/api/comparison-review-queue/retry', {method: 'POST', headers: {'Accept': 'application/json'}});
      if (response.ok) renderQueue(await response.json());
      scheduleQueuePoll(true);
    } finally {
      retryButton.disabled = false;
    }
  });

  // Transparently reroute only Step-6 review decisions. Other mutations, such
  // as '+ Toevoegen aan GT', stay synchronous because they alter canonical GT.
  window.fetch = function(input, init) {
    try {
      const options = init || {};
      const method = String(options.method || 'GET').toUpperCase();
      const body = options.body;
      const rawUrl = typeof input === 'string' ? input : (input?.url || String(input));
      const target = new URL(rawUrl, window.location.href);
      const action = body instanceof FormData ? String(body.get('comparison_action') || '') : '';
      if (method === 'POST' && target.pathname === '/process/table-compare' && action === 'review_issue') {
        const requestOptions = {...options, headers: {...(options.headers || {}), 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}};
        const queued = nativeFetch('/api/comparison-review-queue', requestOptions);
        queued.then(response => {
          response.clone().json().then(payload => {
            if (payload?.queue) renderQueue(payload.queue);
            // A poll backed off to the idle interval must not sit on a newly
            // pending item for up to 15s; track its drain at full cadence.
            scheduleQueuePoll(true);
          }).catch(() => {});
        }).catch(() => {});
        return queued;
      }
    } catch (_) {}
    return nativeFetch(input, init);
  };

  // The Step-6 template updates data-issue-open after a successful enqueue.
  // Recalculate the global counters locally; no expensive comparison rebuild is
  // needed for every click anymore.
  function refreshComparisonCounters() {
    const rows = Array.from(document.querySelectorAll('.comparison-issue-row'));
    if (!rows.length) return;
    const open = rows.filter(row => row.dataset.issueOpen === '1').length;
    const reviewed = rows.length - open;
    const openCount = document.getElementById('comparison-open-count');
    const reviewedCount = document.getElementById('comparison-reviewed-count');
    const issueCount = document.getElementById('comparison-issue-count');
    if (openCount) {
      openCount.textContent = String(open);
      openCount.classList.toggle('ok', open === 0);
      openCount.classList.toggle('warn', open !== 0);
    }
    if (reviewedCount) reviewedCount.textContent = String(reviewed);
    if (issueCount) issueCount.textContent = String(rows.length);
  }
  const comparisonObserver = new MutationObserver(mutations => {
    if (mutations.some(item => item.type === 'attributes' && item.attributeName === 'data-issue-open')) refreshComparisonCounters();
  });
  document.querySelectorAll('.comparison-issue-row').forEach(row => comparisonObserver.observe(row, {attributes: true, attributeFilter: ['data-issue-open']}));

  // Any jump from an individual discrepancy to Ground Truth Studio gets a
  // return target to the exact Step-6 issue. The return target is also kept in
  // sessionStorage so browsing another GT source does not lose it.
  if (window.location.pathname === '/process/table-compare') {
    document.querySelectorAll('a[href^="/detection-review"]').forEach(link => {
      const row = link.closest('.comparison-issue-row');
      const returnUrl = new URL(window.location.href);
      returnUrl.searchParams.delete('focus_issue');
      if (row?.dataset.issueId) returnUrl.searchParams.set('focus_issue', row.dataset.issueId);
      const target = new URL(link.href, window.location.origin);
      target.searchParams.set('return_to', returnUrl.pathname + returnUrl.search);
      link.href = target.pathname + target.search;
    });

    const focusIssue = new URLSearchParams(window.location.search).get('focus_issue') || '';
    if (focusIssue) {
      const row = Array.from(document.querySelectorAll('.comparison-issue-row')).find(item => item.dataset.issueId === focusIssue);
      if (row) {
        const filter = document.getElementById('comparison-issue-filter');
        if (filter && row.classList.contains('is-filtered')) {
          filter.value = 'all';
          filter.dispatchEvent(new Event('change'));
        }
        row.classList.add('is-selected');
        document.querySelectorAll('[data-compare-issue-id]').forEach(box => {
          if (box.dataset.compareIssueId === focusIssue) box.classList.add('is-selected');
        });
        requestAnimationFrame(() => row.scrollIntoView({behavior: 'smooth', block: 'center'}));
      }
    }
  }

  if (window.location.pathname.startsWith('/detection-review')) {
    const params = new URLSearchParams(window.location.search);
    let returnTo = params.get('return_to') || '';
    const storageKey = 'isala-gt-return-to-step6';
    if (validLocalReturn(returnTo)) {
      try { sessionStorage.setItem(storageKey, JSON.stringify({url: returnTo, savedAt: Date.now()})); } catch (_) {}
    } else {
      returnTo = '';
      try {
        const stored = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
        if (stored && validLocalReturn(stored.url) && Date.now() - Number(stored.savedAt || 0) < 2 * 60 * 60 * 1000) returnTo = stored.url;
      } catch (_) {}
    }
    if (validLocalReturn(returnTo)) {
      const back = document.createElement('a');
      back.className = 'button primary isala-return-to-review';
      back.href = returnTo;
      back.textContent = '← Terug naar afwijking';
      back.addEventListener('click', () => { try { sessionStorage.removeItem(storageKey); } catch (_) {} });
      const toolbar = document.querySelector('.review-studio-toolbar .review-source-nav');
      if (toolbar) toolbar.insertBefore(back, toolbar.firstChild);
      else {
        const content = document.querySelector('.content');
        if (content) {
          const wrapper = document.createElement('div');
          wrapper.className = 'card';
          wrapper.style.marginBottom = '12px';
          wrapper.appendChild(back);
          content.insertBefore(wrapper, content.firstChild);
        }
      }
    }
  }

  pollQueue();
  window.addEventListener('pagehide', () => clearTimeout(queuePollTimer));
})();
</script>
"""


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
            return json_error("Alleen reviewbeslissingen horen in deze wachtrij", 400)
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
            return json_error(str(exc), 400)

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

    @app.after_request
    def inject_comparison_review_queue_ui(response):
        if response.status_code >= 400 or response.mimetype != "text/html" or response.direct_passthrough:
            return response
        try:
            body = response.get_data(as_text=True)
        except (RuntimeError, UnicodeError):
            return response
        if "</body>" not in body or "__ISALA_PERSISTENT_REVIEW_QUEUE_INSTALLED__" in body:
            return response
        response.set_data(body.replace("</body>", _GLOBAL_REVIEW_QUEUE_UI + "\n</body>", 1))
        response.headers.pop("Content-Length", None)
        return response

    return queue
