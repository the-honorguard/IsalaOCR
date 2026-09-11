from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The fullscreen, SPA-like Panel Setup focus editor this file used to test
# (id="panel-focus", async loadSource(), requestFullscreen(), etc.) has been
# replaced by a simple full-page-reload <select> for switching between
# sources (see table_panel_setup.html). There is no equivalent feature left
# to assert against, so the corresponding test was removed rather than
# rewritten against behavior that no longer exists.
