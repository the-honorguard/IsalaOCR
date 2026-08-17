/* Dataset & detector training workbench. */

declare const React: any;
declare const ReactDOM: any;

const h = React.createElement;
const Component = React.Component;

type SplitName = "train" | "val" | "test";
type JobStatus = "pending" | "running" | "completed" | "failed" | string;

interface SplitTargets {
  train: number;
  val: number;
  test: number;
}

interface LocalizationReadiness {
  dataset_id: string;
  dataset_present: boolean;
  dataset_created_at: string;
  image_count: number;
  annotation_count: number;
  negative_image_count: number;
  splits: SplitTargets;
  app_valid: boolean;
  paddlex_valid: boolean;
  split_current: boolean;
  ready_marker_valid: boolean;
  training_ready: boolean;
  validated_at: string;
  validation_totals: Record<string, number>;
  warnings: string[];
  errors: string[];
  blockers: Array<{ code: string; message: string; next_step: string }>;
  next_step: string;
  models: Array<Record<string, any>>;
  training_profile?: {
    name: string;
    epochs: number;
    batch_size: number;
    learning_rate: number;
    warmup_steps: number;
    eval_interval: number;
    steps_per_epoch: number;
    estimated_optimizer_steps: number;
    sanity_check: boolean;
    warning: string;
  };
}

interface PreviewSource {
  source_id: string;
  ready: boolean;
  included: boolean;
  completed_at?: string;
  split: SplitName | "";
  split_override: SplitName | "";
  candidate_total: number;
  pending: number;
  positive: number;
  negative: number;
  adjusted: number;
  incorrect: number;
  irrelevant: number;
  added: number;
}

interface LocalizationPreview {
  totals: Record<string, number>;
  splits: SplitTargets;
  sources: PreviewSource[];
  split_plan: {
    mode: "auto" | "counts";
    targets: SplitTargets;
    auto_targets: SplitTargets;
    overrides: Record<string, SplitName>;
    assignments: Record<string, SplitName>;
    counts: SplitTargets;
    warnings: string[];
    updated_at: string;
  };
  split_pending: boolean;
}

interface Job {
  job_id: string;
  action_id: string;
  action_name: string;
  status: JobStatus;
  progress_percent?: number;
  progress_mode?: string;
  progress_label?: string;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  exit_code?: number;
}

interface WorkbenchPayload {
  schema_version: number;
  generated_at: string;
  project: { project_id: string; name: string; use_case_id: string };
  readiness: LocalizationReadiness;
  preview: LocalizationPreview;
  jobs: Job[];
  active_job?: Job | null;
  worker: { online?: boolean; current_job_id?: string; heartbeat_age_seconds?: number };
}

interface AppState {
  data: WorkbenchPayload | null;
  loading: boolean;
  refreshing: boolean;
  error: string;
  mutation: string;
  splitTargets: SplitTargets;
  splitOverrides: Record<string, SplitName>;
  splitDirty: boolean;
  lastUpdated: string;
}

function numberValue(value: any): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function safeText(value: any, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function formatWhen(value?: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("nl-NL");
}

function artifactWhen(value?: string): string {
  if (!value) return "onbekende datum";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("nl-NL", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  }).replace(",", "");
}

function datasetFriendlyName(projectName: string, readiness: LocalizationReadiness): string {
  const project = safeText(projectName, "Project");
  if (!readiness.dataset_present) return "Nog geen dataset";
  return `${project} · veld-dataset · ${artifactWhen(readiness.dataset_created_at)}`;
}

function actionControl(button: any, reason = "") {
  return h("div", { className: "react-action-control" },
    button,
    reason ? h("small", { className: "action-disabled-reason", role: "note" }, `Niet beschikbaar: ${reason}`) : null
  );
}

function phaseClass(ok: boolean, warning = false): string {
  if (ok) return "react-status react-status-ok";
  return warning ? "react-status react-status-warn" : "react-status react-status-missing";
}

function StatusCheck(props: { ok: boolean; label: string; good: string; bad: string; soft?: boolean }) {
  return h("div", { className: phaseClass(props.ok, Boolean(props.soft)) },
    h("span", { className: "react-status-mark" }, props.ok ? "✓" : props.soft ? "•" : "×"),
    h("div", null,
      h("strong", null, props.label),
      h("small", null, props.ok ? props.good : props.bad)
    )
  );
}

function Metric(props: { label: string; value: any; tone?: string; mono?: boolean }) {
  return h("div", { className: `react-metric ${props.tone || ""}` },
    h("span", { className: "muted" }, props.label),
    h("strong", { className: props.mono ? "mono wrap-anywhere" : "" }, safeText(props.value))
  );
}

function JobRow(props: { job: Job }) {
  const job = props.job;
  const percent = Math.max(0, Math.min(100, numberValue(job.progress_percent)));
  const running = job.status === "pending" || job.status === "running";
  const determinate = job.progress_mode === "determinate" || !running;
  return h("div", { className: `react-job-row react-job-${job.status || "unknown"}` },
    h("div", { className: "react-job-main" },
      h("strong", null, job.action_name),
      h("small", null, safeText(job.progress_label, job.status))
    ),
    h("div", { className: "react-job-progress" },
      h("div", { className: `react-inline-progress ${!determinate ? "indeterminate" : ""}` },
        h("span", { style: determinate ? { width: `${percent}%` } : undefined })
      ),
      h("span", { className: `job-status ${job.status}` }, job.status)
    )
  );
}


class WorkbenchBoundary extends Component {
  state = { failed: false, message: "" };
  componentDidCatch(error: any) {
    console.error("Localization workbench render failed", error);
    this.setState({
      failed: true,
      message: error && error.message ? String(error.message) : String(error || "Onbekende JavaScript-fout"),
    });
  }
  render() {
    if (this.state.failed) return h("div", { className: "notice error react-render-error" },
      h("strong", null, "Dit scherm kon niet worden weergegeven."),
      h("span", null, ` Technische fout: ${this.state.message}`),
      h("small", { className: "muted", style: { display: "block", marginTop: "6px" } }, "De fout staat ook in de browserconsole. De overige webinterface blijft beschikbaar.")
    );
    return this.props.children;
  }
}
class LocalizationWorkbench extends Component {
  state: AppState;
  pollTimer: number | null;
  unmounted: boolean;

  constructor(props: any) {
    super(props);
    this.state = {
      data: null,
      loading: true,
      refreshing: false,
      error: "",
      mutation: "",
      splitTargets: { train: 0, val: 0, test: 0 },
      splitOverrides: {},
      splitDirty: false,
      lastUpdated: "",
    };
    this.pollTimer = null;
    this.unmounted = false;
  }

  componentDidMount() {
    document.addEventListener("visibilitychange", this.visibilityHandler);
    this.refresh(true);
  }

  componentWillUnmount() {
    this.unmounted = true;
    document.removeEventListener("visibilitychange", this.visibilityHandler);
    if (this.pollTimer !== null) window.clearTimeout(this.pollTimer);
  }

  visibilityHandler = () => {
    if (!document.hidden) this.refresh(false);
  };

  scheduleRefresh(data: WorkbenchPayload | null) {
    if (this.unmounted) return;
    if (this.pollTimer !== null) window.clearTimeout(this.pollTimer);
    const jobs = data ? data.jobs || [] : [];
    const active = Boolean(data && data.active_job) || jobs.some(job => job.status === "pending" || job.status === "running");
    const delay = document.hidden ? 30000 : active ? 2500 : 12000;
    this.pollTimer = window.setTimeout(() => this.refresh(false), delay);
  }

  syncSplitDraft(data: WorkbenchPayload, force = false): Partial<AppState> {
    if (this.state.splitDirty && !force) return {};
    const plan = data.preview && data.preview.split_plan;
    return {
      splitTargets: { ...(plan && plan.targets ? plan.targets : { train: 0, val: 0, test: 0 }) },
      splitOverrides: { ...(plan && plan.overrides ? plan.overrides : {}) },
      splitDirty: false,
    };
  }

  async refresh(initial = false) {
    if (this.unmounted) return;
    if (!initial && this.state.refreshing) return;
    if (this.pollTimer !== null) { window.clearTimeout(this.pollTimer); this.pollTimer = null; }
    this.setState(initial ? { loading: true, error: "" } : { refreshing: true });
    try {
      const response = await fetch(`/api/v2/localization/workbench?_=${Date.now()}`, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`Status ophalen mislukt (${response.status})`);
      const data = await response.json() as WorkbenchPayload;
      if (this.unmounted) return;
      const splitState = this.syncSplitDraft(data, initial);
      this.setState({
        data,
        loading: false,
        refreshing: false,
        error: "",
        lastUpdated: new Date().toISOString(),
        ...splitState,
      });
      this.scheduleRefresh(data);
    } catch (error: any) {
      if (this.unmounted) return;
      this.setState({
        loading: false,
        refreshing: false,
        error: error && error.message ? String(error.message) : "Status ophalen mislukt",
      });
      this.scheduleRefresh(this.state.data);
    }
  }

  activeAction(actionId: string): Job | null {
    const jobs = this.state.data ? this.state.data.jobs : [];
    return jobs.find(job => String(job.action_id) === actionId && (job.status === "pending" || job.status === "running")) || null;
  }

  async startJob(actionId: string) {
    if (this.state.mutation) return;
    this.setState({ mutation: `job:${actionId}`, error: "" });
    try {
      const response = await fetch("/api/v2/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ action_id: actionId, options: {} }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok && response.status !== 409) {
        throw new Error(payload.error || `Taak starten mislukt (${response.status})`);
      }
      await this.refresh(false);
    } catch (error: any) {
      this.setState({ error: error && error.message ? String(error.message) : "Taak starten mislukt" });
    } finally {
      if (!this.unmounted) this.setState({ mutation: "" });
    }
  }

  updateTarget(name: SplitName, raw: string) {
    const value = Math.max(0, Math.floor(numberValue(raw)));
    this.setState((previous: AppState) => ({
      splitTargets: { ...previous.splitTargets, [name]: value },
      splitDirty: true,
    }));
  }

  updateOverride(sourceId: string, split: string) {
    this.setState((previous: AppState) => {
      const next = { ...previous.splitOverrides };
      if (split === "train" || split === "val" || split === "test") next[sourceId] = split;
      else delete next[sourceId];
      return { splitOverrides: next, splitDirty: true };
    });
  }

  async saveSplit(auto: boolean) {
    if (this.state.mutation) return;
    this.setState({ mutation: auto ? "split:auto" : "split:save", error: "" });
    try {
      const response = await fetch("/api/v2/localization/split", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(auto ? { action: "auto" } : {
          action: "save",
          targets: this.state.splitTargets,
          overrides: this.state.splitOverrides,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `Split opslaan mislukt (${response.status})`);
      const data = payload.workbench as WorkbenchPayload;
      if (data) {
        this.setState({
          data,
          splitTargets: { ...data.preview.split_plan.targets },
          splitOverrides: { ...data.preview.split_plan.overrides },
          splitDirty: false,
          lastUpdated: new Date().toISOString(),
        });
      } else {
        await this.refresh(false);
      }
    } catch (error: any) {
      this.setState({ error: error && error.message ? String(error.message) : "Split opslaan mislukt" });
    } finally {
      if (!this.unmounted) this.setState({ mutation: "" });
    }
  }

  renderPhaseActions(data: WorkbenchPayload) {
    const readiness = data.readiness;
    const preview = data.preview || ({ totals: {}, split_pending: false } as any);
    const previewTotals = preview.totals || {};
    const build = this.activeAction("5");
    const validate = this.activeAction("6");
    const gpu = this.activeAction("7");
    const cpu = this.activeAction("8");
    const anyActive = Boolean(build || validate || gpu || cpu || this.state.mutation);
    const activeTask = build || validate || gpu || cpu;
    const workerReason = !(data.worker && data.worker.online) ? "De achtergrondworker is offline. Start de webinterface/worker opnieuw of controleer Wachtrijbeheer." : "";
    const busyReason = workerReason || (anyActive
      ? `Er loopt al een taak${activeTask ? `: ${activeTask.action_name}` : ""}. Rond die taak eerst af.`
      : "");
    const readySources = numberValue(previewTotals.ready_sources);
    const buildReason = busyReason || (readySources === 0
      ? "Er zijn nog geen afgeronde bronbeelden. Ga naar Detection Review en markeer minimaal één afbeelding als klaar."
      : "");
    const validateReason = busyReason || (!readiness.dataset_present
      ? "Er is nog geen dataset. Voer eerst Dataset bouwen uit."
      : "");
    const trainingBlockers = Array.isArray(readiness.blockers) ? readiness.blockers : [];
    const trainReason = busyReason || (!readiness.training_ready
      ? (trainingBlockers.length
        ? trainingBlockers.map(item => `${item.message} ${item.next_step}`).join(" ")
        : "De dataset is nog niet trainingsklaar. Bouw en valideer de dataset eerst.")
      : "");

    return h("div", { className: "react-phase-grid" },
      h("section", { className: `card react-phase-card ${preview.split_pending ? "needs-attention" : ""}` },
        h("div", { className: "react-phase-heading" },
          h("span", { className: "react-phase-number", "aria-hidden": "true" }, "1"),
          h("div", null,
            h("h3", null, "Dataset bouwen"),
            h("p", { className: "muted" }, `${readySources} afgeronde bronbeelden · ${previewTotals.positive_rois || 0} positieve ROI's`)
          )
        ),
        preview.split_pending ? h("div", { className: "notice warning compact" }, "Split of reviewstate is gewijzigd. Bouw opnieuw voordat je verdergaat.") : null,
        actionControl(h("button", {
          className: "primary react-action-button",
          disabled: Boolean(buildReason),
          title: buildReason || "Dataset bouwen",
          onClick: () => this.startJob("5"),
        }, build ? safeText(build.progress_label, "Dataset bouwen…") : readiness.dataset_present && !preview.split_pending ? "Dataset opnieuw bouwen" : "Dataset bouwen"), buildReason)
      ),
      h("section", { className: "card react-phase-card" },
        h("div", { className: "react-phase-heading" },
          h("span", { className: "react-phase-number", "aria-hidden": "true" }, "2"),
          h("div", null,
            h("h3", null, "Dataset valideren"),
            h("p", { className: "muted" }, readiness.dataset_present
              ? datasetFriendlyName(data.project && data.project.name, readiness)
              : "Bouw eerst een dataset")
          )
        ),
        h("div", { className: "react-mini-checks" },
          h("span", { className: readiness.app_valid ? "ok" : "warn" }, `IsalaOCR ${readiness.app_valid ? "✓" : "×"}`),
          h("span", { className: readiness.paddlex_valid ? "ok" : "warn" }, `PaddleX ${readiness.paddlex_valid ? "✓" : "×"}`)
        ),
        actionControl(h("button", {
          className: "react-action-button",
          disabled: Boolean(validateReason),
          title: validateReason || "Dataset valideren",
          onClick: () => this.startJob("6"),
        }, validate ? safeText(validate.progress_label, "Valideren…") : readiness.app_valid && readiness.paddlex_valid ? "Opnieuw valideren" : "Dataset valideren"), validateReason)
      ),
      h("section", { className: `card react-phase-card ${readiness.training_ready ? "ready" : "blocked"}` },
        h("div", { className: "react-phase-heading" },
          h("span", { className: "react-phase-number", "aria-hidden": "true" }, "3"),
          h("div", null,
            h("h3", null, "Detector trainen"),
            h("p", { className: "muted" }, readiness.training_ready ? "Dataset is trainingsklaar." : safeText(readiness.next_step, "Training blijft geblokkeerd tot alle checks groen zijn."))
          )
        ),
        readiness.training_profile && readiness.training_profile.epochs ? h("div", { className: "notice compact" },
          h("strong", null, `Profiel: ${readiness.training_profile.name}. `),
          h("span", null, `${readiness.training_profile.epochs} epochs · batch ${readiness.training_profile.batch_size} · LR ${readiness.training_profile.learning_rate} · warmup ${readiness.training_profile.warmup_steps} · ~${readiness.training_profile.estimated_optimizer_steps} updates.`),
          readiness.training_profile.sanity_check ? h("span", null, " Eerst wordt automatisch een sanity-check op 2 trainingsbeelden uitgevoerd.") : null
        ) : null,
        h("div", { className: "react-train-actions" },
          actionControl(h("button", {
            className: "primary react-action-button",
            disabled: Boolean(trainReason),
            title: trainReason || "Train detector op NVIDIA GPU",
            onClick: () => this.startJob("7"),
          }, gpu ? safeText(gpu.progress_label, "GPU-training…") : "NVIDIA GPU trainen")),
          actionControl(h("button", {
            className: "react-action-button",
            disabled: Boolean(trainReason),
            title: trainReason || "Train detector op CPU",
            onClick: () => this.startJob("8"),
          }, cpu ? safeText(cpu.progress_label, "CPU-training…") : "CPU")),
          trainReason ? h("small", { className: "action-disabled-reason react-train-reason", role: "note" }, `Niet beschikbaar: ${trainReason}`) : null
        )
      )
    );
  }

  renderSplitEditor(data: WorkbenchPayload) {
    const preview = data.preview;
    if (!preview || !preview.split_plan) {
      return h("section", { className: "card" },
        h("div", { className: "notice warning compact" }, "Splitinformatie ontbreekt nog. Vernieuw de pagina of bouw de dataset opnieuw.")
      );
    }
    const previewTotals = preview.totals || {};
    const previewSources = Array.isArray(preview.sources) ? preview.sources : [];
    const readyCount = numberValue(previewTotals.ready_sources);
    const targets = this.state.splitTargets;
    const total = targets.train + targets.val + targets.test;
    const countsValid = total === readyCount && (readyCount === 0 || targets.train >= 1);
    const fixedCounts: SplitTargets = { train: 0, val: 0, test: 0 };
    Object.keys(this.state.splitOverrides).forEach(sourceId => {
      const split = this.state.splitOverrides[sourceId];
      if (split) fixedCounts[split] += 1;
    });
    const overrideValid = fixedCounts.train <= targets.train && fixedCounts.val <= targets.val && fixedCounts.test <= targets.test;
    const valid = countsValid && overrideValid;

    const targetEditors = (["train", "val", "test"] as SplitName[]).map(name => h("label", { key: name },
      h("span", null, name === "val" ? "Validation" : name.charAt(0).toUpperCase() + name.slice(1)),
      h("input", {
        type: "number", min: 0, step: 1, value: targets[name],
        onChange: (event: any) => this.updateTarget(name, event.target.value),
      }),
      h("small", { className: "muted" }, `${fixedCounts[name]} handmatig vast`)
    ));

    const sourceRows = previewSources.map(source => {
      const splitControl = source.included ? h("select", {
        value: this.state.splitOverrides[source.source_id] || "",
        className: this.state.splitOverrides[source.source_id] ? "react-manual-split" : "",
        onChange: (event: any) => this.updateOverride(source.source_id, event.target.value),
      },
        h("option", { value: "" }, `Auto → ${source.split || "—"}`),
        h("option", { value: "train" }, "Train"),
        h("option", { value: "val" }, "Validation"),
        h("option", { value: "test" }, "Test")
      ) : "—";
      return h("tr", { key: source.source_id, className: source.ready ? "" : "react-source-excluded" },
        h("td", { className: "mono wrap-anywhere" }, source.source_id),
        h("td", null, source.ready ? h("span", { className: "pill ok" }, "✓ Klaar") : h("span", { className: "pill warn" }, "Uitgesloten")),
        h("td", null, splitControl),
        h("td", null, source.candidate_total),
        h("td", { className: "ok" }, source.positive),
        h("td", null, source.negative),
        h("td", { className: source.pending ? "warn" : "" }, source.pending),
        h("td", null, h("a", { className: "button small-button", href: `/detection-review/${encodeURIComponent(source.source_id)}` }, "Bekijken"))
      );
    });

    const warning = preview.split_plan.warnings && preview.split_plan.warnings.length
      ? h("div", { className: "notice warning" }, preview.split_plan.warnings.join(" "))
      : null;
    const dirty = this.state.splitDirty
      ? h("div", { className: "notice warning compact" }, "Niet-opgeslagen wijzigingen in de split.")
      : null;

    return h("section", { className: "card react-section-gap" },
      h("div", { className: "react-section-toolbar" },
        h("div", null,
          h("h3", null, "Train / validation / test"),
          h("p", { className: "muted" }, "Pas alleen aan als je een andere verdeling wilt gebruiken.")
        ),
        h("div", { className: "react-split-actions" },
          actionControl(h("button", {
            disabled: Boolean(this.state.mutation),
            title: this.state.mutation ? "Er wordt al een wijziging verwerkt." : "Automatische veilige verdeling toepassen",
            onClick: () => this.saveSplit(true)
          }, "Veilige auto"), this.state.mutation ? "Er wordt al een wijziging verwerkt." : ""),
          actionControl(h("button", {
            className: "primary",
            disabled: Boolean(this.state.mutation) || !this.state.splitDirty || !valid,
            title: this.state.mutation ? "Er wordt al een wijziging verwerkt." : !this.state.splitDirty ? "Er zijn geen niet-opgeslagen splitwijzigingen." : !valid ? "De split-aantallen of handmatige overrides zijn ongeldig." : "Split opslaan",
            onClick: () => this.saveSplit(false)
          }, "Split opslaan"), this.state.mutation ? "Er wordt al een wijziging verwerkt." : !this.state.splitDirty ? "Er zijn geen wijzigingen om op te slaan." : !valid ? `Train + validation + test moet exact ${readyCount} zijn en handmatige overrides moeten binnen de gekozen aantallen passen.` : "")
        )
      ),
      h("div", { className: "react-split-targets" },
        ...targetEditors,
        h("div", { className: `react-split-total ${valid ? "ok" : "bad"}` },
          h("span", null, "Totaal"),
          h("strong", null, `${total} / ${readyCount}`),
          h("small", null, valid ? "Geldig" : "Aantallen/overrides kloppen niet")
        )
      ),
      warning,
      dirty,
      h("div", { className: "table-wrap react-source-table-wrap" },
        h("table", { className: "react-source-table" },
          h("thead", null, h("tr", null,
            h("th", null, "Bron"), h("th", null, "Klaar"), h("th", null, "Split"),
            h("th", null, "ROI"), h("th", null, "Positief"), h("th", null, "Negatief"),
            h("th", null, "Open"), h("th", null, "Review")
          )),
          h("tbody", null, ...sourceRows)
        )
      )
    );
  }

  renderReadiness(data: WorkbenchPayload) {
    const state = data.readiness;
    return h("section", { className: "card react-section-gap" },
      h("div", { className: "react-section-toolbar" },
        h("div", null,
          h("h3", null, "Datasetstatus"),
          h("strong", null, datasetFriendlyName(data.project && data.project.name, state)),
          state.dataset_id ? h("p", { className: "mono muted wrap-anywhere compact" }, state.dataset_id) : null
        ),
        h("span", { className: `pill ${state.training_ready ? "ok" : "warn"}` }, state.training_ready ? "KLAAR" : "NIET KLAAR")
      ),
      h("div", { className: "react-metric-grid" },
        h(Metric, { label: "Beelden", value: state.image_count }),
        h(Metric, { label: "Positieve boxes", value: state.annotation_count }),
        h(Metric, { label: "Train / val / test", value: `${state.splits.train} / ${state.splits.val} / ${state.splits.test}` }),
        h(Metric, { label: "Gevalideerd", value: formatWhen(state.validated_at) })
      ),
      h("div", { className: "react-check-grid" },
        h(StatusCheck, { ok: state.app_valid, label: "Datasetcontrole", good: "Structuur en kaders geldig", bad: "Nog niet gevalideerd" }),
        h(StatusCheck, { ok: state.paddlex_valid, label: "Trainingscontrole", good: "Dataset wordt door de trainer geaccepteerd", bad: "Nog niet gevalideerd" }),
        h(StatusCheck, { ok: state.split_current, label: "Verdeling", good: "Train / validation / test is actueel", bad: "Verdeling of review gewijzigd; opnieuw bouwen" }),
        h(StatusCheck, { ok: state.ready_marker_valid, soft: !state.ready_marker_valid, label: "Trainingsklaar", good: "Dataset is klaar voor training", bad: "Valideer de dataset opnieuw" })
      ),
      !state.training_ready && Array.isArray(state.blockers) ? state.blockers.map((item, index) => h("div", { key: `b-${index}`, className: "notice warning compact prerequisite-message" },
        h("strong", null, item.message), h("span", null, ` Volgende stap: ${item.next_step}`)
      )) : null,
      (Array.isArray(state.warnings) ? state.warnings : []).map((warning, index) => h("div", { key: `w-${index}`, className: "notice warning compact" }, warning)),
      (Array.isArray(state.errors) ? state.errors : []).map((error, index) => h("div", { key: `e-${index}`, className: "notice error compact" }, error))
    );
  }

  renderJobs(data: WorkbenchPayload) {
    const jobs = Array.isArray(data.jobs) ? data.jobs : [];
    return h("section", { className: "card react-section-gap" },
      h("div", { className: "react-section-toolbar" },
        h("div", null, h("h3", null, "Recente Stap 4-taken"), h("p", { className: "muted" }, "Logs blijven beschikbaar in de compacte terminalbalk onderaan.")),
        h("a", { href: "/jobs/manage" }, "Wachtrijbeheer")
      ),
      jobs.length ? jobs.slice(0, 10).map(job => h(JobRow, { key: job.job_id, job })) : h("p", { className: "muted" }, "Nog geen build-, validate- of trainingstaken voor dit project.")
    );
  }

  render() {
    if (this.state.loading && !this.state.data) {
      return h("section", { className: "card react-bootstrap-state" },
        h("h3", null, "Laden…"),
        h("div", { className: "react-loading-line" })
      );
    }
    const data = this.state.data;
    if (!data) {
      return h("section", { className: "card" },
        h("div", { className: "notice error" }, this.state.error || "Stap 4 kon niet worden geladen."),
        h("button", { className: "primary", onClick: () => this.refresh(true) }, "Opnieuw proberen")
      );
    }

    const workerOnline = Boolean(data.worker && data.worker.online);
    const jobs = Array.isArray(data.jobs) ? data.jobs : [];
    const failedLatest = jobs.find(job => job.status === "failed");

    return h("div", { className: "react-localization-workbench" },
      !workerOnline ? h("div", { className: "notice warning compact" }, "De achtergrondworker is niet bereikbaar. Taken kunnen pas starten zodra de worker weer online is.") : null,
      this.state.error ? h("div", { className: "notice error" }, this.state.error) : null,
      failedLatest && !data.active_job ? h("div", { className: "notice warning" },
        h("strong", null, "Laatste taak mislukt. "),
        h("span", null, `${failedLatest.action_name}. Open de terminalbalk onderaan voor de volledige foutuitvoer.`)
      ) : null,
      this.renderPhaseActions(data),
      this.renderReadiness(data),
      this.renderSplitEditor(data)
    );
  }
}

const mount = document.getElementById("react-localization-workbench");
if (mount) {
  const app = h(WorkbenchBoundary, null, h(LocalizationWorkbench, null));
  ReactDOM.render(app, mount);
}
