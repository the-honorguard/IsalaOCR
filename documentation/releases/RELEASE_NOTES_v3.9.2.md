# IsalaOCR 3.9.2 — resilient React quality UI

v3.9.2 fixes a regression introduced by the derived Detection Gate in 3.9.1. Because the gate was evaluated from the global Jinja context, any unexpected legacy evaluation or ground-truth state could raise an exception while rendering every page, producing Flask's generic Internal Server Error.

The derived gate is now fail-closed and exception-safe. A gate calculation problem blocks Pipeline B but never takes down the web interface. The exception is written to the active project's `webui_errors.log` with a reference shown in the UI. Unhandled HTTP 500 errors also receive a local diagnostic reference instead of the opaque Flask error page.

No localization dataset, model, evaluation or training image rebuild is required.
