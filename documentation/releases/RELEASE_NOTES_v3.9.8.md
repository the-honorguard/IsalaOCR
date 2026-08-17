# IsalaOCR 3.9.8

- Project management and dataset/model management are combined into one **Projecten & modellen** entry in the sidebar.
- The new **Beheer** page contains two client-side tabs: **Projecten** and **Data & modellen**.
- Switching between management tabs does not reload the page.
- The project selector stays focused on switching projects; its separate **Projecten** management link was removed.
- Legacy `/projects` and `/process/artifacts` URLs remain supported and render the corresponding tab of the unified management page.
- Existing queued artifact deletion, active-model safeguards, project isolation, and artifact polling behavior are unchanged.
