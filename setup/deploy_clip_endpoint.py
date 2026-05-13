"""Deploy OpenCLIP ViT-B/32 as an MLflow pyfunc endpoint.

Endpoint: instockcv-clip (CPU Small, scale-to-zero)

Input:  DataFrame with "image" (base64 string)
Output: DataFrame with "embedding" (JSON array of 512 floats)

Run locally:
    pip install open-clip-torch torch torchvision Pillow mlflow databricks-sdk
    python -m setup.deploy_clip_endpoint --catalog vdm_classic_rikfy0_catalog --schema instockcv_dev
"""
from __future__ import annotations
import os
import time

ENDPOINT_NAME = "instockcv-clip"
MODEL_NAME = "clip_image_encoder"
CLIP_MODEL_NAME = "ViT-B-32"
CLIP_PRETRAINED = "openai"

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.getcwd()

DEFAULT_OUTPUT = os.path.join(_here, "clip_endpoint_name.txt")


def _get_catalog_schema() -> tuple[str, str]:
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--catalog", default=os.environ.get("CATALOG", "vdm_classic_rikfy0_catalog"))
    parser.add_argument("--schema", default=os.environ.get("SCHEMA", "instockcv_dev"))
    args, _ = parser.parse_known_args()
    return args.catalog, args.schema


def _log_clip_model(workspace_client, catalog: str, schema: str) -> str:
    import mlflow
    import mlflow.pyfunc
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

    class ClipPyfunc(mlflow.pyfunc.PythonModel):
        def load_context(self, context):
            import open_clip
            import torch
            self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="openai"
            )
            self.model.eval()
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model = self.model.to(self.device)

        def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
            import base64
            import json
            import torch
            from io import BytesIO
            from PIL import Image as PILImage

            results = []
            for _, row in model_input.iterrows():
                img = PILImage.open(BytesIO(base64.b64decode(row["image"]))).convert("RGB")
                tensor = self.preprocess(img).unsqueeze(0).to(self.device)
                with torch.no_grad():
                    embedding = self.model.encode_image(tensor)
                    embedding = embedding / embedding.norm(dim=-1, keepdim=True)
                vec = embedding[0].cpu().tolist()
                results.append({"embedding": json.dumps(vec)})
            return pd.DataFrame(results)

    from mlflow.models.signature import ModelSignature
    from mlflow.types.schema import ColSpec, Schema

    signature = ModelSignature(
        inputs=Schema([ColSpec("string", "image")]),
        outputs=Schema([ColSpec("string", "embedding")]),
    )

    mlflow.set_experiment("/Users/jesus.rodriguez@databricks.com/clip_image_encoder")
    with mlflow.start_run(run_name="clip_image_encoder_registration"):
        model_info = mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=ClipPyfunc(),
            artifacts={},
            pip_requirements=[
                "open-clip-torch>=2.24.0",
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
    from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedModelInput

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
        workspace_client.serving_endpoints.update_config(
            name=ENDPOINT_NAME, served_models=served_models
        )
    except NotFound:
        workspace_client.serving_endpoints.create(name=ENDPOINT_NAME, config=config)

    for _ in range(120):
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        ready = ep.state.ready if ep.state else None
        config_update = ep.state.config_update if ep.state else None
        print(f"  state: ready={ready}")
        if str(ready) == "EndpointStateReady.READY":
            print(f"Endpoint '{ENDPOINT_NAME}' is READY.")
            return
        if (str(ready) == "EndpointStateReady.NOT_READY" and
                str(config_update) == "EndpointStateConfigUpdate.NOT_UPDATING"):
            raise RuntimeError(f"Endpoint '{ENDPOINT_NAME}' failed.")
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
    full_model_name = _log_clip_model(w, catalog, schema)
    version = _get_latest_model_version(w, full_model_name)
    _create_or_update_endpoint(w, full_model_name, version)
    write_endpoint_name(ENDPOINT_NAME)
    print(f"CLIP endpoint name written to: {DEFAULT_OUTPUT}")


if __name__ == "__main__":
    main()
