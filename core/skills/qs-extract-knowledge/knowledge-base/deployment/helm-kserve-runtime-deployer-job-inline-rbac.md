---
name: helm-kserve-runtime-deployer-job-inline-rbac
description: Helm Job with inline SA, Role, RoleBinding, and SCC that programmatically creates KServe ServingRuntime and InferenceService
summary: "Decouples KServe ServingRuntime and InferenceService creation from Helm chart templates by bundling six RBAC resources (optional SCC, ServiceAccount, Role, RoleBinding, optional SCC RoleBinding, and Job) in a single template that runs create_runtime.py via the kubernetes Python client to programmatically create the CRDs. Use when deploying model serving that must toggle between OVMS (CPU/OpenVINO, multi-model via --config_path) and Triton (GPU/ONNX with nvidia.com/gpu resources and tolerations), with ArgoCD sync-wave ordering and optional Model Registry integration (DEPLOY_FROM_REGISTRY=true) -- prefer over direct Helm-templated InferenceService CRDs when runtime logic requires conditional Python-based construction. Critical config: runtimeDeployer.enabled toggles the entire Job; modelServing.runtimeType selects openvino or kserve; Job uses backoffLimit: 3, RawDeployment mode with automountServiceAccountToken: false, and storage-config secret keyed by namespace for KServe storage.key lookup requiring accessible MinIO. Multi-model OVMS --config_path=/mnt/models/config.json is mutually exclusive with per-model CLI flags (--model_name, --model_path); inferenceServiceName defaults to \"ppe\" so predictor Service must match backend.defaultOvmsModelUrl (http://ppe-predictor:9000); Triton requires modelPath: triton not triton/ppe because KServe strips storage.path under /mnt/models yielding invalid model name \"1\"."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python]
  ai_pattern: [model-serving, multimodal]
  platform: [kserve, openvino, triton, rhoai, openshift]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Single template bundles SCC, SA, Role, RoleBinding, and Job; Python script creates ServingRuntime + InferenceService for OVMS or Triton with multi-model and GPU support"
    approach: "A"
---

# KServe Runtime Deployer Job with Inline RBAC

## Overview

A Helm Job template that bundles all required RBAC resources (ServiceAccount, Role, RoleBinding, and optional SCC) in a single template file, then runs a Python script that programmatically creates KServe ServingRuntime and InferenceService custom resources. This pattern decouples model serving infrastructure creation from the main Helm chart, allowing the same Job to deploy either OVMS (CPU/OpenVINO) or Triton (GPU/ONNX) based on a runtime type toggle.

## Pattern Description

Instead of templating ServingRuntime and InferenceService CRDs directly in Helm templates, this pattern uses a Kubernetes Job that runs a Python script (`create_runtime.py`) using the `kubernetes` Python client. The Job template defines six sections in one file: optional SCC, ServiceAccount, Role, RoleBinding, optional SCC RoleBinding, and the Job itself. The Python script supports dual runtime types (OVMS and Triton), multi-model serving, GPU allocation with tolerations, and optional Model Registry integration.

## Implementation

### Single Template with Six Sections

The `runtime-deployer.yaml` template contains all resources separated by `---` dividers:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/runtime-deployer.yaml
{{- if .Values.runtimeDeployer.enabled }}
{{- $fullName := include "ppe-compliance-monitor.fullname" . }}
{{- $saName := printf "%s-runtime-deployer" $fullName }}

# 1. SecurityContextConstraints (optional)
{{- if .Values.runtimeDeployer.scc.enabled }}
apiVersion: security.openshift.io/v1
kind: SecurityContextConstraints
metadata:
  name: {{ $saName }}-scc
# ...
{{- end }}
---
# 2. ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ $saName }}
---
# 3. Role – permissions for create_runtime.py
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ $saName }}
rules:
  - apiGroups: [""]
    resources: ["secrets", "serviceaccounts"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
  - apiGroups: ["serving.kserve.io"]
    resources: ["servingruntimes", "inferenceservices"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
---
# 4. RoleBinding
# 5. SCC RoleBinding (optional)
# 6. Job
```

### Job with ArgoCD Sync Wave

The Job uses an ArgoCD sync wave annotation to order execution after prerequisite resources:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/runtime-deployer.yaml (Job section)
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ $saName }}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  backoffLimit: 3
  template:
    spec:
      serviceAccountName: {{ $saName }}
      restartPolicy: OnFailure
      containers:
        - name: runtime-deployer
          image: "{{ .Values.global.imageRegistry }}/{{ .Values.runtimeDeployer.image.repository }}:{{ .Values.runtimeDeployer.image.tag }}"
```

### Runtime Type Switching via Environment Variables

The Job passes 30+ environment variables to the Python script, branching on `modelServing.runtimeType`:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/runtime-deployer.yaml (env section)
- name: RUNTIME_TYPE
  value: {{ .Values.modelServing.runtimeType | quote }}
{{- if eq .Values.modelServing.runtimeType "kserve" }}
- name: SERVING_RUNTIME_IMAGE
  value: {{ .Values.modelServing.kserve.image | quote }}
- name: GPU_ENABLED
  value: "true"
- name: GPU_COUNT
  value: {{ .Values.modelServing.kserve.gpu.count | quote }}
- name: GPU_TOLERATIONS
  value: {{ .Values.modelServing.kserve.gpu.tolerations | toJson | quote }}
{{- else }}
- name: SERVING_RUNTIME_IMAGE
  value: {{ .Values.modelServing.openvino.image | quote }}
{{- end }}
```

### Python Script: Dual Runtime Support

The `create_runtime.py` script in `app/runtime/` builds either an OVMS or Triton ServingRuntime spec. For multi-model OVMS, it uses `--config_path` instead of per-model CLI flags:

```python
# app/runtime/create_runtime.py (excerpt)
def _build_ovms_args(cfg):
    if cfg.get("multi_model_serving") and cfg["runtime_type"] == "openvino":
        return [
            "--config_path=/mnt/models/config.json",
            f"--port={cfg['grpc_port']}",
            f"--rest_port={cfg['rest_port']}",
            *common_tail_config_file,
        ]
    return [
        "--model_name={{.Name}}",
        f"--port={cfg['grpc_port']}",
        f"--rest_port={cfg['rest_port']}",
        "--model_path=/mnt/models",
        *common_tail,
    ]
```

### InferenceService with GPU and Tolerations

When GPU is enabled, the script adds `nvidia.com/gpu` resources and node tolerations to the predictor spec:

```python
# app/runtime/create_runtime.py (excerpt)
if cfg.get("gpu_enabled"):
    gpu_res = {"nvidia.com/gpu": cfg.get("gpu_count", "1")}
    resources = {
        "requests": {**resources["requests"], **gpu_res},
        "limits": {**resources["limits"], **gpu_res},
    }
if cfg.get("gpu_tolerations"):
    predictor["tolerations"] = cfg["gpu_tolerations"]
```

## Configuration

- **Key settings:** `runtimeDeployer.enabled` toggles the entire Job; `modelServing.runtimeType` selects openvino or kserve; `modelServing.kserve.gpu.enabled` and `modelServing.kserve.gpu.tolerations` control GPU allocation; `runtimeDeployer.inferenceServiceName` sets the KServe ISVC name (defaults to "ppe")
- **Defaults:** `runtimeType: kserve` (Triton GPU path); `backoffLimit: 3`; `runtimeDeployer.scc.enabled: false`; InferenceService uses `RawDeployment` mode with `automountServiceAccountToken: false`
- **Dependencies:** Requires KServe CRDs installed on the cluster (serving.kserve.io); MinIO must be accessible for the storage-config secret

## Gotchas

- Multi-model OVMS uses `--config_path=/mnt/models/config.json` which is mutually exclusive with per-model CLI flags (`--model_name`, `--model_path`, `--nireq`, `--plugin_config`). The script comments note: "Model parameters in CLI are exclusive with the config file"
- The `runtimeDeployer.inferenceServiceName` defaults to "ppe" so the KServe predictor Service becomes `ppe-predictor`, which must match `backend.defaultOvmsModelUrl` (set to `http://ppe-predictor:9000` in values.yaml)
- For Triton, `modelPath: triton` (not `triton/ppe`) is required because KServe strips `storage.path` under `/mnt/models`, so `triton/ppe` would yield `.../1/model.onnx` (invalid model name "1") instead of `.../ppe/1/model.onnx`, as documented in the values.yaml comment
- The storage-config secret keys the data connection by namespace (`cfg["namespace"]`) so KServe can look it up via `storage.key`
- The script supports an optional Model Registry integration path (`DEPLOY_FROM_REGISTRY=true`) that fetches model artifacts from a Model Registry API instead of direct S3

## Related Patterns

- `container-build-multistage-7z-yolo-export-minio-upload.md` -- uploads the model artifacts that this runtime deployer consumes
- `kserve-rawdeployment-detector-fleet-gpu-toggle.md` -- alternative pattern using direct Helm-templated InferenceService CRDs
