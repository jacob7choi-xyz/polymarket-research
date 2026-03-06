"""Checkpoint logic for resumable market fetching."""

import json
import os
from typing import Any

CHECKPOINT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "checkpoint.json")


def load_checkpoint() -> dict[str, Any]:
    """Load the checkpoint file, returning an empty dict if it doesn't exist."""
    path = os.path.normpath(CHECKPOINT_PATH)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        data: dict[str, Any] = json.load(f)
        return data


def save_checkpoint(data: dict[str, Any]) -> None:
    """Save checkpoint data to disk, creating the data directory if needed."""
    path = os.path.normpath(CHECKPOINT_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
