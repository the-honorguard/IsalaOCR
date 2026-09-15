/* Shared formatting/UI helpers for the localization-* React page controllers.
 *
 * Before this file existed, `text`/`qtext`/`safeText`, `artifactWhen`/`qwhen`,
 * `artifactAction`/`qAction`/`actionControl`, `datasetName`/`qdatasetName`
 * and `modelName`/`qmodelName`/`evaluationName`/`qevalName` were each
 * duplicated near-verbatim across localization-artifacts.ts,
 * localization-quality.ts and localization-workbench.ts
 * (CODE_REVIEW_v3.16.0.md, sectie Middel: "drie React-paginacontrollers...
 * met bijna letterlijk gekopieerde format-helpers"; zie ook
 * documentation/architecture/refactor-phase2-plan.md, item 10).
 *
 * Declared here as ambient globals (matching this build's `module: "none"`
 * + `outFile` setup, where each page's tsconfig lists this file before its
 * own .ts file so tsc concatenates them into one global-scope program) --
 * NOT extracted: each page's Boundary class and poll/refresh scaffolding.
 * Those look similar but differ in real ways (different render markup and
 * state shape per Boundary; different "is a job still active" predicates
 * and extra per-page hooks in the poll loops) -- unifying them would mean
 * either a user-visible behavior change or a real abstraction-design
 * decision, neither of which this pass makes blindly without a way to
 * verify it live in a browser.
 */

declare const React: any;
declare const ReactDOM: any;

/** Empty/None/undefined -> `fallback` (default "—"), otherwise String(value). */
function sharedText(value: any, fallback = "—"): string {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

/** Dutch-locale "26 mrt 2025, 14:03"-style datetime, or a placeholder for an empty value. */
function sharedFriendlyWhen(value: any): string {
  if (!value) return "onbekende datum";
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed
    .toLocaleString("nl-NL", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    .replace(",", "");
}

/** A button plus an optional "why this is disabled" note, in the shared action-control shape. */
function sharedActionControl(className: string, button: any, reason = "") {
  return React.createElement(
    "div", { className },
    button,
    reason ? React.createElement("small", { className: "action-disabled-reason", role: "note" }, `Niet beschikbaar: ${reason}`) : null
  );
}

function sharedDatasetName(item: any, projectName: string): string {
  return `${sharedText(projectName, "Project")} · veld-dataset · ${sharedFriendlyWhen(item && item.created_at)}`;
}

function sharedModelName(item: any, projectName: string): string {
  const model = sharedText(item && item.model_name, "veld-detector");
  const device = item && item.device ? ` · ${String(item.device).toUpperCase()}` : "";
  return `${sharedText(projectName, "Project")} · ${model}${device} · ${sharedFriendlyWhen((item && (item.registered_at || item.created_at)) || "")}`;
}

function sharedEvaluationName(item: any): string {
  const kind = String((item && item.kind) || "evaluatie").toLowerCase() === "baseline" ? "Baseline" : "Getraind";
  return `${kind} · ${sharedFriendlyWhen(item && item.created_at)}`;
}
