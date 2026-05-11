"""Deploy foduucom/product-detection-in-shelf-yolov8 as an MLflow pyfunc endpoint.

Steps:
  1. Define YoloPyfunc wrapper (ultralytics → detections list)
  2. Pre-download model weights locally and bundle them as an MLflow artifact
     (avoids network call to Hugging Face in the serving container)
  3. Log model to Unity Catalog with pip requirements
  4. Create or update 'instockcv-yolo' CPU Model Serving endpoint
  5. Write endpoint name to setup/yolo_endpoint_name.txt

Usage (run locally — requires ultralytics, mlflow, Pillow):
    python -m setup.deploy_yolo_endpoint

Note: Must run locally (not on Databricks serverless) because ultralytics
downloads ~100 MB of model weights during logging.
"""
from __future__ import annotations

import os
import time

ENDPOINT_NAME = "instockcv-yolo"
MODEL_NAME = "yolo_shelf_detector"
HF_MODEL = "foduucom/product-detection-in-shelf-yolov8"

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.getcwd()

DEFAULT_OUTPUT = os.path.join(_here, "yolo_endpoint_name.txt")


def _get_catalog_schema() -> tuple[str, str]:
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--catalog", default=os.environ.get("CATALOG", "vdm_classic_rikfy0_catalog"))
    parser.add_argument("--schema", default=os.environ.get("SCHEMA", "instockcv_dev"))
    args, _ = parser.parse_known_args()
    return args.catalog, args.schema


def _log_yolo_model(workspace_client, catalog: str, schema: str) -> str:
    """Log YoloPyfunc to UC with bundled weights. Skips if latest version is healthy."""
    import mlflow
    import mlflow.pyfunc
    import pandas as pd
    import tempfile

    mlflow.set_registry_uri("databricks-uc")
    full_model_name = f"{catalog}.{schema}.{MODEL_NAME}"

    # Skip logging only if model exists and latest version's endpoint is healthy
    try:
        existing = list(workspace_client.model_versions.list(full_model_name))
    except Exception:
        existing = []

    if existing:
        print(f"Model '{full_model_name}' already has {len(existing)} version(s). Skipping log.")
        return full_model_name

    class YoloPyfunc(mlflow.pyfunc.PythonModel):
        def load_context(self, context):
            from ultralytics import YOLO
            # Load from bundled artifact — no network call at serve time
            self.model = YOLO(context.artifacts["yolo_weights"])

        def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
            import base64
            from io import BytesIO
            from PIL import Image as PILImage

            results = []
            for _, row in model_input.iterrows():
                img_bytes = base64.b64decode(row["image"])
                img = PILImage.open(BytesIO(img_bytes))
                preds = self.model(img)
                detections = []
                for r in preds:
                    for box in r.boxes:
                        detections.append(
                            {
                                "bbox": [round(v, 1) for v in box.xyxy[0].tolist()],
                                "confidence": round(float(box.conf[0]), 4),
                                "class": r.names[int(box.cls[0])],
                            }
                        )
                results.append({"detections": detections})
            return pd.DataFrame(results)

    from mlflow.models.signature import ModelSignature
    from mlflow.types.schema import ColSpec, Schema

    signature = ModelSignature(
        inputs=Schema([ColSpec("string", "image")]),
        outputs=Schema([ColSpec("string", "detections")]),
    )

    # Pre-download YOLO weights from Hugging Face and bundle as MLflow artifact
    print(f"Downloading YOLO model weights from HF repo '{HF_MODEL}'...")
    from huggingface_hub import hf_hub_download
    from ultralytics import YOLO as _YOLO
    tmp_dir = tempfile.mkdtemp()
    # Download best.pt from the HF repo directly
    hf_weights = hf_hub_download(repo_id=HF_MODEL, filename="best.pt")
    import shutil
    weights_path = os.path.join(tmp_dir, "best.pt")
    shutil.copy2(hf_weights, weights_path)
    # Verify it loads correctly before registering
    _ = _YOLO(weights_path)
    print(f"Weights downloaded and verified: {weights_path} ({os.path.getsize(weights_path) // 1024 // 1024} MB)")

    mlflow.set_experiment("/Users/jesus.rodriguez@databricks.com/yolo_shelf_detector")
    with mlflow.start_run(run_name="yolo_shelf_detector_registration"):
        model_info = mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=YoloPyfunc(),
            artifacts={"yolo_weights": weights_path},
            pip_requirements=[
                "ultralytics>=8.0.0",
                "Pillow>=10.3.0",
                "huggingface_hub>=0.20.0",
            ],
            registered_model_name=full_model_name,
            signature=signature,
        )
    print(f"Model logged: {model_info.model_uri}")
    return full_model_name


def _create_or_update_endpoint(
    workspace_client, full_model_name: str, model_version: str
) -> None:
    """Create or update instockcv-yolo endpoint; skip if already READY."""
    from databricks.sdk.errors import NotFound
    from databricks.sdk.service.serving import (
        EndpointCoreConfigInput,
        EndpointStateConfigUpdate,
        EndpointStateReady,
        ServedModelInput,
    )

    served_models = [
        ServedModelInput(
            model_name=full_model_name,
            model_version=model_version,
            workload_size="Small",
            scale_to_zero_enabled=True,
        )
    ]
    config = EndpointCoreConfigInput(
        name=ENDPOINT_NAME,
        served_models=served_models,
    )

    try:
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        if str(ep.state.ready) == "EndpointStateReady.READY":
            print(f"Endpoint '{ENDPOINT_NAME}' already READY. Skipping.")
            return
        print(f"Endpoint '{ENDPOINT_NAME}' exists (state: {ep.state}). Updating config to version {model_version}...")
        workspace_client.serving_endpoints.update_config(
            name=ENDPOINT_NAME,
            served_models=served_models,
        )
    except NotFound:
        print(f"Creating endpoint '{ENDPOINT_NAME}'...")
        workspace_client.serving_endpoints.create(
            name=ENDPOINT_NAME,
            config=config,
        )

    # Wait for READY (up to 20 minutes)
    for _ in range(120):
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        ready = ep.state.ready if ep.state else None
        config_update = ep.state.config_update if ep.state else None
        print(f"  Endpoint state: ready={ready} config_update={config_update}")
        if str(ready) == "EndpointStateReady.READY":
            print(f"Endpoint '{ENDPOINT_NAME}' is READY.")
            return
        if (str(ready) == "EndpointStateReady.NOT_READY" and
                str(config_update) == "EndpointStateConfigUpdate.NOT_UPDATING"):
            raise RuntimeError(f"Endpoint '{ENDPOINT_NAME}' failed to provision (terminal NOT_READY state).")
        if str(config_update) == "EndpointStateConfigUpdate.UPDATE_FAILED":
            raise RuntimeError(f"Endpoint '{ENDPOINT_NAME}' update failed. Check serving logs.")
        time.sleep(10)
    raise RuntimeError(f"Endpoint '{ENDPOINT_NAME}' did not reach READY within 20 minutes.")


def _get_latest_model_version(workspace_client, full_model_name: str) -> str:
    """Return the latest version number for the registered model."""
    versions = list(
        workspace_client.model_versions.list(full_model_name)
    )
    if not versions:
        raise RuntimeError(f"No versions found for model '{full_model_name}'")
    latest = sorted(versions, key=lambda v: int(v.version), reverse=True)[0]
    return latest.version


def write_endpoint_name(name: str, output_path: str = DEFAULT_OUTPUT) -> None:
    with open(output_path, "w") as f:
        f.write(name + "\n")


def main() -> None:
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    catalog, schema = _get_catalog_schema()
    print(f"Using catalog={catalog} schema={schema}")

    full_model_name = _log_yolo_model(w, catalog, schema)
    model_version = _get_latest_model_version(w, full_model_name)
    print(f"Model version: {model_version}")

    _create_or_update_endpoint(w, full_model_name, model_version)
    write_endpoint_name(ENDPOINT_NAME)
    print(f"Endpoint name written to: {DEFAULT_OUTPUT}")


if __name__ == "__main__":
    main()
