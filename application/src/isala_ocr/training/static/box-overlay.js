/* Shared pixel-to-percentage box/point overlay positioning.
 * mapping-review-studio.js's setBox() and several spots in
 * detection_review_studio.html's inline script (setCoords, syncMarker,
 * renderRasterPreview, appendManualAnnotation) each computed the same
 * "pixel box + natural image size -> CSS percentage rect" math
 * independently (see documentation/architecture/refactor-phase2-remaining-plan.md,
 * punt 1, stap 4). Callers keep their own validation/clamping/hide-on-invalid
 * behavior, since that differs per screen -- only the coordinate math and
 * the resulting style assignment are shared here.
 */
(function (global) {
  'use strict';

  function applyBoxRect(element, box, width, height) {
    const [x1, y1, x2, y2] = box;
    element.style.left = `${x1 / width * 100}%`;
    element.style.top = `${y1 / height * 100}%`;
    element.style.width = `${(x2 - x1) / width * 100}%`;
    element.style.height = `${(y2 - y1) / height * 100}%`;
  }

  function applyPointPosition(element, x, y, width, height) {
    element.style.left = `${x / width * 100}%`;
    element.style.top = `${y / height * 100}%`;
  }

  global.IsalaBoxOverlay = {applyBoxRect: applyBoxRect, applyPointPosition: applyPointPosition};
})(window);
