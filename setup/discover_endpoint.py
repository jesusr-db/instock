"""Discover an AI Gateway / GPT-compatible serving endpoint in the workspace.

The Databricks workspace (DEFAULT profile) already has an AI Gateway deployment
serving GPT models. This script identifies the endpoint name and writes it to
setup/endpoint_name.txt — the handoff artifact consumed by app-developer
(MODEL_ROUTE default) and deploy-engineer (env var in app/app.yml).

Selection priority:
  1. Endpoint whose `ai_gateway` config is set
  2. Endpoint whose name contains 'gpt' or 'openai' (case-insensitive)
  3. Endpoint whose served entity exposes task='llm/v1/chat'

Raises NoEligibleEndpointError if none match.

Usage:
    python -m setup.discover_endpoint
"""
from __future__ import annotations

import os
import sys
from typing import Iterable, Optional

DEFAULT_OUTPUT = os.path.join(os.path.dirname(__file__), "endpoint_name.txt")


class NoEligibleEndpointError(RuntimeError):
    """Raised when no GPT/AI Gateway endpoint is found in the workspace."""


def _has_ai_gateway(endpoint) -> bool:
    """True if the endpoint has ai_gateway config set (non-None)."""
    return getattr(endpoint, "ai_gateway", None) is not None


def _name_matches_gpt(endpoint) -> bool:
    """True if the endpoint name contains 'gpt' or 'openai' (case-insensitive)."""
    name = (getattr(endpoint, "name", "") or "").lower()
    return "gpt" in name or "openai" in name


def _is_chat_task(endpoint) -> bool:
    """True if any served entity exposes task='llm/v1/chat'."""
    config = getattr(endpoint, "config", None)
    if config is None:
        return False
    entities = getattr(config, "served_entities", None) or []
    for entity in entities:
        ext = getattr(entity, "external_model", None)
        if ext is None:
            continue
        if getattr(ext, "task", None) == "llm/v1/chat":
            return True
    return False


def discover_endpoint(workspace_client) -> str:
    """Return the name of the best-fit AI Gateway / chat endpoint.

    Selection priority: ai_gateway config > GPT/OpenAI name > llm/v1/chat task.
    """
    endpoints: Iterable = workspace_client.serving_endpoints.list()
    endpoints = list(endpoints)

    # Tier 1: ai_gateway config
    for ep in endpoints:
        if _has_ai_gateway(ep):
            return ep.name

    # Tier 2: name pattern
    for ep in endpoints:
        if _name_matches_gpt(ep):
            return ep.name

    # Tier 3: llm/v1/chat task
    for ep in endpoints:
        if _is_chat_task(ep):
            return ep.name

    raise NoEligibleEndpointError(
        "No eligible AI Gateway / GPT / chat endpoint found in workspace. "
        "Expected at least one endpoint with ai_gateway config, a GPT/OpenAI "
        "name, or task='llm/v1/chat'."
    )


def write_endpoint_name(name: str, output_path: str = DEFAULT_OUTPUT) -> None:
    """Write the endpoint name to a file with a trailing newline (UNIX style).

    The name itself is whitespace-free; only the trailing newline is added.
    """
    cleaned = name.strip()
    if not cleaned or any(ch.isspace() for ch in cleaned):
        raise ValueError(f"Endpoint name must not contain whitespace: {name!r}")
    with open(output_path, "w") as f:
        f.write(cleaned + "\n")


def main() -> Optional[int]:
    """CLI entry point — discover and persist the endpoint name."""
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()  # DEFAULT profile
    try:
        name = discover_endpoint(w)
    except NoEligibleEndpointError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    write_endpoint_name(name)
    print(f"Discovered endpoint: {name}")
    print(f"Written to: {DEFAULT_OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
