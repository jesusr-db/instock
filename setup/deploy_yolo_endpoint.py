"""Deploy foduucom/product-detection-in-shelf-yolov8 as an MLflow pyfunc endpoint.

Steps:
  1. Define YoloPyfunc wrapper (ultralytics → detections list)
  2. Log model to Unity Catalog with pip requirements
  3. Create or update 'instockcv-yolo' CPU Model Serving endpoint
  4. Write endpoint name to setup/yolo_endpoint_name.txt

Usage (run as Databricks job task or locally):
    python -m setup.deploy_yolo_endpoint
"""
from __future__ import annotations

import os
import time

ENDPOINT_NAME = "instockcv-yolo"
MODEL_NAME = "yolo_shelf_detector"

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.getcwd()

DEFAULT_OUTPUT = os.path.join(_here, "yolo_endpoint_name.txt")


def _get_catalog_schema() -> tuple[str, str]:
    catalog = os.environ.get("CATALOG", "vdm_classic_rikfy0_catalog")
    schema = os.environ.get("SCHEMA", "instockcv_dev")
    return catalog, schema


def _log_yolo_model(catalog: str, schema: str) -> str:
    """Log YoloPyfunc to UC. Returns the registered model URI."""
    import mlflow
    import mlflow.pyfunc
    import pandas as pd

    class YoloPyfunc(mlflow.pyfunc.PythonModel):
        def load_context(self, context):
            from ultralytics import YOLO
            self.model = YOLO("foduucom/product-detection-in-shelf-yolov8")

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

    mlflow.set_registry_uri("databricks-uc")
    full_model_name = f"{catalog}.{schema}.{MODEL_NAME}"

    with mlflow.start_run(run_name="yolo_shelf_detector_registration"):
        model_info = mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=YoloPyfunc(),
            pip_requirements=[
                "ultralytics>=8.0.0",
                "Pillow>=10.3.0",
            ],
            registered_model_name=full_model_name,
        )
    print(f"Model logged: {model_info.model_uri}")
    return full_model_name


def _create_or_update_endpoint(
    workspace_client, full_model_name: str, model_version: str
) -> None:
    """Create instockcv-yolo endpoint if absent; skip if already READY."""
    from databricks.sdk.service.serving import (
        EndpointCoreConfigInput,
        ServedModelInput,
        ServedModelInputWorkloadSize,
    )

    try:
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        print(f"Endpoint '{ENDPOINT_NAME}' already exists (state: {ep.state}). Skipping creation.")
        return
    except Exception:
        pass  # Does not exist — create it

    print(f"Creating endpoint '{ENDPOINT_NAME}'...")
    workspace_client.serving_endpoints.create(
        name=ENDPOINT_NAME,
        config=EndpointCoreConfigInput(
            served_models=[
                ServedModelInput(
                    model_name=full_model_name,
                    model_version=model_version,
                    workload_size=ServedModelInputWorkloadSize.SMALL,
                    scale_to_zero_enabled=True,
                )
            ]
        ),
    )

    # Wait for READY (up to 10 minutes)
    for _ in range(60):
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        state = ep.state.ready if ep.state else None
        print(f"  Endpoint state: {state}")
        if str(state) == "EndpointStateReady.READY":
            print(f"Endpoint '{ENDPOINT_NAME}' is READY.")
            return
        time.sleep(10)
    raise RuntimeError(f"Endpoint '{ENDPOINT_NAME}' did not reach READY within 10 minutes.")


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

    full_model_name = _log_yolo_model(catalog, schema)
    model_version = _get_latest_model_version(w, full_model_name)
    print(f"Model version: {model_version}")

    _create_or_update_endpoint(w, full_model_name, model_version)
    write_endpoint_name(ENDPOINT_NAME)
    print(f"Endpoint name written to: {DEFAULT_OUTPUT}")


if __name__ == "__main__":
    main()
