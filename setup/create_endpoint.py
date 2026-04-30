"""Create a dedicated AI Gateway serving endpoint for inStockCV.

Creates 'instockcv-gateway' backed by Databricks Foundation Model
claude-3-7-sonnet (vision-capable, no external credentials required).
AI Gateway usage tracking is enabled so costs are visible in system tables.

Idempotent: skips creation if the endpoint already exists.
Waits up to 15 minutes for the endpoint to reach READY state.

Usage (run as Databricks job task or locally with DEFAULT profile):
    python -m setup.create_endpoint
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

ENDPOINT_NAME = "instockcv-gateway"

# UC path for Databricks-hosted Claude Sonnet 4.6 — vision-capable, no external creds.
# Confirmed present in this workspace via `system.ai` catalog.
ENTITY_NAME = "system.ai.databricks-claude-sonnet-4-6"
ENTITY_VERSION = "1"

POLL_INTERVAL_SECONDS = 30
TIMEOUT_SECONDS = 900  # 15 minutes

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Databricks job context: __file__ undefined; fall back to cwd
    _here = os.path.join(os.getcwd(), "setup")

DEFAULT_OUTPUT = os.path.join(_here, "endpoint_name.txt")


class EndpointTimeoutError(RuntimeError):
    """Raised when the endpoint does not reach READY within the timeout."""


def endpoint_exists(workspace_client) -> bool:
    """Return True if instockcv-gateway already exists (any state)."""
    try:
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        return ep is not None
    except Exception:
        return False


def create_endpoint(workspace_client) -> None:
    """Create instockcv-gateway via REST API (bypasses SDK typed-class validation).

    Replicates the aigwjmr creation pattern: system.ai entity + provisioned_model_units=0
    + AI Gateway usage tracking. Uses WorkspaceClient only for auth headers.
    """
    import requests

    host = workspace_client.config.host
    if not host.startswith("https://"):
        host = f"https://{host}"

    auth_headers: dict = {}
    workspace_client.config.authenticate(auth_headers)

    payload = {
        "name": ENDPOINT_NAME,
        "config": {
            "served_entities": [
                {
                    "name": "claude-sonnet-4-6",
                    "entity_name": ENTITY_NAME,
                    "entity_version": ENTITY_VERSION,
                    "provisioned_model_units": 0,
                }
            ]
        },
        "ai_gateway": {
            "usage_tracking_config": {"enabled": True}
        },
    }

    resp = requests.post(
        f"{host}/api/2.0/serving-endpoints",
        headers={**auth_headers, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()


def wait_for_ready(workspace_client, timeout: int = TIMEOUT_SECONDS) -> None:
    """Poll until the endpoint reaches READY state or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        state = getattr(ep, "state", None)
        ready = str(getattr(state, "ready", "")) if state else ""
        config_update = str(getattr(state, "config_update", "")) if state else ""

        if "READY" in ready and "NOT_READY" not in ready:
            return
        if "FAILED" in config_update or "FAILED" in ready:
            raise RuntimeError(f"Endpoint creation failed. State: {state}")

        time.sleep(POLL_INTERVAL_SECONDS)

    raise EndpointTimeoutError(
        f"Endpoint '{ENDPOINT_NAME}' did not reach READY within {timeout}s. "
        "Check the Databricks Serving UI for details."
    )


def write_endpoint_name(output_path: str = DEFAULT_OUTPUT) -> None:
    """Write the endpoint name to endpoint_name.txt (consumed by app and deploy)."""
    with open(output_path, "w") as f:
        f.write(ENDPOINT_NAME + "\n")


def main() -> Optional[int]:
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()

    if endpoint_exists(w):
        print(f"Endpoint '{ENDPOINT_NAME}' already exists — skipping creation.")
    else:
        print(f"Creating endpoint '{ENDPOINT_NAME}' backed by {ENTITY_NAME} ...")
        create_endpoint(w)
        print("Waiting for endpoint to reach READY state (up to 15 min)...")
        wait_for_ready(w)
        print(f"Endpoint '{ENDPOINT_NAME}' is READY.")

    write_endpoint_name()
    print(f"Endpoint name written to: {DEFAULT_OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
