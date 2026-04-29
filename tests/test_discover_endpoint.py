"""Unit tests for setup.discover_endpoint.

The discovery script should:
- Find an AI Gateway endpoint (preferring ones with ai_gateway config),
- Fall back to endpoints whose name contains 'gpt' or 'openai',
- Raise when no eligible endpoint exists,
- Write the discovered name to setup/endpoint_name.txt with no whitespace.

All tests mock the Databricks SDK — they must NEVER hit the live workspace.
"""
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from setup.discover_endpoint import (  # noqa: E402
    NoEligibleEndpointError,
    discover_endpoint,
    write_endpoint_name,
)


def _mk_endpoint(name, ai_gateway=None, task=None):
    """Build a minimal endpoint stub matching the SDK shape used by discover_endpoint."""
    config = SimpleNamespace(served_entities=None) if task is None else SimpleNamespace(
        served_entities=[SimpleNamespace(external_model=SimpleNamespace(task=task))]
    )
    return SimpleNamespace(name=name, ai_gateway=ai_gateway, config=config)


def test_finds_endpoint_with_ai_gateway_config():
    """Endpoints with ai_gateway config win over plain GPT-named endpoints."""
    mock_w = MagicMock()
    mock_w.serving_endpoints.list.return_value = [
        _mk_endpoint("some-other-endpoint"),
        _mk_endpoint("instockcv-gateway", ai_gateway=SimpleNamespace(usage_tracking_config=SimpleNamespace(enabled=True))),
        _mk_endpoint("gpt-fallback-endpoint"),
    ]
    name = discover_endpoint(mock_w)
    assert name == "instockcv-gateway"


def test_finds_endpoint_by_gpt_name_pattern():
    """Falls back to GPT-named endpoint when no ai_gateway endpoint exists."""
    mock_w = MagicMock()
    mock_w.serving_endpoints.list.return_value = [
        _mk_endpoint("databricks-meta-llama-3"),
        _mk_endpoint("databricks-gpt-oss-120b"),
        _mk_endpoint("custom-endpoint"),
    ]
    name = discover_endpoint(mock_w)
    assert "gpt" in name.lower() or "openai" in name.lower()


def test_raises_when_no_eligible_endpoint():
    """Raises NoEligibleEndpointError when no endpoint matches selection rules."""
    mock_w = MagicMock()
    mock_w.serving_endpoints.list.return_value = [
        _mk_endpoint("some-embedding-endpoint"),
        _mk_endpoint("custom-classifier"),
    ]
    with pytest.raises(NoEligibleEndpointError):
        discover_endpoint(mock_w)


def test_writes_endpoint_name_to_file():
    """write_endpoint_name writes the name with no surrounding whitespace."""
    with tempfile.TemporaryDirectory() as td:
        target = os.path.join(td, "endpoint_name.txt")
        write_endpoint_name("instockcv-gateway", target)
        with open(target) as f:
            content = f.read()
        # File contents must equal the name with at most a single trailing newline,
        # and the name itself must contain no whitespace.
        stripped = content.strip()
        assert stripped == "instockcv-gateway"
        assert "\n" not in stripped and " " not in stripped
