(() => {
  const root = document.getElementById('preparation-overview');
  if (!root) return;

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

  function repairPlan(prep) {
    const component = Array.isArray(prep.components) ? prep.components[0] : null;
    if (!component || !component.download) {
      return {
        actionId: '19',
        title: 'Status opnieuw controleren',
        detail: 'Bepaal opnieuw wat lokaal aanwezig is',
        message: 'De actuele table-pipeline status kon niet worden bepaald. Controleer de voorbereiding opnieuw.',
      };
    }
    if (component.download.state === 'unknown') {
      return {
        actionId: '19',
        title: 'Status opnieuw controleren',
        detail: 'Bepaal opnieuw wat lokaal aanwezig is',
        message: 'De modelcache is nog niet actueel gecontroleerd. Vernieuw eerst de status.',
      };
    }
    if (component.download.state === 'missing') {
      return {
        actionId: String(component.download_action_id || '30'),
        title: 'Table modellen downloaden',
        detail: 'Vul de lokale PP-Structure/OCR modelcache',
        message: 'De lokale table/cell-modelcache ontbreekt nog. Download eerst de benodigde PP-Structure/OCR-modellen.',
      };
    }
    if (!component.install || component.install.state === 'unknown') {
      return {
        actionId: String(component.check_action_id || '42'),
        title: 'Table pipeline controleren',
        detail: 'Voer de offline runtime-validatie uit',
        message: 'De bestanden zijn aanwezig, maar de offline runtimecheck ontbreekt nog of is verouderd.',
      };
    }
    if (component.install.state === 'missing') {
      return {
        actionId: String(component.install_action_id || '35'),
        title: 'Inference runtime installeren',
        detail: 'Bouw de PP-OCRv6 + PP-Structure runtime',
        message: 'De modellen zijn aanwezig, maar de inference-runtime is nog niet geïnstalleerd of gevalideerd.',
      };
    }
    return {
      actionId: String(component.full_action_id || '14'),
      title: 'Table pipeline voorbereiden',
      detail: 'Download, installeer en controleer de table-pipeline',
      message: 'De voorbereiding is nog niet volledig afgerond.',
    };
  }

  function render(prep) {
    const total = Number(prep.component_count || 0);
    const ready = Number(prep.ready_count || 0);
    const allReady = Boolean(prep.all_ready);
    const plan = repairPlan(prep);

    if (hero) {
      hero.classList.toggle('ready', allReady);
      hero.classList.toggle('incomplete', !allReady);
    }
    if (mainStatus) mainStatus.textContent = allReady ? 'GEREED' : 'NIET GEREED';
    if (mainIcon) mainIcon.textContent = allReady ? '✓' : '!';
    if (mainMessage) {
      mainMessage.textContent = allReady
        ? 'PP-StructureV3, de OCR-runtime en alle benodigde table/cell-modellen zijn lokaal aanwezig en offline gevalideerd. Je hoeft hier niets meer te installeren.'
        : plan.message;
    }
    if (readyAction) readyAction.hidden = !allReady;
    if (repairAction) repairAction.hidden = allReady;
    if (repairActionId) repairActionId.value = plan.actionId;
    if (repairTitle) repairTitle.textContent = plan.title;
    if (repairDetail) repairDetail.textContent = plan.detail;

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
      warning.textContent = `${unknown} controle(s) zijn niet actueel. Vernieuw de status voordat je verdergaat.`;
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

  refresh();
  window.setInterval(refresh, document.hidden ? 30000 : 10000);
})();
