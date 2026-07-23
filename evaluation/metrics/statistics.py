"""Seeded bootstrap confidence intervals and paired comparisons."""

from __future__ import annotations

import math
import random
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estimate: float
    lower: float
    upper: float
    confidence: float = Field(default=0.95, gt=0, lt=1)
    method: str
    samples: int = Field(ge=1)
    seed: int


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def bootstrap_statistic_ci(
    values: list[float],
    *,
    statistic: Callable[[list[float]], float],
    samples: int = 2000,
    seed: int = 0,
    confidence: float = 0.95,
) -> ConfidenceInterval:
    if not values:
        raise ValueError("bootstrap requires at least one value")
    if samples < 1:
        raise ValueError("bootstrap samples must be positive")
    rng = random.Random(seed)
    estimates = [
        statistic([values[rng.randrange(len(values))] for _ in values])
        for _ in range(samples)
    ]
    alpha = (1.0 - confidence) / 2.0
    return ConfidenceInterval(
        estimate=statistic(values),
        lower=percentile(estimates, alpha),
        upper=percentile(estimates, 1.0 - alpha),
        confidence=confidence,
        method="percentile_bootstrap",
        samples=samples,
        seed=seed,
    )


def bootstrap_mean_ci(
    values: list[float], *, samples: int = 2000, seed: int = 0
) -> ConfidenceInterval:
    return bootstrap_statistic_ci(
        values,
        statistic=lambda items: sum(items) / len(items),
        samples=samples,
        seed=seed,
    )


def paired_bootstrap_statistic_delta(
    candidate: list[float],
    baseline: list[float],
    *,
    statistic: Callable[[list[float]], float],
    samples: int = 2000,
    seed: int = 0,
    confidence: float = 0.95,
) -> ConfidenceInterval:
    if not candidate or len(candidate) != len(baseline):
        raise ValueError("paired bootstrap requires non-empty equally sized inputs")
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(samples):
        indexes = [rng.randrange(len(candidate)) for _ in candidate]
        candidate_sample = [candidate[index] for index in indexes]
        baseline_sample = [baseline[index] for index in indexes]
        deltas.append(statistic(candidate_sample) - statistic(baseline_sample))
    alpha = (1.0 - confidence) / 2.0
    return ConfidenceInterval(
        estimate=statistic(candidate) - statistic(baseline),
        lower=percentile(deltas, alpha),
        upper=percentile(deltas, 1.0 - alpha),
        confidence=confidence,
        method="paired_percentile_bootstrap",
        samples=samples,
        seed=seed,
    )


def paired_bootstrap_delta(
    candidate: list[float], baseline: list[float], *, samples: int = 2000, seed: int = 0
) -> ConfidenceInterval:
    return paired_bootstrap_statistic_delta(
        candidate,
        baseline,
        statistic=lambda items: sum(items) / len(items),
        samples=samples,
        seed=seed,
    )
