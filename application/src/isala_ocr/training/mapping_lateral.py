"""Compatibility shim for application-level lateral mapping semantics."""

from ..application_processing.lateral import (
    ambiguous_lateral_suffixes,
    field_lateral_side,
    field_lateral_suffix,
    lateral_candidate_allowed,
    relation_lateral_side,
)

__all__ = [
    "ambiguous_lateral_suffixes",
    "field_lateral_side",
    "field_lateral_suffix",
    "lateral_candidate_allowed",
    "relation_lateral_side",
]
