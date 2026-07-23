"""Unified evaluation metric definitions, computation and statistics."""

from evaluation.metrics.catalog import (
    CORE_METRICS,
    MetricCategory,
    MetricDefinition,
    MetricName,
)
from evaluation.metrics.engine import CaseMetricRecord, MetricsEngine
from evaluation.metrics.statistics import (
    ConfidenceInterval,
    bootstrap_mean_ci,
    paired_bootstrap_delta,
)

__all__ = [
    "CORE_METRICS",
    "CaseMetricRecord",
    "ConfidenceInterval",
    "MetricCategory",
    "MetricDefinition",
    "MetricName",
    "MetricsEngine",
    "bootstrap_mean_ci",
    "paired_bootstrap_delta",
]
