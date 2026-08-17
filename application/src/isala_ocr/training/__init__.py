"""Local dataset collection, exact labeling, training and evaluation tools."""

# Keep the table-model evaluator's acceptance policy in one small, testable
# module. Package import installs it before callers import comparison symbols.
from .table_model_evaluation_policy import install_table_model_evaluation_policy as _install_table_model_evaluation_policy

_install_table_model_evaluation_policy()
del _install_table_model_evaluation_policy
