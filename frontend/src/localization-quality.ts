/* Localization quality / gate workbench. */
declare const React: any;
declare const ReactDOM: any;
const hq = React.createElement;
const QualityComponent = React.Component;

type QualityJob = {
  job_id: string; action_id: string; action_name: string; status: string;
  progress_percent?: number; progress_label?: string;
};

type Metrics = Record<string, any>;
type Evaluation = { evaluation_id?: string; model_id?: string; dataset_id?: string; split?: string; metrics?: Metrics } | null;
type DiagnosticFilter = "all" | "fp" | "fn" | "tp";
type DiagnosticCauseFilter = "all" | "localization" | "duplicate" | "unmatched" | "negative_region";

type QualityPayload = {
  schema_version: number;
  generated_at: string;
  project: { project_id: string; name: string; use_case_id: string };
  gate: Record<string, any>;
  thresholds: Record<string, any>;
  selection: Record<string, any>;
  datasets: Array<Record<string, any>>;
  models: Array<Record<string, any>>;
  evaluations: Array<Record<string, any>>;
  baseline: Evaluation;
  trained: Evaluation;
  comparison: Record<string, any> | null;
  diagnostics: Record<string, any> | null;
  active_model: Record<string, any> | null;
  jobs: QualityJob[];
  worker: { online?: boolean; current_job_id?: string; heartbeat_age_seconds?: number };
};

type QualityState = {
  data: QualityPayload | null;
  loading: boolean;
  refreshing: boolean;
  error: string;
  mutation: string;
  notice: string;
  detail: Record<string, any> | null;
  detailLoading: boolean;
  detailError: string;
  detailEvaluationId: string;
  detailThreshold: number;
  detailIouThreshold: number;
  detailSplit: string;
  detailSourceId: string;
  detailFilter: DiagnosticFilter;
  detailCauseFilter: DiagnosticCauseFilter;
  detailSelected: Record<string, any> | null;
  detailMutation: string;
};

function qnum(value: any): number { const n = Number(value); return Number.isFinite(n) ? n : 0; }
function qpct(value: any): string { return `${(qnum(value) * 100).toFixed(1)}%`; }
function qfixed(value: any, digits = 3): string { return qnum(value).toFixed(digits); }
function qtext(value: any, fallback = "—"): string { return value === null || value === undefined || value === "" ? fallback : String(value); }
function qwhen(value: any): string {
  if (!value) return "onbekende datum";
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString("nl-NL", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).replace(",", "");
}
function qdatasetName(item: any, projectName: string): string {
  return `${qtext(projectName, "Project")} · veld-dataset · ${qwhen(item && item.created_at)}`;
}
function qmodelName(item: any, projectName: string): string {
  const model = qtext(item && item.model_name, "veld-detector");
  const device = item && item.device ? ` · ${String(item.device).toUpperCase()}` : "";
  return `${qtext(projectName, "Project")} · ${model}${device} · ${qwhen((item && (item.registered_at || item.created_at)) || "")}`;
}
function qevalName(item: any): string {
  const kind = String((item && item.kind) || "evaluatie").toLowerCase() === "baseline" ? "Baseline" : "Getraind";
  return `${kind} · ${qwhen(item && item.created_at)}`;
}
function qAction(button: any, reason = "") {
  return hq("div", { className: "quality-action-control" }, button, reason ? hq("small", { className: "action-disabled-reason", role: "note" }, `Niet beschikbaar: ${reason}`) : null);
}
function gateTone(state: string): string {
  if (state === "open") return "ok";
  if (state === "awaiting_activation") return "warn";
  return "bad";
}
function metricCard(label: string, value: string, tone = "") {
  return hq("div", { className: `quality-metric ${tone}` }, hq("span", { className: "muted" }, label), hq("strong", null, value));
}
function evaluationMetrics(evaluation: Evaluation) {
  const m = evaluation && evaluation.metrics ? evaluation.metrics : {};
  return hq("div", { className: "quality-metric-grid" },
    metricCard("Precision", qpct(m.precision)),
    metricCard("Recall", qpct(m.recall)),
    metricCard("Mean IoU", qfixed(m.mean_iou)),
    metricCard(m.auto_accept_iou_threshold === null || m.auto_accept_iou_threshold === undefined
      ? "Strakke referentiematch" : `Referentie-match ≥ IoU ${qfixed(m.auto_accept_iou_threshold, 2)}`, qpct(m.auto_accept_rate)),
    metricCard("FP / beeld", qfixed(m.false_positives_per_image, 2)),
    metricCard("Voorspellingen", qtext(m.scored_predictions, "0"))
  );
}
function causeLabel(cause: string): string {
  if (cause === "duplicate") return "Dubbele detectie";
  if (cause === "localization") return "Kader ligt bij een veld, maar IoU is te laag";
  if (cause === "negative_region") return "Overlap met expliciet negatief gebied";
  return "Geen ground-truth match";
}
function detailKindLabel(kind: string): string {
  if (kind === "tp") return "Correct gevonden veld (TP)";
  if (kind === "fn") return "Gemist referentieveld (FN)";
  return "Onjuiste / unmatched detectie (FP)";
}

class QualityBoundary extends QualityComponent {
  state = { failed: false, message: "" };
  componentDidCatch(error: any) {
    const message = error && error.message ? String(error.message) : String(error || "Onbekende renderfout");
    console.error("Localization quality render failed", error);
    this.setState({ failed: true, message });
  }
  render() {
    if (this.state.failed) return hq("div", { className: "notice error" },
      hq("strong", null, "Stap 5 kon niet worden weergegeven."),
      hq("div", { className: "mono compact" }, this.state.message || "Onbekende renderfout")
    );
    return this.props.children;
  }
}

class LocalizationQuality extends QualityComponent {
  state: QualityState;
  pollTimer: number | null;
  unmounted: boolean;
  pageKey: string;

  constructor(props: any) {
    super(props);
    this.state = {
      data: null, loading: true, refreshing: false, error: "", mutation: "", notice: "",
      detail: null, detailLoading: false, detailError: "", detailEvaluationId: "",
      detailThreshold: 0.25, detailIouThreshold: 0.75, detailSplit: "val", detailSourceId: "", detailFilter: "all", detailCauseFilter: "all",
      detailSelected: null, detailMutation: "",
    };
    this.pollTimer = null; this.unmounted = false;
    this.pageKey = String((props && props.pageKey) || "localization-evaluate");
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
  visibilityHandler = () => { if (!document.hidden) this.refresh(false); };
  scheduleRefresh(data: QualityPayload | null) {
    if (this.unmounted) return;
    if (this.pollTimer !== null) window.clearTimeout(this.pollTimer);
    const active = Boolean(data && (Array.isArray(data.jobs) ? data.jobs : []).some(job => job.status === "pending" || job.status === "running"));
    const delay = document.hidden ? 30000 : active ? 2500 : 12000;
    this.pollTimer = window.setTimeout(() => this.refresh(false), delay);
  }
  detailIdentity(data: QualityPayload | null): string {
    return String(data && data.trained && data.trained.evaluation_id || "");
  }
  defaultDetailThreshold(data: QualityPayload | null): number {
    const pipeline = data && data.diagnostics && data.diagnostics.improvement_pipeline;
    const calibrated = qnum(pipeline && pipeline.calibration && pipeline.calibration.diagnostic_threshold);
    if (calibrated > 0) return calibrated;
    const recommended = qnum(data && data.diagnostics && data.diagnostics.recommended_threshold);
    if (recommended > 0) return recommended;
    const value = qnum(data && data.trained && data.trained.metrics && data.trained.metrics.minimum_confidence);
    return value > 0 ? value : 0.25;
  }
  defaultDetailIou(data: QualityPayload | null): number {
    const value = qnum(data && data.trained && data.trained.metrics && data.trained.metrics.iou_threshold);
    return value > 0 ? value : 0.75;
  }
  syncDetails(data: QualityPayload, force = false) {
    const evaluationId = this.detailIdentity(data);
    if (!evaluationId) {
      if (this.state.detail || this.state.detailEvaluationId) this.setState({ detail: null, detailEvaluationId: "", detailSourceId: "", detailSelected: null, detailError: "" });
      return;
    }
    if (force || evaluationId !== this.state.detailEvaluationId) {
      const threshold = this.defaultDetailThreshold(data);
      this.loadDetails(data, threshold, "val", true, this.defaultDetailIou(data));
    }
  }
  async refresh(initial: boolean) {
    if (!initial && this.state.refreshing) return;
    if (this.pollTimer !== null) { window.clearTimeout(this.pollTimer); this.pollTimer = null; }
    this.setState(initial ? { loading: true, error: "" } : { refreshing: true, error: "" });
    try {
      const response = await fetch("/api/v2/localization/quality", { cache: "no-store" });
      if (!response.ok) throw new Error(`Status ophalen mislukt (${response.status})`);
      const data = await response.json() as QualityPayload;
      if (!this.unmounted) {
        const previousEvaluation = this.state.detailEvaluationId;
        this.setState({ data, loading: false, refreshing: false, error: "" }, () => {
          if (!this.unmounted && this.detailIdentity(data) && this.detailIdentity(data) !== previousEvaluation) this.syncDetails(data, true);
        });
        this.scheduleRefresh(data);
      }
    } catch (error: any) {
      if (!this.unmounted) {
        this.setState({ loading: false, refreshing: false, error: error && error.message ? error.message : String(error) });
        this.scheduleRefresh(this.state.data);
      }
    }
  }
  async startJob(actionId: string) {
    if (this.state.mutation) return;
    this.setState({ mutation: actionId, error: "", notice: "" });
    try {
      const response = await fetch("/api/v2/jobs", {
        method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ action_id: actionId, options: {} })
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `Taak starten mislukt (${response.status})`);
      await this.refresh(false);
    } catch (error: any) {
      this.setState({ error: error && error.message ? error.message : String(error) });
    } finally { this.setState({ mutation: "" }); }
  }
  async saveSelection(patch: Record<string, any>) {
    if (this.state.mutation) return;
    this.setState({ mutation: "selection", error: "", notice: "", detailSelected: null });
    try {
      const response = await fetch("/api/v2/localization/selection", {
        method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(patch)
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `Selectie opslaan mislukt (${response.status})`);
      if (payload.quality && !this.unmounted) {
        const quality = payload.quality as QualityPayload;
        this.setState({ data: quality, loading: false, refreshing: false }, () => this.syncDetails(quality, true));
      } else await this.refresh(false);
    } catch (error: any) {
      this.setState({ error: error && error.message ? error.message : String(error) });
    } finally { this.setState({ mutation: "" }); }
  }
  async loadDetails(data: QualityPayload, threshold: number, split = "val", force = false, iouThreshold?: number): Promise<boolean> {
    const evaluationId = this.detailIdentity(data);
    if (!evaluationId) return false;
    const normalizedThreshold = Math.max(0, Math.min(1, Number(threshold) || 0));
    const normalizedIou = Math.max(0.05, Math.min(0.95, Number(iouThreshold === undefined ? this.state.detailIouThreshold : iouThreshold) || 0.75));
    if (!force && this.state.detailLoading) return false;
    this.setState({ detailLoading: true, detailError: "", detailThreshold: normalizedThreshold, detailIouThreshold: normalizedIou, detailSplit: split, detailSelected: null });
    try {
      const params = new URLSearchParams({ evaluation_id: evaluationId, threshold: normalizedThreshold.toFixed(4), iou_threshold: normalizedIou.toFixed(4), split });
      const response = await fetch(`/api/v2/localization/quality/details?${params.toString()}`, { cache: "no-store" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `Visuele diagnostiek ophalen mislukt (${response.status})`);
      const detail = payload.details || {};
      const sources = Array.isArray(detail.sources) ? detail.sources : [];
      const previousSource = this.state.detailSourceId;
      const sourceId = sources.some((item: any) => String(item.source_id) === previousSource)
        ? previousSource : String((sources[0] && sources[0].source_id) || "");
      if (!this.unmounted) this.setState({
        detail, detailLoading: false, detailError: "", detailEvaluationId: evaluationId,
        detailThreshold: normalizedThreshold, detailIouThreshold: normalizedIou, detailSplit: split, detailSourceId: sourceId, detailSelected: null,
      });
      return true;
    } catch (error: any) {
      if (!this.unmounted) this.setState({ detailLoading: false, detailError: error && error.message ? error.message : String(error), detailEvaluationId: evaluationId });
      return false;
    }
  }
  async viewThreshold(data: QualityPayload, threshold: number, split = "val") {
    const ok = await this.loadDetails(data, threshold, split, true, this.state.detailIouThreshold);
    if (this.unmounted) return;
    window.requestAnimationFrame(() => {
      const target = document.getElementById("visual-diagnostics");
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    if (!ok && !this.state.detailError) {
      this.setState({ detailError: "De gekozen threshold kon niet worden weergegeven." });
    }
  }
  async addMissingGroundTruth(sourceId: string, item: Record<string, any>) {
    if (this.state.detailMutation || !Array.isArray(item.box) || item.box.length !== 4) return;
    this.setState({ detailMutation: "ground-truth", detailError: "", notice: "" });
    try {
      const response = await fetch(`/api/detection-review/${encodeURIComponent(sourceId)}/manual`, {
        method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({
          box: item.box,
          reason_code: "other",
          notes: "Toegevoegd vanuit Stap 5 detectiediagnostiek: deze unmatched modeldetectie is expliciet bevestigd als echt veld."
        })
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `Ground truth toevoegen mislukt (${response.status})`);
      this.setState({
        notice: "Kader toegevoegd aan de ground truth. De huidige dataset/evaluatie is hierdoor verouderd: rond de Detection Review opnieuw af en bouw daarna de dataset opnieuw.",
        detailSelected: null,
      });
      const currentData = this.state.data;
      if (currentData) await this.loadDetails(currentData, this.state.detailThreshold, this.state.detailSplit, true);
      await this.refresh(false);
    } catch (error: any) {
      this.setState({ detailError: error && error.message ? error.message : String(error) });
    } finally { this.setState({ detailMutation: "" }); }
  }
  renderSelection(data: QualityPayload) {
    const selection = data.selection || {};
    const datasets = Array.isArray(data.datasets) ? data.datasets : [];
    const models = Array.isArray(data.models) ? data.models : [];
    const evaluations = Array.isArray(data.evaluations) ? data.evaluations : [];
    const projectName = qtext(data.project && data.project.name, "Project");
    const baselines = evaluations.filter((item: any) => item.kind === "baseline" && (!selection.evaluation_dataset_id || item.dataset_id === selection.evaluation_dataset_id));
    const trained = evaluations.filter((item: any) => item.kind === "trained" && (!selection.evaluation_dataset_id || item.dataset_id === selection.evaluation_dataset_id) && (!selection.evaluation_model_id || item.model_id === selection.evaluation_model_id));
    return hq("section", { className: "card quality-selection section-gap" },
      hq("div", { className: "toolbar" },
        hq("div", null, hq("h3", null, "Evaluatieselectie"), hq("p", { className: "muted" }, "Kies de dataset en detector die je wilt beoordelen. De actieve detector verandert pas wanneer je hem apart activeert.")),
        hq("a", { className: "button ghost", href: "/process/artifacts" }, "Data & modellen")
      ),
      hq("div", { className: "quality-select-grid" },
        hq("label", null, "Dataset om te evalueren", hq("select", {
          value: qtext(selection.evaluation_dataset_id, ""), disabled: this.state.mutation === "selection",
          onChange: (event: any) => this.saveSelection({ evaluation_dataset_id: event.target.value, baseline_evaluation_id: "", trained_evaluation_id: "" })
        }, datasets.map((item: any) => hq("option", { key: item.dataset_id, value: item.dataset_id }, `${qdatasetName(item, projectName)} · ${item.image_count || 0} beelden`)))),
        hq("label", null, "Detector om te evalueren", hq("select", {
          value: qtext(selection.evaluation_model_id, ""), disabled: this.state.mutation === "selection",
          onChange: (event: any) => this.saveSelection({ evaluation_model_id: event.target.value, trained_evaluation_id: "" })
        }, hq("option", { value: "" }, "Alleen baseline"), models.map((item: any) => hq("option", { key: item.model_id, value: item.model_id }, `${qmodelName(item, projectName)}${item.active ? " · ACTIEF" : ""}`)))),
        hq("label", null, "Baseline-evaluatie", hq("select", {
          value: qtext(selection.baseline_evaluation_id, ""), onChange: (event: any) => this.saveSelection({ baseline_evaluation_id: event.target.value })
        }, hq("option", { value: "" }, "Nieuwste passende"), baselines.map((item: any) => hq("option", { key: item.evaluation_id, value: item.evaluation_id }, qevalName(item))))),
        hq("label", null, "Trained-evaluatie", hq("select", {
          value: qtext(selection.trained_evaluation_id, ""), onChange: (event: any) => this.saveSelection({ trained_evaluation_id: event.target.value })
        }, hq("option", { value: "" }, "Nieuwste passende"), trained.map((item: any) => hq("option", { key: item.evaluation_id, value: item.evaluation_id }, qevalName(item)))))
      )
    );
  }
  isBusy(actionId: string): boolean {
    const jobs = this.state.data && Array.isArray(this.state.data.jobs) ? this.state.data.jobs : [];
    return jobs.some(job => job.action_id === actionId && (job.status === "pending" || job.status === "running")) || this.state.mutation === actionId;
  }
  renderGate(data: QualityPayload) {
    const gate = data.gate || {};
    const state = String(gate.state || (gate.ready ? "open" : "closed"));
    return hq("section", { className: `card quality-gate quality-gate-${gateTone(state)}` },
      hq("div", { className: "toolbar" },
        hq("div", null, hq("span", { className: "eyebrow" }, "DETECTION GATE"), hq("h2", null, state === "open" ? "OPEN" : "GESLOTEN")),
        hq("span", { className: `pill ${gateTone(state)}` }, state.replace(/_/g, " ").toUpperCase())
      ),
      hq("p", null, qtext(gate.reason)),
      gate.evaluation_id ? hq("p", { className: "mono muted" }, gate.evaluation_id) : null,
      gate.model_id ? hq("p", { className: "muted" }, "Model: ", hq("span", { className: "mono" }, gate.model_id)) : null,
      Array.isArray(gate.failures) && gate.failures.length ? hq("ul", { className: "quality-failures" }, gate.failures.map((x: string) => hq("li", { key: x }, x))) : null
    );
  }
  renderEvaluation(title: string, evaluation: Evaluation) {
    if (!evaluation) return hq("section", { className: "card" }, hq("h3", null, title), hq("p", { className: "muted" }, "Nog geen evaluatie."));
    return hq("section", { className: "card" },
      hq("div", { className: "toolbar" }, hq("h3", null, title), hq("span", { className: "pill" }, qtext(evaluation.split).toUpperCase())),
      evaluationMetrics(evaluation),
      hq("p", { className: "mono muted compact" }, qtext(evaluation.evaluation_id)),
      hq("p", { className: "muted compact" }, `Confidence ≥ ${qfixed((evaluation.metrics || {}).minimum_confidence, 2)} · ${qtext((evaluation.metrics || {}).evaluated_images, "0")} beelden · ${qtext((evaluation.metrics || {}).ground_truth_rois, "0")} referentiekaders`)
    );
  }
  async focusRecommendedAction(data: QualityPayload) {
    const pipeline = data.diagnostics && data.diagnostics.improvement_pipeline || {};
    const action = pipeline.recommended_action || {};
    const calibration = pipeline.calibration || {};
    const threshold = qnum(calibration.diagnostic_threshold) || this.defaultDetailThreshold(data);
    const split = String(action.focus_split || "val");
    const filter = String(action.focus_filter || "all") as DiagnosticFilter;
    const cause = String(action.focus_cause || "all") as DiagnosticCauseFilter;
    this.setState({ detailFilter: filter, detailCauseFilter: cause, detailSelected: null });
    await this.loadDetails(data, threshold, split, true, this.state.detailIouThreshold || this.defaultDetailIou(data));
    if (this.unmounted) return;
    window.requestAnimationFrame(() => {
      const target = document.getElementById("visual-diagnostics");
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
  renderImprovementAssistant(data: QualityPayload) {
    const diag = data.diagnostics || {};
    const pipeline = diag.improvement_pipeline || null;
    if (!data.trained) return hq("section", { className: "card improvement-assistant section-gap" },
      hq("span", { className: "eyebrow" }, "MODEL IMPROVEMENT ASSISTANT"),
      hq("h2", null, "Nog geen getrainde detector geëvalueerd"),
      hq("p", { className: "muted" }, "Train/selecteer eerst een detector en voer daarna Evalueren & diagnose uit. De assistent bepaalt vervolgens automatisch welke stap het meeste effect heeft.")
    );
    if (!pipeline) return hq("section", { className: "card improvement-assistant section-gap" },
      hq("span", { className: "eyebrow" }, "MODEL IMPROVEMENT ASSISTANT"),
      hq("h2", null, "Slimme diagnose nog niet opgebouwd"),
      hq("p", null, "De bestaande evaluatie bevat nog de oude diagnostiek. Voer één nieuwe evaluatie uit; opnieuw trainen is niet nodig."),
      hq("div", { className: "notice info" }, "De nieuwe evaluatie gebruikt TRAIN voor sanity-checks, VALIDATION voor confidence-keuze en TEST alleen als hold-out eindmeting.")
    );
    const primary = pipeline.primary_diagnosis || {};
    const action = pipeline.recommended_action || {};
    const calibration = pipeline.calibration || {};
    const stages = Array.isArray(pipeline.stages) ? pipeline.stages : [];
    const breakdown = pipeline.error_breakdown || {};
    const topSources = Array.isArray(pipeline.top_problem_sources) ? pipeline.top_problem_sources : [];
    const pipelineModelId = String(diag.model_id || (data.trained && data.trained.model_id) || "");
    const gateReady = Boolean(data.gate && data.gate.ready && pipelineModelId && String(data.gate.model_id || "") === pipelineModelId);
    const status = gateReady ? "passed" : String(pipeline.status || "improve");
    const tone = status === "passed" ? "ok" : status === "ready_for_final_test" ? "warn" : "bad";
    const displayLabel = gateReady ? "Finale test geslaagd" : qtext(primary.label, qtext(pipeline.headline, "Model analyseren"));
    const displaySummary = gateReady ? "De geselecteerde detector haalt de actuele Detection Gate op de hold-out test. De volgende stap is het model activeren." : qtext(primary.summary, qtext(pipeline.summary));
    return hq("section", { className: `card improvement-assistant section-gap assistant-${tone}` },
      hq("div", { className: "toolbar improvement-head" },
        hq("div", null,
          hq("span", { className: "eyebrow" }, "MODEL IMPROVEMENT ASSISTANT"),
          hq("h2", null, displayLabel),
          hq("p", null, displaySummary)
        ),
        hq("span", { className: `pill ${tone}` }, status === "passed" ? "GATE GESLAAGD" : status === "ready_for_final_test" ? "KLAAR VOOR TEST" : "VERBETEREN")
      ),
      hq("div", { className: "improvement-stage-grid" }, stages.map((stage: any) => hq("div", { className: `improvement-stage stage-${qtext(stage.status, "blocked")}`, key: qtext(stage.id) },
        hq("div", { className: "stage-title" }, hq("strong", null, qtext(stage.title)), hq("span", { className: `pill ${stage.status === "pass" ? "ok" : stage.status === "action" || stage.status === "ready" ? "warn" : "bad"}` }, qtext(stage.status).toUpperCase())),
        hq("small", null, qtext(stage.summary))
      ))),
      hq("div", { className: "improvement-next" },
        hq("span", { className: "eyebrow" }, "AANBEVOLEN VOLGENDE STAP"),
        hq("h3", null, gateReady ? "Field detector activeren" : qtext(action.label, "Bekijk validatiefouten")),
        hq("p", null, gateReady ? "De kwaliteit is voldoende. Activeer dit model in Stap 6 voordat je nieuwe bronnen opnieuw laat detecteren." : qtext(action.description)),
        hq("div", { className: "actions" },
          gateReady
            ? hq("a", { className: "button primary", href: "/process/localization-register" }, "Ga naar Stap 6 · activeren")
            : hq("button", { className: "primary", disabled: this.state.detailLoading, onClick: () => this.focusRecommendedAction(data) }, this.state.detailLoading ? "Diagnose laden…" : qtext(action.label, "Open diagnose")),
          hq("span", { className: "muted" }, calibration.production_ready
            ? `Production-confidence ${qfixed(calibration.production_threshold, 2)} is op VALIDATION gekozen.`
            : `Diagnostische confidence ${qfixed(calibration.diagnostic_threshold, 2)} · geen production-confidence beschikbaar.`)
        )
      ),
      hq("div", { className: "improvement-evidence-grid" },
        hq("div", null,
          hq("strong", null, "Waarom dit advies?"),
          Array.isArray(primary.evidence) && primary.evidence.length ? hq("ul", null, primary.evidence.map((item: string, index: number) => hq("li", { key: index }, item))) : hq("p", { className: "muted" }, "Nog geen aanvullende evidence.")
        ),
        hq("div", null,
          hq("strong", null, "Validation-fouten"),
          hq("p", { className: "compact" }, `Near-match ${qtext(breakdown.near_match, "0")} · unmatched FP ${qtext(breakdown.unmatched, "0")} · duplicates ${qtext(breakdown.duplicate, "0")} · negatieve regio ${qtext(breakdown.negative_region, "0")} · FN ${qtext(breakdown.false_negatives, "0")}`),
          topSources.length ? hq("small", { className: "muted" }, `Slechtste bronnen: ${topSources.slice(0, 3).map((item: any) => `${qtext(item.source_id)} (FP ${qtext(item.fp, "0")}, FN ${qtext(item.fn, "0")})`).join(" · ")}`) : null
        )
      )
    );
  }
  renderMetricHelp() {
    const entries = [
      ["TP (true positive)", "Een voorspeld kader dat voldoende overlapt met precies één echt referentiekader."],
      ["FP (false positive)", "Een modelkader zonder geldige match. Dit kan een echte fout, near-match, duplicate, negatieve regio of ontbrekende annotation zijn."],
      ["FN (false negative)", "Een echt referentieveld waarvoor geen geldige modelmatch is gevonden."],
      ["Precision", "Van alle detecties: welk deel is correct? Lage precision betekent relatief veel false positives."],
      ["Recall", "Van alle echte velden: welk deel is gevonden? Lage recall betekent dat het model echte velden mist."],
      ["IoU", "Intersection over Union: overlap tussen voorspeld kader en ground truth. 1,00 is exact; onder de ingestelde IoU-drempel telt de match niet als TP."],
      ["Mean IoU", "Gemiddelde IoU van de detecties die al als correcte match gelden. Dit zegt dus niets over volledig gemiste velden."],
      ["FP / beeld", "Gemiddeld aantal onjuiste detecties per bronafbeelding. Voor de gate moet dit zeer laag zijn."],
      ["Confidence", "Zekerheidsscore van het model. Hoger filtert meer detecties weg: vaak minder FP, maar meestal ook meer FN."],
      ["Strakke referentiematch", "Aandeel referentiekaders dat de extra strenge referentie-IoU haalt. Dit is géén percentage van alle output dat automatisch akkoord is."],
      ["Near-match", "De detector zit bij een echt veld, maar de box is te verschoven/groot/klein om de IoU-drempel te halen."],
      ["Duplicate", "Een extra modelkader rond een ground-truth veld dat al door een betere voorspelling is gematcht."],
      ["Unmatched FP", "Een detectie met vrijwel geen overlap met een referentieveld. Controleer: echte model-fout of ontbrekend label?"],
    ];
    return hq("details", { className: "card metric-help-panel section-gap" },
      hq("summary", null, "Wat betekenen deze waarden?"),
      hq("div", { className: "metric-help-grid" }, entries.map(([term, explanation]) => hq("div", { key: term }, hq("strong", null, term), hq("span", null, explanation))))
    );
  }
  renderDiagnosticLegend() {
    return hq("div", { className: "diagnostic-legend", "aria-label": "Legenda detectiediagnostiek" },
      hq("span", null, hq("i", { className: "legend-swatch tp" }), "Groen: correct gevonden (TP)"),
      hq("span", null, hq("i", { className: "legend-swatch fp" }), "Rood: detectie zonder geldige match (FP)"),
      hq("span", null, hq("i", { className: "legend-swatch fn" }), "Oranje: echt veld dat is gemist (FN)")
    );
  }
  renderSelectedDetail(source: Record<string, any>) {
    const item = this.state.detailSelected;
    if (!item) return hq("div", { className: "diagnostic-inspector-empty muted" }, "Klik op een kader in het beeld om te zien waarom het als TP, FP of FN is geteld.");
    const kind = String(item.kind || "");
    const cause = String(item.cause || "");
    let explanation = "";
    if (kind === "tp") explanation = "Deze modeldetectie overlapt voldoende met één ground-truth kader en telt daarom als correct.";
    else if (kind === "fn") explanation = qnum(item.best_prediction_iou) > 0
      ? "Dit ground-truth veld is niet goed genoeg gematcht. Er ligt wel een voorspelling in de buurt; vergelijk de kaders en IoU."
      : "Voor dit ground-truth veld is bij deze confidence-drempel geen overlappende voorspelling gevonden.";
    else if (cause === "duplicate") explanation = "Een ander modelkader heeft hetzelfde ground-truth veld al beter gematcht. Dit extra kader telt als false positive en wijst vaak op NMS/duplicate-detecties.";
    else if (cause === "negative_region") explanation = "Dit modelkader overlapt met een regio die in Detection Review expliciet als negatief/niet te detecteren is vastgelegd.";
    else if (cause === "localization") explanation = "Het model zit in de buurt van een echt veld, maar het kader overlapt niet genoeg om de IoU-drempel te halen. Dit is vooral een positionerings/groottefout.";
    else explanation = "Dit modelkader heeft vrijwel geen overlap met de huidige ground truth. Controleer visueel of het écht geen veld is, of dat er een annotation ontbreekt.";

    return hq("div", { className: `diagnostic-inspector kind-${kind}` },
      hq("div", { className: "toolbar compact-toolbar" }, hq("strong", null, detailKindLabel(kind)), kind === "fp" ? hq("span", { className: "pill bad" }, causeLabel(cause)) : null),
      hq("p", null, explanation),
      hq("div", { className: "diagnostic-facts" },
        kind !== "fn" ? hq("span", null, "Confidence ", hq("strong", null, qfixed(item.score, 3))) : null,
        kind === "tp" ? hq("span", null, "IoU ", hq("strong", null, qfixed(item.iou, 3))) : null,
        kind === "fp" ? hq("span", null, "Beste truth-IoU ", hq("strong", null, qfixed(item.best_truth_iou, 3))) : null,
        kind === "fn" ? hq("span", null, "Beste prediction-IoU ", hq("strong", null, qfixed(item.best_prediction_iou, 3))) : null
      ),
      hq("div", { className: "actions diagnostic-item-actions" },
        kind === "fp" && cause === "unmatched" ? hq("button", {
          className: "primary", disabled: Boolean(this.state.detailMutation),
          title: "Alleen gebruiken wanneer het rode kader werkelijk een veld is dat in de ground truth ontbreekt.",
          onClick: () => this.addMissingGroundTruth(String(source.source_id || ""), item)
        }, this.state.detailMutation ? "Toevoegen…" : "Dit is wél een echt veld → voeg toe aan ground truth") : null,
        hq("a", { className: "button ghost", href: `/detection-review/${encodeURIComponent(String(source.source_id || ""))}` }, "Open deze bron in Detection Review")
      ),
      kind === "fp" && cause === "unmatched" ? hq("small", { className: "muted" }, "Gebruik de toevoegknop alleen als je op het bronbeeld duidelijk ziet dat dit een echt veld is. Anders is rood hier juist een echte model-fout.") : null
    );
  }
  renderDiagnosticOverlay(source: Record<string, any>) {
    const width = Math.max(1, qnum(source.image_width));
    const height = Math.max(1, qnum(source.image_height));
    const filter = this.state.detailFilter;
    const selected = this.state.detailSelected;
    const boxes: any[] = [];
    const addRect = (item: any, kind: string, index: number) => {
      const box = Array.isArray(item.box) ? item.box : [];
      if (box.length !== 4) return;
      const x = qnum(box[0]), y = qnum(box[1]), w = Math.max(1, qnum(box[2]) - x), h = Math.max(1, qnum(box[3]) - y);
      boxes.push(hq("rect", {
        key: `${kind}-${index}`, x, y, width: w, height: h,
        className: `diagnostic-box ${kind}${selected === item ? " selected" : ""}`,
        vectorEffect: "non-scaling-stroke", role: "button",
        onClick: () => this.setState({ detailSelected: item }),
      }, hq("title", null, kind === "tp" ? `TP · confidence ${qfixed(item.score, 3)} · IoU ${qfixed(item.iou, 3)}` : kind === "fp" ? `FP · confidence ${qfixed(item.score, 3)} · ${causeLabel(String(item.cause || ""))}` : `FN · beste IoU ${qfixed(item.best_prediction_iou, 3)}`)));
    };
    if (filter === "all" || filter === "tp") (Array.isArray(source.true_positives) ? source.true_positives : []).forEach((item: any, i: number) => addRect(item, "tp", i));
    if (filter === "all" || filter === "fp") {
      const causeFilter = this.state.detailCauseFilter;
      (Array.isArray(source.false_positives) ? source.false_positives : [])
        .filter((item: any) => causeFilter === "all" || String(item.cause || "unmatched") === causeFilter)
        .forEach((item: any, i: number) => addRect(item, "fp", i));
    }
    if (filter === "all" || filter === "fn") (Array.isArray(source.false_negatives) ? source.false_negatives : []).forEach((item: any, i: number) => addRect(item, "fn", i));

    if (selected) {
      const reference = selected.kind === "tp" ? selected.truth_box : selected.kind === "fp" ? selected.nearest_truth_box : selected.best_prediction_box;
      if (Array.isArray(reference) && reference.length === 4) {
        const x = qnum(reference[0]), y = qnum(reference[1]), w = Math.max(1, qnum(reference[2]) - x), h = Math.max(1, qnum(reference[3]) - y);
        boxes.push(hq("rect", { key: "selected-reference", x, y, width: w, height: h, className: "diagnostic-reference", vectorEffect: "non-scaling-stroke" }));
      }
    }
    return hq("svg", { className: "diagnostic-overlay", viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "xMidYMid meet", "aria-label": "TP FP FN overlay" }, boxes);
  }
  renderVisualDiagnostics(data: QualityPayload) {
    if (!data.trained) return hq("section", { id: "visual-diagnostics", className: "card section-gap" }, hq("h3", null, "Waarom faalt de detector?"), hq("p", { className: "muted" }, "Selecteer en evalueer eerst een getrainde detector. Daarna worden TP, FP en FN direct op de testbeelden getekend."));
    if (this.state.detailLoading && !this.state.detail) return hq("section", { id: "visual-diagnostics", className: "card section-gap" }, hq("h3", null, "Waarom faalt de detector?"), hq("p", { className: "muted" }, "Visuele TP/FP/FN-diagnostiek laden…"));
    if (this.state.detailError && !this.state.detail) return hq("section", { id: "visual-diagnostics", className: "card section-gap" },
      hq("h3", null, "Waarom faalt de detector?"), hq("div", { className: "notice warning" }, this.state.detailError),
      hq("button", { onClick: () => this.loadDetails(data, this.state.detailThreshold, this.state.detailSplit, true) }, "Opnieuw proberen")
    );
    const detail = this.state.detail;
    if (!detail) return null;
    const summary = detail.summary || {};
    const sources = Array.isArray(detail.sources) ? detail.sources : [];
    const source = sources.find((item: any) => String(item.source_id) === this.state.detailSourceId) || sources[0] || null;
    const causes = summary.cause_counts || {};
    const splitRows = data.diagnostics && data.diagnostics.splits && data.diagnostics.splits[this.state.detailSplit];
    const thresholdRows = Array.isArray(splitRows) ? splitRows : [];
    const thresholdOptions = Array.from(new Set([this.state.detailThreshold, ...thresholdRows.map((row: any) => Number(row.threshold)).filter((x: number) => Number.isFinite(x))])).sort((a: number, b: number) => a - b);
    return hq("section", { id: "visual-diagnostics", className: "card section-gap diagnostic-workbench" },
      hq("div", { className: "toolbar diagnostic-titlebar" },
        hq("div", null,
          hq("span", { className: "eyebrow" }, "VISUELE DETECTIEDIAGNOSE"),
          hq("h3", null, "Waarom faalt de detector?"),
          hq("p", { className: "muted" }, `Diagnose op ${this.state.detailSplit === "val" ? "VALIDATION" : this.state.detailSplit.toUpperCase()}. Voor modelverbetering gebruiken we standaard VALIDATION; TEST is alleen de hold-out eindmeting.`)
        ),
        hq("div", { className: "diagnostic-control-grid" },
          hq("label", { className: "diagnostic-threshold-control" }, "Split",
            hq("select", {
              value: this.state.detailSplit, disabled: this.state.detailLoading,
              onChange: (event: any) => this.loadDetails(data, this.state.detailThreshold, String(event.target.value), true, this.state.detailIouThreshold)
            }, hq("option", { value: "train" }, "TRAIN"), hq("option", { value: "val" }, "VALIDATION"), hq("option", { value: "test" }, "TEST (hold-out)"))
          ),
          hq("label", { className: "diagnostic-threshold-control" }, "Confidence",
            hq("select", {
              value: String(this.state.detailThreshold), disabled: this.state.detailLoading,
              onChange: (event: any) => this.loadDetails(data, Number(event.target.value), this.state.detailSplit, true, this.state.detailIouThreshold)
            }, thresholdOptions.map((value: number) => hq("option", { key: value, value: String(value) }, value.toFixed(2))))
          ),
          hq("label", { className: "diagnostic-threshold-control" }, "IoU (alleen diagnose)",
            hq("select", {
              value: String(this.state.detailIouThreshold), disabled: this.state.detailLoading,
              title: "Verandert alleen de visualisatie/matching. De Detection Gate zelf blijft de geconfigureerde IoU gebruiken.",
              onChange: (event: any) => this.loadDetails(data, this.state.detailThreshold, this.state.detailSplit, true, Number(event.target.value))
            }, [0.30,0.40,0.50,0.60,0.70,0.75,0.80,0.90].map((value: number) => hq("option", { key: value, value: String(value) }, value.toFixed(2))))
          )
        )
      ),
      this.state.detailError ? hq("div", { className: "notice warning", role: "alert" }, this.state.detailError) : null,
      hq("div", { className: "diagnostic-summary-grid" },
        metricCard("Correct gevonden (TP)", qtext(summary.true_positives, "0"), "ok"),
        metricCard("Onjuiste detecties (FP)", qtext(summary.false_positives, "0"), "bad"),
        metricCard("Gemiste velden (FN)", qtext(summary.false_negatives, "0"), "warn"),
        metricCard("FP per beeld", qfixed(summary.false_positives_per_image, 1), "bad")
      ),
      this.renderDiagnosticLegend(),
      hq("div", { className: "diagnostic-cause-grid" },
        hq("div", null, hq("strong", null, qtext(causes.unmatched, "0")), hq("span", null, "zonder ground-truth match")),
        hq("div", null, hq("strong", null, qtext(causes.localization, "0")), hq("span", null, "kader/IoU-probleem")),
        hq("div", null, hq("strong", null, qtext(causes.duplicate, "0")), hq("span", null, "dubbele detecties")),
        hq("div", null, hq("strong", null, qtext(causes.negative_region, "0")), hq("span", null, "op negatieve regio"))
      ),
      Array.isArray(detail.explanations) && detail.explanations.length ? hq("div", { className: "diagnostic-explanations" }, detail.explanations.map((item: any, index: number) => hq("div", { className: `notice ${item.tone === "warning" ? "warning" : "info"}`, key: index }, qtext(item.text)))) : null,
      hq("div", { className: "diagnostic-filterbar" },
        hq("strong", null, "Toon kaders:"),
        ([['all', 'Alles'], ['fp', 'Alleen rood (FP)'], ['fn', 'Alleen oranje (FN)'], ['tp', 'Alleen groen (TP)']] as Array<[DiagnosticFilter, string]>).map(([key, label]) => hq("button", {
          key, className: this.state.detailFilter === key ? "active" : "", onClick: () => this.setState({ detailFilter: key, detailSelected: null })
        }, label))
      ),
      this.state.detailFilter === "fp" || this.state.detailFilter === "all" ? hq("div", { className: "diagnostic-filterbar cause-filterbar" },
        hq("strong", null, "FP-categorie:"),
        ([['all', 'Alle FP'], ['localization', 'Near-match / IoU'], ['unmatched', 'Unmatched'], ['duplicate', 'Duplicates'], ['negative_region', 'Negatieve regio']] as Array<[DiagnosticCauseFilter, string]>).map(([key, label]) => hq("button", {
          key, className: this.state.detailCauseFilter === key ? "active" : "",
          onClick: () => this.setState({ detailCauseFilter: key, detailFilter: "fp", detailSelected: null })
        }, label))
      ) : null,
      hq("div", { className: "diagnostic-layout" },
        hq("aside", { className: "diagnostic-source-list" },
          hq("strong", null, `${this.state.detailSplit === "val" ? "Validationbeelden" : this.state.detailSplit === "train" ? "Trainingsbeelden" : "Testbeelden"} (${sources.length})`),
          sources.map((item: any) => hq("button", {
            key: item.source_id, className: String(item.source_id) === String(source && source.source_id) ? "active" : "",
            onClick: () => this.setState({ detailSourceId: String(item.source_id), detailSelected: null })
          }, hq("span", { className: "mono" }, qtext(item.source_id)), hq("small", null, `TP ${qtext(item.tp, "0")} · FP ${qtext(item.fp, "0")} · FN ${qtext(item.fn, "0")}`)))
        ),
        hq("div", { className: "diagnostic-main" },
          source ? hq("div", { className: "diagnostic-image-shell" },
            hq("div", { className: "diagnostic-image-toolbar" },
              hq("strong", { className: "mono" }, qtext(source.source_id)),
              hq("span", { className: "muted" }, `TP ${qtext(source.tp, "0")} · FP ${qtext(source.fp, "0")} · FN ${qtext(source.fn, "0")}`)
            ),
            hq("div", { className: "diagnostic-image-stage" },
              hq("img", { src: `/api/v2/localization/quality/image/${encodeURIComponent(String(detail.dataset_id || ""))}/${encodeURIComponent(String(source.source_id || ""))}?split=${encodeURIComponent(String(detail.split || "test"))}`, alt: `${this.state.detailSplit.toUpperCase()} bron ${qtext(source.source_id)}`, loading: "lazy", decoding: "async" }),
              this.renderDiagnosticOverlay(source)
            )
          ) : hq("div", { className: "notice warning" }, "Geen testbron beschikbaar."),
          source ? this.renderSelectedDetail(source) : null
        )
      ),
      hq("div", { className: "diagnostic-howto" },
        hq("strong", null, "Hoe gebruik je dit?"),
        hq("ol", null,
          hq("li", null, "Kies eerst ‘Alleen rood (FP)’ en open de beelden met veel rode kaders."),
          hq("li", null, "Is een rood kader eigenlijk een echt veld en heeft het geen ground-truth match? Bevestig het expliciet met ‘voeg toe aan ground truth’."),
          hq("li", null, "Is rood echt geen veld? Laat de ground truth ongemoeid. Op VALIDATION mag je het patroon gebruiken om TRAIN te verbeteren; tune nooit rechtstreeks op TEST."),
          hq("li", null, "Bekijk daarna oranje (FN): dat zijn velden die het model gemist heeft. Zoek naar terugkerende posities/vormen."),
          hq("li", null, "Verander Confidence om te zien of rood afneemt zonder dat oranje sterk toeneemt. Dat onderscheidt threshold-calibratie van een trainingsprobleem.")
        )
      )
    );
  }
  renderSweep(data: QualityPayload) {
    const diag = data.diagnostics;
    if (!diag || !diag.splits || !Array.isArray(diag.splits.val)) {
      return hq("section", { className: "card section-gap" }, hq("h3", null, "Confidence-analyse"), hq("p", { className: "muted" }, "Nog geen validation-confidence-analyse. Voer een nieuwe evaluatie uit om meerdere thresholds te vergelijken."));
    }
    const validationRows = diag.splits.val;
    const pipeline = diag.improvement_pipeline || {};
    const calibration = pipeline.calibration || {};
    const recommended = Number(calibration.diagnostic_threshold ?? diag.recommended_threshold);
    const production = Number(calibration.production_threshold);
    const splitAtRecommended = (name: string) => {
      const rows = Array.isArray(diag.splits[name]) ? diag.splits[name] : [];
      return rows.find((row: any) => Math.abs(Number(row.threshold) - recommended) < 1e-9) || rows[0];
    };
    return hq("div", { className: "quality-diagnostic-stack" },
      hq("section", { className: "card section-gap" },
        hq("div", { className: "toolbar" },
          hq("div", null, hq("h3", null, "Confidence-calibratie op VALIDATION"), hq("p", { className: "muted" }, "Confidence wordt uitsluitend op VALIDATION gekozen. TEST is geen tuning-set. ‘Bekijk’ opent dezelfde validation-voorspellingen visueel, zonder inference opnieuw te draaien.")),
          hq("span", { className: `pill ${Number.isFinite(production) ? "ok" : "warn"}` }, Number.isFinite(production) ? `Production-kandidaat ${production.toFixed(2)}` : `Diagnose ${Number.isFinite(recommended) ? recommended.toFixed(2) : "—"}`)
        ),
        hq("div", { className: "table-wrap" }, hq("table", { className: "quality-sweep-table" },
          hq("thead", null, hq("tr", null, ["Threshold", "Pred.", "TP", "FP", "FN", "FP/beeld", "Precision", "Recall", "Strakke ref.match", "Validation", ""].map(x => hq("th", { key: x }, x)))),
          hq("tbody", null, validationRows.map((row: any) => {
            const m = row.metrics || {};
            const threshold = Number(row.threshold);
            const isRecommended = Math.abs(threshold - recommended) < 1e-9;
            const isOperating = Math.abs(threshold - 0.25) < 1e-9;
            return hq("tr", { key: row.threshold, className: isRecommended ? "recommended" : isOperating ? "operating" : "" },
              hq("td", null, threshold.toFixed(2), isOperating ? hq("small", { className: "table-subtag" }, "huidig") : null),
              hq("td", null, qtext(m.scored_predictions, "0")), hq("td", null, qtext(m.true_positives, "0")),
              hq("td", null, qtext(m.false_positives, "0")), hq("td", null, qtext(m.false_negatives, "0")),
              hq("td", null, qfixed(m.false_positives_per_image, 1)), hq("td", null, qpct(m.precision)), hq("td", null, qpct(m.recall)),
              hq("td", null, qpct(m.auto_accept_rate)),
              hq("td", null, hq("span", { className: `pill ${row.calibration_passed ? "ok" : "bad"}` }, row.calibration_passed ? "PASS" : "FAIL")),
              hq("td", null, hq("button", { className: "compact-button", disabled: this.state.detailLoading, onClick: () => this.viewThreshold(data, threshold, "val") }, "Bekijk"))
            );
          }))
        )),
        Array.isArray(diag.diagnosis) && diag.diagnosis.length ? hq("div", { className: "quality-diagnosis" }, diag.diagnosis.map((text: string) => hq("div", { className: "notice warning", key: text }, text))) : null
      ),
      hq("section", { className: "card section-gap" },
        hq("h3", null, "Train / validation / test bij de diagnostische validation-threshold"),
        hq("div", { className: "quality-split-grid" }, ["train", "val", "test"].map(name => {
          const row = splitAtRecommended(name) || {}; const m = row.metrics || {};
          return hq("div", { className: "quality-split-card", key: name },
            hq("strong", null, name === "val" ? "VALIDATION" : name.toUpperCase()),
            hq("span", null, `Recall ${qpct(m.recall)}`), hq("span", null, `Precision ${qpct(m.precision)}`),
            hq("span", null, `FP/beeld ${qfixed(m.false_positives_per_image, 1)}`),
            hq("span", null, `Voorsp. ${qtext(m.scored_predictions, "0")}`), hq("span", null, `Referentie ${qtext(m.ground_truth_rois, "0")}`)
          );
        }))
      )
    );
  }
  renderAdvancedDiagnostics(data: QualityPayload) {
    return hq("details", { className: "card advanced-diagnostics section-gap" },
      hq("summary", null, "Geavanceerde diagnostiek en ruwe metrics"),
      hq("p", { className: "muted" }, "Gebruik dit alleen wanneer je de automatische diagnose wilt controleren. De Model Improvement Assistant hierboven bepaalt de normale volgende stap."),
      this.renderGate(data),
      hq("div", { className: "grid cols-2 section-gap" }, this.renderEvaluation("Baseline", data.baseline), this.renderEvaluation("Getrainde detector", data.trained)),
      data.comparison ? hq("section", { className: "card section-gap" },
        hq("div", { className: "toolbar" }, hq("h3", null, "Vergelijkbaarheid"), hq("span", { className: `pill ${data.comparison.same_split && data.comparison.same_dataset && data.comparison.same_ground_truth ? "ok" : "bad"}` }, data.comparison.same_split && data.comparison.same_dataset && data.comparison.same_ground_truth ? "IDENTIEK" : "NIET VERGELIJKBAAR")),
        hq("p", { className: "muted" }, `Zelfde verdeling: ${data.comparison.same_split ? "ja" : "nee"} · dataset: ${data.comparison.same_dataset ? "ja" : "nee"} · reviewdata: ${data.comparison.same_ground_truth ? "ja" : "nee"}`)
      ) : null,
      this.renderSweep(data)
    );
  }
  renderJobs(data: QualityPayload) {
    const jobs = Array.isArray(data.jobs) ? data.jobs : [];
    return hq("section", { className: "card section-gap" }, hq("h3", null, "Recente taken"), jobs.length ? jobs.slice(0, 8).map(job => hq("div", { className: `quality-job job-${job.status}`, key: job.job_id },
      hq("div", null, hq("strong", null, job.action_name)),
      hq("span", { className: `job-status ${job.status}` }, qtext(job.progress_label, job.status))
    )) : hq("p", { className: "muted" }, "Nog geen taken."));
  }
  render() {
    const data = this.state.data;
    if (this.state.loading && !data) return hq("section", { className: "card" }, hq("h3", null, "Detectiekwaliteit laden…"));
    if (!data) return hq("section", { className: "notice error" }, this.state.error || "Geen quality-state beschikbaar.");
    const gateState = String((data.gate || {}).state || "");
    const selection = data.selection || {};
    const gateModelId = String((data.gate || {}).model_id || "");
    const evaluationBusy = this.isBusy("9");
    const compareBusy = this.isBusy("10");
    const activateBusy = this.isBusy("11");
    const reportBusy = this.isBusy("13");
    const workerReason = !(data.worker && data.worker.online) ? "De achtergrondworker is offline. Start de webinterface/worker opnieuw of controleer Wachtrijbeheer." : "";
    const evaluationReason = workerReason || (evaluationBusy ? "Er loopt al een evaluatietaak." : !selection.evaluation_dataset_id ? "Selecteer of bouw eerst een dataset." : "");
    const compareReason = workerReason || (compareBusy ? "Er loopt al een vergelijkingstaak."
      : !data.baseline && !data.trained ? "Voer eerst een baseline- én een getrainde evaluatie uit."
      : !data.baseline ? "De baseline-evaluatie ontbreekt. Voer Nieuwe evaluatie uitvoeren uit."
      : !data.trained ? "De evaluatie van de geselecteerde detector ontbreekt. Selecteer een detector en voer Nieuwe evaluatie uitvoeren uit."
      : "");
    let activateReason = "";
    if (workerReason) activateReason = workerReason;
    else if (activateBusy) activateReason = "Er loopt al een activatietaak.";
    else if (!selection.evaluation_model_id) activateReason = "Selecteer eerst een detector.";
    else if (String(selection.evaluation_dataset_id || "") !== String(selection.current_dataset_id || "")) activateReason = "De evaluatiedataset is niet de huidige werkdataset. Kies dezelfde dataset als werkdataset in Data & modellen.";
    else if (gateState !== "awaiting_activation") activateReason = gateState === "open" ? "Er staat geen nieuwe goedgekeurde detector klaar; de huidige detection gate is al open." : `${qtext((data.gate || {}).reason, "De detection gate is nog niet gehaald.")} Bekijk hieronder de rode/oranje kaders en confidence-analyse.`;
    else if (gateModelId !== String(selection.evaluation_model_id || "")) activateReason = "De detector die door de gate is goedgekeurd is niet de geselecteerde detector. Selecteer het goedgekeurde model.";
    const reportReason = workerReason || (reportBusy ? "Er loopt al een rapporttaak." : (!data.baseline && !data.trained) ? "Er is nog geen evaluatie. Voer eerst een evaluatie uit." : "");
    return hq("div", { className: "quality-root" },
      this.state.error ? hq("div", { className: "notice error" }, this.state.error) : null,
      this.state.notice ? hq("div", { className: "notice success" }, this.state.notice) : null,
      this.state.detailError && this.state.detail ? hq("div", { className: "notice warning" }, this.state.detailError) : null,
      hq("section", { className: "quality-actionbar" },
        hq("div", { className: "actions" },
          this.pageKey === "localization-evaluate" ? qAction(hq("button", { className: "primary", disabled: Boolean(evaluationReason), title: evaluationReason || "Nieuwe evaluatie uitvoeren", onClick: () => this.startJob("9") }, evaluationBusy ? "Evalueren…" : "Nieuwe evaluatie uitvoeren"), evaluationReason) : null,
          this.pageKey === "localization-evaluate" ? qAction(hq("button", { disabled: Boolean(compareReason), title: compareReason || "Bestaande evaluaties vergelijken", onClick: () => this.startJob("10") }, "Bestaande evaluaties vergelijken"), compareReason) : null,
          this.pageKey === "localization-register" ? qAction(hq("button", { className: "primary", disabled: Boolean(activateReason), title: activateReason || "Geselecteerde detector activeren", onClick: () => this.startJob("11") }, activateBusy ? "Activeren…" : "Geselecteerde detector activeren"), activateReason) : null,
          this.pageKey === "detection-report" ? qAction(hq("button", { className: "primary", disabled: Boolean(reportReason), title: reportReason || "Rapport bijwerken", onClick: () => this.startJob("13") }, "Rapport bijwerken"), reportReason) : null
        )
      ),
      this.renderSelection(data),
      this.pageKey === "localization-evaluate" ? this.renderImprovementAssistant(data) : this.renderGate(data),
      this.pageKey === "localization-evaluate" ? this.renderMetricHelp() : null,
      this.pageKey === "localization-evaluate" ? this.renderVisualDiagnostics(data) : null,
      this.pageKey === "localization-evaluate" ? this.renderAdvancedDiagnostics(data) : hq("div", { className: "grid cols-2 section-gap" }, this.renderEvaluation("Baseline", data.baseline), this.renderEvaluation("Getrainde detector", data.trained))
    );
  }
}

const qualityMount = document.getElementById("react-localization-quality");
if (qualityMount) {
  const element = hq(QualityBoundary, null, hq(LocalizationQuality, { pageKey: qualityMount.getAttribute("data-page") || "localization-evaluate" }));
  ReactDOM.render(element, qualityMount);
}
