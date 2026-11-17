"""Default pytest stays on unit tests. Integration and the model need an explicit flag."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("INTEGRATION") != "1":
        skip_integration = pytest.mark.skip(reason="INTEGRATION=1 is not set")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)
    if os.environ.get("SLOW") != "1":
        skip_slow = pytest.mark.skip(reason="SLOW=1 is not set")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
