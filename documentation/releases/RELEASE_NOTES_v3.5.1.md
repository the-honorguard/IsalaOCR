# IsalaOCR 3.5.2

This release adds persistent, live task feedback to the local web interface.

## Activity dock

- A collapsible terminal is fixed to the bottom of every web page.
- Job submissions are shown immediately, before the host worker picks them up.
- Pending, running, completed and failed states have clear visual styling.
- A generic progress bar is available for all actions; model training uses real epoch progress.
- Standard output and standard error can be followed live.
- The last tasks remain selectable after completion.
- Registration and activation completion refreshes the page so the active model is visible immediately.

## Worker observability

- The PowerShell worker now writes a heartbeat and current-job state.
- `START.cmd` replaces an idle worker from an older release and recreates an outdated web container automatically.
- The browser shows whether the worker is ready, running or unavailable.
- Status snapshots are updated while a child PowerShell process is running.
- Activation emits four explicit progress stages.

The web container still has no Docker-socket access. All privileged execution remains in the allow-listed host worker.
