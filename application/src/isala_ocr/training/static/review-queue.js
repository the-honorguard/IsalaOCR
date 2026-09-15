/* Shared persistent retry queue for review-studio save actions.
 *
 * Generalized from detection_review_studio.html's original inline
 * localStorage-backed ROI-review queue (the richest of the review-studio
 * save strategies: bounded-concurrency, capped-attempt automatic retry with
 * backoff, survives a page reload via localStorage, and a definitive
 * "Opnieuw" retry after the attempt cap). Adopted as the shared standard for
 * all review-studio save paths per
 * documentation/architecture/refactor-phase2-remaining-plan.md, punt 1,
 * stap 5 -- callers that previously did a single fetch with full rollback on
 * any failure (mapping-review-studio.js, step7-review-flow.js) get this
 * queue's retry/backoff instead: this is a deliberate, approved behavior
 * change for those screens, not a bug.
 *
 * The engine only owns queue bookkeeping (persistence, concurrency,
 * attempt/backoff, dedup). It knows nothing about URLs, payload shape, or
 * how to apply a successful/failed result to the page -- that is the
 * caller's `execute(task)` callback (throw to signal failure) plus the
 * `onChange`/`onTaskError` hooks for status UI.
 */
(function (global) {
  'use strict';

  function createTaskQueue(options) {
    const opts = options || {};
    const storageKey = opts.storageKey;
    const concurrency = opts.concurrency || 3;
    const maxAttempts = opts.maxAttempts || 3;
    const backoff = opts.backoff || function (attempt) { return Math.min(4000, 700 * attempt); };
    const isEligible = opts.isEligible || function () { return true; };
    const execute = opts.execute;
    const onChange = opts.onChange || function () {};
    const onTaskError = opts.onTaskError || function () {};
    const makeId = opts.makeId || function (task) {
      return `${task.kind || 'task'}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
    };

    let tasks = [];
    const inFlight = new Set();

    function load() {
      try {
        const stored = JSON.parse(window.localStorage.getItem(storageKey) || '[]');
        if (Array.isArray(stored)) tasks = stored;
      } catch (_) {
        tasks = [];
      }
    }

    function persist() {
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(tasks));
      } catch (error) {
        onChange({tasks: tasks, inFlight: inFlight, persistError: error});
      }
    }

    function notify() {
      onChange({tasks: tasks, inFlight: inFlight});
    }

    function remove(id) {
      tasks = tasks.filter(function (task) { return task.id !== id; });
      inFlight.delete(id);
      persist();
      notify();
    }

    function pump() {
      notify();
      while (inFlight.size < concurrency) {
        const task = tasks.find(function (candidate) {
          return !candidate.failed && !inFlight.has(candidate.id) && isEligible(candidate, {tasks: tasks, inFlight: inFlight});
        });
        if (!task) break;
        run(task);
      }
    }

    async function run(task) {
      inFlight.add(task.id);
      notify();
      try {
        await execute(task);
        remove(task.id);
        // A freed concurrency slot may let another queued task proceed now;
        // this task itself is done, so re-running it is not a concern here.
        pump();
      } catch (error) {
        inFlight.delete(task.id);
        task.attempt = Number(task.attempt || 0) + 1;
        task.last_error = String((error && error.message) || error);
        if (task.attempt >= maxAttempts) task.failed = true;
        persist();
        notify();
        onTaskError(task, error);
        // A non-terminal failure must wait for its backoff -- pumping here
        // too would immediately re-pick this same task and defeat the
        // backoff entirely. A terminal failure can pump right away: this
        // task is now `failed` and pump()'s eligibility check skips it, so
        // the call only lets *other* queued tasks proceed.
        if (task.failed) pump();
        else global.setTimeout(pump, backoff(task.attempt));
      }
    }

    function enqueue(task, dedupe) {
      const withMeta = Object.assign({}, task, {
        id: task.id || makeId(task),
        attempt: 0,
        failed: false,
        created_at: Date.now(),
      });
      if (typeof dedupe === 'function') {
        tasks = tasks.filter(function (existing) {
          return !(!inFlight.has(existing.id) && dedupe(existing, withMeta));
        });
      }
      tasks.push(withMeta);
      persist();
      notify();
      pump();
      return withMeta;
    }

    function retryFailed() {
      tasks.forEach(function (task) {
        if (task.failed) {
          task.failed = false;
          task.attempt = 0;
          task.last_error = '';
        }
      });
      persist();
      pump();
    }

    load();

    return {
      enqueue: enqueue,
      retryFailed: retryFailed,
      pump: pump,
      tasks: function () { return tasks; },
      inFlight: inFlight,
    };
  }

  global.IsalaReviewQueue = {createTaskQueue: createTaskQueue};
})(window);
