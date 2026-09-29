from __future__ import annotations

from pathlib import Path

from isala_ocr.training.recognition_ground_truth import (
    relation_column_eligible,
    save_unrecognized_panel_policy,
    unrecognized_panel_policy,
)


def test_default_policy_is_block_and_round_trips(tmp_path: Path) -> None:
    assert unrecognized_panel_policy(tmp_path) == "block"
    save_unrecognized_panel_policy(tmp_path, "allow")
    assert unrecognized_panel_policy(tmp_path) == "allow"
    save_unrecognized_panel_policy(tmp_path, "block")
    assert unrecognized_panel_policy(tmp_path) == "block"


def test_save_unrecognized_panel_policy_rejects_unknown_value(tmp_path: Path) -> None:
    try:
        save_unrecognized_panel_policy(tmp_path, "sometimes")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unknown policy")


_PANEL_BY_ID = {"left": {"panel_id": "left", "name": "Left ventricle"}}
_COLUMN_ROLES = {"left": {"0": "label", "1": "value", "2": "skip"}}


def _relation(context_text: str, value_column_index: int) -> dict:
    return {"context_text": context_text, "value_column_index": value_column_index}


def test_recognized_panel_is_unaffected_by_policy() -> None:
    # A relation whose panel *is* recognized keeps obeying Table Studio's
    # actual column roles regardless of the unrecognized-panel policy.
    value_column = _relation("Left ventricle", 1)
    skip_column = _relation("Left ventricle", 2)
    for policy_blocks in (True, False):
        assert relation_column_eligible(
            value_column, panel_by_id=_PANEL_BY_ID, column_roles=_COLUMN_ROLES,
            block_when_panel_unrecognized=policy_blocks,
        )
        assert not relation_column_eligible(
            skip_column, panel_by_id=_PANEL_BY_ID, column_roles=_COLUMN_ROLES,
            block_when_panel_unrecognized=policy_blocks,
        )


def test_unrecognized_panel_is_blocked_only_when_policy_says_so_and_panels_exist() -> None:
    # Panel Setup has a panel configured, but this relation's context matches
    # none of them (e.g. its table sits outside every configured panel box).
    unrecognized = _relation("Some other table entirely", 1)

    assert relation_column_eligible(
        unrecognized, panel_by_id=_PANEL_BY_ID, column_roles=_COLUMN_ROLES,
        block_when_panel_unrecognized=False,
    ), "default/legacy behaviour: let it through like any unconfigured table"

    assert not relation_column_eligible(
        unrecognized, panel_by_id=_PANEL_BY_ID, column_roles=_COLUMN_ROLES,
        block_when_panel_unrecognized=True,
    ), "policy='block': an unrecognized table must not silently bypass Table Studio's roles"


def test_unrecognized_panel_is_never_blocked_when_panel_setup_has_no_panels_at_all() -> None:
    """A project that has never configured Panel Setup has nothing for any
    table to be 'unrecognized' against - block_when_panel_unrecognized must
    not turn that ordinary, common state into a universal block."""
    unrecognized = _relation("Whatever this table's context is", 1)
    assert relation_column_eligible(
        unrecognized, panel_by_id={}, column_roles={}, block_when_panel_unrecognized=True,
    )
