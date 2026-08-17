# IsalaOCR 3.9.5 — WebUI stability and cleanup

This release fixes the blank localization quality screen and removes implementation noise from the user interface.

## Fixed

- The bundled runtime is React 16.0.x; `React.Fragment` was unavailable and caused React invariant 130 on the quality page. The quality client no longer uses later React APIs.
- Interactive clients no longer open `/api/v2/events`. They use lightweight JSON polling, avoiding the failing Firefox EventSource connection while still updating buttons and state without a full-page refresh.
- Step 4, Step 5/6/8 quality screens and Data & modellen use `ReactDOM.render`, matching the bundled runtime.
- Error boundaries prevent a component rendering error from leaving the page empty.
- Automatic full-page reloads were removed from the global activity dock and Detection Review manual-box actions.

## UI cleanup

- Removed React/SSE/migration/phase banners and implementation labels from the WebUI.
- Removed duplicate page status cards and repeated recent-job lists where the global activity dock already provides that information.
- Simplified project information in the sidebar.
- Review counters are no longer shown in unrelated dataset/evaluation pages.
- Renamed `Artifacts & opslag` to `Data & modellen`.
- Simplified technical status copy while retaining actionable validation and Detection Gate information.

No localization/recognition training image rebuild is required; `TRAINING_IMAGE_VERSION` remains unchanged.
