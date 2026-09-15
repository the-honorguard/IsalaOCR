(() => {
  const rows = Array.from(document.querySelectorAll('.mapping-relation-row'));
  const relationData = document.getElementById('mapping-relations-data');
  const fieldData = document.getElementById('mapping-fields-data');
  const form = document.getElementById('relation-mapping-form');
  const sourceStage = document.querySelector('.mapping-source-stage');
  const sourceImage = sourceStage?.querySelector('img');
  const toolbarActions = document.querySelector('.mapping-action-toolbar .actions');
  if (!rows.length || !relationData || !fieldData || !form || !sourceStage || !sourceImage || !toolbarActions) return;

  let relations = {};
  let fields = {};
  try {
    relations = JSON.parse(relationData.textContent || '{}');
    fields = JSON.parse(fieldData.textContent || '{}');
  } catch (_) {
    return;
  }

  const sourceWidth = Number(sourceStage.dataset.sourceWidth || 0);
  const sourceHeight = Number(sourceStage.dataset.sourceHeight || 0);
  if (!(sourceWidth > 0 && sourceHeight > 0)) return;

  const launch = document.createElement('button');
  launch.type = 'button';
  launch.id = 'mapping-review-launch';
  launch.className = 'primary mapping-review-launch';
  launch.textContent = '⛶ Review fullscreen';
  launch.title = 'Open Mapping Review Studio (F)';
  toolbarActions.prepend(launch);

  const studio = document.createElement('section');
  studio.id = 'mapping-review-studio';
  studio.className = 'mapping-review-studio';
  studio.hidden = true;
  studio.setAttribute('aria-hidden', 'true');
  studio.innerHTML = `
    <header class="mapping-review-head">
      <div class="mapping-review-title">
        <button type="button" class="ghost" id="mapping-review-close" title="Sluiten (Esc/F)">← Terug</button>
        <div class="mapping-review-title-copy">
          <strong>Mapping Review Studio</strong>
          <small id="mapping-review-source"></small>
        </div>
      </div>
      <div class="mapping-review-head-actions">
        <label class="mapping-review-checkbox"><input type="checkbox" id="mapping-review-open-only" checked> Alleen open / voorgesteld</label>
        <button type="button" class="ghost" id="mapping-review-prev">← Vorige</button>
        <span class="mapping-review-counter" id="mapping-review-counter">0 / 0</span>
        <button type="button" class="ghost" id="mapping-review-next">Volgende →</button>
      </div>
    </header>
    <div class="mapping-review-body">
      <section class="mapping-review-viewer">
        <div class="mapping-review-viewbar">
          <small>Blauw = label · groen = finale Pipeline-A ROI · muiswiel = zoom · Pan of spatie + slepen = verplaatsen</small>
          <div class="mapping-review-view-controls">
            <button type="button" class="ghost" id="mapping-review-fit">Fit</button>
            <button type="button" class="ghost" id="mapping-review-zoom-out">−</button>
            <span class="mapping-review-counter" id="mapping-review-zoom-label">Fit</span>
            <button type="button" class="ghost" id="mapping-review-zoom-in">+</button>
            <button type="button" class="ghost" id="mapping-review-one-to-one">1:1</button>
            <button type="button" class="ghost" id="mapping-review-focus">Focus</button>
            <button type="button" class="ghost" id="mapping-review-pan" aria-pressed="false" title="Panmodus aan/uit (P)">✋ Pan</button>
          </div>
        </div>
        <div class="mapping-review-viewport" id="mapping-review-viewport">
          <div class="mapping-review-stage" id="mapping-review-stage">
            <img id="mapping-review-source-image" alt="Bronbeeld">
            <span class="mapping-review-box label" id="mapping-review-label-box" hidden></span>
            <span class="mapping-review-box value" id="mapping-review-value-box" hidden></span>
          </div>
        </div>
      </section>
      <aside class="mapping-review-inspector">
        <div id="mapping-review-empty" class="mapping-review-empty" hidden>
          <div><strong>Geen relaties in deze reviewqueue.</strong><br><span>Schakel ‘Alleen open / voorgesteld’ uit of pas eerst de filters in Mapping Studio aan.</span></div>
        </div>
        <div id="mapping-review-content">
          <section class="mapping-review-section">
            <div class="mapping-review-kicker">
              <strong id="mapping-review-relation-title">Relatie</strong>
              <span class="mapping-review-status" id="mapping-review-status">open</span>
            </div>
            <div class="mapping-review-pair">
              <div class="mapping-review-crop">
                <span>Label</span>
                <img id="mapping-review-label-crop" alt="Gedetecteerd label">
                <strong id="mapping-review-label">—</strong>
              </div>
              <div class="mapping-review-arrow">→</div>
              <div class="mapping-review-crop">
                <span>Waarde</span>
                <img id="mapping-review-value-crop" alt="Gedetecteerde waarde">
                <strong id="mapping-review-value">—</strong>
              </div>
            </div>
            <div class="mapping-review-meta">
              <div><span>Structuur</span><strong id="mapping-review-structure">—</strong></div>
              <div><span>Confidence</span><strong id="mapping-review-confidence">—</strong></div>
              <div><span>Pipeline-A crop</span><strong id="mapping-review-roi-state">—</strong></div>
              <div><span>Functioneel pad</span><strong class="mono" id="mapping-review-path">—</strong></div>
            </div>
            <p class="mapping-review-context" id="mapping-review-context"></p>
          </section>
          <section class="mapping-review-section mapping-review-editor">
            <h3>Functioneel veld</h3>
            <label>Veld
              <select id="mapping-review-field"></select>
            </label>
            <label>Notitie
              <textarea id="mapping-review-notes" placeholder="optioneel"></textarea>
            </label>
            <div class="mapping-review-field-summary" id="mapping-review-field-summary">Kies het functionele veld dat bij deze relatie hoort.</div>
            <div class="mapping-review-message" id="mapping-review-message"></div>
          </section>
        </div>
      </aside>
    </div>
    <footer class="mapping-review-foot">
      <div class="mapping-review-progress">
        <div class="mapping-review-progress-copy"><span id="mapping-review-progress-copy">0 afgehandeld</span><span class="mapping-review-shortcuts">Enter = goedkeuren · ←/→ = navigeren · P = pan · F/Esc = sluiten</span><span class="mapping-review-queue-status" id="mapping-review-queue-status"></span><button type="button" class="ghost hidden" id="mapping-review-queue-retry">Opnieuw</button></div>
        <div class="mapping-review-progress-track"><span id="mapping-review-progress-bar"></span></div>
      </div>
      <div class="mapping-review-actions">
        <button type="button" class="ghost" id="mapping-review-skip">Overslaan →</button>
        <button type="button" class="danger ghost" id="mapping-review-reject">Afkeuren…</button>
        <button type="button" class="primary" id="mapping-review-approve">Goedkeuren & volgende</button>
      </div>
    </footer>`;
  document.body.appendChild(studio);

  const $ = (id) => document.getElementById(id);
  const closeButton = $('mapping-review-close');
  const previousButton = $('mapping-review-prev');
  const nextButton = $('mapping-review-next');
  const skipButton = $('mapping-review-skip');
  const rejectButton = $('mapping-review-reject');
  const approveButton = $('mapping-review-approve');
  const openOnlyToggle = $('mapping-review-open-only');
  const counter = $('mapping-review-counter');
  const sourceOut = $('mapping-review-source');
  const emptyState = $('mapping-review-empty');
  const content = $('mapping-review-content');
  const statusOut = $('mapping-review-status');
  const titleOut = $('mapping-review-relation-title');
  const labelOut = $('mapping-review-label');
  const valueOut = $('mapping-review-value');
  const structureOut = $('mapping-review-structure');
  const confidenceOut = $('mapping-review-confidence');
  const roiStateOut = $('mapping-review-roi-state');
  const pathOut = $('mapping-review-path');
  const contextOut = $('mapping-review-context');
  const fieldSelect = $('mapping-review-field');
  const notesInput = $('mapping-review-notes');
  const fieldSummary = $('mapping-review-field-summary');
  const messageOut = $('mapping-review-message');
  const labelCrop = $('mapping-review-label-crop');
  const valueCrop = $('mapping-review-value-crop');
  const viewport = $('mapping-review-viewport');
  const stage = $('mapping-review-stage');
  const reviewImage = $('mapping-review-source-image');
  const labelBox = $('mapping-review-label-box');
  const valueBox = $('mapping-review-value-box');
  const zoomLabel = $('mapping-review-zoom-label');
  const panButton = $('mapping-review-pan');
  const progressCopy = $('mapping-review-progress-copy');
  const progressBar = $('mapping-review-progress-bar');
  const queueStatusOut = $('mapping-review-queue-status');
  const queueRetryButton = $('mapping-review-queue-retry');
  const rejectDialog = document.getElementById('mapping-reject-dialog');

  reviewImage.src = sourceImage.src;
  sourceOut.textContent = document.querySelector('select[name="source_id"]')?.value || window.location.pathname;

  let currentRow = null;
  let zoom = 1;
  let panMode = false;
  let spaceDown = false;
  let autoAdvanceAfterReject = false;
  const studioStateKey = 'isala-mapping-review-studio-state';

  function rememberStudioState(open) {
    try {
      if (!open) {
        sessionStorage.removeItem(studioStateKey);
        return;
      }
      sessionStorage.setItem(studioStateKey, JSON.stringify({
        path: window.location.pathname,
        relationId: currentRow?.dataset.relationId || '',
      }));
    } catch (_) {
      // Private browsing or disabled storage must not affect review itself.
    }
  }

  function rememberedRelationId() {
    try {
      const state = JSON.parse(sessionStorage.getItem(studioStateKey) || 'null');
      return state?.path === window.location.pathname ? String(state.relationId || '') : '';
    } catch (_) {
      return '';
    }
  }

  function syncPanMode() {
    const ready = panMode || spaceDown;
    viewport.classList.toggle('pan-ready', ready);
    panButton.classList.toggle('active', panMode);
    panButton.setAttribute('aria-pressed', panMode ? 'true' : 'false');
    panButton.textContent = panMode ? '✋ Pan aan' : '✋ Pan';
  }

  function togglePanMode() {
    panMode = !panMode;
    if (!panMode && !spaceDown) endPan();
    syncPanMode();
  }

  function isOpenStatus(row) {
    return row.dataset.status === 'open' || row.dataset.status === 'suggested';
  }

  function reviewQueue() {
    return rows.filter((row) => {
      if (row.hidden) return false;
      if (openOnlyToggle.checked && !isOpenStatus(row)) return false;
      return true;
    });
  }

  function statusLabel(status) {
    return ({open: 'open', suggested: 'voorgesteld', confirmed: 'bevestigd', rejected: 'afgekeurd'})[status] || status || 'open';
  }

  function clearMessage() {
    messageOut.textContent = '';
    messageOut.className = 'mapping-review-message';
  }

  function setMessage(text, kind = '') {
    messageOut.textContent = text || '';
    messageOut.className = `mapping-review-message${kind ? ' ' + kind : ''}`;
  }

  function setBox(element, coords) {
    if (!Array.isArray(coords) || coords.length !== 4) {
      element.hidden = true;
      return;
    }
    const [x1, y1, x2, y2] = coords.map(Number);
    if (!(x2 > x1 && y2 > y1)) {
      element.hidden = true;
      return;
    }
    element.hidden = false;
    IsalaBoxOverlay.applyBoxRect(element, [x1, y1, x2, y2], sourceWidth, sourceHeight);
  }

  function relationLabelBox(relation) {
    return [relation.label_x1, relation.label_y1, relation.label_x2, relation.label_y2].map(Number);
  }

  function relationValueBox(relation) {
    return Array.isArray(relation.pipeline_a_roi) ? relation.pipeline_a_roi.map(Number) : [];
  }

  function baseFitScale() {
    const rect = viewport.getBoundingClientRect();
    if (!(rect.width > 0 && rect.height > 0)) return 1;
    return Math.max(0.02, Math.min((rect.width - 32) / sourceWidth, (rect.height - 32) / sourceHeight));
  }

  function applyZoom(preserveCenter = false) {
    const oldWidth = stage.offsetWidth || 1;
    const oldHeight = stage.offsetHeight || 1;
    const centerX = viewport.scrollLeft + viewport.clientWidth / 2;
    const centerY = viewport.scrollTop + viewport.clientHeight / 2;
    const relativeX = centerX / oldWidth;
    const relativeY = centerY / oldHeight;
    const scale = baseFitScale() * zoom;
    stage.style.width = `${Math.max(1, sourceWidth * scale)}px`;
    stage.style.height = `${Math.max(1, sourceHeight * scale)}px`;
    zoomLabel.textContent = Math.abs(zoom - 1) < 0.02 ? 'Fit' : `${Math.round(scale * 100)}%`;
    if (preserveCenter) {
      requestAnimationFrame(() => {
        viewport.scrollLeft = Math.max(0, relativeX * stage.offsetWidth - viewport.clientWidth / 2);
        viewport.scrollTop = Math.max(0, relativeY * stage.offsetHeight - viewport.clientHeight / 2);
      });
    }
  }

  function fitView() {
    zoom = 1;
    applyZoom();
    requestAnimationFrame(() => {
      viewport.scrollLeft = 0;
      viewport.scrollTop = 0;
    });
  }

  function oneToOne() {
    const fit = baseFitScale();
    zoom = Math.max(0.2, Math.min(12, 1 / fit));
    applyZoom();
  }

  function focusCurrent() {
    if (!currentRow) return;
    const relation = relations[currentRow.dataset.relationId] || {};
    const boxes = [];
    const label = relationLabelBox(relation);
    const value = relationValueBox(relation);
    if (label.every(Number.isFinite) && label[2] > label[0] && label[3] > label[1]) boxes.push(label);
    if (value.length === 4 && value.every(Number.isFinite) && value[2] > value[0] && value[3] > value[1]) boxes.push(value);
    if (!boxes.length) return fitView();
    const x1 = Math.min(...boxes.map((box) => box[0]));
    const y1 = Math.min(...boxes.map((box) => box[1]));
    const x2 = Math.max(...boxes.map((box) => box[2]));
    const y2 = Math.max(...boxes.map((box) => box[3]));
    const padding = 80;
    const targetWidth = Math.max(1, x2 - x1 + padding * 2);
    const targetHeight = Math.max(1, y2 - y1 + padding * 2);
    const desiredScale = Math.min(viewport.clientWidth / targetWidth, viewport.clientHeight / targetHeight);
    zoom = Math.max(0.35, Math.min(8, desiredScale / baseFitScale()));
    applyZoom();
    requestAnimationFrame(() => {
      const scale = stage.offsetWidth / sourceWidth;
      const centerX = ((x1 + x2) / 2) * scale;
      const centerY = ((y1 + y2) / 2) * scale;
      viewport.scrollLeft = Math.max(0, stage.offsetLeft + centerX - viewport.clientWidth / 2);
      viewport.scrollTop = Math.max(0, stage.offsetTop + centerY - viewport.clientHeight / 2);
    });
  }

  function updateProgress() {
    const total = rows.filter((row) => !row.hidden).length;
    const handled = rows.filter((row) => !row.hidden && !isOpenStatus(row)).length;
    const pct = total ? handled / total * 100 : 0;
    progressCopy.textContent = `${handled} van ${total} afgehandeld`;
    progressBar.style.width = `${pct}%`;
  }

  function syncStudioEditorToRow() {
    if (!currentRow) return;
    const select = currentRow.querySelector('.mapping-field-select');
    const notes = currentRow.querySelector('.mapping-notes-input');
    if (select && !select.disabled && select.value !== fieldSelect.value) {
      select.value = fieldSelect.value;
      select.dispatchEvent(new Event('change', {bubbles: true}));
    }
    if (notes && !notes.disabled && notes.value !== notesInput.value) {
      notes.value = notesInput.value;
      notes.dispatchEvent(new Event('input', {bubbles: true}));
    }
  }

  function updateFieldSummary() {
    if (!currentRow) return;
    const relation = relations[currentRow.dataset.relationId] || {};
    const field = fields[fieldSelect.value];
    if (!field) {
      fieldSummary.textContent = 'Niet gemapt. Kies een veld om deze relatie te kunnen goedkeuren.';
      pathOut.textContent = '—';
      return;
    }
    const group = field.group_name ? `${field.group_name} · ` : '';
    const unit = field.preferred_unit ? ` · verwacht ${field.preferred_unit}` : '';
    fieldSummary.textContent = `${group}${field.display_name}${unit}`;
    pathOut.textContent = `measurements.${field.field_key}`;
    if (relation.value_text && field.preferred_unit) {
      fieldSummary.title = `Gedetecteerde waarde: ${relation.value_text}`;
    }
  }

  function renderRow(row, {focus = false} = {}) {
    currentRow = row || null;
    clearMessage();
    const queue = reviewQueue();
    if (!currentRow || !queue.length) {
      emptyState.hidden = false;
      content.hidden = true;
      counter.textContent = '0 / 0';
      previousButton.disabled = true;
      nextButton.disabled = true;
      skipButton.disabled = true;
      rejectButton.disabled = true;
      approveButton.disabled = true;
      labelBox.hidden = true;
      valueBox.hidden = true;
      updateProgress();
      return;
    }

    emptyState.hidden = true;
    content.hidden = false;
    previousButton.disabled = false;
    nextButton.disabled = false;
    skipButton.disabled = false;

    const relationId = currentRow.dataset.relationId;
    const relation = relations[relationId] || {};
    const sourceSelect = currentRow.querySelector('.mapping-field-select');
    const sourceNotes = currentRow.querySelector('.mapping-notes-input');
    const status = currentRow.dataset.status || 'open';
    const index = Math.max(0, queue.indexOf(currentRow));
    counter.textContent = `${index + 1} / ${queue.length}`;

    rows.forEach((item) => item.classList.toggle('preview-active', item === currentRow));
    titleOut.textContent = relation.relation_type === 'table_cell'
      ? `Tabelrij ${Number(relation.row_index || 0) + 1}`
      : 'OCR-relatie';
    statusOut.textContent = statusLabel(status);
    statusOut.className = `mapping-review-status ${status}`;
    labelOut.textContent = relation.label_text || '—';
    valueOut.textContent = relation.value_text || '—';
    confidenceOut.textContent = `${Math.round(Number(relation.confidence || currentRow.dataset.confidence || 0) * 100)}%`;
    structureOut.textContent = relation.relation_type === 'table_cell'
      ? `Paddle tabel · rij ${Number(relation.row_index || 0) + 1} · waardekolom ${Number(relation.value_column_index || 0) + 1}`
      : (relation.relation_type || 'OCR-relatie');
    roiStateOut.textContent = relation.pipeline_a_roi_ready
      ? `${relation.pipeline_a_geometry_source || 'Pipeline-A ROI'}`
      : 'geen betrouwbare ROI';
    contextOut.textContent = relation.context_text ? `Context: ${relation.context_text}` : '';

    const rowImages = Array.from(currentRow.querySelectorAll('.mapping-crop-pair img'));
    if (rowImages[0]?.src) {
      labelCrop.src = rowImages[0].src;
      labelCrop.hidden = false;
    } else {
      labelCrop.removeAttribute('src');
      labelCrop.hidden = true;
    }
    if (rowImages[1]?.src) {
      valueCrop.src = rowImages[1].src;
      valueCrop.hidden = false;
    } else {
      valueCrop.removeAttribute('src');
      valueCrop.hidden = true;
    }

    fieldSelect.innerHTML = sourceSelect?.innerHTML || '<option value="">— niet mappen —</option>';
    fieldSelect.value = sourceSelect?.value || '';
    fieldSelect.disabled = Boolean(sourceSelect?.disabled);
    notesInput.value = sourceNotes?.value || '';
    notesInput.disabled = Boolean(sourceNotes?.disabled);
    rejectButton.disabled = false;
    approveButton.disabled = Boolean(sourceSelect?.disabled || !relation.pipeline_a_roi_ready || status === 'rejected');
    rejectButton.textContent = status === 'rejected' ? 'Afkeuring herstellen' : 'Afkeuren…';

    setBox(labelBox, relationLabelBox(relation));
    setBox(valueBox, relation.pipeline_a_roi_ready ? relationValueBox(relation) : []);
    updateFieldSummary();
    updateProgress();
    applyZoom();
    if (focus) requestAnimationFrame(focusCurrent);
  }

  function nearestQueueRow(direction) {
    const queue = reviewQueue();
    if (!queue.length) return null;
    if (currentRow && queue.includes(currentRow)) {
      const index = queue.indexOf(currentRow);
      return queue[(index + direction + queue.length) % queue.length];
    }
    if (!currentRow) return direction > 0 ? queue[0] : queue[queue.length - 1];
    const currentIndex = rows.indexOf(currentRow);
    if (direction > 0) {
      return queue.find((row) => rows.indexOf(row) > currentIndex) || queue[0];
    }
    return [...queue].reverse().find((row) => rows.indexOf(row) < currentIndex) || queue[queue.length - 1];
  }

  function move(direction) {
    syncStudioEditorToRow();
    renderRow(nearestQueueRow(direction));
  }

  function openStudio() {
    if (!studio.hidden) return;
    studio.hidden = false;
    studio.setAttribute('aria-hidden', 'false');
    document.body.classList.add('mapping-review-studio-open');
    const remembered = rememberedRelationId();
    const active = rows.find((row) => row.dataset.relationId === remembered && reviewQueue().includes(row))
      || rows.find((row) => row.classList.contains('preview-active') && reviewQueue().includes(row));
    renderRow(active || reviewQueue()[0] || null);
    rememberStudioState(true);
    syncPanMode();
    requestAnimationFrame(fitView);
  }

  function closeStudio() {
    if (studio.hidden) return;
    syncStudioEditorToRow();
    studio.hidden = true;
    studio.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('mapping-review-studio-open');
    rememberStudioState(false);
    panMode = false;
    spaceDown = false;
    endPan();
    syncPanMode();
    currentRow?.scrollIntoView({block: 'center'});
  }

  function extractServerError(html) {
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const error = Array.from(parsed.querySelectorAll('main.shell > .notice.error'))
      .map((item) => item.textContent?.trim())
      .find(Boolean);
    return {parsed, error: error || ''};
  }

  function copyFreshRowState(row, parsed) {
    const fresh = Array.from(parsed.querySelectorAll('.mapping-relation-row'))
      .find((item) => item.dataset.relationId === row.dataset.relationId);
    if (!fresh) return;
    row.dataset.status = fresh.dataset.status || row.dataset.status;
    row.classList.toggle('mapped', fresh.classList.contains('mapped'));
    row.classList.toggle('mapping-rejected', fresh.classList.contains('mapping-rejected'));
    row.classList.remove('mapping-dirty');
    const sourceSelect = row.querySelector('.mapping-field-select');
    const freshSelect = fresh.querySelector('.mapping-field-select');
    if (sourceSelect && freshSelect) {
      sourceSelect.value = freshSelect.value;
      sourceSelect.dataset.originalValue = freshSelect.dataset.originalValue || freshSelect.value;
    }
    const sourceNotes = row.querySelector('.mapping-notes-input');
    const freshNotes = fresh.querySelector('.mapping-notes-input');
    if (sourceNotes && freshNotes) sourceNotes.value = freshNotes.value;
    const pill = row.querySelector('.mapping-status-pill');
    const freshPill = fresh.querySelector('.mapping-status-pill');
    if (pill && freshPill) {
      pill.className = freshPill.className;
      pill.textContent = freshPill.textContent;
    }
    const dirty = row.querySelector('.mapping-dirty-label');
    if (dirty) dirty.hidden = true;
  }

  function renderQueueStatus() {
    const state = approveQueue.tasks(), failed = state.filter((t) => t.failed).length,
      pending = state.length - failed, running = approveQueue.inFlight.size;
    queueStatusOut.textContent = !state.length ? '' :
      [running ? `${running} bezig` : null, pending ? `${pending} wacht` : null, failed ? `${failed} fout` : null]
        .filter(Boolean).join(' · ');
    queueRetryButton.classList.toggle('hidden', failed === 0);
  }

  const approveQueue = IsalaReviewQueue.createTaskQueue({
    storageKey: `isala-mapping-review-studio:approve-queue:${window.location.pathname}`,
    concurrency: 3,
    execute: async (task) => {
      const row = rows.find((item) => item.dataset.relationId === task.relationId);
      if (!row) return;
      const body = new FormData();
      body.append('mapping_action', 'save');
      body.append('relation_id', task.relationId);
      body.append(`field_${task.relationId}`, task.fieldKey);
      body.append(`notes_${task.relationId}`, task.notes);
      const response = await fetch(form.action || window.location.href, {
        method: 'POST',
        body,
        credentials: 'same-origin',
        headers: {'X-Requested-With': 'MappingReviewStudio'},
      });
      const html = await response.text();
      const {parsed, error} = extractServerError(html);
      if (!response.ok || error) throw new Error(error || `HTTP ${response.status}`);
      copyFreshRowState(row, parsed);
      updateProgress();
      if (currentRow === row) renderRow(row);
    },
    onChange: renderQueueStatus,
    onTaskError: (task, error) => {
      const row = rows.find((item) => item.dataset.relationId === task.relationId);
      if (currentRow !== row) return;
      setMessage(
        task.failed
          ? `Opslaan mislukt: ${error.message || error}. Klik Opnieuw om te retryen.`
          : `Opslaan mislukt, wordt opnieuw geprobeerd (${task.attempt}/3): ${error.message || error}`,
        'error',
      );
    },
  });
  queueRetryButton.addEventListener('click', () => approveQueue.retryFailed());

  function approveCurrent() {
    if (!currentRow) return;
    syncStudioEditorToRow();
    const sourceSelect = currentRow.querySelector('.mapping-field-select');
    const sourceNotes = currentRow.querySelector('.mapping-notes-input');
    const relationId = currentRow.dataset.relationId;
    if (!sourceSelect || sourceSelect.disabled) {
      setMessage('Deze relatie kan niet worden opgeslagen zolang de Pipeline-A ROI ontbreekt of de relatie is afgekeurd.', 'error');
      return;
    }
    if (!sourceSelect.value) {
      setMessage('Kies eerst een functioneel veld.', 'error');
      fieldSelect.focus();
      return;
    }
    if (currentRow.classList.contains('mapping-duplicate')) {
      setMessage('Dit functionele veld is al bij een andere relatie geselecteerd. Los de dubbele mapping eerst op.', 'error');
      return;
    }

    approveQueue.enqueue(
      {kind: 'approve', relationId, fieldKey: sourceSelect.value, notes: sourceNotes?.value || ''},
      (existing, incoming) => existing.kind === 'approve' && existing.relationId === incoming.relationId,
    );
    setMessage('In wachtrij: wordt op de achtergrond opgeslagen…', 'ok');
    window.setTimeout(() => {
      const next = nearestQueueRow(1);
      renderRow(next);
    }, 180);
  }

  function proxyFeedbackAction() {
    if (!currentRow) return;
    const status = currentRow.dataset.status;
    if (status === 'rejected') {
      currentRow.querySelector('.mapping-restore-button')?.click();
      return;
    }
    autoAdvanceAfterReject = true;
    currentRow.querySelector('.mapping-reject-button')?.click();
  }

  launch.addEventListener('click', openStudio);
  closeButton.addEventListener('click', closeStudio);
  previousButton.addEventListener('click', () => move(-1));
  nextButton.addEventListener('click', () => move(1));
  skipButton.addEventListener('click', () => move(1));
  approveButton.addEventListener('click', approveCurrent);
  rejectButton.addEventListener('click', proxyFeedbackAction);
  panButton.addEventListener('click', togglePanMode);
  openOnlyToggle.addEventListener('change', () => {
    const queue = reviewQueue();
    renderRow(currentRow && queue.includes(currentRow) ? currentRow : queue[0] || null);
  });
  fieldSelect.addEventListener('change', () => {
    syncStudioEditorToRow();
    updateFieldSummary();
    clearMessage();
  });
  notesInput.addEventListener('input', syncStudioEditorToRow);

  $('mapping-review-fit').addEventListener('click', fitView);
  $('mapping-review-zoom-in').addEventListener('click', () => {
    zoom = Math.min(12, zoom * 1.22);
    applyZoom(true);
  });
  $('mapping-review-zoom-out').addEventListener('click', () => {
    zoom = Math.max(0.2, zoom / 1.22);
    applyZoom(true);
  });
  $('mapping-review-one-to-one').addEventListener('click', oneToOne);
  $('mapping-review-focus').addEventListener('click', focusCurrent);

  viewport.addEventListener('wheel', (event) => {
    if (studio.hidden) return;
    event.preventDefault();
    zoom = event.deltaY < 0 ? Math.min(12, zoom * 1.12) : Math.max(0.2, zoom / 1.12);
    applyZoom(true);
  }, {passive: false});

  const dragPan = IsalaViewportPan.createDragPan(viewport, {
    panningClass: 'panning',
    shouldStart: (event) => (panMode || spaceDown) && event.button === 0,
  });
  const endPan = () => dragPan.cancel();

  const observer = new MutationObserver((mutations) => {
    if (studio.hidden || !currentRow) return;
    const currentChanged = mutations.some((mutation) => mutation.target === currentRow && mutation.attributeName === 'data-status');
    if (!currentChanged) return;
    const status = currentRow.dataset.status;
    updateProgress();
    if (autoAdvanceAfterReject && status === 'rejected' && openOnlyToggle.checked) {
      autoAdvanceAfterReject = false;
      window.setTimeout(() => renderRow(nearestQueueRow(1)), 80);
      return;
    }
    renderRow(currentRow);
  });
  rows.forEach((row) => observer.observe(row, {attributes: true, attributeFilter: ['data-status']}));

  window.addEventListener('resize', () => {
    if (!studio.hidden) applyZoom();
  });

  document.addEventListener('keydown', (event) => {
    const tag = event.target?.tagName?.toLowerCase();
    const editing = tag === 'input' || tag === 'textarea' || tag === 'select';
    if ((event.key === 'f' || event.key === 'F') && !editing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      if (studio.hidden) openStudio(); else if (!rejectDialog?.open) closeStudio();
      return;
    }
    if (studio.hidden) return;
    if (event.key === 'Escape') {
      if (rejectDialog?.open) return;
      event.preventDefault();
      closeStudio();
      return;
    }
    if ((event.key === 'p' || event.key === 'P') && !editing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      togglePanMode();
      return;
    }
    if (event.code === 'Space' && !editing) {
      spaceDown = true;
      syncPanMode();
      event.preventDefault();
      return;
    }
    if (editing) return;
    if (event.key === 'ArrowRight' || (event.altKey && event.key === 'ArrowDown')) {
      event.preventDefault();
      move(1);
    } else if (event.key === 'ArrowLeft' || (event.altKey && event.key === 'ArrowUp')) {
      event.preventDefault();
      move(-1);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      approveCurrent();
    }
  });

  document.addEventListener('keyup', (event) => {
    if (event.code !== 'Space') return;
    spaceDown = false;
    if (!panMode) endPan();
    syncPanMode();
  });

  // A decision may still cause a server-side form redirect in an older cached
  // page or after a transient network retry. Restore the overlay on that
  // navigation so reviewing never falls back to the normal Mapping Studio.
  try {
    const state = JSON.parse(sessionStorage.getItem(studioStateKey) || 'null');
    if (state?.path === window.location.pathname) {
      window.setTimeout(openStudio, 0);
    }
  } catch (_) {
    // Ignore unavailable or malformed session storage.
  }
})();
