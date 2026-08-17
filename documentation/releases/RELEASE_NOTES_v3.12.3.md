# IsalaOCR 3.12.3

## Table-cell registration recovery

A completed wireless table-cell training run can now be registered reliably from Docker Desktop bind-mounted workspaces. Registration copies exported inference model bytes without attempting to preserve POSIX metadata, avoiding host-filesystem `copystat`/permission failures after a successful training run.

The GPU/CPU table-cell training action is also recovery-aware. If the current validated dataset already has a completed and evaluated run whose registration did not finish, the action registers that existing `best_model` first and exits successfully **without retraining**. Model activation remains explicit.
