# IsalaOCR v3.4.3

## GPU preflight stability

- Replaces the inline `python -c` GPU probe with the dedicated `paddlex_runner.py runtime-check` command.
- Avoids complex quoted Docker arguments that are unreliable with Windows PowerShell 5.1 `Start-Process`.
- Skips the GPU container probe when dataset, dictionary, pretrained weight or GPU image prerequisites already fail.
- Converts every GPU preflight implementation exception into a visible failed check instead of crashing the menu.
- Persists unexpected preflight crashes under `training/workspace/diagnostics`.
- Does not change the reusable training image revision (`3.3.11`).
