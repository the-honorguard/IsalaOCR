(() => {
  const root = document.getElementById('preparation-overview');
  if (!root) return;

  const ONE_CLICK_PREPARATION = Object.freeze({
    actionId: '1',
    title: 'Alles voorbereiden',
    detail: 'Downloadt, bouwt/installeert en controleert alle benodigde runtime- en modelcomponenten in één taak.',
  });

  const summary = root.querySelector('[data-prep-summary]');
  const counts = root.querySelector('[data-prep-counts]');
  const checkedAt = root.querySelector('[data-prep-checked-at]');
  const warning = root.querySelector('[data-prep-warning]');
  const hero = root.querySelector('.preparation-readiness-hero');
  const mainStatus = root.querySelector('[data-prep-main-status]');
  const mainIcon = root.querySelector('[data-prep-main-icon]');
  const mainMessage = root.querySelector('[data-prep-main-message]');
  const readyAction = root.querySelector('[data-prep-ready-action]');
  const repairAction = root.querySelector('[data-prep-repair-action]');
  const repairActionId = root.querySelector('[data-prep-repair-action-id]');
  const repairTitle = root.querySelector('[data-prep-repair-title]');
  const repairDetail = root.querySelector('[data-prep-repair-detail]');
  let polling = false;
  let autoRefreshAttempted = false;

  // Stap 1 is een normale workflowstap, geen onderhoudsconsole. De losse
  // download/install/check-acties blijven backend/CLI-hulpmiddelen maar worden
  // niet als alternatieve knoppen in de normale WebUI aangeboden.
  root.querySelector('.preparation-maintenance')?.remove();

  function enforceOneClickAction() {
    if (repairActionId) repairActionId.value = ONE_CLICK_PREPARATION.actionId;
    if (repairTitle) repairTitle.textContent = ONE_CLICK_PREPARATION.title;
    if (repairDetail) repairDetail.textContent = ONE_CLICK_PREPARATION.detail;
  }

  function phaseLabel(phase, kind) {
    if (phase.state === 'ready') return kind === 'download' ? 'Aanwezig' : 'Gevalideerd';
    if (phase.state === 'missing') return 'Ontbreekt';
    return kind === 'download' ? 'Onbekend' : 'Niet gecontroleerd';
  }

  function renderPhase(cell, phase, kind) {
    if (!cell || !phase) return;
    const icon = cell.querySelector('.prep-check');
    const label = cell.querySelector('strong');
    const detail = cell.querySelector('p');
    if (icon) {
      icon.className = `prep-check ${phase.state || 'unknown'}`;
      icon.textContent = phase.state === 'ready' ? '✓' : phase.state === 'missing' ? '×' : '?';
    }
    if (label) label.textContent = phaseLabel(phase, kind);
    if (detail) detail.textContent = phase.detail || '';
  }

  function render(prep) {
    const total = Number(prep.component_count || 0);
    const ready = Number(prep.ready_count || 0);
    const allReady = Boolean(prep.all_ready);

    if (hero) {
      hero.classList.toggle('ready', allReady);
      hero.classList.toggle('incomplete', !allReady);
    }
    if (mainStatus) mainStatus.textContent = allReady ? 'GEREED' : 'NIET GEREED';
    if (mainIcon) mainIcon.textContent = allReady ? '✓' : '!';
    if (mainMessage) {
      mainMessage.textContent = allReady
        ? 'Alle benodigde modellen, runtimes en trainingsimages zijn lokaal voorbereid en gevalideerd. Je hoeft hier niets meer te installeren.'
        : 'De voorbereiding is nog niet compleet. Klik één keer op Alles voorbereiden; deze taak handelt downloads, builds/installaties en validaties zelf af.';
    }
    if (readyAction) readyAction.hidden = !allReady;
    if (repairAction) repairAction.hidden = allReady;
    enforceOneClickAction();

    if (summary) {
      summary.classList.toggle('ready', allReady);
      summary.classList.toggle('incomplete', !allReady);
      summary.textContent = allReady ? '✓ GEREED' : `${ready}/${total} GEREED`;
    }
    if (counts) {
      counts.textContent = `Modellen ${prep.download_ready_count || 0}/${total} · Runtime ${prep.install_ready_count || 0}/${total}`;
    }
    if (checkedAt) {
      const suffix = prep.status_stale ? ' · status wordt vernieuwd' : '';
      checkedAt.textContent = prep.status_checked_at ? `Laatst gecontroleerd: ${prep.status_checked_at}${suffix}` : `Nog niet gecontroleerd${suffix}`;
    }

    const unknown = Number(prep.unknown_count || 0);
    if (warning) {
      warning.hidden = unknown === 0;
      warning.textContent = `${unknown} controle(s) zijn niet actueel. Dit wordt automatisch geïnventariseerd; de knop Alles voorbereiden blijft de enige handmatige voorbereidingstaak.`;
    }

    for (const item of (prep.components || [])) {
      const row = root.querySelector(`[data-prep-component="${CSS.escape(String(item.key || ''))}"]`);
      if (!row) continue;
      row.classList.toggle('ready', Boolean(item.ready));
      row.classList.toggle('missing', !item.ready);
      renderPhase(row.querySelector('[data-prep-phase="download"]'), item.download, 'download');
      renderPhase(row.querySelector('[data-prep-phase="install"]'), item.install, 'install');
    }
  }

  async function enqueueInventoryIfNeeded(prep) {
    if (!prep.status_stale) {
      autoRefreshAttempted = false;
      return;
    }
    if (autoRefreshAttempted) return;
    autoRefreshAttempted = true;
    try {
      const response = await fetch('/api/v2/jobs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action_id: '19'}),
      });
      if (!response.ok && response.status !== 409) throw new Error(`HTTP ${response.status}`);
    } catch (_) {
      window.setTimeout(() => { autoRefreshAttempted = false; }, 10000);
    }
  }

  async function refresh() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(`/api/v2/preparation?_=${Date.now()}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const prep = payload.preparation || {};
      render(prep);
      await enqueueInventoryIfNeeded(prep);
    } catch (_) {
      // Keep the last known status instead of replacing it with a false state.
      enforceOneClickAction();
    } finally {
      polling = false;
    }
  }

  window.addEventListener('isala:job-status', event => {
    const job = event.detail || {};
    const action = String(job.action_id || '');
    if (action === '19' && String(job.status || '') === 'failed') {
      autoRefreshAttempted = false;
    }
    if (['1','14','19','30','35','42'].includes(action)) {
      window.setTimeout(refresh, 150);
    }
  });

  enforceOneClickAction();
  refresh();
  window.setInterval(refresh, document.hidden ? 30000 : 10000);
})();
