/* Shared pointer-drag-pan mechanics for the review-studio viewports.
 * mapping-review-studio.js and detection_review_studio.html's inline script
 * each had their own copy of this exact scrollLeft/scrollTop dragging code;
 * this is the byte-for-byte-equivalent shared version (see
 * documentation/architecture/refactor-phase2-remaining-plan.md, punt 1,
 * stap 3). Callers keep their own trigger condition (space+drag, pan-mode
 * toggle, middle-click, ...) and event-phase/propagation choices, since
 * those differ per screen's other interactions (box drawing, selection).
 */
(function (global) {
  'use strict';

  function createDragPan(viewport, options) {
    const opts = options || {};
    const panningClass = opts.panningClass || 'is-panning';
    const capture = Boolean(opts.capture);
    const stopPropagationOnStart = Boolean(opts.stopPropagationOnStart);
    let panStart = null;

    function pointerDown(event) {
      if (typeof opts.shouldStart === 'function' && !opts.shouldStart(event)) return;
      event.preventDefault();
      if (stopPropagationOnStart) event.stopPropagation();
      panStart = {x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop};
      viewport.classList.add(panningClass);
      try {
        viewport.setPointerCapture?.(event.pointerId);
      } catch (_) {
        // Some browsers/pointer types reject capture; the drag still works.
      }
    }

    function pointerMove(event) {
      if (!panStart) return;
      if (capture) event.preventDefault();
      viewport.scrollLeft = panStart.left - (event.clientX - panStart.x);
      viewport.scrollTop = panStart.top - (event.clientY - panStart.y);
    }

    function pointerEnd(event) {
      if (!panStart) return;
      panStart = null;
      viewport.classList.remove(panningClass);
      try {
        if (event) viewport.releasePointerCapture?.(event.pointerId);
      } catch (_) {
        // Capture may already be gone (pointercancel); nothing to release.
      }
    }

    viewport.addEventListener('pointerdown', pointerDown, capture);
    viewport.addEventListener('pointermove', pointerMove, capture);
    viewport.addEventListener('pointerup', pointerEnd, capture);
    viewport.addEventListener('pointercancel', pointerEnd, capture);
    viewport.addEventListener('lostpointercapture', pointerEnd, capture);

    return {
      isPanning: function () {
        return panStart !== null;
      },
      cancel: function () {
        pointerEnd();
      },
    };
  }

  global.IsalaViewportPan = {createDragPan: createDragPan};
})(window);
