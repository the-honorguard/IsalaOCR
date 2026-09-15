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
    const filter = document.getElementById('comparison-issue-filter');

    const stabilityStyle = document.createElement('style');
    stabilityStyle.textContent = `
      .comparison-panel-list,.comparison-issue-list{overflow-anchor:none}
      #comparison-inline-status{position:fixed;right:20px;bottom:84px;z-index:12050;max-width:min(520px,calc(100vw - 40px));margin:0;box-shadow:0 12px 36px rgba(0,0,0,.35)}
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

    // A saved review only changes the issue list. Keep the document at exactly
    // the same scroll offset; moving it to follow an adjacent row made every
    // click feel like a navigation action.
    const restoreViewportAnchor = snapshot => {
      window.requestAnimationFrame(() => {
        if (document.body.classList.contains('step7-review-focus-mode')) return;
        const y = Number(snapshot?.windowY);
        if (Number.isFinite(y) && Math.abs(window.scrollY - y) > 0.5) {
          window.scrollTo({top: y, behavior: 'auto'});
        }
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

    const setStatusRetryable = (message, onRetry) => {
      if (!status) return;
      status.replaceChildren();
      status.classList.remove('ok');
      status.classList.add('bad');
      status.append(document.createTextNode(message));
      const retryButton = document.createElement('button');
      retryButton.type = 'button';
      retryButton.className = 'ghost';
      retryButton.textContent = 'Opnieuw';
      retryButton.style.marginLeft = '10px';
      retryButton.addEventListener('click', onRetry);
      status.append(retryButton);
    };

    // Build a viewport-filling review mode that mirrors the GT Studio focus mode:
    // same page, no navigation/reload, fixed review surface, compact floating
    // controls, image on the left and review queue on the right.
    const reviewSection = filter?.closest('section.card') || null;
    let fullscreenReturnScrollY = 0;
    if (reviewSection) {
      reviewSection.classList.add('step7-review-stage');
      const toolbar = reviewSection.querySelector(':scope > .toolbar');
      const controls = document.createElement('div');
      controls.className = 'step7-review-view-actions';

      const filterLabel = filter?.closest('.compare-filter');
      if (filterLabel) controls.appendChild(filterLabel);

      const liveCount = document.createElement('span');
      liveCount.className = 'pill step7-review-live-count';
      const refreshLiveCount = () => {
        liveCount.textContent = `${parseCount(openCount)} open · ${parseCount(reviewedCount)} beoordeeld`;
      };
      refreshLiveCount();
      controls.appendChild(liveCount);

      const fullscreenButton = document.createElement('button');
      fullscreenButton.type = 'button';
      fullscreenButton.id = 'step7-review-focus-toggle';
      fullscreenButton.className = 'primary';
      fullscreenButton.setAttribute('aria-pressed', 'false');
      fullscreenButton.title = 'Open/sluit viewport-vullende reviewmodus (F)';
      fullscreenButton.textContent = '⛶ Review fullscreen';
      controls.appendChild(fullscreenButton);
      toolbar?.appendChild(controls);

      const countObserver = new MutationObserver(refreshLiveCount);
      if (openCount) countObserver.observe(openCount, {childList: true, characterData: true, subtree: true});
      if (reviewedCount) countObserver.observe(reviewedCount, {childList: true, characterData: true, subtree: true});

      const setFullscreen = enabled => {
        const active = Boolean(enabled);
        if (active === document.body.classList.contains('step7-review-focus-mode')) return;
        if (active) fullscreenReturnScrollY = window.scrollY;
        document.body.classList.toggle('step7-review-focus-mode', active);
        fullscreenButton.setAttribute('aria-pressed', String(active));
        fullscreenButton.textContent = active ? '× Fullscreen sluiten' : '⛶ Review fullscreen';
        document.documentElement.classList.toggle('step7-review-focus-mode', active);
        if (!active) {
          window.requestAnimationFrame(() => window.scrollTo(0, fullscreenReturnScrollY));
        } else {
          window.requestAnimationFrame(() => {
            const firstVisible = visibleReviewRows()[0];
            firstVisible?.closest('.comparison-issue-list')?.scrollTo({top: 0});
          });
        }
      };

      fullscreenButton.addEventListener('click', () => {
        setFullscreen(!document.body.classList.contains('step7-review-focus-mode'));
      });

      window.addEventListener('keydown', event => {
        const target = event.target;
        const typing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target?.isContentEditable;
        if (typing || event.ctrlKey || event.metaKey || event.altKey) return;
        if ((event.key === 'f' || event.key === 'F') && !event.repeat) {
          event.preventDefault();
          setFullscreen(!document.body.classList.contains('step7-review-focus-mode'));
        } else if (event.key === 'Escape' && document.body.classList.contains('step7-review-focus-mode')) {
          event.preventDefault();
          setFullscreen(false);
        }
      });
    }

    // Runtime-only (not persisted): a queued task surviving a page reload has
    // no meaningful prior scroll position to restore anyway.
    const viewportSnapshots = new Map();

    const issueQueue = IsalaReviewQueue.createTaskQueue({
      storageKey: 'isala-step7-review:issue-queue-v1',
      concurrency: 3,
      execute: async task => {
        const row = document.querySelector(`.comparison-issue-row[data-issue-id="${CSS.escape(task.issueId)}"]`);
        const form = document.querySelector(`form.comparison-issue-form[data-pending-task-id="${task.id}"]`);
        const button = form?.querySelector('button') || null;
        const body = new FormData();
        Object.entries(task.fields).forEach(([key, value]) => body.append(key, value));
        const response = await fetch(task.formAction, {
          method: 'POST',
          body,
          headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
          cache: 'no-store',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);

        const savedDecision = String(payload.decision || task.requestedDecision || '');
        if (row) {
          row.dataset.issueDecision = savedDecision;
          row.dataset.issueOpen = savedDecision === '' || savedDecision === 'deferred' || savedDecision === 'clear' ? '1' : '0';
        }
        applyServerCounts(payload);

        if (savedDecision === 'gt_check') {
          const href = row ? sourceHrefForRow(row) : '';
          if (href) {
            const separator = href.includes('?') ? '&' : '?';
            window.location.assign(`${href}${separator}from_step7=1&issue_id=${encodeURIComponent(task.issueId || '')}`);
            return;
          }
        }

        // A promoted prediction is removed from the blue candidate layer. Reload
        // the current review image so the freshly persisted canonical GT is
        // painted by the normal purple GT overlay immediately.
        if (row && !task.closesItem) {
          delete row.dataset.optimisticHidden;
          row.style.display = '';
        }
        if (form) delete form.dataset.pendingTaskId;
        if (button?.isConnected) {
          button.disabled = false;
          button.textContent = task.originalButtonText;
        }
        syncAllPanelVisibility();
        restoreViewportAnchor(viewportSnapshots.get(task.id));
        viewportSnapshots.delete(task.id);
        setStatus(payload.message || 'Vervolg-review opgeslagen.', true);
      },
      onChange: () => {
        const failed = issueQueue.tasks().filter(t => t.failed).length;
        if (!failed) return;
        setStatusRetryable(
          `${failed} wijziging${failed === 1 ? '' : 'en'} niet opgeslagen na 3 pogingen.`,
          () => issueQueue.retryFailed(),
        );
      },
      onTaskError: (task, error) => {
        if (task.failed) return;
        setStatus(`Opslaan mislukt, wordt opnieuw geprobeerd (${task.attempt}/3): ${error.message || error}`, false);
      },
    });

    // Capture phase intentionally runs before the older per-form AJAX handler in
    // table_model_comparison.html. This gives immediate optimistic removal, then
    // queues the actual save: a transient failure retries automatically with
    // backoff instead of rolling back after the first hiccup (deliberate,
    // approved behavior change -- see refactor-phase2-remaining-plan.md, punt 1).
    document.addEventListener('submit', event => {
      const form = event.target instanceof HTMLFormElement ? event.target : null;
      if (!form?.classList.contains('comparison-issue-form')) return;
      event.preventDefault();
      event.stopImmediatePropagation();

      const row = form.closest('.comparison-issue-row');
      if (!row || form.dataset.pendingTaskId) return;
      const data = new FormData(form);
      const action = String(data.get('comparison_action') || '');
      let requestedDecision = String(data.get('decision') || '');
      if (action === 'add_prediction_to_gt') requestedDecision = 'gt_added';
      const closesItem = ['model_error', 'functional_ok', 'gt_check', 'gt_added'].includes(requestedDecision);
      const optimisticDecision = requestedDecision || 'deferred';
      const button = form.querySelector('button');
      const originalButtonText = button?.textContent || '';
      const issueId = row.dataset.issueId || '';
      const viewportSnapshot = captureViewportAnchor(row);

      if (button) {
        button.disabled = true;
        button.textContent = requestedDecision === 'gt_check' ? 'GT openen…' : 'Opslaan…';
      }
      setStatus('');

      if (closesItem) {
        hideOptimistically(row, optimisticDecision);
        restoreViewportAnchor(viewportSnapshot);
      }

      const task = issueQueue.enqueue(
        {
          issueId,
          formAction: form.action || window.location.href,
          fields: Object.fromEntries(data.entries()),
          requestedDecision,
          closesItem,
          originalButtonText,
        },
        (existing, incoming) => existing.issueId === incoming.issueId,
      );
      viewportSnapshots.set(task.id, viewportSnapshot);
      form.dataset.pendingTaskId = task.id;
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
