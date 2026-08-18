---
name: runtime-deployer
description: Kubernetes Job that programmatically creates KServe ServingRuntime and InferenceService resources on RHOAI
summary: "Python Kubernetes Job on UBI8/Python 3.12 that programmatically creates KServe ServingRuntime and InferenceService CRs on RHOAI, supporting dual runtimes (OVMS: openvino_ir/onnx/tensorflow/paddle/pytorch formats, REST 8888; Triton: onnx/tensorflow/pytorch/tensorrt, REST 8000), single/multi-model modes, GPU tolerations via nvidia.com/gpu, and optional Model Registry v1alpha3 lookup via DEPLOY_FROM_REGISTRY=true. Use when automating KServe model serving deployment via Helm Jobs with ArgoCD sync-wave ordering; RUNTIME_TYPE selects openvino (OVMS) or kserve (Triton), with Makefile deploy-gpu/deploy-cpu targets and all config driven by env vars (MULTI_MODEL_SERVING, GPU_ENABLED, S3_BUCKET, RESOURCE_REQ_*). Helm template bundles six resources (SCC, ServiceAccount, Role, RoleBinding, SCC RoleBinding, Job); deployer uses try-create/catch-409-update idempotency pattern and 300-second readiness polling at 10-second intervals. OVMS multi-model rejects per-model CLI flags when --config_path is set; RawDeployment merges ServingRuntime+template args causing \"Model parameters in CLI are exclusive with config file\" -- fix by overriding predictor.model.args; Triton multi-model requires --strict-model-config=false; KServe storage.path stripping means MinIO prefix must be triton/ not triton/stem; storage-config secret uses namespace as key matching KServe storage.key convention."
metadata:
  type: component
tags:
  tech_stack: [python, kubernetes-client, uv]
  ai_pattern: [model-serving, multimodal]
  platform: [kserve, rhoai, openshift, openvino, triton]
  data_layer: [minio]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Job-based runtime deployer supporting OVMS and Triton with single/multi-model serving and optional Model Registry integration"
    approach: "A"
---

# Runtime Deployer

## Overview

A Python-based Kubernetes Job that programmatically creates KServe `ServingRuntime` and `InferenceService` custom resources on OpenShift AI. It replaces manual dashboard clicks with a Helm-driven, environment-variable-configured deployer that supports two runtime backends (OpenVINO Model Server and NVIDIA Triton), single- and multi-model serving modes, and optional Model Registry integration for version resolution.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 on UBI8 (`registry.access.redhat.com/ubi8/python-312`)
- **Container image:** Built from `app/runtime/Containerfile`, uses `uv` (v0.9.7) for dependency management
- **Key dependencies:** `kubernetes>=35.0.0` (Python client for K8s API)
- **Helm integration:** Not a subchart; deployed as a Job within the parent `ppe-compliance-monitor` Helm chart via `templates/runtime-deployer.yaml`

## Key Patterns

### Dual-Runtime Support (OVMS vs Triton)

The deployer builds different `ServingRuntime` specs depending on `RUNTIME_TYPE`. The `runtime_type` config selects the builder function and determines which image, ports, args, and model formats are used.

```python
# create_runtime.py - runtime dispatch
if cfg["runtime_type"] == "kserve":
    spec = build_kserve_serving_runtime_spec(cfg)
else:
    spec = build_serving_runtime_spec(cfg)
```

OVMS defaults to REST port 8888 / gRPC 9000; Triton uses REST 8000 / gRPC 9000. Each runtime advertises different `supportedModelFormats` (OVMS: openvino_ir, onnx, tensorflow, paddle, pytorch; Triton: onnx, tensorflow, pytorch, tensorrt).

### Multi-Model vs Single-Model Serving

The deployer handles both modes. Multi-model OVMS uses `--config_path=/mnt/models/config.json` while single-model uses `--model_path=/mnt/models` with `--model_name={{.Name}}`.

```python
# create_runtime.py - OVMS args selection (lines 336-349)
if cfg.get("multi_model_serving") and cfg["runtime_type"] == "openvino":
    return [
        "--config_path=/mnt/models/config.json",
        f"--port={cfg['grpc_port']}",
        f"--rest_port={cfg['rest_port']}",
        *common_tail_config_file,
    ]
return [
    "--model_name={{.Name}}",
    # ...single-model args with nireq, plugin_config...
]
```

### Helm Job with RBAC Bootstrap

The Helm template bundles six resources in a single file (`runtime-deployer.yaml`): SCC (optional), ServiceAccount, Role, RoleBinding, SCC RoleBinding (optional), and the Job itself. ArgoCD sync-wave annotation (`"1"`) ensures it runs after prerequisite resources.

```yaml
# runtime-deployer.yaml - Role permissions
rules:
  - apiGroups: [""]
    resources: ["secrets", "serviceaccounts"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
  - apiGroups: ["serving.kserve.io"]
    resources: ["servingruntimes", "inferenceservices"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
```

### Model Registry Integration

When `DEPLOY_FROM_REGISTRY=true`, the deployer fetches model metadata from the RHOAI Model Registry v1alpha3 API instead of relying on static S3 env vars. It resolves the registered model by name, finds versions, extracts storage URIs from custom properties or artifacts, and parses S3 URIs.

```python
# create_runtime.py - registry lookup flow (lines 96-162)
api_base = f"{cfg['model_registry_url']}/api/model_registry/v1alpha3"
response = requests.get(f"{api_base}/registered_model", params={"name": model_name})
# ...resolve version, extract storage_uri from customProperties or artifacts...
bucket, model_path = _parse_s3_uri(storage_uri)
```

### Create-or-Update Idempotency

All K8s resource creation uses a try-create / catch-409-update pattern, making the Job safe to re-run.

```python
# create_runtime.py - idempotent resource creation (lines 218-228)
def create_or_update_resource(create_fn, update_fn, resource_name):
    try:
        create_fn()
        print(f"{resource_name} created")
    except ApiException as e:
        if e.status == 409:
            update_fn()
            print(f"{resource_name} updated")
        else:
            raise
```

### GPU Support with Tolerations

When `GPU_ENABLED=true`, the deployer adds `nvidia.com/gpu` resource requests/limits and optional node tolerations to the InferenceService predictor spec. Tolerations are passed as JSON via the `GPU_TOLERATIONS` env var.

```yaml
# values.yaml - GPU config for kserve runtime
kserve:
  gpu:
    enabled: true
    count: "1"
    tolerations:
      - key: g5-gpu
        operator: Exists
        effect: NoSchedule
```

## Configuration

- **Environment variables:** All configuration flows through env vars set by the Helm Job template. Key vars include:
  - `RUNTIME_TYPE` - `openvino` or `kserve` (selects runtime backend)
  - `DEPLOY_MODEL` - `true`/`false` (enable/disable deployment)
  - `MULTI_MODEL_SERVING` - `true`/`false` (single vs multi-model)
  - `INFERENCE_SERVICE_NAME` - explicit ISVC name (required for multi-model)
  - `DEPLOY_FROM_REGISTRY` / `MODEL_REGISTRY_URL` - enable Model Registry lookup
  - `S3_BUCKET`, `S3_MODEL_PATH`, `MINIO_ENDPOINT` - S3 model location
  - `SERVING_RUNTIME_IMAGE` - container image for the model server
  - `GPU_ENABLED`, `GPU_COUNT`, `GPU_TOLERATIONS` - GPU configuration
  - `RESOURCE_REQ_CPU`, `RESOURCE_REQ_MEMORY`, `RESOURCE_LIM_CPU`, `RESOURCE_LIM_MEMORY` - resource requests/limits
- **Config files:** None beyond `pyproject.toml` for dependencies; all config is env-var driven
- **Helm values:** Controlled via `runtimeDeployer.*` and `modelServing.*` in `values.yaml`

## Known Gotchas

- **OVMS multi-model CLI conflict:** With `--config_path`, OVMS rejects per-model CLI flags (`nireq!=0`, non-empty `plugin_config`, `batch_size`, `shape`). The code uses a separate `common_tail_config_file` list that omits these flags for multi-model mode. Source: comment at line 327-328 of `create_runtime.py`.
- **RawDeployment args merging with multi-model OVMS:** RawDeployment merges ServingRuntime args with per-model template args (`--model_name`, `--model_path`). Multi-model OVMS uses only `--config_path`; mixing both makes OVMS exit with "Model parameters in CLI are exclusive with the config file". The fix is setting `predictor.model.args` to replace the merged list. Source: comment at lines 596-599 of `create_runtime.py`.
- **Triton strict-model-config for multi-model:** When `runtime_type=kserve` (Triton), `--strict-model-config=false` is appended so optional fields in `config.pbtxt` do not cause errors. Without this, auto-generated configs for some models fail to load. Source: comment at lines 426-428 of `create_runtime.py`.
- **KServe storage.path vs model directory structure:** For Triton single-model, the MinIO prefix must be `triton/` (not `triton/<stem>`). KServe strips `storage.path` under `/mnt/models`, so `triton/ppe` yields `.../1/model.onnx` (invalid model name "1") while `triton` yields `.../ppe/1/model.onnx`. Source: comment at lines 301-302 of `values.yaml`.
- **Storage secret keyed by namespace:** The `storage-config` secret uses the namespace as the key in `string_data`, matching the KServe `storage.key` convention. Source: `create_storage_secret()` at line 261.

## Testing Notes

- Verify the Job completes: `kubectl get jobs -l app.kubernetes.io/component=runtime-deployer -n <namespace>`
- Check ServingRuntime exists: `kubectl get servingruntimes -n <namespace>`
- Check InferenceService readiness: `kubectl get isvc -n <namespace>` -- status should show `Ready=True`
- The deployer has a built-in 300-second readiness wait with 10-second polling
- Use `make deploy-gpu` or `make deploy-cpu` to select runtime type via Makefile

## Related Patterns

- `minio.md` -- S3 storage backend for model artifacts
- `model-serving.md` -- broader model serving patterns on RHOAI
