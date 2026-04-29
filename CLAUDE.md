# inStockCV — Project Notes

Mobile-optimized Databricks App (React + FastAPI) for retail store employees to
photograph products and check inventory quantities via AI-powered SKU extraction.

Project root: `/Users/jesus.rodriguez/Documents/ItsAVibe/gitrepos_FY27/inStockCV`

## Quick reference

- **Catalog/schema:** `main.instockcv` (prod) / `main.instockcv_dev` (dev)
- **AI Gateway endpoint:** `aigwjmr` (discovered via `setup/discover_endpoint.py`)
- **Bundle target:** `dev` (default), `prod`
- **Run tests:** `pytest tests/ -v`
- **Validate bundle:** `DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle validate`

## Introspection

### Phase 1: Foundation (2026-04-29)

#### What worked
- **data-engineer:** TDD flow was clean — write tests, hit red, implement, hit green. The 6 inventory tests caught a real combinatorial-space bug on the first run.
- **genai-architect:** Mocked SDK tests stayed isolated from the live workspace. The three-tier selection priority (ai_gateway > GPT name > llm/v1/chat) gracefully picked the right endpoint without manual intervention.
- **Both agents in parallel-conceptually:** No file-path overlap between the two scopes, so they could have run truly concurrently in a worktree-capable orchestrator.

#### What failed or needed fixing
- **data-engineer / generate_inventory.py:** First implementation hit only 381 rows — the brand×variant×size combinatorial space totaled 430 unique combos, below the 450..550 target. Saturation kicked in long before reaching 500.
  - Error: `AssertionError: Expected 450..550 rows, got 381`
  - Fix: Added a `pack_count` axis (1ct / 6pk / 12pk / 24pk) — realistic for retail (single vs. carton) and bumps the space to ~1300 unique combos. SKU id grew to include the pack code.
  - Pattern to watch: When generating synthetic data with a target row count and uniqueness constraint, pre-compute combinatorial space first; budget at least 2× headroom.

- **databricks.yml workspace.host placeholder:** Including `workspace.host: ${workspace.host}` caused `databricks bundle validate` to fail with "host in profile doesn't match host in bundle" — the templating expects the variable to be defined, not literally `${workspace.host}`.
  - Error: `cannot resolve bundle auth configuration: the host in the profile (...) doesn't match the host configured in the bundle (${workspace.host})`
  - Fix: Removed the `workspace:` stanza from each target. Bundle now picks up host from the active profile.
  - Pattern to watch: For profile-driven (CLI auth) deployments, omit `workspace.host` entirely. Hardcode it only when targeting a specific URL across all profiles.

- **WorkspaceClient() default auth picked up env tokens:** `DATABRICKS_TOKEN` was set in the parent shell, blocking profile-based auth. Required explicit `env -u DATABRICKS_TOKEN -u DATABRICKS_HOST DATABRICKS_CONFIG_PROFILE=DEFAULT` prefix.
  - Pattern to watch: Auth precedence in databricks-sdk is env vars > profile. Tests/scripts that assume "DEFAULT profile" need clean env or `Config(profile="DEFAULT")`.

#### Concerns flagged for downstream phases
- **Endpoint `aigwjmr` is multi-model:** Routes 40% to gemma-3-12b-it (vision-capable) and 60% to gpt-oss-120b (text-only). Vision messages may fail when traffic lands on gpt-oss-120b.
  - Mitigation: Phase 3 QA must include an integration test that submits an image; if rejection rate is high, consider pinning to gemma-3 via a model-route override or filing a workspace-side fix to add a vision-only model.
- **Endpoint name in plan vs. reality:** Plan/team manifest both reference `instockcv-gateway` as a placeholder; real endpoint is `aigwjmr`. App-developer MUST read `setup/endpoint_name.txt` for the MODEL_ROUTE default rather than hardcoding the placeholder string.

#### QA iterations
- Attempt 1: PASS — all 13 tests green, bundle validates, endpoint_name.txt populated.

### Phase 2: Application (in progress)
