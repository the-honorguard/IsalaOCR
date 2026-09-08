"""Local dataset collection, exact labeling, training and evaluation tools."""

# Keep the table-model evaluator's acceptance policy in one small, testable
# module. Package import installs it before callers import comparison symbols.
from .table_model_evaluation_policy import install_table_model_evaluation_policy as _install_table_model_evaluation_policy

_install_table_model_evaluation_policy()
del _install_table_model_evaluation_policy

# Explicit model errors become dynamic panel-level hard examples for the next
# training round. The replay policy keeps the canonical COCO dataset single-copy
# and lets the PaddleDetection runtime draw difficult panels more often instead
# of creating permanent negative-only crops or duplicate PNG files.
from .table_hard_negative_policy import install_table_hard_example_replay_policy as _install_table_hard_example_replay_policy

_install_table_hard_example_replay_policy()
del _install_table_hard_example_replay_policy
