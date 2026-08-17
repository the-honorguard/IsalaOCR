# IsalaOCR frontend

Interactive localization screens are implemented as a small React/TypeScript client on top of the existing Python backend. React is an implementation detail; user-facing pages should describe workflow actions rather than frontend technology.

## Backend contract

- `GET /api/v2/localization/workbench` - dataset/training state
- `GET /api/v2/localization/quality` - evaluation and Detection Gate state
- `GET /api/v2/localization/artifacts` - datasets, models, evaluations and runs
- `POST /api/v2/localization/split` - split changes
- `POST /api/v2/localization/selection` - explicit dataset/model/evaluation selection
- `POST /api/v2/jobs` - queued actions

The clients refresh their own JSON state on a short interval. They never reload the complete page to synchronize buttons or task results. This deliberately avoids long-lived EventSource connections in the local Waitress server.

## Compatibility

The bundled runtime is React 16.0.x. Embedded clients therefore use `ReactDOM.render` and avoid APIs introduced in later React releases, including `React.Fragment` and `createRoot`. Each client is wrapped in an error boundary so a rendering fault produces a visible error instead of an empty page.

## Build

Production JavaScript is checked in so the labeler image does not require Node.js. Rebuild it with:

```powershell
cd frontend
npm run build:embedded
```
