"""_argument_value() reads --name value and --name=value alike.

Split out as its own test: this pre-scan used to only recognize the
space-separated form (CODE_REVIEW_v3.16.0.md, sectie Middel; zie
documentation/architecture/refactor-phase2-remaining-plan.md, punt 2), so
a caller using --workspace=/path would silently fall back to the default
workspace here while cli.py's own argparse further down the line still
resolved it correctly -- a subtle mismatch between what the gate-sync
pre-scan saw and what the actual command ran against.
"""

from isala_ocr.table_first_cli import _argument_value


def test_reads_space_separated_form() -> None:
    assert _argument_value(["--config", "/foo/bar.yaml"], "--config") == "/foo/bar.yaml"


def test_reads_equals_separated_form() -> None:
    assert _argument_value(["--config=/foo/bar.yaml"], "--config") == "/foo/bar.yaml"


def test_reads_equals_separated_form_after_a_subcommand() -> None:
    assert _argument_value(["collect-mapping", "--workspace=/ws"], "--workspace") == "/ws"


def test_missing_option_returns_none() -> None:
    assert _argument_value(["collect-mapping"], "--workspace") is None


def test_option_at_end_without_a_value_returns_none() -> None:
    assert _argument_value(["--config"], "--config") is None


def test_empty_value_returns_none_for_both_forms() -> None:
    assert _argument_value(["--config", " "], "--config") is None
    assert _argument_value(["--config="], "--config") is None
