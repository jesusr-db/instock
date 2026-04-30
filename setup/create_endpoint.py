"""Resolve and record the AI serving endpoint for inStockCV.

Selects a vision-capable Claude endpoint backed by Databricks Foundation
Model (no external credentials required). Preference order:
  1. 'instockcv-gateway' if it already exists (user-created, dedicated)
  2. 'databricks-claude-sonnet-4-6' — the workspace-managed system endpoint
     for system.ai.databricks-claude-sonnet-4-6 (always present in this workspace)

Writes the chosen name to setup/endpoint_name.txt for consumption by the
app and DAB deploy. Idempotent.

Usage (run as Databricks job task or locally with DEFAULT profile):
    python -m setup.create_endpoint
"""
from __future__ import annotations

import os
import sys
from typing import Optional

# Primary: dedicated endpoint (in case it was created separately)
ENDPOINT_NAME = "instockcv-gateway"

# Fallback: workspace-managed Foundation Model endpoint for Claude Sonnet 4.6.
# This endpoint is pre-provisioned by Databricks in every workspace and is always
# READY. Using it avoids the workload-spec validation that the REST API applies to
# user-created endpoints backed by system.ai.* entities.
SYSTEM_ENDPOINT_NAME = "databricks-claude-sonnet-4-6"

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Databricks job context: __file__ undefined; fall back to cwd
    _here = os.path.join(os.getcwd(), "setup")

DEFAULT_OUTPUT = os.path.join(_here, "endpoint_name.txt")


class EndpointTimeoutError(RuntimeError):
    """Raised when the endpoint does not reach READY within the timeout."""


def endpoint_exists(workspace_client, name: str) -> bool:
    """Return True if the named endpoint exists (any state)."""
    try:
        ep = workspace_client.serving_endpoints.get(name)
        return ep is not None
    except Exception:
        return False


def resolve_endpoint(workspace_client) -> str:
    """Return the endpoint name to use for inStockCV.

    Prefers the dedicated instockcv-gateway if it exists; falls back to the
    workspace-managed databricks-claude-sonnet-4-6 system endpoint.
    """
    if endpoint_exists(workspace_client, ENDPOINT_NAME):
        print(f"Using existing dedicated endpoint '{ENDPOINT_NAME}'.")
        return ENDPOINT_NAME

    if endpoint_exists(workspace_client, SYSTEM_ENDPOINT_NAME):
        print(
            f"Dedicated endpoint '{ENDPOINT_NAME}' not found. "
            f"Using workspace system endpoint '{SYSTEM_ENDPOINT_NAME}' "
            "(databricks-claude-sonnet-4-6, vision-capable, no external creds)."
        )
        return SYSTEM_ENDPOINT_NAME

    raise RuntimeError(
        f"Neither '{ENDPOINT_NAME}' nor '{SYSTEM_ENDPOINT_NAME}' found in this workspace. "
        "Create a serving endpoint manually or re-run after provisioning."
    )


def write_endpoint_name(name: str, output_path: str = DEFAULT_OUTPUT) -> None:
    """Write the endpoint name to endpoint_name.txt (consumed by app and deploy)."""
    with open(output_path, "w") as f:
        f.write(name + "\n")


def main() -> Optional[int]:
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    chosen = resolve_endpoint(w)
    write_endpoint_name(chosen)
    print(f"Endpoint name written to: {DEFAULT_OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
