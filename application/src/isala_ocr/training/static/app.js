(() => {
  // Worker-backed actions refresh the current process page after successful
  // completion so newly unlocked buttons/state become visible. Preserve the
  // user's scroll position across that deliberate refresh.
  const autoRefreshScrollKey = `isala-auto-refresh-scroll:${window.location.pathname}`;
  const savedAutoRefreshScroll = window.sessionStorage.getItem(autoRefreshScrollKey);
  if (savedAutoRefreshScroll !== null) {
    window.sessionStorage.removeItem(autoRefreshScrollKey);
    const y = Number(savedAutoRefreshScroll);
    if (Number.isFinite(y)) window.requestAnimationFrame(() => window.scrollTo({top: y, behavior: 'auto'}));
  }

  document.addEventListener('click', event => {
    const box = event.target.closest('[data-sample]');
    if (!box) return;
    const id = box.dataset.sample;
    document.querySelectorAll('[data-sample]').forEach(item => item.classList.toggle('active', item.dataset.sample === id));
    const row = document.getElementById(`row-${id}`);
    if (row) row.scrollIntoView({behavior: 'smooth', block: 'center'});
  });

  document.querySelectorAll('.header-target-select').forEach(select => {
    select.addEventListener('change', () => {
      const option = select.options[select.selectedIndex];
      const card = select.closest('.header-review-card');
      const exact = card ? card.querySelector('input[name^="header_exact_"]') : null;
      if (exact && option && option.dataset.canonical) exact.value = option.dataset.canonical;
    });
  });

  // v3.13.3: show an approximate wall-clock duration next to every queued
  // workflow action. Navigation/editor buttons stay unlabelled because they are
  // immediate and do not start worker work.
  const actionDurationEstimates = window.ISALA_ACTION_DURATION_ESTIMATES || {};

  function annotateActionDurations(root = document) {
    root.querySelectorAll('form[action="/jobs"]').forEach(form => {
      if (form.dataset.durationAnnotated === '1') return;
      const actionInput = form.querySelector('input[name="action_id"]');
      const actionId = actionInput ? String(actionInput.value || '') : '';
      const estimate = actionDurationEstimates[actionId];
      if (!estimate || !estimate.label) return;
      const button = form.querySelector('button[type="submit"], button:not([type])');
      if (!button) return;

      const detail = String(estimate.detail || 'Indicatie; werkelijke duur kan afwijken.');
      button.title = button.title
        ? `${button.title} · Verwachte duur ${estimate.label}. ${detail}`
        : `Verwachte duur ${estimate.label}. ${detail}`;

      // Very small technical check buttons get a tooltip only; a visible badge
      // would make the preparation matrix unnecessarily wide.
      if (!button.classList.contains('small-button')) {
        const badge = document.createElement('span');
        badge.className = 'action-duration-estimate';
        badge.title = detail;
        badge.setAttribute('aria-label', `Geschatte duur ${estimate.label}`);
        badge.innerHTML = `<span aria-hidden="true">⏱</span> ${escapeHtml(estimate.label)}`;
        form.appendChild(badge);
        form.classList.add('action-duration-form');
      }
      form.dataset.durationAnnotated = '1';
    });
  }

  annotateActionDurations();

  const dock = document.getElementById('activity-dock');
  if (!dock) return;

  const elements = {
    toggle: document.getElementById('activity-toggle'),
    copyAll: document.getElementById('activity-copy-all'),
    select: document.getElementById('activity-job-select'),
    title: document.getElementById('activity-title'),
    subtitle: document.getElementById('activity-subtitle'),
    status: document.getElementById('activity-status'),
    workerDot: document.getElementById('worker-dot'),
    workerLabel: document.getElementById('worker-label'),
    miniBar: document.getElementById('activity-mini-bar'),
    progressBar: document.getElementById('activity-progress-bar'),
    progressText: document.getElementById('activity-progress-text'),
    progressDetail: document.getElementById('activity-progress-detail'),
    terminal: document.getElementById('activity-terminal'),
    followLive: document.getElementById('activity-follow-live'),
    logTabs: Array.from(document.querySelectorAll('[data-activity-log-stream]')),
    stderrBadge: document.getElementById('activity-stderr-badge'),
    activeModel: document.getElementById('active-model-summary'),
  };

  const params = new URLSearchParams(window.location.search);
  let activeJobId = params.get('job_id') || window.localStorage.getItem('isala-active-job') || '';
  let jobs = [];
  let polling = false;
  let pollTimer = null;
  let lastWorker = {};
  const refreshOnCompleteJobs = new Set();
  let pageReloadScheduled = false;
  const validLogStreams = new Set(['stdout', 'stderr', 'worker', 'overview']);
  const observedJobStatuses = new Map();
  let activeLogStream = window.localStorage.getItem('isala-log-stream') || 'stdout';
  if (!validLogStreams.has(activeLogStream)) activeLogStream = 'stdout';
  const logStates = new Map();

  const labels = {
    pending: 'In wachtrij',
    running: 'Bezig',
    completed: 'Voltooid',
    failed: 'Mislukt',
  };

  function setExpanded(expanded) {
    dock.classList.toggle('collapsed', !expanded);
    elements.toggle.setAttribute('aria-expanded', String(expanded));
    window.localStorage.setItem('isala-activity-terminal-expanded-v2', expanded ? '1' : '0');
    if (expanded) loadLog(true);
  }

  function updateUrlJob(jobId) {
    const url = new URL(window.location.href);
    if (jobId) url.searchParams.set('job_id', jobId);
    else url.searchParams.delete('job_id');
    window.history.replaceState({}, '', url);
  }

  function setActiveJob(jobId, open = false) {
    activeJobId = jobId || '';
    if (activeJobId) window.localStorage.setItem('isala-active-job', activeJobId);
    else window.localStorage.removeItem('isala-active-job');
    updateUrlJob(activeJobId);
    if (elements.select.value !== activeJobId) elements.select.value = activeJobId;
    renderLogTabs();
    renderFollowState();
    if (open) setExpanded(true);
    renderCurrentJob();
    loadLog(true);
  }

  function currentJob() {
    return jobs.find(job => job.job_id === activeJobId) || null;
  }

  function formatTime(value) {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? '' : date.toLocaleTimeString('nl-NL', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
  }

  function statusText(job) {
    return labels[job?.status] || job?.status || 'Gereed';
  }

  function progressFor(job) {
    const value = Number(job?.progress_percent || 0);
    return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  }

  function progressModeFor(job) {
    if (!job) return 'determinate';
    if (job.progress_mode) return job.progress_mode;
    return ['running', 'pending'].includes(job.status) ? 'indeterminate' : 'determinate';
  }

  function logState() {
    const key = `${activeJobId || 'none'}:${activeLogStream}`;
    if (!logStates.has(key)) logStates.set(key, {lastLog: '', autoFollow: true, scrollTop: 0});
    return logStates.get(key);
  }

  function terminalAtBottom() {
    if (!elements.terminal) return true;
    return elements.terminal.scrollHeight - elements.terminal.scrollTop - elements.terminal.clientHeight < 60;
  }

  function stderrSeenKey(jobId) {
    return `isala-stderr-seen:${jobId}`;
  }

  function stderrSeenBytes(job) {
    if (!job?.job_id) return 0;
    const value = Number(window.localStorage.getItem(stderrSeenKey(job.job_id)) || 0);
    return Number.isFinite(value) ? value : 0;
  }

  function markStderrSeen(job) {
    if (!job?.job_id) return;
    window.localStorage.setItem(stderrSeenKey(job.job_id), String(Number(job.stderr_bytes || 0)));
  }

  function renderLogTabs() {
    const job = currentJob();
    elements.logTabs.forEach(tab => {
      const selected = tab.dataset.activityLogStream === activeLogStream;
      tab.classList.toggle('active', selected);
      tab.setAttribute('aria-selected', String(selected));
    });
    if (!elements.stderrBadge) return;
    const stderrBytes = Number(job?.stderr_bytes || 0);
    if (activeLogStream === 'stderr' && job) markStderrSeen(job);
    const unseen = stderrBytes > stderrSeenBytes(job);
    elements.stderrBadge.hidden = !unseen || activeLogStream === 'stderr';
  }

  function renderFollowState() {
    if (!elements.followLive) return;
    elements.followLive.hidden = logState().autoFollow;
  }

  function followLiveOutput() {
    const state = logState();
    state.autoFollow = true;
    renderFollowState();
    window.requestAnimationFrame(() => {
      elements.terminal.scrollTop = elements.terminal.scrollHeight;
      state.scrollTop = elements.terminal.scrollTop;
    });
  }

  function setLogStream(stream) {
    if (!validLogStreams.has(stream) || stream === activeLogStream) return;
    const previous = logState();
    previous.scrollTop = elements.terminal.scrollTop;
    activeLogStream = stream;
    window.localStorage.setItem('isala-log-stream', activeLogStream);
    renderLogTabs();
    renderFollowState();
    elements.terminal.textContent = 'Uitvoer laden…';
    loadLog(true);
  }

  function renderJobOptions() {
    const current = activeJobId;
    elements.select.innerHTML = '';
    if (!jobs.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'Geen taken';
      elements.select.appendChild(option);
      return;
    }
    jobs.forEach(job => {
      const option = document.createElement('option');
      option.value = job.job_id;
      option.textContent = `${statusText(job)} · ${job.action_name}`;
      elements.select.appendChild(option);
    });
    if (jobs.some(job => job.job_id === current)) elements.select.value = current;
  }

  function renderWorker(worker) {
    lastWorker = worker || {};
    const online = Boolean(worker?.online);
    elements.workerDot.classList.toggle('ok', online);
    elements.workerDot.classList.toggle('bad-dot', !online);
    if (online) {
      elements.workerLabel.textContent = worker.current_job_id ? 'Worker actief' : 'Worker gereed';
    } else {
      elements.workerLabel.textContent = 'Worker niet bereikbaar';
    }
  }

  function renderCurrentJob() {
    const job = currentJob();
    renderLogTabs();
    if (!job) {
      elements.title.textContent = 'Geen actieve taak';
      elements.subtitle.textContent = jobs.length ? 'Selecteer een eerdere taak om de uitvoer te bekijken.' : 'Klik op een taak om de voortgang hier te volgen.';
      elements.status.textContent = 'Gereed';
      elements.status.className = 'activity-status';
      elements.progressText.textContent = '0%';
      elements.progressDetail.textContent = 'Geen taak geselecteerd';
      elements.progressBar.style.setProperty('--value', '0%');
      elements.miniBar.style.width = '0%';
      elements.progressBar.parentElement?.classList.remove('indeterminate');
      elements.miniBar.parentElement?.classList.remove('indeterminate');
      dock.classList.remove('is-running', 'is-failed', 'is-completed');
      return;
    }

    const percent = progressFor(job);
    const progressMode = progressModeFor(job);
    const indeterminate = progressMode === 'indeterminate';
    elements.title.textContent = job.action_name || 'Taak';
    const started = formatTime(job.started_at || job.created_at);
    elements.subtitle.textContent = started ? `Gestart ${started}` : (job.progress_label || statusText(job));
    elements.status.textContent = statusText(job);
    elements.status.className = `activity-status ${job.status || ''}`;
    elements.progressText.textContent = indeterminate ? (job.status === 'pending' ? 'Wachtrij' : 'Bezig') : `${percent.toFixed(percent % 1 ? 1 : 0)}%`;
    elements.progressDetail.textContent = job.progress_label || statusText(job);
    elements.progressBar.parentElement?.classList.toggle('indeterminate', indeterminate);
    elements.miniBar.parentElement?.classList.toggle('indeterminate', indeterminate);
    elements.progressBar.style.setProperty('--value', indeterminate ? '0%' : `${percent}%`);
    elements.miniBar.style.width = indeterminate ? '0%' : `${percent}%`;
    dock.classList.toggle('is-running', job.status === 'running' || job.status === 'pending');
    dock.classList.toggle('is-failed', job.status === 'failed');
    dock.classList.toggle('is-completed', job.status === 'completed');

  }

  function syntheticLog(job) {
    if (!job) return 'Nog geen taakuitvoer.';
    const lines = [
      `[${formatTime(job.created_at) || '--:--:--'}] Taak aangemaakt: ${job.action_name}`,
      `Taak-ID: ${job.job_id}`,
    ];
    if (job.status === 'pending') {
      lines.push(lastWorker?.online
        ? 'Status: in wachtrij; de lokale PowerShell-worker is online.'
        : 'Status: in wachtrij; de lokale PowerShell-worker is niet bereikbaar.');
      lines.push('Nog geen scriptuitvoer ontvangen.');
    }
    if (job.status === 'running') {
      lines.push(`[${formatTime(job.started_at) || '--:--:--'}] Worker heeft de taak opgepakt.`);
      lines.push('PowerShell/Docker wordt uitgevoerd; nieuwe regels verschijnen automatisch.');
    }
    if (job.status === 'completed') lines.push(`[${formatTime(job.finished_at) || '--:--:--'}] Taak is succesvol voltooid.`);
    if (job.status === 'failed') lines.push(`[${formatTime(job.finished_at) || '--:--:--'}] Taak is mislukt. Controleer STDERR hieronder.`);
    return lines.join('\n');
  }

  function normalizeLog(text) {
    const normalized = String(text || '')
      .replace(/\u0000/g, '')
      .replace(/\u001b\[[0-9;?]*[ -\/]*[@-~]/g, '')
      .replace(/\r\n?/g, '\n');
    const visible = normalized.replace(/[\s\uFEFF\u200B]/g, '');
    return visible.length ? normalized : '';
  }

  async function copyAllTerminalOutput() {
    const job = currentJob();
    if (!job || !elements.copyAll) return;
    const button = elements.copyAll;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = 'Terminaloutput ophalen…';
    try {
      const streams = [
        ['STDOUT', 'stdout'],
        ['STDERR', 'stderr'],
        ['WORKER', 'worker'],
      ];
      const sections = await Promise.all(streams.map(async ([label, stream]) => {
        const response = await fetch(`/api/jobs/${encodeURIComponent(job.job_id)}/log?stream=${stream}&_=${Date.now()}`, {cache: 'no-store'});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return `===== ${label} =====\n${normalizeLog(await response.text()) || '(geen uitvoer)'}`;
      }));
      const text = [`===== ${job.action_name || 'Taak'} · ${job.job_id} =====`, ...sections].join('\n\n');
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const helper = document.createElement('textarea');
        helper.value = text;
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        document.body.appendChild(helper);
        helper.focus();
        helper.select();
        if (!document.execCommand('copy')) throw new Error('Klembord niet beschikbaar');
        helper.remove();
      }
      button.textContent = 'Volledige output gekopieerd';
      window.setTimeout(() => { button.textContent = original; }, 1600);
    } catch (error) {
      button.textContent = 'Kopiëren mislukt';
      window.setTimeout(() => { button.textContent = original; }, 2200);
    } finally {
      button.disabled = false;
    }
  }

  async function loadLog(force = false) {
    const job = currentJob();
    if (!job) {
      elements.terminal.textContent = 'Nog geen taakuitvoer.';
      return;
    }
    if (dock.classList.contains('collapsed') && !force) return;
    const state = logState();
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(job.job_id)}/log?stream=${encodeURIComponent(activeLogStream)}&_=${Date.now()}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const text = normalizeLog(await response.text());
      const fallback = activeLogStream === 'overview' ? syntheticLog(job)
        : activeLogStream === 'stderr' ? 'Geen STDERR-uitvoer voor deze taak.'
        : activeLogStream === 'worker' ? 'Nog geen worker-uitvoer voor deze taak.'
        : 'Nog geen STDOUT-uitvoer ontvangen.';
      const rendered = text || fallback;
      if (rendered !== state.lastLog || force) {
        const shouldFollow = state.autoFollow;
        const savedScrollTop = state.scrollTop;
        elements.terminal.textContent = rendered;
        state.lastLog = rendered;
        if (shouldFollow) followLiveOutput();
        else {
          elements.terminal.scrollTop = Math.min(savedScrollTop, Math.max(0, elements.terminal.scrollHeight - elements.terminal.clientHeight));
          renderFollowState();
        }
      }
      if (activeLogStream === 'stderr') {
        markStderrSeen(job);
        renderLogTabs();
      }
    } catch (error) {
      elements.terminal.textContent = `Terminal kon niet worden geladen: ${error}`;
    }
  }

  function schedulePoll(delay) {
    if (pollTimer !== null) window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(() => pollStatus(), delay);
  }

  function refreshPageAfterCompletedJob(job) {
    if (pageReloadScheduled) return;
    pageReloadScheduled = true;
    window.sessionStorage.setItem(autoRefreshScrollKey, String(window.scrollY));
    const label = job?.action_name || 'Taak';
    elements.progressDetail.textContent = `${label} voltooid · pagina wordt bijgewerkt…`;
    window.setTimeout(() => window.location.replace(window.location.href), 450);
  }

  async function pollStatus() {
    if (polling) return;
    if (pollTimer !== null) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
    polling = true;
    try {
      const response = await fetch(`/api/status?_=${Date.now()}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const state = await response.json();
      jobs = Array.isArray(state.jobs) ? state.jobs : [];
      jobs.forEach(job => {
        const id = String(job.job_id || '');
        const status = String(job.status || 'pending');
        if (!id) return;
        const previous = observedJobStatuses.get(id);
        if (previous !== undefined && previous !== status) {
          window.dispatchEvent(new CustomEvent('isala:job-status', {
            detail: {...job, previous_status: previous},
          }));
        }
        observedJobStatuses.set(id, status);
        if (refreshOnCompleteJobs.has(id)) {
          if (status === 'completed') {
            refreshOnCompleteJobs.delete(id);
            refreshPageAfterCompletedJob(job);
          } else if (status === 'failed') {
            refreshOnCompleteJobs.delete(id);
          }
        }
      });
      if (!activeJobId || !jobs.some(job => job.job_id === activeJobId)) {
        const live = jobs.find(job => job.status === 'running' || job.status === 'pending');
        const next = live || jobs[0];
        if (next) {
          activeJobId = next.job_id;
          window.localStorage.setItem('isala-active-job', activeJobId);
          updateUrlJob(activeJobId);
        }
      }
      renderJobOptions();
      renderWorker(state.worker || {});
      renderCurrentJob();
      if (state.active_model && elements.activeModel) {
        elements.activeModel.innerHTML = `<span class="dot ok"></span>${escapeHtml(state.active_model.model_id || 'Actief model')}`;
      }
      await loadLog(false);
    } catch (error) {
      elements.workerDot.classList.remove('ok');
      elements.workerDot.classList.add('bad-dot');
      elements.workerLabel.textContent = 'Status niet bereikbaar';
    } finally {
      polling = false;
      const hasLiveJobs = jobs.some(job => job.status === 'running' || job.status === 'pending');
      schedulePoll(document.hidden ? 30000 : (hasLiveJobs ? 2000 : 10000));
    }
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[char]));
  }

  async function submitJob(form) {
    const button = form.querySelector('button[type="submit"], button:not([type])');
    const original = button ? button.textContent : '';
    if (button) {
      button.disabled = true;
      button.textContent = button.dataset.busyText || 'Starten…';
    }
    // Keep the activity dock compact while jobs are submitted. The user can
    // explicitly expand the terminal when detailed output is needed.
    elements.title.textContent = 'Taak aanmaken…';
    elements.subtitle.textContent = 'De opdracht wordt naar de lokale worker gestuurd.';
    elements.status.textContent = 'Bezig';
    const now = new Date().toLocaleTimeString('nl-NL', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
    elements.terminal.textContent = `[${now}] Taak wordt aangemaakt…\nDe opdracht wordt naar de lokale PowerShell-worker gestuurd.`;
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      jobs = [payload, ...jobs.filter(job => job.job_id !== payload.job_id)];
      observedJobStatuses.set(String(payload.job_id || ''), String(payload.status || 'pending'));
      // Default for worker-backed forms: refresh after successful completion.
      // A future long-running/background-only form can opt out with
      // data-refresh-on-complete="0".
      if (form.dataset.refreshOnComplete !== '0' && payload.job_id) {
        refreshOnCompleteJobs.add(String(payload.job_id));
      }
      // Source-specific detector reruns stay in the background, but must never
      // disappear behind a previously hidden review task bar. The compact dock
      // remains collapsed; it now shows this task and exposes the full queue.
      if (form.dataset.trackInQueue === 'true') {
        dock.classList.remove('force-hidden');
        document.body.classList.remove('review-activity-hidden');
        window.localStorage.setItem('isala-detection-review:activity', '0');
      }
      window.dispatchEvent(new CustomEvent('isala:job-created', {detail: payload}));
      renderJobOptions();
      setActiveJob(payload.job_id, false);
      await pollStatus();
    } catch (error) {
      elements.status.textContent = 'Mislukt';
      elements.status.className = 'activity-status failed';
      elements.terminal.textContent = `Taak kon niet worden gestart.\n${error}`;
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
  }

  document.querySelectorAll('form[action="/jobs"]').forEach(form => {
    form.addEventListener('submit', event => {
      event.preventDefault();
      submitJob(form);
    });
  });

  elements.toggle.addEventListener('click', () => setExpanded(dock.classList.contains('collapsed')));
  elements.copyAll?.addEventListener('click', copyAllTerminalOutput);
  elements.select.addEventListener('change', () => setActiveJob(elements.select.value, false));
  elements.logTabs.forEach(tab => tab.addEventListener('click', () => setLogStream(tab.dataset.activityLogStream || 'stdout')));
  elements.followLive?.addEventListener('click', followLiveOutput);
  elements.terminal.addEventListener('scroll', () => {
    const state = logState();
    state.scrollTop = elements.terminal.scrollTop;
    const atBottom = terminalAtBottom();
    if (atBottom !== state.autoFollow) {
      state.autoFollow = atBottom;
      renderFollowState();
    }
  }, {passive: true});
  elements.terminal.addEventListener('wheel', event => {
    const state = logState();
    if (event.deltaY < 0 && state.autoFollow) {
      state.autoFollow = false;
      renderFollowState();
    }
  }, {passive: true});

  renderLogTabs();
  const initiallyExpanded = window.localStorage.getItem('isala-activity-terminal-expanded-v2') === '1';
  setExpanded(initiallyExpanded);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      pollStatus();
    }
  });
  window.addEventListener('focus', () => {
    if (!document.hidden) pollStatus();
  });

  pollStatus();
})();
