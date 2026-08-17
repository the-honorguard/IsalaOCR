# IsalaOCR 3.9.7

- Artifact deletes are asynchronous worker jobs instead of synchronous browser requests.
- Dataset/model/evaluation/run deletion is visible as queued/running in Data & modellen and in the global task dock.
- Duplicate delete clicks reuse the existing pending/running delete job.
- Dependency and active-model safeguards are checked before queueing and rechecked by the worker before mutation.
- Current-dataset replacement and cascade deletion execute inside the queued worker task.
- Failed delete jobs retain stdout/stderr and can be retried from queue management.
