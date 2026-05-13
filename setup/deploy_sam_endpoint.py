"""Deploy EfficientViT-SAM-L0 as an MLflow pyfunc endpoint.

Model: han-cai/efficientvit-sam, checkpoint xl1.pt (L1 variant)
Endpoint: instockcv-sam (GPU Small, scale-to-zero)

Input:  DataFrame with "image" (base64 JPEG/PNG) and "bbox" (JSON "[x1,y1,x2,y2]")
Output: DataFrame with "mask" (base64 PNG, same H×W as input, binary mask)

Run locally (requires efficientvit, torch, torchvision, Pillow, huggingface_hub):
    pip install efficientvit torch torchvision Pillow huggingface_hub mlflow databricks-sdk
    python -m setup.deploy_sam_endpoint --catalog vdm_classic_rikfy0_catalog --schema instockcv_dev
"""
from __future__ import annotations
import os
import time

ENDPOINT_NAME = "instockcv-sam"
MODEL_NAME = "sam_shelf_segmenter"
HF_REPO = "mit-han-lab/efficientvit-sam"
HF_FILENAME = "efficientvit_sam_xl1.pt"

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
            from efficientvit.sam_model_zoo import create_sam_model
            from efficientvit.models.efficientvit.sam import EfficientViTSamPredictor
            self.predictor = EfficientViTSamPredictor(
                create_sam_model("xl1", pretrained=context.artifacts["sam_weights"])
            )

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
                masks, iou_scores, _ = self.predictor.predict(
                    box=np.array([bbox], dtype=float),
                    multimask_output=True,
                )
                best_mask = masks[iou_scores.argmax()]
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

    print(f"Downloading EfficientViT-SAM weights from '{HF_REPO}'...")
    from huggingface_hub import hf_hub_download
    hf_weights = hf_hub_download(repo_id=HF_REPO, filename=HF_FILENAME)
    tmp_dir = tempfile.mkdtemp()
    weights_path = os.path.join(tmp_dir, HF_FILENAME)
    shutil.copy2(hf_weights, weights_path)
    print(f"Weights: {weights_path} ({os.path.getsize(weights_path) // 1024 // 1024} MB)")

    mlflow.set_experiment("/Users/jesus.rodriguez@databricks.com/sam_shelf_segmenter")
    with mlflow.start_run(run_name="sam_shelf_segmenter_registration"):
        model_info = mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=SamPyfunc(),
            artifacts={"sam_weights": weights_path},
            pip_requirements=[
                "efficientvit>=2.1.0",
                "torch>=2.0.0",
                "torchvision>=0.15.0",
                "Pillow>=10.3.0",
            ],
            registered_model_name=full_model_name,
            signature=signature,
        )
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
        if str(ep.state.ready) == "EndpointStateReady.READY":
            print(f"Endpoint '{ENDPOINT_NAME}' already READY. Skipping.")
            return
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
        if str(config_update) == "EndpointStateConfigUpdate.UPDATE_FAILED":
            raise RuntimeError(f"Endpoint '{ENDPOINT_NAME}' update failed.")
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
