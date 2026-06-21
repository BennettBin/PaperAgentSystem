"""Standalone model-training contracts and pipelines.

This package deliberately has no dependency on API, Worker, database, Agent
Runtime, or other online application modules.
"""

from training.contracts import DatasetManifest, TrainingSample
from training.dataset import validate_dataset

__all__ = ["DatasetManifest", "TrainingSample", "validate_dataset"]
