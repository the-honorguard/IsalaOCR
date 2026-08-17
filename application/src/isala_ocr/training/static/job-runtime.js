(() => {
  const estimates = window.ISALA_ACTION_DURATION_ESTIMATES || {};
  const trackedForms = Array.from(document.querySelectorAll('form[action="/jobs"]')).filter(form => {
    const input = form.querySelector('input[name="action_id"]');
    const actionId = String(input?.value || '');
    return actionId && estimates[actionId];
  });
  if (!trackedForms.length) return;

  const style = document.createElement('style');
  style.textContent = `
    .action-runtime-meta{margin-top:7px;display:grid;gap:5px;min-width:180px;font-size:11px;color:var(--muted)}
    .action-runtime-line{display:flex;align-items:center;justify-content:space-between;gap:10px;white-space:nowrap}
    .action-runtime-line strong{color:#c9d5df;font-weight:650}
    .action-runtime-bar{height:5px;background:#0b1118;border:1px solid var(--line);border-radius:999px;overflow:hidden}
    .action-runtime-bar>span{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--accent2),var(--accent));transition:width .45s ease}
    .action-runtime-meta.running .action-runtime-bar>span{position:relative}
    .action-runtime-meta.running .action-runtime-bar>span::after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.28),transparent);animation:runtime-scan 1.4s linear infinite}
    .action-runtime-meta.completed .action-runtime-bar>span{background:var(--ok)}
    .action-runtime-meta.failed .action-runtime-line strong{color:var(--bad)}
    @keyframes runtime-scan{from{transform:translateX(-100%)}to{transform:translateX(100%)}}
  `;
  document.head.appendChild(style);

  const projectId = String(document.getElementById('project-switch-select')?.value || 'default');
  const byAction = new Map();
  trackedForms.forEach(form => {
    const actionId = String(form.querySelector('input[name="action_id"]')?.value || '');
    if (!byAction.has(actionId)) byAction.set(actionId, []);
    byAction.get(actionId).push(form);
    if (form.querySelector('.action-runtime-meta')) return;
    const meta = document.createElement('div');
    meta.className = 'action-runtime-meta';
    meta.dataset.actionId = actionId;
    meta.innerHTML = '<div class="action-runtime-line"><span>Laatste run</span><strong>Nog geen meting</strong></div><div class="action-runtime-bar" hidden><span></span></div>';
    form.appendChild(meta);
  });

  const cacheKey = actionId => `isala-job-runtime:${projectId}:${actionId}`;

  function parseTime(value) {
    if (!value) return NaN;
    const ms = new Date(value).getTime();
    return Number.isFinite(ms) ? ms : NaN;
  }

  function durationMs(job) {
    const start = parseTime(job?.started_at || job?.created_at);
    const end = parseTime(job?.finished_at || job?.updated_at);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return 0;
    return end - start;
  }

  function formatDuration(ms) {
    if (!Number.isFinite(ms) || ms <= 0) return '—';
    const total = Math.max(1, Math.round(ms / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    if (hours) return `${hours}u ${String(minutes).padStart(2, '0')}m`;
    if (minutes) return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
    return `${seconds}s`;
  }

  function formatClock(value) {
    const ms = parseTime(value);
    if (!Number.isFinite(ms)) return '';
    return new Date(ms).toLocaleString('nl-NL', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'});
  }

  function readCached(actionId) {
    try {
      const raw = window.localStorage.getItem(cacheKey(actionId));
      const parsed = raw ? JSON.parse(raw) : null;
      return parsed && Number(parsed.duration_ms) > 0 ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  function cacheFinished(job) {
    const actionId = String(job?.action_id || '');
    if (!byAction.has(actionId) || !['completed', 'failed'].includes(String(job?.status || ''))) return;
    const measured = durationMs(job);
    if (!measured) return;
    const current = readCached(actionId);
    const finished = parseTime(job.finished_at || job.updated_at);
    const currentFinished = parseTime(current?.finished_at);
    if (current && Number.isFinite(currentFinished) && Number.isFinite(finished) && currentFinished > finished) return;
    try {
      window.localStorage.setItem(cacheKey(actionId), JSON.stringify({
        duration_ms: measured,
        status: String(job.status || ''),
        started_at: job.started_at || job.created_at || '',
        finished_at: job.finished_at || job.updated_at || '',
        job_id: job.job_id || '',
      }));
    } catch (_) {}
  }

  function latestByStatus(actionJobs, statuses) {
    return actionJobs
      .filter(job => statuses.includes(String(job.status || '')))
      .sort((a, b) => parseTime(b.finished_at || b.updated_at || b.started_at || b.created_at) - parseTime(a.finished_at || a.updated_at || a.started_at || a.created_at))[0] || null;
  }

  function render(actionId, jobs) {
    const actionJobs = jobs.filter(job => String(job?.action_id || '') === actionId);
    actionJobs.forEach(cacheFinished);

    const live = latestByStatus(actionJobs, ['running', 'pending']);
    const latestFinished = latestByStatus(actionJobs, ['completed', 'failed']);
    const latestSuccessful = latestByStatus(actionJobs, ['completed']);
    const cached = readCached(actionId);
    const referenceMs = durationMs(latestSuccessful) || Number(cached?.status === 'completed' ? cached.duration_ms : 0) || durationMs(latestFinished) || Number(cached?.duration_ms || 0);
    const last = latestFinished || cached;

    byAction.get(actionId).forEach(form => {
      const meta = form.querySelector('.action-runtime-meta');
      if (!meta) return;
      const line = meta.querySelector('.action-runtime-line');
      const bar = meta.querySelector('.action-runtime-bar');
      const fill = bar?.querySelector('span');
      meta.classList.remove('running', 'completed', 'failed');

      if (live) {
        const status = String(live.status || '');
        meta.classList.add(status === 'running' ? 'running' : 'pending');
        if (status === 'pending') {
          line.innerHTML = '<span>Deze run</span><strong>In wachtrij</strong>';
          if (bar) bar.hidden = true;
          return;
        }

        const start = parseTime(live.started_at || live.created_at);
        const elapsed = Number.isFinite(start) ? Math.max(0, Date.now() - start) : 0;
        const actualProgress = String(live.progress_mode || '') === 'determinate' ? Number(live.progress_percent || 0) : 0;
        const estimatedProgress = referenceMs > 0 ? Math.min(95, Math.max(1, (elapsed / referenceMs) * 100)) : 0;
        const percent = actualProgress > 0 ? Math.min(99, actualProgress) : estimatedProgress;
        const basis = actualProgress > 0
          ? `${Math.round(actualProgress)}% gemeten`
          : referenceMs > 0 ? `~${Math.round(estimatedProgress)}% op basis van vorige run` : 'tijd wordt gemeten';
        line.innerHTML = `<span>Deze run · ${formatDuration(elapsed)}</span><strong>${basis}</strong>`;
        if (bar && fill && percent > 0) {
          bar.hidden = false;
          fill.style.width = `${percent}%`;
        } else if (bar) {
          bar.hidden = true;
        }
        meta.title = referenceMs > 0 ? `Voortgangsindicatie gebruikt vorige succesvolle duur: ${formatDuration(referenceMs)}.` : 'Nog geen vorige runtijd beschikbaar; deze run wordt nu gemeten.';
        return;
      }

      if (bar) bar.hidden = true;
      if (!last) {
        line.innerHTML = '<span>Laatste run</span><strong>Nog geen meting</strong>';
        meta.title = 'Na de eerste voltooide run wordt hier de gemeten start-tot-eindtijd getoond.';
        return;
      }

      const measured = Number(last.duration_ms || durationMs(last));
      const status = String(last.status || 'completed');
      const finishedAt = last.finished_at || last.updated_at || '';
      meta.classList.add(status === 'failed' ? 'failed' : 'completed');
      const suffix = status === 'failed' ? ' · mislukt' : '';
      line.innerHTML = `<span>Laatste run${formatClock(finishedAt) ? ` · ${formatClock(finishedAt)}` : ''}</span><strong>${formatDuration(measured)}${suffix}</strong>`;
      meta.title = `Gemeten van start tot einde${last.started_at ? `: ${formatClock(last.started_at)} → ${formatClock(finishedAt)}` : ''}.`;
    });
  }

  function renderAll(jobs) {
    for (const actionId of byAction.keys()) render(actionId, jobs);
  }

  let lastJobs = [];
  let timer = null;
  let polling = false;

  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(`/api/status?_runtime=${Date.now()}`, {cache:'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const state = await response.json();
      lastJobs = Array.isArray(state.jobs) ? state.jobs : [];
      renderAll(lastJobs);
    } catch (_) {
      renderAll(lastJobs);
    } finally {
      polling = false;
      const trackedIds = new Set(byAction.keys());
      const hasLive = lastJobs.some(job => trackedIds.has(String(job?.action_id || '')) && ['running', 'pending'].includes(String(job?.status || '')));
      timer = window.setTimeout(poll, document.hidden ? 30000 : (hasLive ? 2000 : 15000));
    }
  }

  window.addEventListener('isala:job-created', event => {
    const job = event.detail || {};
    if (!byAction.has(String(job.action_id || ''))) return;
    lastJobs = [job, ...lastJobs.filter(item => item.job_id !== job.job_id)];
    renderAll(lastJobs);
    if (timer) window.clearTimeout(timer);
    window.setTimeout(poll, 400);
  });

  window.addEventListener('isala:job-status', event => {
    const job = event.detail || {};
    if (!byAction.has(String(job.action_id || ''))) return;
    lastJobs = [job, ...lastJobs.filter(item => item.job_id !== job.job_id)];
    renderAll(lastJobs);
  });

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      if (timer) window.clearTimeout(timer);
      poll();
    }
  });

  renderAll([]);
  poll();
})();

// Step 7: a GT-check decision is both a review classification and an explicit
// request to edit the canonical Ground Truth. Save the decision first through
// the existing AJAX handler, then move straight to the source-specific GT Studio.
(() => {
  if (window.location.pathname !== '/process/table-compare') return;

  const studioUrlFor = row => {
    const link = row?.querySelector('a[href^="/detection-review/"]');
    return link?.getAttribute('href') || '';
  };

  const observer = new MutationObserver(mutations => {
    for (const mutation of mutations) {
      if (mutation.type !== 'attributes' || mutation.attributeName !== 'data-issue-decision') continue;
      const row = mutation.target;
      if (!(row instanceof HTMLElement) || row.dataset.issueDecision !== 'gt_check') continue;
      const studioUrl = studioUrlFor(row);
      if (!studioUrl) continue;
      observer.disconnect();
      window.location.assign(studioUrl);
      return;
    }
  });

  document.querySelectorAll('.comparison-issue-row').forEach(row => {
    observer.observe(row, {attributes: true, attributeFilter: ['data-issue-decision']});
  });
})();
