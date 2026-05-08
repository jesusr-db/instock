# Gotchas

Non-obvious behaviors that a developer would only learn by being burned. Standard errors covered in [quickstart.md](quickstart.md) are excluded.

---

## DAB / Bundle

**`workspace.host: ${workspace.host}` breaks bundle validate**
If you include `workspace: host: ${workspace.host}` in a target stanza, `databricks bundle validate` fails with "host in profile doesn't match host in bundle" — the placeholder is not a valid variable reference in this context; the CLI expects a literal URL or no stanza at all. For profile-driven deployments, omit the `workspace:` stanza entirely. The bundle picks up the host from the active CLI profile.

**DAB skips `.gitignore`'d files — including your built frontend**
DAB's default sync excludes anything matched by `.gitignore`. If you `.gitignore` `app/frontend/dist/` (correct for git hygiene) and don't add an explicit override, the React build is never uploaded and the app serves a 404 at `/`. Fix: add a `sync.include: [app/frontend/dist/**]` block at the top of `databricks.yml`.

**Terraform GPG key expires in CLI v0.294**
`databricks bundle deploy` downloads Terraform internally and verifies checksums with a bundled GPG key. That key expired in CLI v0.294.0. Symptom: `error downloading Terraform: unable to verify checksums signature: openpgp: key expired`. Fix: `brew reinstall terraform` then pass `DATABRICKS_TF_EXEC_PATH=/opt/homebrew/bin/terraform DATABRICKS_TF_VERSION=1.14.9` so the CLI uses the local binary and skips re-downloading.

---

## AI Gateway

**`aigwjmr` is a multi-model endpoint — 60% of requests go to a text-only model**
The `aigwjmr` AI Gateway endpoint routes 40% to `gemma-3-12b-it` (vision-capable) and 60% to `gpt-oss-120b` (text-only). Vision payloads that land on `gpt-oss-120b` are rejected, causing roughly 60% scan failure rate. To fix, either pin to `databricks-claude-sonnet-4-6` via `MODEL_ROUTE`, or request a workspace-side fix to make `aigwjmr` vision-only.

**Endpoint name is a runtime artifact, not a config constant**
The AI Gateway endpoint name is written to `setup/endpoint_name.txt` by `setup/create_endpoint.py` at setup_job time. `config.py` reads it at startup. If you clone the repo and run the app without running the setup job, the fallback is the placeholder `"instockcv-gateway"` which may not exist. Always run `setup_job` first, or set `MODEL_ROUTE` explicitly.

---

## OAuth & Auth Tokens

**Databricks Apps do not set `DATABRICKS_TOKEN`**
The platform auto-provisions OAuth m2m credentials (`DATABRICKS_CLIENT_ID` + `DATABRICKS_CLIENT_SECRET`) for the app's service principal, but does not inject a pre-minted `DATABRICKS_TOKEN`. Pydantic `Settings` must declare `databricks_token: Optional[str] = None`. Use `get_databricks_token(settings)` which mints a token on demand via `WorkspaceClient().config.authenticate()`.

**`DATABRICKS_HOST` in Databricks Apps lacks the `https://` scheme**
The platform injects `DATABRICKS_HOST` as a bare hostname (e.g. `fe-vm-vdm-classic-rikfy0.cloud.databricks.com`) without the scheme. The OpenAI client's `base_url` and the `databricks-sql-connector` both need the scheme. `config.py` prepends `https://` in `model_post_init` — but only if `databricks_host` is non-empty after construction. Don't strip the scheme manually elsewhere.

**Env var auth precedence overrides profiles**
The databricks-sdk resolves auth in order: env vars → profile → instance metadata. If `DATABRICKS_TOKEN` or `DATABRICKS_HOST` are set in the shell, they shadow the `DEFAULT` CLI profile. Tests and scripts that rely on profile auth need either `Config(profile="DEFAULT")` or `env -u DATABRICKS_TOKEN -u DATABRICKS_HOST DATABRICKS_CONFIG_PROFILE=DEFAULT ...`.

---

## Python Packaging

**Databricks Apps reads `requirements.txt` from the app source root only**
Databricks Apps installs dependencies from `requirements.txt` at the `source_code_path` root — it does not traverse subdirectories. If your requirements are in `app/backend/requirements.txt` but not in `app/requirements.txt`, the app crashes with `ModuleNotFoundError` on startup. Both files must exist and be in sync.

**`__file__` is undefined in Databricks job `spark_python_task` context**
Databricks executes `spark_python_task` Python files via `exec(compile(f.read(), filename, 'exec'))`. This means `__file__` is not defined in the module's global scope. Any code that does `os.path.dirname(__file__)` at import time will raise `NameError`. Wrap in `try/except NameError` and fall back to `os.getcwd()`. See `create_tables.py`'s `_load_generate_inventory()` for the three-strategy resolver pattern.

---

## Delta / Unity Catalog

**Python `int` infers as `LongType` — breaks Delta `INT` columns on overwrite**
When you call `spark.createDataFrame(list_of_dicts)` without an explicit schema, Spark infers Python `int` as `LongType`. If your Delta table DDL declares the column as `INT` (`IntegerType`), an overwrite with schema evolution fails with `DELTA_FAILED_TO_MERGE_FIELDS`. Always pass an explicit `StructType` with `IntegerType` for integer columns.

**The `main` catalog may not exist in your workspace**
Don't assume `main` is an accessible catalog. In workspaces without Unity Catalog's default catalog configured, `main` raises `PERMISSION_DENIED`. Always discover available catalogs first (`databricks catalogs list`) or use a workspace-specific catalog variable. The inStockCV bundle variable `catalog` defaults to `vdm_classic_rikfy0_catalog`.

**`from setup.generate_inventory import ...` fails in Databricks job context**
Python's package import system doesn't have the project root on `sys.path` when a file is exec'd by the Databricks job runner. Sibling-file imports that work fine under `pytest` or `python -m setup.create_tables` will raise `ModuleNotFoundError: No module named 'setup'` in the job. Use `importlib.util.spec_from_file_location` with candidate paths as the fallback strategy.
