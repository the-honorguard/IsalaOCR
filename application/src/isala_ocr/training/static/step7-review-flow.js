(() => {
  const isStep7 = window.location.pathname === '/process/table-compare';
  const isGtPage = window.location.pathname === '/detection-review' || window.location.pathname.startsWith('/detection-review/');
  if (!isStep7 && !isGtPage) return;

  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));

  const parseCount = element => {
    const value = Number.parseInt(String(element?.textContent || '').trim(), 10);
    return Number.isFinite(value) ? value : 0;
  };

  const setCount = (element, value) => {
    if (!element) return;
    element.textContent = String(Math.max(0, value));
  };

  const sourceHrefForRow = row => {
    const link = row?.querySelector('a[href^="/detection-review/"]')
      || row?.closest('.comparison-panel-card')?.querySelector('a[href^="/detection-review/"]');
    return link?.getAttribute('href') || '';
  };

  if (isStep7) {
    const status = document.getElementById('comparison-inline-status');
    const openCount = document.getElementById('comparison-open-count');
    const reviewedCount = document.getElementById('comparison-reviewed-count');
    const issueCount = document.getElementById('comparison-issue-count');

    const stabilityStyle = document.createElement('style');
    stabilityStyle.textContent = `
      .comparison-panel-list,.comparison-issue-list{overflow-anchor:none}
      #comparison-inline-status{position:fixed;right:20px;bottom:84px;z-index:1200;max-width:min(520px,calc(100vw - 40px));margin:0;box-shadow:0 12px 36px rgba(0,0,0,.35)}
      #comparison-inline-status:empty{display:none}
    `;
    document.head.appendChild(stabilityStyle);

    const setStatus = (message, ok = true) => {
      if (!status) return;
      status.textContent = message || '';
      status.classList.toggle('ok', Boolean(message) && ok);
      status.classList.toggle('bad', Boolean(message) && !ok);
      if (message && ok) {
        window.setTimeout(() => {
          if (status.textContent === message) status.textContent = '';
        }, 1800);
      }
    };

    const syncPanelVisibility = panel => {
      if (!panel) return;
      const rows = Array.from(panel.querySelectorAll('.comparison-issue-row'));
      const hasVisible = rows.some(row => row.dataset.optimisticHidden !== '1' && !row.classList.contains('is-filtered'));
      panel.style.display = hasVisible ? '' : 'none';
    };

    const syncAllPanelVisibility = () => {
      document.querySelectorAll('.comparison-panel-card').forEach(syncPanelVisibility);
    };

    const visibleReviewRows = () => Array.from(document.querySelectorAll('.comparison-issue-row')).filter(row => (
      row.dataset.optimisticHidden !== '1'
      && !row.classList.contains('is-filtered')
      && row.style.display !== 'none'
    ));

    const captureViewportAnchor = row => {
      const rows = visibleReviewRows();
      const index = rows.indexOf(row);
      let anchor = index >= 0 ? (rows[index + 1] || rows[index - 1]) : null;
      if (!anchor) {
        const panel = row.closest('.comparison-panel-card');
        anchor = panel?.nextElementSibling || panel?.previousElementSibling || document.querySelector('.comparison-panel-list');
      }
      return {
        anchor,
        anchorTop: anchor?.getBoundingClientRect().top ?? 0,
        windowY: window.scrollY,
      };
    };

    const restoreViewportAnchor = snapshot => {
      window.requestAnimationFrame(() => {
        const anchor = snapshot?.anchor;
        if (!anchor || !anchor.isConnected || anchor.style?.display === 'none' || anchor.classList?.contains('is-filtered')) {
          window.scrollTo(0, snapshot?.windowY || 0);
          return;
        }

        const scrollBox = anchor.closest?.('.comparison-issue-list');
        let delta = anchor.getBoundingClientRect().top - snapshot.anchorTop;
        if (scrollBox && Math.abs(delta) > 0.5) {
          const maxScroll = Math.max(0, scrollBox.scrollHeight - scrollBox.clientHeight);
          scrollBox.scrollTop = Math.max(0, Math.min(maxScroll, scrollBox.scrollTop + delta));
        }

        delta = anchor.getBoundingClientRect().top - snapshot.anchorTop;
        if (Math.abs(delta) > 0.5) window.scrollBy(0, delta);
      });
    };

    const applyServerCounts = payload => {
      const counts = payload?.counts || {};
      if (Number.isFinite(Number(counts.open_issue_count))) {
        const value = Number(counts.open_issue_count);
        setCount(openCount, value);
        openCount?.classList.toggle('ok', value === 0);
        openCount?.classList.toggle('warn', value !== 0);
      }
      if (Number.isFinite(Number(counts.reviewed_issue_count))) setCount(reviewedCount, Number(counts.reviewed_issue_count));
      if (Number.isFinite(Number(counts.issue_count))) setCount(issueCount, Number(counts.issue_count));
    };

    const hideOptimistically = (row, decision) => {
      row.dataset.optimisticHidden = '1';
      row.dataset.issueOpen = decision === 'clear' || decision === 'deferred' ? '1' : '0';
      row.dataset.issueDecision = decision === 'clear' ? '' : decision;
      row.style.display = decision === 'clear' || decision === 'deferred' ? '' : 'none';
      if (decision !== 'clear' && decision !== 'deferred') {
        setCount(openCount, parseCount(openCount) - 1);
        setCount(reviewedCount, parseCount(reviewedCount) + 1);
        openCount?.classList.toggle('ok', parseCount(openCount) === 0);
        openCount?.classList.toggle('warn', parseCount(openCount) !== 0);
      }
      syncPanelVisibility(row.closest('.comparison-panel-card'));
    };

    const restoreOptimisticState = (row, snapshot) => {
      row.dataset.issueOpen = snapshot.issueOpen;
      row.dataset.issueDecision = snapshot.issueDecision;
      delete row.dataset.optimisticHidden;
      row.style.display = snapshot.display;
      if (openCount) openCount.textContent = snapshot.openCount;
      if (reviewedCount) reviewedCount.textContent = snapshot.reviewedCount;
      if (issueCount) issueCount.textContent = snapshot.issueCount;
      if (openCount) {
        const value = parseCount(openCount);
        openCount.classList.toggle('ok', value === 0);
        openCount.classList.toggle('warn', value !== 0);
      }
      const panel = row.closest('.comparison-panel-card');
      if (panel) panel.style.display = snapshot.panelDisplay;
    };

    // Capture phase intentionally runs before the older per-form AJAX handler in
    // table_model_comparison.html. This gives immediate optimistic removal while
    // still rolling back cleanly if persistence fails.
    document.addEventListener('submit', async event => {
      const form = event.target instanceof HTMLFormElement ? event.target : null;
      if (!form?.classList.contains('comparison-issue-form')) return;
      event.preventDefault();
      event.stopImmediatePropagation();

      const row = form.closest('.comparison-issue-row');
      if (!row || form.dataset.optimisticBusy === '1') return;
      const data = new FormData(form);
      const action = String(data.get('comparison_action') || '');
      let requestedDecision = String(data.get('decision') || '');
      if (action === 'add_prediction_to_gt') requestedDecision = 'gt_added';
      const closesItem = ['model_error', 'functional_ok', 'gt_check', 'gt_added'].includes(requestedDecision);
      const optimisticDecision = requestedDecision || 'deferred';
      const button = form.querySelector('button');
      const originalButtonText = button?.textContent || '';
      const panel = row.closest('.comparison-panel-card');
      const viewportSnapshot = captureViewportAnchor(row);
      const snapshot = {
        issueOpen: String(row.dataset.issueOpen || '1'),
        issueDecision: String(row.dataset.issueDecision || ''),
        display: row.style.display,
        panelDisplay: panel?.style.display || '',
        openCount: openCount?.textContent || '0',
        reviewedCount: reviewedCount?.textContent || '0',
        issueCount: issueCount?.textContent || '0',
      };

      form.dataset.optimisticBusy = '1';
      if (button) {
        button.disabled = true;
        button.textContent = requestedDecision === 'gt_check' ? 'GT openen…' : 'Opslaan…';
      }
      setStatus('');

      if (closesItem) {
        hideOptimistically(row, optimisticDecision);
        restoreViewportAnchor(viewportSnapshot);
      }

      try {
        const response = await fetch(form.action || window.location.href, {
          method: 'POST',
          body: data,
          headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
          cache: 'no-store',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);

        const savedDecision = String(payload.decision || requestedDecision || '');
        row.dataset.issueDecision = savedDecision;
        row.dataset.issueOpen = savedDecision === '' || savedDecision === 'deferred' || savedDecision === 'clear' ? '1' : '0';
        applyServerCounts(payload);

        if (savedDecision === 'gt_check') {
          const href = sourceHrefForRow(row);
          if (href) {
            const separator = href.includes('?') ? '&' : '?';
            window.location.assign(`${href}${separator}from_step7=1&issue_id=${encodeURIComponent(row.dataset.issueId || '')}`);
            return;
          }
        }

        if (!closesItem) {
          delete row.dataset.optimisticHidden;
          row.style.display = '';
        }
        syncAllPanelVisibility();
        restoreViewportAnchor(viewportSnapshot);
        setStatus(payload.message || 'Vervolg-review opgeslagen.', true);
      } catch (error) {
        restoreOptimisticState(row, snapshot);
        restoreViewportAnchor(viewportSnapshot);
        setStatus(`Opslaan mislukt: ${error instanceof Error ? error.message : error}`, false);
      } finally {
        delete form.dataset.optimisticBusy;
        if (button?.isConnected) {
          button.disabled = false;
          button.textContent = originalButtonText;
        }
      }
    }, true);
  }

  if (isGtPage) {
    const loadGtChecks = async () => {
      try {
        const response = await fetch(`/process/table-compare?_gt_checks=${Date.now()}`, {cache: 'no-store'});
        if (!response.ok) return [];
        const html = await response.text();
        const doc = new DOMParser().parseFromString(html, 'text/html');
        return Array.from(doc.querySelectorAll('.comparison-issue-row[data-issue-decision="gt_check"]')).map(row => {
          const href = sourceHrefForRow(row);
          let sourceId = '';
          if (href) {
            const path = new URL(href, window.location.origin).pathname;
            sourceId = decodeURIComponent(path.slice('/detection-review/'.length));
          }
          return {
            sourceId,
            issueId: String(row.dataset.issueId || ''),
            type: String(row.dataset.issueType || ''),
            label: String(row.querySelector('.comparison-issue-copy strong')?.textContent || 'GT controleren').trim(),
            meta: String(row.querySelector('.comparison-issue-copy small')?.textContent || '').trim(),
          };
        }).filter(item => item.sourceId);
      } catch (_) {
        return [];
      }
    };

    const renderIndexMarkers = checks => {
      if (window.location.pathname !== '/detection-review' || !checks.length) return;
      const bySource = new Map();
      checks.forEach(item => {
        if (!bySource.has(item.sourceId)) bySource.set(item.sourceId, []);
        bySource.get(item.sourceId).push(item);
      });

      const firstCard = document.querySelector('.content .card');
      if (firstCard && !document.getElementById('step7-gt-check-summary')) {
        const summary = document.createElement('section');
        summary.id = 'step7-gt-check-summary';
        summary.className = 'notice warning';
        summary.innerHTML = `<strong>${checks.length} GT-controle${checks.length === 1 ? '' : 's'} uit Stap 7.</strong> `
          + `${bySource.size} bron${bySource.size === 1 ? '' : 'nen'} bevatten punten die je expliciet als “GT controleren” hebt gemarkeerd.`;
        firstCard.parentNode?.insertBefore(summary, firstCard);
      }

      document.querySelectorAll('[data-gt-source-id]').forEach(row => {
        const sourceId = String(row.dataset.gtSourceId || '');
        const items = bySource.get(sourceId) || [];
        if (!items.length) return;
        row.classList.add('step7-gt-check-source');
        const cells = row.querySelectorAll('td');
        if (cells.length >= 3 && !cells[2].querySelector('.step7-gt-check-pill')) {
          const pill = document.createElement('span');
          pill.className = 'pill warn step7-gt-check-pill';
          pill.style.marginLeft = '8px';
          pill.textContent = `GT controleren: ${items.length}`;
          cells[2].appendChild(pill);
        }
        const link = row.querySelector('a[href^="/detection-review/"]');
        if (link) {
          link.textContent = `GT openen · ${items.length} gemarkeerd`;
          link.classList.remove('primary');
        }
      });
    };

    const renderStudioMarkers = checks => {
      if (!window.location.pathname.startsWith('/detection-review/')) return;
      const sourceId = decodeURIComponent(window.location.pathname.slice('/detection-review/'.length));
      const items = checks.filter(item => item.sourceId === sourceId);
      if (!items.length) return;

      const toolbar = document.querySelector('.review-studio-toolbar');
      if (toolbar && !document.getElementById('step7-gt-check-worklist')) {
        const panel = document.createElement('section');
        panel.id = 'step7-gt-check-worklist';
        panel.className = 'notice warning step7-gt-check-worklist';
        panel.innerHTML = `
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap">
            <div><strong>${items.length} punt${items.length === 1 ? '' : 'en'} gemarkeerd als GT controleren</strong><div class="muted">Deze komen uit de actuele Stap-7-review voor deze bron.</div></div>
            <a class="button ghost" href="/process/table-compare">Terug naar Stap 7</a>
          </div>
          <div style="display:grid;gap:6px;margin-top:10px">
            ${items.map(item => `<div style="border-top:1px solid var(--line);padding-top:7px"><strong>${escapeHtml(item.label)}</strong> <span class="pill warn">${escapeHtml(item.type || 'gt_check')}</span><div class="muted" style="font-size:12px">${escapeHtml(item.meta)}</div><div class="mono muted" style="font-size:11px">${escapeHtml(item.issueId)}</div></div>`).join('')}
          </div>`;
        toolbar.parentNode?.insertBefore(panel, toolbar);
      }

      const options = document.querySelectorAll('#source-switch option');
      const counts = new Map();
      checks.forEach(item => counts.set(item.sourceId, (counts.get(item.sourceId) || 0) + 1));
      options.forEach(option => {
        const count = counts.get(String(option.value || '')) || 0;
        if (count && !option.dataset.gtCheckDecorated) {
          option.textContent = `⚑ ${option.textContent} · ${count} GT-check`;
          option.dataset.gtCheckDecorated = '1';
        }
      });
    };

    loadGtChecks().then(checks => {
      renderIndexMarkers(checks);
      renderStudioMarkers(checks);
    });
  }
})();
