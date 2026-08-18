# Step 5 diagnostics

`run-table-cell-pipeline.ps1` overwrites two deliberately tracked files on every **Stap 5 · Alles laten draaien** run:

- `latest.txt` — the full PowerShell/Docker/Paddle console transcript.
- `latest.json` — a compact machine-readable summary with dataset, validation, execution backend, hard-example replay plan/runtime, model/run IDs and validation output.

These files contain diagnostic/runtime metadata and local paths, but the logger does not intentionally copy DICOM images, model weights or the training dataset into Git. Inspect them before sharing outside the development repository.

After a run, commit and push these two modified files normally. Once they are on GitHub, ChatGPT can inspect the exact Step 5 run through the repository connector instead of requiring a pasted terminal log.

```powershell
git add diagnostics/step5/latest.txt diagnostics/step5/latest.json
git commit -m "Add latest Step 5 diagnostics"
git push
```

Git history acts as the archive; the working tree keeps only the latest run so repeated training does not create an unbounded diagnostics directory.
