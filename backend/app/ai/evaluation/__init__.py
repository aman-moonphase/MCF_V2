"""Evaluate & Improve evaluators. See base.py for the interface and finding types."""

from .base import DIMENSIONS, ContentEvaluator, EvaluationContext
from .rules import RuleBasedEvaluator


def get_evaluator() -> ContentEvaluator:
    """The evaluator to use. Always the deterministic rule-based one: an AI evaluator must be added and selected
    deliberately, never implicitly through AI_PROVIDER (so evaluation can never become a paid call by accident)."""
    return RuleBasedEvaluator()


__all__ = ["ContentEvaluator", "DIMENSIONS", "EvaluationContext", "RuleBasedEvaluator", "get_evaluator"]
