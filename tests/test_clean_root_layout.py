from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_preflight_allows_standard_git_metadata_but_not_other_root_files() -> None:
    preflight = (ROOT / "automation" / "powershell" / "preflight.ps1").read_text(encoding="utf-8")
    assert '$allowedRootFiles = @("START.cmd", "run.cmd", "AGENTS.md", ".gitignore", ".gitattributes", "gitignore_generator.ps1")' in preflight
    assert '$allowedRootFiles -notcontains $_' in preflight
    whitelist_line = next(line for line in preflight.splitlines() if "$allowedRootFiles =" in line)
    assert ".gitignore.backup" not in whitelist_line
    assert "gitignore_generator.ps1" in whitelist_line
    assert "gitignore-scan-report.txt" not in whitelist_line


def test_operational_content_is_grouped_into_directories() -> None:
    expected = {
        "application",
        "automation",
        "documentation",
        "infrastructure",
        "project",
        "tests",
        "input",
        "output",
        "models",
        "training",
    }
    directories = {path.name for path in ROOT.iterdir() if path.is_dir()}
    assert expected.issubset(directories)


def test_no_secondary_cmd_wrappers_exist() -> None:
    assert set(ROOT.glob("*.cmd")) == {ROOT / "START.cmd", ROOT / "run.cmd"}


def test_launcher_runs_safe_legacy_layout_migration_first() -> None:
    launcher = (ROOT / "automation" / "powershell" / "launcher.ps1").read_text(encoding="utf-8")
    migration_pos = launcher.index("layout-migration.ps1")
    preflight_pos = launcher.index("preflight.ps1")
    assert migration_pos < preflight_pos

    migration = (ROOT / "automation" / "powershell" / "layout-migration.ps1").read_text(encoding="utf-8")
    assert "audit-only" in migration
    assert "Remove-Item" not in migration
    assert "Move-Item" not in migration
    assert "Add-Content" not in migration
    assert '"scripts", "src", "config", "schemas", "training_runtime"' in migration
