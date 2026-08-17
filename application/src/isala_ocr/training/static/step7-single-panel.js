(() => {
  if (window.location.pathname !== '/process/table-compare') return;

  const stage = document.querySelector('.step7-review-stage');
  const panelList = stage?.querySelector('.comparison-panel-list');
  const filter = document.getElementById('comparison-issue-filter');
  const focusButton = document.getElementById('step7-review-focus-toggle');
  if (!stage || !panelList || !filter || !focusButton) return;

  const panels = Array.from(panelList.querySelectorAll(':scope > .comparison-panel-card'));
  if (!panels.length) return;

  panels.forEach((panel, index) => {
    panel.dataset.step7PanelIndex = String(index);
  });

  const toolbar = stage.querySelector(':scope > .toolbar');
  const toolbarLead = toolbar?.querySelector(':scope > div:first-child');
  const controls = toolbar?.querySelector('.step7-review-view-actions');

  const context = document.createElement('div');
  context.className = 'step7-single-panel-context';
  context.innerHTML = '<strong></strong><small></small>';
  toolbarLead?.appendChild(context);

  const nav = document.createElement('div');
  nav.className = 'step7-single-panel-nav';

  const previousButton = document.createElement('button');
  previousButton.type = 'button';
  previousButton.className = 'ghost';
  previousButton.title = 'Vorige bron/panel (← of K)';
  previousButton.textContent = '← Vorige';

  const panelPosition = document.createElement('span');
  panelPosition.className = 'pill step7-single-panel-position';

  const nextButton = document.createElement('button');
  nextButton.type = 'button';
  nextButton.className = 'ghost';
  nextButton.title = 'Volgende bron/panel (→ of J)';
  nextButton.textContent = 'Volgende →';

  nav.append(previousButton, panelPosition, nextButton);
  controls?.insertBefore(nav, controls.firstChild);

  const panelTitle = panel => String(panel.querySelector('.comparison-panel-head strong')?.textContent || 'Panel').trim();
  const panelMeta = panel => String(panel.querySelector('.comparison-panel-head small')?.textContent || '').trim();
  const rowsForPanel = panel => Array.from(panel.querySelectorAll('.comparison-issue-row'));
  const rowVisibleForCurrentFilter = row => (
    row.dataset.optimisticHidden !== '1'
    && !row.classList.contains('is-filtered')
    && row.style.display !== 'none'
  );
  const visibleRowsForPanel = panel => rowsForPanel(panel).filter(rowVisibleForCurrentFilter);
  const openRowsForPanel = panel => rowsForPanel(panel).filter(row => row.dataset.issueOpen === '1');

  const panelEligible = panel => {
    if (filter.value === 'open') return openRowsForPanel(panel).some(rowVisibleForCurrentFilter);
    return visibleRowsForPanel(panel).length > 0;
  };

  let activeIndex = 0;
  let switching = false;

  const eligibleIndexes = () => panels
    .map((panel, index) => ({ panel, index }))
    .filter(item => panelEligible(item.panel))
    .map(item => item.index);

  const nearestEligibleIndex = (preferred, direction = 1) => {
    const eligible = eligibleIndexes();
    if (!eligible.length) return -1;
    if (eligible.includes(preferred)) return preferred;

    const sorted = direction >= 0 ? eligible : [...eligible].reverse();
    const candidate = sorted.find(index => direction >= 0 ? index > preferred : index < preferred);
    return candidate ?? (direction >= 0 ? eligible[0] : eligible[eligible.length - 1]);
  };

  const ensureEmptyState = panel => {
    let empty = panel.querySelector('.step7-single-panel-empty');
    const hasVisible = visibleRowsForPanel(panel).length > 0;
    if (hasVisible) {
      empty?.remove();
      return;
    }
    if (!empty) {
      empty = document.createElement('div');
      empty.className = 'step7-single-panel-empty';
      empty.innerHTML = '<strong>Geen afwijkingen meer in dit panel.</strong><span>Ga naar het volgende panel of sluit de reviewmodus.</span>';
      panel.querySelector('.comparison-issue-list')?.appendChild(empty);
    }
  };

  const updateContext = () => {
    const panel = panels[activeIndex];
    if (!panel) return;
    context.querySelector('strong').textContent = panelTitle(panel);
    context.querySelector('small').textContent = panelMeta(panel);

    const eligible = eligibleIndexes();
    const logicalPosition = eligible.indexOf(activeIndex);
    panelPosition.textContent = logicalPosition >= 0
      ? `${logicalPosition + 1} / ${eligible.length}`
      : `${Math.min(activeIndex + 1, panels.length)} / ${panels.length}`;

    const open = openRowsForPanel(panel).length;
    const total = rowsForPanel(panel).length;
    const reviewed = Math.max(0, total - open);
    const badge = panel.querySelector('.comparison-panel-head > .pill');
    if (badge) badge.textContent = `${open} open · ${reviewed} beoordeeld`;

    previousButton.disabled = eligible.length <= 1;
    nextButton.disabled = eligible.length <= 1;
    ensureEmptyState(panel);
  };

  const showPanel = (index, { scrollIssues = true } = {}) => {
    if (!Number.isInteger(index) || index < 0 || index >= panels.length) return;
    switching = true;
    activeIndex = index;
    panels.forEach((panel, panelIndex) => {
      panel.classList.toggle('step7-single-panel-active', panelIndex === activeIndex);
      panel.setAttribute('aria-hidden', panelIndex === activeIndex ? 'false' : 'true');
    });
    updateContext();
    if (scrollIssues) {
      window.requestAnimationFrame(() => {
        panels[activeIndex]?.querySelector('.comparison-issue-list')?.scrollTo({ top: 0 });
      });
    }
    window.requestAnimationFrame(() => { switching = false; });
  };

  const movePanel = direction => {
    const eligible = eligibleIndexes();
    if (!eligible.length) {
      showPanel(activeIndex, { scrollIssues: false });
      return;
    }
    let position = eligible.indexOf(activeIndex);
    if (position < 0) {
      showPanel(direction >= 0 ? eligible[0] : eligible[eligible.length - 1]);
      return;
    }
    position = (position + direction + eligible.length) % eligible.length;
    showPanel(eligible[position]);
  };

  const syncForFilterOrReview = ({ autoAdvance = false } = {}) => {
    if (!document.body.classList.contains('step7-review-focus-mode')) return;
    const current = panels[activeIndex];
    if (!current) return;

    const currentEligible = panelEligible(current);
    if (!currentEligible) {
      const next = nearestEligibleIndex(activeIndex, 1);
      if (next >= 0 && (autoAdvance || next !== activeIndex)) {
        showPanel(next);
        return;
      }
    }
    showPanel(activeIndex, { scrollIssues: false });
  };

  const enterSinglePanelMode = () => {
    document.body.classList.add('step7-single-panel-mode');
    document.documentElement.classList.add('step7-single-panel-mode');
    const first = nearestEligibleIndex(activeIndex, 1);
    showPanel(first >= 0 ? first : activeIndex);
  };

  const leaveSinglePanelMode = () => {
    document.body.classList.remove('step7-single-panel-mode');
    document.documentElement.classList.remove('step7-single-panel-mode');
    panels.forEach(panel => {
      panel.classList.remove('step7-single-panel-active');
      panel.removeAttribute('aria-hidden');
    });
  };

  const focusObserver = new MutationObserver(() => {
    const enabled = document.body.classList.contains('step7-review-focus-mode');
    if (enabled && !document.body.classList.contains('step7-single-panel-mode')) enterSinglePanelMode();
    if (!enabled && document.body.classList.contains('step7-single-panel-mode')) leaveSinglePanelMode();
  });
  focusObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });

  previousButton.addEventListener('click', () => movePanel(-1));
  nextButton.addEventListener('click', () => movePanel(1));

  filter.addEventListener('change', () => {
    window.requestAnimationFrame(() => syncForFilterOrReview({ autoAdvance: true }));
  });

  const rowObserver = new MutationObserver(mutations => {
    if (switching || !document.body.classList.contains('step7-single-panel-mode')) return;
    const current = panels[activeIndex];
    const currentChanged = mutations.some(mutation => current?.contains(mutation.target));
    if (!currentChanged) return;
    window.requestAnimationFrame(() => syncForFilterOrReview({ autoAdvance: filter.value === 'open' }));
  });

  rowsForPanel({ querySelectorAll: selector => panelList.querySelectorAll(selector) }).forEach(row => {
    rowObserver.observe(row, {
      attributes: true,
      attributeFilter: ['data-issue-open', 'data-optimistic-hidden', 'class', 'style'],
    });
  });

  window.addEventListener('keydown', event => {
    if (!document.body.classList.contains('step7-single-panel-mode')) return;
    const target = event.target;
    const typing = target instanceof HTMLInputElement
      || target instanceof HTMLTextAreaElement
      || target instanceof HTMLSelectElement
      || target?.isContentEditable;
    if (typing || event.ctrlKey || event.metaKey || event.altKey) return;

    if (event.key === 'ArrowRight' || event.key === 'j' || event.key === 'J') {
      event.preventDefault();
      movePanel(1);
    } else if (event.key === 'ArrowLeft' || event.key === 'k' || event.key === 'K') {
      event.preventDefault();
      movePanel(-1);
    }
  });

  // If the legacy focus script already enabled fullscreen before this enhancer
  // loaded, promote it immediately to the single-panel studio.
  if (document.body.classList.contains('step7-review-focus-mode')) enterSinglePanelMode();
})();
