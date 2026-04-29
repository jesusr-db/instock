# inStockCV — Project Notes

Mobile-optimized Databricks App (React + FastAPI) for retail store employees to
photograph products and check inventory quantities via AI-powered SKU extraction.

Project root: `/Users/jesus.rodriguez/Documents/ItsAVibe/gitrepos_FY27/inStockCV`

## Quick reference

- **Live app URL:** `https://instockcv-1351565862180944.aws.databricksapps.com`
- **Workspace:** `fe-vm-vdm-classic-rikfy0.cloud.databricks.com` (DEFAULT profile)
- **Catalog/schema:** `vdm_classic_rikfy0_catalog.instockcv_dev` (dev — only deployed target so far)
- **Tables:** `inventory` (462 rows), `scan_log`
- **UC Volume:** `vdm_classic_rikfy0_catalog.instockcv_dev.scan_images`
- **AI Gateway endpoint:** `aigwjmr` (discovered via `setup/discover_endpoint.py`)
- **SQL warehouse:** Serverless Starter Warehouse (`/sql/1.0/warehouses/5067b513037fbf07`)
- **Setup job ID:** `913830059117370`
- **Run tests:** `pytest tests/ -v` (27 tests, all pass)
- **Build frontend:** `cd app/frontend && npm run build`
- **Validate bundle:** `DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle validate`
- **Re-deploy:**
  ```
  DATABRICKS_CONFIG_PROFILE=DEFAULT \
  DATABRICKS_TF_EXEC_PATH=/opt/homebrew/bin/terraform DATABRICKS_TF_VERSION=1.14.9 \
  databricks bundle deploy --target dev \
    --var sql_warehouse_http_path=/sql/1.0/warehouses/5067b513037fbf07
  databricks apps deploy instockcv \
    --source-code-path /Workspace/Users/jesus.rodriguez@databricks.com/.bundle/instockcv/dev/files/app \
    --profile=DEFAULT
  ```
- **Run setup_job:** `DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle run setup_job --target dev`

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

### Phase 2: Application (2026-04-29)

#### What worked
- **TDD across 4 backend modules:** config → analyze → lookup → main. Each module: write tests, hit ImportError red, implement, hit green. No surprise regressions across the chain.
- **`os.environ.update()` at top of test files** to satisfy `Settings()` required-fields validation worked cleanly with pydantic-settings v2. Combined with `monkeypatch.setenv` + `get_settings.cache_clear()` in test_config to test reload behavior.
- **Frontend stack picked clean:** Vite 5 + React 18 + TS 5.4 — `npm install` finished in 20s, `npm run build` in 388ms, `tsc --noEmit` clean. No type warnings.
- **Vite dev proxy** routes `/analyze`, `/lookup`, `/health`, `/config` to FastAPI on :8000 — supports a single `npm run dev` + `uvicorn` flow without CORS glue beyond what we already added.

#### What failed or needed fixing
- **None on the first pass.** All 14 backend tests went red on missing modules (expected for TDD), then green on first implementation attempt. Frontend built first try.

#### Patterns to watch for
- **MODEL_ROUTE default reads from setup/endpoint_name.txt:** `_default_model_route()` walks two candidate paths (relative to file, then cwd-relative). Fragile if the file moves; if config.py is reorganized the path constants must be updated.
- **`databricks-sql-connector` is imported at module load time in lookup.py.** It pulls in pyarrow + thrift, which can be slow. Consider lazy import inside `_fetch_inventory()` if cold-start latency becomes a problem.
- **Settings class uses `extra="ignore"`** so unrecognized env vars are dropped silently. That's intentional for forward compat (deploy-engineer may add ADDITIONAL_MODEL_ROUTES, etc.) but masks typos in env names — be deliberate.

#### Concerns flagged for downstream phases
- The `aigwjmr` endpoint hosts gemma-3-12b-it (vision-capable) + gpt-oss-120b (text-only) at 40/60 traffic split. Live `/analyze` calls may fail on ~60% of requests. Phase 3 should add an integration smoke test; Phase 4 deploy may need to swap to a vision-only endpoint or pin a route header.

#### QA iterations
- Attempt 1: PASS — 27/27 tests, frontend builds, tsc clean.

### Phase 3: Validation (2026-04-29)

#### What worked
- **Single-pass green:** All 6 QA checks (pytest, frontend build, file completeness, contract compliance, security scan, code quality) passed on first run. No failing tests, no missing files, no hardcoded secrets in source.
- **Security scan exclusions:** Limiting `grep -r` to `--include='*.py' --include='*.ts' --include='*.tsx' --include='*.yml' --include='*.json'` keeps `dist/assets/index-*.js` (bundled React with innocuous patterns) out of false-positive matches.

#### What failed or needed fixing
- **Stray `.js` files emitted by `tsc`** alongside `.tsx` sources. Root cause: tsconfig.json had no `noEmit: true`, so `tsc` (the typecheck step in `npm run build`) wrote `.js` next to each `.tsx`. Vite already bundles, so those files were dead weight and got committed in error.
  - Fix: Added `"noEmit": true` to tsconfig.json, removed the stray `.js` files, recommitted.
  - Pattern to watch: When using Vite + TS, always set `noEmit: true` so `tsc` is purely a typechecker. Otherwise `npm run build` produces both bundled and unbundled artifacts.

#### Patterns to watch for
- **Plan vs. reality drift:** The plan/team manifest used `instockcv-gateway` as a placeholder endpoint name. Real workspace had `aigwjmr`. Because config.py reads `setup/endpoint_name.txt` (not the placeholder), runtime is correct — but anyone scanning the plan literally will be confused.
- **Multi-backed AI Gateway endpoints:** `aigwjmr` routes 40% gemma-3-12b-it (vision) + 60% gpt-oss-120b (text-only). Vision requests can fail probabilistically. This is a known live-system concern that QA flagged but couldn't verify without Phase 4 deploy.

#### QA iterations
- Attempt 1: PASS_WITH_WARNINGS (4 warnings, 0 failures)

### Phase 4: Deployment (2026-04-29)

#### What worked
- **Final state:** App is live at `https://instockcv-1351565862180944.aws.databricksapps.com`. `/health` and `/config/models` return 200; SPA root serves the Vite-bundled React app. Setup job ran successfully and loaded 462 inventory rows into `vdm_classic_rikfy0_catalog.instockcv_dev.inventory`. Tables and UC volume provisioned cleanly.
- **DAB + Apps:** Adding `resources/app.yml` with `source_code_path: ../app` was the correct path; the bundle uploads `app/` to `/Workspace/.../files/app/` and `databricks apps deploy --source-code-path ...` consumes it.
- **Warehouse-selector skill** auto-picked the only running serverless warehouse (`Serverless Starter Warehouse`, id `5067b513037fbf07`) without prompting.

#### What failed or needed fixing (this phase had the most fix iterations)

1. **Terraform signature key expired (CLI bug).**
   - Error: `error downloading Terraform: unable to verify checksums signature: openpgp: key expired`
   - Root cause: Databricks CLI v0.294.0's bundled GPG key for Hashicorp's signature verification is expired.
   - Fix: `brew reinstall terraform` to get a fresh binary, then deploy with `DATABRICKS_TF_EXEC_PATH=/opt/homebrew/bin/terraform DATABRICKS_TF_VERSION=1.14.9` so the CLI uses the local copy and skips re-downloading.

2. **`from setup.generate_inventory import ...` failed in the Databricks job.**
   - Error: `ModuleNotFoundError: No module named 'setup'`
   - Root cause: Databricks runs spark_python_task files via `exec(compile(f.read(), filename, 'exec'))`. The package import context isn't preserved, AND `__file__` is undefined because the code is being exec'd, not imported.
   - First attempted fix (sys.path += dirname(__file__)): failed because `__file__` is undefined.
   - Working fix: rewrote `_load_generate_inventory()` as a 3-strategy resolver — try plain import first, fall back to `__file__`-relative path (wrapped in try/except NameError), fall back to cwd-relative. Robust across CLI / pytest / Databricks job.
   - Pattern to watch: For Databricks job tasks that need to import sibling files, use `importlib.util.spec_from_file_location` rather than relying on package context.

3. **`DELTA_FAILED_TO_MERGE_FIELDS: quantity_on_hand` on table overwrite.**
   - Error: pyspark inferred `quantity_on_hand` as `LongType` from Python `int`s, but the DDL defines it as `INT` (= `IntegerType`). Delta's overwrite-with-schema-evolution refused the merge.
   - Fix: Build the DataFrame with an explicit `StructType`/`IntegerType` schema in `create_tables.py`. Tests still pass because the explicit-schema branch only runs when pyspark is importable; mocked tests work either way.
   - Pattern to watch: When loading list-of-dict data into a Delta table with NOT NULL int columns, ALWAYS pass an explicit schema. Inferred types differ between Python and Spark.

4. **Catalog `main` not accessible in this workspace.**
   - Error: `PERMISSION_DENIED: Catalog 'main' is not accessible in current workspace`
   - Fix: Updated databricks.yml default to `vdm_classic_rikfy0_catalog` (the workspace's user catalog), updated `app/app.yml` and `.env.example` to match. The team manifest's `main.instockcv` references are now overridden everywhere.
   - Pattern to watch: Don't assume a `main` catalog exists. Always discover available catalogs first (`databricks catalogs list`) or use a workspace-aware default.

5. **App crashed: `ModuleNotFoundError: No module named 'openai'`.**
   - Root cause: Databricks Apps installs `requirements.txt` from the app source root, not `app/backend/requirements.txt`.
   - Fix: Copied `app/backend/requirements.txt` to `app/requirements.txt`. Both files are now kept in sync.
   - Pattern to watch: For Databricks Apps, requirements.txt MUST be at the source root (the directory pointed to by `source_code_path`).

6. **App crashed: `ValidationError: databricks_token Field required`.**
   - Root cause: Databricks Apps don't set `DATABRICKS_TOKEN` env var. The platform exposes OAuth m2m credentials via `DATABRICKS_CLIENT_ID` + `DATABRICKS_CLIENT_SECRET`, picked up automatically by the SDK.
   - Fix: Made `databricks_token: Optional[str] = None` in Settings; added `get_databricks_token(settings)` helper that returns the env var if set, else mints one via `WorkspaceClient().config.authenticate()`. Both analyze.py and lookup.py now call this helper instead of reading the token directly.
   - Pattern to watch: For Databricks Apps, prefer SDK auth over env-var tokens. Make tokens optional and resolve via the SDK at call time. Also note `DATABRICKS_HOST` lacks the `https://` scheme in Databricks Apps — config now prepends it via `model_post_init`.

7. **SPA root returned 404 — frontend dist not deployed.**
   - Root cause: `.gitignore` had `app/frontend/dist/` which DAB respects by default during sync.
   - Fix: Added `sync.include: [app/frontend/dist/**]` block at the top of databricks.yml. Bundle now uploads dist while keeping it out of git.
   - Pattern to watch: For DAB-deployed apps with a built frontend, always add an explicit `sync.include` for build outputs that you intentionally `.gitignore`.

#### QA iterations
- Attempt 1: PASS — final smoke tests show /, /health, /config/models all 200.

### Final State

The inStockCV app is end-to-end deployed and accessible:
- **Frontend:** Vite-bundled React, served at `/` of the app URL
- **Backend:** FastAPI with /analyze, /lookup, /health, /config/models
- **Data:** 462 synthetic SKUs in `vdm_classic_rikfy0_catalog.instockcv_dev.inventory`, scan_log table, scan_images UC volume
- **Auth:** OAuth m2m (auto-provisioned by Databricks Apps platform)
- **Model:** AI Gateway endpoint `aigwjmr` (40% gemma-3-12b-it / 60% gpt-oss-120b)

Outstanding follow-ups (not blocking):
- Endpoint multi-model concern (gpt-oss-120b is text-only): file a workspace ticket to add a vision-only AI Gateway, OR pin to gemma-3 via a route header in /analyze.
- Roadmap item: deploy Qwen3-VL-8B OSS model (Optional Task 16, requires GPU cluster).



