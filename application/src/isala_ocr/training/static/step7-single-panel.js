(() => {
  if (window.location.pathname !== '/process/table-compare') return;

  // Review clicks are intentionally optimistic, so a fast reviewer can submit
  // several decisions before the previous HTTP request has completed. Sending
  // those writes concurrently made the lightweight local Flask server/Docker
  // bind mount intermittently time out. Keep the UI instant, but serialize the
  // actual network writes and retry transient failures with backoff.
  const nativeFetch = window.fetch.bind(window);
  const reviewNetworkQueue = [];
  let reviewNetworkBusy = false;
  let reviewQueueSequence = 0;

  const emitQueueState = (state, detail = {}) => {
    window.dispatchEvent(new CustomEvent('isala:step7-review-queue', {
      detail: {
        state,
        waiting: reviewNetworkQueue.length + (reviewNetworkBusy ? 1 : 0),
        ...detail,
      },
    }));
  };

  const isReviewWrite = (input, init = {}) => {
    const method = String(init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (method !== 'POST') return false;
    let url;
    try {
      url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
    } catch (_) {
      return false;
    }
    if (url.pathname !== '/process/table-compare') return false;
    const body = init.body;
    return body instanceof FormData && (body.has('decision') || body.has('comparison_action'));
  };

  const retryableStatus = status => status === 408 || status === 425 || status === 429 || status >= 500;
  const wait = ms => new Promise(resolve => window.setTimeout(resolve, ms));

  const executeQueuedReviewWrite = async item => {
    const maxAttempts = 6;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 12000);
      try {
        emitQueueState(attempt > 1 ? 'retrying' : 'saving', {attempt, id: item.id});
        const response = await nativeFetch(item.input, {...item.init, signal: controller.signal});
        if (response.ok || !retryableStatus(response.status) || attempt === maxAttempts) return response;
      } catch (error) {
        if (attempt === maxAttempts) throw error;
      } finally {
        window.clearTimeout(timeout);
      }
      const delay = Math.min(8000, 600 * (2 ** (attempt - 1)));
      emitQueueState('retrying', {attempt, retryInMs: delay, id: item.id});
      await wait(delay);
    }
    throw new Error('Review write queue exhausted retries');
  };

  const drainReviewNetworkQueue = async () => {
    if (reviewNetworkBusy) return;
    reviewNetworkBusy = true;
    try {
      while (reviewNetworkQueue.length) {
        const item = reviewNetworkQueue.shift();
        try {
          const response = await executeQueuedReviewWrite(item);
          item.resolve(response);
        } catch (error) {
          item.reject(error);
        }
      }
    } finally {
      reviewNetworkBusy = false;
      emitQueueState('idle');
    }
  };

  window.fetch = (input, init = {}) => {
    if (!isReviewWrite(input, init)) return nativeFetch(input, init);
    return new Promise((resolve, reject) => {
      reviewNetworkQueue.push({
        id: ++reviewQueueSequence,
        input,
        init,
        resolve,
        reject,
      });
      emitQueueState('queued');
      void drainReviewNetworkQueue();
    });
  };

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

  const saveQueuePill = document.createElement('span');
  saveQueuePill.className = 'pill step7-review-save-queue';
  saveQueuePill.hidden = true;
  controls?.insertBefore(saveQueuePill, controls.firstChild);
  let queueIdleTimer = 0;
  window.addEventListener('isala:step7-review-queue', event => {
    const detail = event.detail || {};
    window.clearTimeout(queueIdleTimer);
    saveQueuePill.hidden = false;
    saveQueuePill.classList.toggle('warn', detail.state === 'retrying');
    saveQueuePill.classList.toggle('ok', detail.state === 'idle');
    if (detail.state === 'retrying') {
      saveQueuePill.textContent = `Netwerk traag · ${Math.max(1, Number(detail.waiting) || 1)} in wachtrij`;
    } else if (detail.state === 'idle') {
      saveQueuePill.textContent = '✓ reviews opgeslagen';
      queueIdleTimer = window.setTimeout(() => { saveQueuePill.hidden = true; }, 1400);
    } else {
      saveQueuePill.textContent = `${Math.max(1, Number(detail.waiting) || 1)} review${Number(detail.waiting) === 1 ? '' : 's'} opslaan…`;
    }
  });

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

  // In normal Step 7 the image itself is the sizing reference for the absolute
  // overlay boxes. Fullscreen previously made .comparison-image-stage fill the
  // complete left viewport while the image kept its own aspect ratio. The box
  // percentages were therefore calculated against a different rectangle than
  // the rendered image. Wrap image + overlays in one explicitly fitted canvas so
  // every GT/prediction/issue box uses exactly the same coordinate surface.
  const ensureImageCanvas = panel => {
    const imageStage = panel?.querySelector('.comparison-image-stage');
    if (!imageStage) return null;
    let canvas = imageStage.querySelector(':scope > .step7-single-panel-image-canvas');
    if (!canvas) {
      canvas = document.createElement('div');
      canvas.className = 'step7-single-panel-image-canvas';
      const children = Array.from(imageStage.childNodes);
      children.forEach(child => canvas.appendChild(child));
      imageStage.appendChild(canvas);
    }
    return {
      stage: imageStage,
      canvas,
      image: canvas.querySelector('img'),
    };
  };

  const unwrapImageCanvas = panel => {
    const imageStage = panel?.querySelector('.comparison-image-stage');
    const canvas = imageStage?.querySelector(':scope > .step7-single-panel-image-canvas');
    if (!imageStage || !canvas) return;
    while (canvas.firstChild) imageStage.insertBefore(canvas.firstChild, canvas);
    canvas.remove();
  };

  const stageAspectRatio = (imageStage, image) => {
    if (image?.naturalWidth > 0 && image?.naturalHeight > 0) {
      return image.naturalWidth / image.naturalHeight;
    }
    const raw = String(imageStage?.style.getPropertyValue('--aspect') || '').trim();
    const parts = raw.split('/').map(value => Number.parseFloat(value.trim()));
    if (parts.length === 2 && parts.every(value => Number.isFinite(value) && value > 0)) {
      return parts[0] / parts[1];
    }
    return 0;
  };

  const fitImageCanvas = panel => {
    if (!document.body.classList.contains('step7-single-panel-mode')) return;
    const prepared = ensureImageCanvas(panel);
    if (!prepared) return;
    const { stage: imageStage, canvas, image } = prepared;

    const apply = () => {
      if (!document.body.classList.contains('step7-single-panel-mode')) return;
      if (!panel.classList.contains('step7-single-panel-active')) return;
      const ratio = stageAspectRatio(imageStage, image);
      if (!(ratio > 0)) return;

      const style = window.getComputedStyle(imageStage);
      const horizontalPadding = (Number.parseFloat(style.paddingLeft) || 0) + (Number.parseFloat(style.paddingRight) || 0);
      const verticalPadding = (Number.parseFloat(style.paddingTop) || 0) + (Number.parseFloat(style.paddingBottom) || 0);
      const availableWidth = Math.max(1, imageStage.clientWidth - horizontalPadding);
      const availableHeight = Math.max(1, imageStage.clientHeight - verticalPadding);

      let width = availableWidth;
      let height = width / ratio;
      if (height > availableHeight) {
        height = availableHeight;
        width = height * ratio;
      }

      canvas.style.width = `${Math.max(1, Math.floor(width))}px`;
      canvas.style.height = `${Math.max(1, Math.floor(height))}px`;
    };

    if (image?.complete && image.naturalWidth > 0) {
      apply();
    } else if (image) {
      image.addEventListener('load', apply, { once: true });
    } else {
      apply();
    }
  };

  const imageStageResizeObserver = typeof ResizeObserver === 'function'
    ? new ResizeObserver(() => {
        if (!document.body.classList.contains('step7-single-panel-mode')) return;
        fitImageCanvas(panels[activeIndex]);
      })
    : null;
  panels.forEach(panel => {
    const imageStage = panel.querySelector('.comparison-image-stage');
    if (imageStage) imageStageResizeObserver?.observe(imageStage);
  });

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

  const forceIssueListTop = panel => {
    const list = panel?.querySelector('.comparison-issue-list');
    if (!list) return;
    // Do both direct assignment and scrollTo: different browser/layout paths can
    // restore scroll anchoring after a reviewed row disappears. Re-assert on the
    // next frame so late button/row reflow cannot shift the controls vertically.
    list.scrollTop = 0;
    list.scrollTo({top: 0, left: 0, behavior: 'auto'});
    window.requestAnimationFrame(() => {
      list.scrollTop = 0;
      list.scrollTo({top: 0, left: 0, behavior: 'auto'});
    });
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
    window.requestAnimationFrame(() => {
      fitImageCanvas(panels[activeIndex]);
      if (scrollIssues) forceIssueListTop(panels[activeIndex]);
      switching = false;
    });
  };

  const movePanel = direction => {
    const eligible = eligibleIndexes();
    if (!eligible.length) {
      showPanel(activeIndex);
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
    // Preserve the reviewer’s place after a decision; only explicit panel navigation
    // returns the issue list to its top.
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
      unwrapImageCanvas(panel);
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