# IsalaOCR 3.9.3 — merged evaluation flow and artifact manager

v3.9.3 completes the next localization UI consolidation and fixes the React quality pages that could remain stuck on **Detectiekwaliteit laden…**.

## Changes

- **Stap 5 + 6 are merged** into **Stap 5 · Evalueren & vergelijken**.
  - one action evaluates the selected dataset/model;
  - baseline and trained inference are evaluated on the same dataset/split;
  - threshold diagnostics run automatically;
  - the matching baseline/trained pair is compared automatically;
  - manual historical evaluation pairs can still be selected and compared.
- The former activation step is now **Stap 6 · Field detector activeren**. The remaining workflow is renumbered contiguously through Step 17.
- Fixed the permanent **Detectiekwaliteit laden…** screen. The bundled runtime is React 16, while the quality client used the React 18-only `createRoot()` API. All embedded React clients now use a React 16-compatible `ReactDOM.render()` fallback while remaining forward-compatible with `createRoot()`.
- Added **Artifacts & opslag** under System:
  - keep multiple localization datasets;
  - explicitly select an evaluation dataset;
  - explicitly select the field detector to evaluate;
  - separately choose the current work dataset;
  - inspect registered detector models, evaluation history, and training runs;
  - select historical baseline/trained evaluations for comparison;
  - activate the explicitly selected detector;
  - delete unused datasets, models, evaluations, and incomplete runs.
- Artifact deletion is dependency-aware:
  - the current work dataset cannot be deleted;
  - the active detector cannot be deleted;
  - referenced artifacts require explicit cascade deletion;
  - filesystem deletion is constrained to the active project workspace.
- Evaluating an archived/alternate dataset no longer changes the Detection Gate for the current work dataset. Gate derivation now filters trained evaluations by the current dataset and test split.
- Evaluation and activation no longer depend on an implicit `localization_runs/latest.txt` model choice. The web UI writes `localization_artifact_selection.json`, and background tasks use that explicit selection.
- Selecting a historical work dataset restores its immutable split when the current reviewed source set still matches it. If the reviewed scope has changed, the dataset is selected but the split is marked pending/stale rather than silently treating it as current.

The heavy detector/recognition training images remain at `TRAINING_IMAGE_VERSION=3.8.4`.
