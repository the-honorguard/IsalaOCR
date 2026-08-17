# IsalaOCR 3.8.7 — truthful progress and split live logs

## Progress

Long-running jobs no longer sit at a fabricated 45%. Generic PowerShell/Docker actions use an indeterminate progress bar because their total runtime cannot be predicted reliably. The status text is derived from the newest useful line in STDOUT or STDERR, so Docker BuildKit steps and active layer downloads remain visible. Training action 26 keeps its real epoch-based percentage.

## Activity terminal

The activity dock now keeps execution streams separate:

- **Live / STDOUT** is the default continuously updating terminal.
- **STDERR** contains only the child process error stream and receives a `nieuw` badge when new error output arrives.
- **Worker** contains IsalaOCR worker lifecycle messages such as pickup, PID and exit status.
- **Overzicht** combines lifecycle information and the three stream sections for diagnostics.

Each job/stream remembers whether the user is following the tail. While live-follow is enabled, new output stays pinned to the newest line. Scrolling upward disables auto-follow and shows **Naar live output ↓**; clicking it resumes tailing. Switching between STDOUT, STDERR and Worker does not disturb the saved scroll state of the other streams.

## Storage

STDOUT remains `<job>.log`, STDERR remains `<job>.log.err`, and worker lifecycle output remains `<job>.worker.log`. The web UI no longer needs to concatenate changing streams into one pseudo-terminal, which was the reason new output could appear above the visible bottom edge.

The heavyweight training image revision remains 3.8.4. No CPU/GPU training image rebuild is required for this UI/worker release.
