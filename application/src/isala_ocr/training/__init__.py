"""Local dataset collection, exact labeling, training and evaluation tools."""

# Keep the table-model evaluator's acceptance policy in one small, testable
# module. Package import installs it before callers import comparison symbols.
from .table_model_evaluation_policy import install_table_model_evaluation_policy as _install_table_model_evaluation_policy

_install_table_model_evaluation_policy()
del _install_table_model_evaluation_policy

# False positives explicitly reviewed as model errors are stronger supervision
# than whole-panel oversampling. Install the persistent hard-negative policy at
# package import so worker scripts and the web UI use the same dataset builder.
from .table_hard_negative_policy import install_table_hard_negative_policy as _install_table_hard_negative_policy

_install_table_hard_negative_policy()
del _install_table_hard_negative_policy
