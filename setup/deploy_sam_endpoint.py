"""Deploy Meta SAM (ViT-B) as an MLflow pyfunc endpoint.

Model: facebook/segment-anything (sam_vit_b) — available on PyPI as 'segment-anything'
Endpoint: instockcv-sam (CPU Small, scale-to-zero)

Input:  DataFrame with "image" (base64 JPEG/PNG) and "bbox" (JSON "[x1,y1,x2,y2]")
Output: DataFrame with "mask" (base64 PNG, same H×W as input, binary mask)

Run locally:
    pip install segment-anything torch torchvision Pillow mlflow databricks-sdk
    python -m setup.deploy_sam_endpoint --catalog vdm_classic_rikfy0_catalog --schema instockcv_dev
"""
from __future__ import annotations
import os
import time

ENDPOINT_NAME = "instockcv-sam"
MODEL_NAME = "sam_shelf_segmenter"
SAM_CHECKPOINT_URL = "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth"
SAM_CHECKPOINT_FILENAME = "sam_vit_b_01ec64.pth"
SAM_MODEL_TYPE = "vit_b"

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.getcwd()

DEFAULT_OUTPUT = os.path.join(_here, "sam_endpoint_name.txt")


def _get_catalog_schema() -> tuple[str, str]:
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--catalog", default=os.environ.get("CATALOG", "vdm_classic_rikfy0_catalog"))
    parser.add_argument("--schema", default=os.environ.get("SCHEMA", "instockcv_dev"))
    args, _ = parser.parse_known_args()
    return args.catalog, args.schema


def _log_sam_model(workspace_client, catalog: str, schema: str) -> str:
    import mlflow
    import mlflow.pyfunc
    import tempfile
    import shutil
    import urllib.request
    import pandas as pd

    mlflow.set_registry_uri("databricks-uc")
    full_model_name = f"{catalog}.{schema}.{MODEL_NAME}"

    try:
        existing = list(workspace_client.model_versions.list(full_model_name))
    except Exception:
        existing = []

    if existing:
        print(f"Model '{full_model_name}' already has {len(existing)} version(s). Skipping log.")
        return full_model_name

    class SamPyfunc(mlflow.pyfunc.PythonModel):
        def load_context(self, context):
            import torch
            from segment_anything import sam_model_registry, SamPredictor
            device = "cuda" if torch.cuda.is_available() else "cpu"
            sam = sam_model_registry[SAM_MODEL_TYPE](checkpoint=context.artifacts["sam_weights"])
            sam.to(device=device)
            sam.eval()
            self.predictor = SamPredictor(sam)

        def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
            import base64
            import json
            import numpy as np
            from io import BytesIO
            from PIL import Image as PILImage

            results = []
            for _, row in model_input.iterrows():
                img = PILImage.open(BytesIO(base64.b64decode(row["image"]))).convert("RGB")
                bbox = json.loads(row["bbox"])
                img_np = np.array(img)
                self.predictor.set_image(img_np)
                masks, scores, _ = self.predictor.predict(
                    box=np.array(bbox, dtype=float),
                    multimask_output=True,
                )
                best_mask = masks[scores.argmax()]
                mask_img = PILImage.fromarray((best_mask * 255).astype(np.uint8))
                buf = BytesIO()
                mask_img.save(buf, format="PNG")
                results.append({"mask": base64.b64encode(buf.getvalue()).decode()})
            return pd.DataFrame(results)

    from mlflow.models.signature import ModelSignature
    from mlflow.types.schema import ColSpec, Schema

    signature = ModelSignature(
        inputs=Schema([ColSpec("string", "image"), ColSpec("string", "bbox")]),
        outputs=Schema([ColSpec("string", "mask")]),
    )

    print(f"Downloading SAM ViT-B weights from '{SAM_CHECKPOINT_URL}'...")
    tmp_dir = tempfile.mkdtemp()
    weights_path = os.path.join(tmp_dir, SAM_CHECKPOINT_FILENAME)
    urllib.request.urlretrieve(SAM_CHECKPOINT_URL, weights_path)
    print(f"Weights: {weights_path} ({os.path.getsize(weights_path) // 1024 // 1024} MB)")

    mlflow.set_experiment("/Users/jesus.rodriguez@databricks.com/sam_shelf_segmenter")
    with mlflow.start_run(run_name="sam_shelf_segmenter_registration"):
        model_info = mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=SamPyfunc(),
            artifacts={"sam_weights": weights_path},
            pip_requirements=[
                "segment-anything",
                "torch>=2.0.0",
                "torchvision>=0.15.0",
                "Pillow>=10.3.0",
            ],
            registered_model_name=full_model_name,
            signature=signature,
        )
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"Model logged: {model_info.model_uri}")
    return full_model_name


def _create_or_update_endpoint(workspace_client, full_model_name: str, model_version: str) -> None:
    from databricks.sdk.errors import NotFound
    from databricks.sdk.service.serving import (
        EndpointCoreConfigInput,
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
    config = EndpointCoreConfigInput(name=ENDPOINT_NAME, served_models=served_models)

    try:
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        ready = str(ep.state.ready) if ep.state else ""
        config_update = str(ep.state.config_update) if ep.state else ""
        if ready == "EndpointStateReady.READY":
            print(f"Endpoint '{ENDPOINT_NAME}' already READY. Skipping.")
            return
        if config_update == "EndpointStateConfigUpdate.UPDATE_FAILED":
            print(f"Endpoint '{ENDPOINT_NAME}' is in UPDATE_FAILED. Deleting and recreating...")
            workspace_client.serving_endpoints.delete(name=ENDPOINT_NAME)
            time.sleep(15)
            workspace_client.serving_endpoints.create(name=ENDPOINT_NAME, config=config)
        elif config_update not in (
            "EndpointStateConfigUpdate.NOT_UPDATING",
            "",
        ):
            print(f"Endpoint '{ENDPOINT_NAME}' is already updating (update={config_update}). Waiting...")
        else:
            print(f"Updating endpoint '{ENDPOINT_NAME}'...")
            workspace_client.serving_endpoints.update_config(
                name=ENDPOINT_NAME, served_models=served_models
            )
    except NotFound:
        print(f"Creating endpoint '{ENDPOINT_NAME}'...")
        workspace_client.serving_endpoints.create(name=ENDPOINT_NAME, config=config)

    for _ in range(120):
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        ready = ep.state.ready if ep.state else None
        config_update = ep.state.config_update if ep.state else None
        print(f"  state: ready={ready} config_update={config_update}")
        if str(ready) == "EndpointStateReady.READY":
            print(f"Endpoint '{ENDPOINT_NAME}' is READY.")
            return
        if (str(ready) == "EndpointStateReady.NOT_READY" and
                str(config_update) == "EndpointStateConfigUpdate.NOT_UPDATING"):
            raise RuntimeError(f"Endpoint '{ENDPOINT_NAME}' failed (terminal NOT_READY).")
        time.sleep(10)
    raise RuntimeError(f"Endpoint '{ENDPOINT_NAME}' did not reach READY within 20 minutes.")


def _get_latest_model_version(workspace_client, full_model_name: str) -> str:
    versions = list(workspace_client.model_versions.list(full_model_name))
    if not versions:
        raise RuntimeError(f"No versions for '{full_model_name}'")
    return sorted(versions, key=lambda v: int(v.version), reverse=True)[0].version


def write_endpoint_name(name: str, output_path: str = DEFAULT_OUTPUT) -> None:
    with open(output_path, "w") as f:
        f.write(name + "\n")


def main() -> None:
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    catalog, schema = _get_catalog_schema()
    print(f"Using catalog={catalog} schema={schema}")
    full_model_name = _log_sam_model(w, catalog, schema)
    version = _get_latest_model_version(w, full_model_name)
    print(f"Model version: {version}")
    _create_or_update_endpoint(w, full_model_name, version)
    write_endpoint_name(ENDPOINT_NAME)
    print(f"SAM endpoint name written to: {DEFAULT_OUTPUT}")


if __name__ == "__main__":
    main()
