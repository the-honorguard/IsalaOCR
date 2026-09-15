const ha = React.createElement;
const ArtifactComponent = React.Component;

type ArtifactPayload = {
  schema_version: number;
  generated_at: string;
  project: { project_id: string; name: string; use_case_id: string };
  selection: Record<string, any>;
  datasets: Array<Record<string, any>>;
  models: Array<Record<string, any>>;
  evaluations: Array<Record<string, any>>;
  runs: Array<Record<string, any>>;
  delete_jobs: Array<Record<string, any>>;
  active_model: Record<string, any> | null;
  gate: Record<string, any>;
  worker: { online?: boolean; current_job_id?: string; heartbeat_age_seconds?: number };
};

type ArtifactState = { data: ArtifactPayload | null; loading: boolean; error: string; notice: string; busy: string };
function bytes(value: any): string {
  let n = Number(value || 0); const units = ["B", "KiB", "MiB", "GiB"];
  let i = 0; while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
const text = sharedText;
const artifactWhen = sharedFriendlyWhen;
const datasetName = sharedDatasetName;
const modelName = sharedModelName;
const evaluationName = sharedEvaluationName;
function runName(item: any, projectName: string): string {
  return `${text(projectName, "Project")} · trainingsrun · ${artifactWhen(item && item.created_at)}`;
}
function artifactAction(button: any, reason = "") {
  return sharedActionControl("artifact-action-control", button, reason);
}
function splitText(item: any): string {
  const s = item && item.splits ? item.splits : {};
  const count = (name: string) => Number((s[name] || {}).images || 0);
  return `${count("train")}/${count("val")}/${count("test")}`;
}


function deleteJob(data: any, kind: string, id: string): any {
    const jobs = data && Array.isArray(data.delete_jobs) ? data.delete_jobs : [];
    return jobs.find((job: any) => job.kind === kind && job.id === id) || null;
}
function deleteLabel(job: any): string {
    if (!job) return "";
    return job.status === "running" ? "WORDT VERWIJDERD" : "VERWIJDERING IN WACHTRIJ";
}
class ArtifactBoundary extends ArtifactComponent {
  state = { failed: false };
  componentDidCatch(error: any) {
    console.error("Localization artifact view render failed", error);
    this.setState({ failed: true });
  }
  render() {
    if (this.state.failed) return ha("div", { className: "notice error" }, "Dit scherm kon niet worden weergegeven. Herstart de webinterface en probeer opnieuw.");
    return this.props.children;
  }
}
class LocalizationArtifacts extends ArtifactComponent {
  state: ArtifactState = { data: null, loading: true, error: "", notice: "", busy: "" };
  timer: number | null = null;
  unmounted = false;
  componentDidMount() { document.addEventListener("visibilitychange", this.visibilityHandler); this.refresh(); }
  componentWillUnmount() { this.unmounted = true; document.removeEventListener("visibilitychange", this.visibilityHandler); if (this.timer !== null) window.clearTimeout(this.timer); }
  visibilityHandler = () => { if (!document.hidden) this.refresh(false); };
  scheduleRefresh(data: ArtifactPayload | null) {
    if (this.unmounted) return;
    if (this.timer !== null) window.clearTimeout(this.timer);
    const active = Boolean(data && (data.delete_jobs || []).some(job => job.status === "pending" || job.status === "running"));
    const delay = document.hidden ? 30000 : active ? 3000 : 15000;
    this.timer = window.setTimeout(() => this.refresh(false), delay);
  }
  async refresh(initial = true) {
    if (this.timer !== null) { window.clearTimeout(this.timer); this.timer = null; }
    if (initial) this.setState({ loading: true, error: "" });
    try {
      const response = await fetch("/api/v2/localization/artifacts", { cache: "no-store" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `Artifacts ophalen mislukt (${response.status})`);
      if (!this.unmounted) { this.setState(initial ? { data: payload, loading: false, error: "" } : { data: payload, loading: false }); this.scheduleRefresh(payload as ArtifactPayload); }
    } catch (error: any) { if (!this.unmounted) { this.setState({ loading: false, error: error.message || String(error) }); this.scheduleRefresh(this.state.data); } }
  }
  async post(url: string, body: any, busy: string, allowWhileBusy = false) {
    if (this.state.busy && !allowWhileBusy) return null;
    this.setState({ busy, error: "", notice: "" });
    try {
      const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" }, body: JSON.stringify(body) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) { const err: any = new Error(payload.error || `Actie mislukt (${response.status})`); err.status = response.status; throw err; }
      await this.refresh(false); return payload;
    } catch (error: any) { this.setState({ error: error.message || String(error) }); throw error; }
    finally { this.setState({ busy: "" }); }
  }
  async selectDataset(datasetId: string, work = false) {
    if (work) await this.post("/api/v2/localization/datasets/select", { dataset_id: datasetId }, `dataset:${datasetId}`);
    else await this.post("/api/v2/localization/selection", { evaluation_dataset_id: datasetId, baseline_evaluation_id: "", trained_evaluation_id: "" }, `dataset:${datasetId}`);
  }
  async selectModel(modelId: string) {
    await this.post("/api/v2/localization/selection", { evaluation_model_id: modelId, trained_evaluation_id: "" }, `model:${modelId}`);
  }
  async activateModel(modelId: string) {
    await this.selectModel(modelId);
    await this.post("/api/v2/jobs", { action_id: "11", options: {} }, `activate:${modelId}`);
  }
  async selectEvaluation(item: any) {
    const key = item.kind === "baseline" ? "baseline_evaluation_id" : "trained_evaluation_id";
    await this.post("/api/v2/localization/selection", { [key]: item.evaluation_id }, `eval:${item.evaluation_id}`);
  }
  async remove(kind: string, id: string) {
    const data = this.state.data;
    const label = `${kind} ${id}`;
    let replacementDatasetId = "";
    if (kind === "dataset" && data) {
      const item: any = data.datasets.find((row: any) => row.dataset_id === id);
      if (item && item.current) {
        const replacement: any = data.datasets.find((row: any) => row.dataset_id !== id);
        if (!replacement) {
          this.setState({ error: "Dit is de enige werkdataset. Bewaar of bouw eerst een andere dataset voordat je deze verwijdert.", notice: "" });
          return;
        }
        replacementDatasetId = replacement.dataset_id;
        if (!window.confirm(`Dit is de huidige werkdataset. ${replacementDatasetId} wordt eerst de nieuwe werkdataset. Daarna ${id} verwijderen?`)) return;
      } else if (!window.confirm(`${label} verwijderen?`)) return;
    } else if (!window.confirm(`${label} verwijderen?`)) return;

    const body: any = { kind, id, cascade: false };
    if (replacementDatasetId) body.replacement_dataset_id = replacementDatasetId;
    try {
      const queued = await this.post("/api/v2/localization/artifacts/delete", body, `delete:${kind}:${id}`);
      if (queued) this.setState({ notice: `Verwijderen in wachtrij: ${id}.`, error: "" });
    } catch (error: any) {
      if (error && error.status === 409 && /afhankelijke|wordt gebruikt door/i.test(error.message || "")) {
        if (!window.confirm(`${error.message}\n\nOok de afhankelijke niet-actieve modellen/evaluaties verwijderen?`)) return;
        try {
          const queued = await this.post("/api/v2/localization/artifacts/delete", { ...body, cascade: true }, `delete:${kind}:${id}:cascade`, true);
          if (queued) this.setState({ notice: `Cascade-verwijdering in wachtrij: ${id}.`, error: "" });
        } catch (cascadeError: any) {
          this.setState({ error: cascadeError.message || String(cascadeError), notice: "" });
        }
      }
    }
  }
  renderDatasets(data: ArtifactPayload) {
    const projectName = text(data.project && data.project.name, "Project");
    return ha("section", { className: "card artifact-section" }, ha("div", { className: "toolbar" }, ha("div", null, ha("h3", null, "Datasets"), ha("p", { className: "muted" }, "Bewaar meerdere datasets en kies welke je wilt gebruiken voor training of evaluatie."))),
      ha("div", { className: "artifact-table-wrap" }, ha("table", { className: "artifact-table" },
        ha("thead", null, ha("tr", null, ["Dataset", "Split", "Validatie", "Afhankelijkheden", "Opslag", "Acties"].map(x => ha("th", { key: x }, x)))),
        ha("tbody", null, data.datasets.map((item: any) => {
          const deleting = deleteJob(data, "dataset", item.dataset_id);
          return ha("tr", { key: item.dataset_id },
            ha("td", null, ha("strong", { className: "artifact-friendly-name" }, datasetName(item, projectName)), ha("small", { className: "mono muted artifact-technical-id" }, item.dataset_id), ha("div", { className: "artifact-badges" }, item.current ? ha("span", { className: "pill ok" }, "WERKDATASET") : null, item.selected_for_evaluation ? ha("span", { className: "pill" }, "EVALUATIE") : null, deleting ? ha("span", { className: "pill warn" }, deleteLabel(deleting)) : null)),
            ha("td", null, splitText(item)),
            ha("td", null, ha("span", { className: `pill ${item.validation_ok && item.paddlex_ok ? "ok" : "warn"}` }, item.validation_ok && item.paddlex_ok ? "OK" : "OPEN")),
            ha("td", null, `${item.model_count || 0} model · ${item.evaluation_count || 0} eval`), ha("td", null, bytes(item.size_bytes)),
            ha("td", { className: "artifact-actions" },
              !item.selected_for_evaluation ? artifactAction(ha("button", { disabled: !!deleting, title: deleting ? "Deze dataset wordt al verwijderd." : "Dataset gebruiken voor evaluatie", onClick: () => this.selectDataset(item.dataset_id, false) }, "Evalueren"), deleting ? "Deze dataset wordt al verwijderd." : "") : null,
              !item.current ? artifactAction(ha("button", { disabled: !!deleting, title: deleting ? "Deze dataset wordt al verwijderd." : "Dataset als werkdataset instellen", onClick: () => this.selectDataset(item.dataset_id, true) }, "Werkdataset"), deleting ? "Deze dataset wordt al verwijderd." : "") : null,
              artifactAction(ha("button", { disabled: !!deleting, className: "danger ghost", title: deleting ? "Verwijdering is al ingepland." : "Dataset verwijderen", onClick: () => this.remove("dataset", item.dataset_id) }, deleting ? "In wachtrij" : item.current ? "Vervangen & verwijderen" : "Verwijderen"), deleting ? "Verwijdering is al ingepland." : ""))
          );
        }))
      ))
    );
  }
  renderModels(data: ArtifactPayload) {
    const projectName = text(data.project && data.project.name, "Project");
    const gate = data.gate || {};
    const gateState = String(gate.state || "");
    const gateModelId = String(gate.model_id || "");
    const workerReason = !(data.worker && data.worker.online) ? "De achtergrondworker is offline. Start de webinterface/worker opnieuw of controleer Wachtrijbeheer." : "";
    return ha("section", { className: "card artifact-section" }, ha("h3", null, "Detectoren"),
      ha("div", { className: "artifact-table-wrap" }, ha("table", { className: "artifact-table" },
        ha("thead", null, ha("tr", null, ["Model", "Trainingsdataset", "Status", "Evaluaties", "Opslag", "Acties"].map(x => ha("th", { key: x }, x)))),
        ha("tbody", null, data.models.map((item: any) => {
          const deleting = deleteJob(data, "model", item.model_id);
          return ha("tr", { key: item.model_id },
            ha("td", null, ha("strong", { className: "artifact-friendly-name" }, modelName(item, projectName)), ha("small", { className: "mono muted artifact-technical-id" }, item.model_id), ha("div", { className: "artifact-badges" }, item.active ? ha("span", { className: "pill ok" }, "ACTIEF") : null, item.selected_for_evaluation ? ha("span", { className: "pill" }, "EVALUATIE") : null, deleting ? ha("span", { className: "pill warn" }, deleteLabel(deleting)) : null)),
            ha("td", null, ha("span", null, text(item.dataset_id ? (data.datasets.find((row: any) => row.dataset_id === item.dataset_id) ? datasetName(data.datasets.find((row: any) => row.dataset_id === item.dataset_id), projectName) : item.dataset_id) : "—")), item.dataset_id ? ha("small", { className: "mono muted artifact-technical-id" }, item.dataset_id) : null), ha("td", null, text(item.status)), ha("td", null, item.evaluation_count || 0), ha("td", null, bytes(item.size_bytes)),
            ha("td", { className: "artifact-actions" },
              !item.selected_for_evaluation ? artifactAction(ha("button", { disabled: !!deleting, title: deleting ? "Dit model wordt al verwijderd." : "Model gebruiken voor evaluatie", onClick: () => this.selectModel(item.model_id) }, "Evalueren"), deleting ? "Dit model wordt al verwijderd." : "") : null,
              !item.active ? (() => {
                const activationReason = workerReason || (deleting ? "Dit model wordt al verwijderd."
                  : gateState !== "awaiting_activation" ? (gateState === "open" ? "De huidige detector is al actief. Evalueer dit model eerst zodat het als nieuwe kandidaat door de gate kan komen." : `${text(gate.reason, "Dit model is nog niet vrijgegeven door de detection gate.")} Voer eerst Evalueren & vergelijken uit.`)
                  : gateModelId !== String(item.model_id || "") ? "Een ander model is door de detection gate goedgekeurd. Selecteer/evalueer dit model eerst."
                  : String(data.selection.current_dataset_id || "") !== String(item.dataset_id || "") ? "Dit model hoort niet bij de huidige werkdataset. Maak eerst de bijbehorende dataset de werkdataset."
                  : "");
                return artifactAction(ha("button", { disabled: Boolean(activationReason), className: "primary", title: activationReason || "Model activeren", onClick: () => this.activateModel(item.model_id) }, "Activeren"), activationReason);
              })() : null,
              !item.active ? artifactAction(ha("button", { disabled: !!deleting, className: "danger ghost", title: deleting ? "Verwijdering is al ingepland." : "Model verwijderen", onClick: () => this.remove("model", item.model_id) }, deleting ? "In wachtrij" : "Verwijderen"), deleting ? "Verwijdering is al ingepland." : "") : null)
          );
        }))
      ))
    );
  }
  renderEvaluations(data: ArtifactPayload) {
    return ha("section", { className: "card artifact-section" }, ha("h3", null, "Evaluaties"),
      ha("div", { className: "artifact-table-wrap" }, ha("table", { className: "artifact-table" },
        ha("thead", null, ha("tr", null, ["Evaluatie", "Type", "Dataset", "Model", "Recall", "Precision", "Opslag", "Acties"].map(x => ha("th", { key: x }, x)))),
        ha("tbody", null, data.evaluations.map((item: any) => {
          const m = item.metrics || {};
          const deleting = deleteJob(data, "evaluation", item.evaluation_id);
          return ha("tr", { key: item.evaluation_id },
            ha("td", null, ha("strong", { className: "artifact-friendly-name" }, evaluationName(item)), ha("small", { className: "mono muted artifact-technical-id" }, item.evaluation_id), item.selected ? ha("span", { className: "pill" }, "GESELECTEERD") : null, deleting ? ha("span", { className: "pill warn" }, deleteLabel(deleting)) : null), ha("td", null, item.kind),
            ha("td", { className: "mono" }, text(item.dataset_id)), ha("td", { className: "mono" }, text(item.model_id)), ha("td", null, `${(Number(m.recall || 0) * 100).toFixed(1)}%`), ha("td", null, `${(Number(m.precision || 0) * 100).toFixed(1)}%`), ha("td", null, bytes(item.size_bytes)),
            ha("td", { className: "artifact-actions" }, artifactAction(ha("button", { disabled: !!deleting, title: deleting ? "Deze evaluatie wordt al verwijderd." : "Evaluatie selecteren", onClick: () => this.selectEvaluation(item) }, "Selecteren"), deleting ? "Deze evaluatie wordt al verwijderd." : ""), artifactAction(ha("button", { disabled: !!deleting, className: "danger ghost", title: deleting ? "Verwijdering is al ingepland." : "Evaluatie verwijderen", onClick: () => this.remove("evaluation", item.evaluation_id) }, deleting ? "In wachtrij" : "Verwijderen"), deleting ? "Verwijdering is al ingepland." : ""))
          );
        }))
      ))
    );
  }
  renderRuns(data: ArtifactPayload) {
    const projectName = text(data.project && data.project.name, "Project");
    return ha("section", { className: "card artifact-section" }, ha("h3", null, "Trainingsruns"), ha("p", { className: "muted" }, "Mislukte of afgebroken runs zonder model kunnen veilig worden verwijderd."),
      ha("div", { className: "artifact-run-grid" }, data.runs.map((item: any) => {
        const deleting = deleteJob(data, "run", item.run_id);
        return ha("div", { className: "artifact-run", key: item.run_id },
          ha("strong", { className: "artifact-friendly-name" }, runName(item, projectName)), ha("small", { className: "mono muted artifact-technical-id" }, item.run_id), ha("span", null, `${text(item.status)} · ${bytes(item.size_bytes)}`), ha("span", { className: "muted mono" }, text(item.model_id)),
          deleting ? ha("span", { className: "pill warn" }, deleteLabel(deleting)) : !item.registered ? ha("button", { className: "danger ghost", onClick: () => this.remove("run", item.run_id) }, "Run verwijderen") : ha("span", { className: "pill" }, "MODEL GEREGISTREERD")
        );
      }))
    );
  }
  render() {
    const data = this.state.data;
    if (this.state.loading && !data) return ha("section", { className: "card" }, ha("h3", null, "Artifacts laden…"));
    if (!data) return ha("div", { className: "notice error" }, this.state.error || "Geen artifact-state beschikbaar.");
    return ha("div", { className: "artifact-root" },
      this.state.error ? ha("div", { className: "notice error" }, this.state.error) : null,
      this.state.notice ? ha("div", { className: "notice success" }, this.state.notice) : null,
      ha("section", { className: "artifact-summary" }, ha("div", null, ha("strong", null, `${data.datasets.length} datasets · ${data.models.length} modellen · ${data.evaluations.length} evaluaties`)), ha("a", { className: "button primary", href: "/process/localization-evaluate" }, "Evalueren & vergelijken")),
      this.renderDatasets(data), this.renderModels(data), this.renderEvaluations(data), this.renderRuns(data)
    );
  }
}

const artifactMount = document.getElementById("react-localization-artifacts");
if (artifactMount) {
  const app = ha(ArtifactBoundary, null, ha(LocalizationArtifacts, null));
  ReactDOM.render(app, artifactMount);
}
