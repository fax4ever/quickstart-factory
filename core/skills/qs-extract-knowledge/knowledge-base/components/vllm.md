---
name: vllm
description: "Standalone Helm chart deploying vLLM as KServe InferenceService+ServingRuntime in RawDeployment mode with optional OAuth proxy on RHOAI"
summary: "Standalone Helm chart deploying vLLM as a KServe InferenceService (v1beta1) in RawDeployment mode on RHOAI, with ServingRuntime (v1alpha1) using community UBI9 vLLM image pinned by digest, Memory-backed emptyDir at /dev/shm for IPC, and three model storage backends (HF URI, S3, PVC) for serving quantized LLMs like Qwen2.5-7B-Instruct-AWQ on NVIDIA GPUs. Use for single-model GPU serving on 24GB GPUs (A10G) with AWQ 4-bit quantization -- integrates as a conditional umbrella chart dependency gated by vllm.enabled (disabled by default; Ollama preferred for CPU-only) with LLM mode switching (ollama/vllm/external) and endpoint discovery via <name>-predictor:8080/v1. Critical config: security.enableAuth triggers RHOAI OAuth proxy sidecar injection patched by a post-install Helm hook Job with --upstream-timeout; runtime args --enforce_eager, --max-num-seqs=4, --gpu-memory-utilization=0.90 trade throughput for memory to fit 24GB; chart creates ServiceAccount with kubernetes.io/service-account-token Secret and sets automountServiceAccountToken: false on predictor; requires dual tolerations for nvidia.com/gpu and g5-gpu taints. Gotchas: OAuth-proxy patch Job silently exits 0 if RHOAI sidecar webhook has not injected yet; serving.knative.dev/progress-deadline annotation is set despite RawDeployment (not Knative) mode; HAProxy route timeout defaults to 600s; vLLM is disabled by default in the umbrella chart requiring explicit --set vllm.enabled=true and llm.mode=vllm."
metadata:
  type: component
tags:
  tech_stack: [vllm, kserve, helm, oauth-proxy]
  ai_pattern: [model-serving]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: []
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Single-model vLLM chart (Qwen2.5-7B-Instruct-AWQ) with KServe RawDeployment, optional OAuth proxy auth, and umbrella chart integration for local/external LLM switching"
    approach: "A"
---

# vLLM

## Overview

The vLLM component is a standalone Helm chart that deploys a vLLM-based model as a KServe InferenceService in RawDeployment mode on RHOAI. In the peoplemesh quickstart, it serves Qwen2.5-7B-Instruct-AWQ on a single NVIDIA GPU (optimized for A10G 24GB), providing inference for a people management application. The chart creates a dedicated ServingRuntime (v1alpha1) with the community vLLM image, and optionally enables OAuth proxy authentication via a post-install Helm hook Job.

## Tech Stack & Dependencies

- **Runtime:** KServe InferenceService (v1beta1, RawDeployment mode) with ServingRuntime (v1alpha1)
- **Container image:** `quay.io/redhat-ai-dev/vllm-openai-ubi9` (community UBI9 image, pinned by digest `sha256:b8f4ad3cb7a3b7db6ba168c4c9658d9ef0e9014633ba9435db6f93ec1f5ec328`)
- **Key dependencies:** RHOAI/OpenShift AI operator, NVIDIA GPU node, KServe
- **Helm subchart:** None (standalone chart `vllm` v0.1.0, used as dependency in `peoplemesh-umbrella` umbrella chart)

## Key Patterns

### ServingRuntime with Community vLLM Image

The ServingRuntime uses the `v1alpha1` API and runs vLLM's OpenAI-compatible API server. It exposes Prometheus metrics on port 8080, sets `HF_HOME` to `/tmp/hf_home`, and mounts a `Memory`-backed emptyDir at `/dev/shm` for vLLM's inter-process communication:

```yaml
# From charts/vllm/templates/servingruntime.yaml
spec:
  containers:
    - args:
        - '--port=8080'
        - '--model=/mnt/models'
        - '--served-model-name={{ "{{.Name}}" }}'
      command:
        - python
        - '-m'
        - vllm.entrypoints.openai.api_server
      env:
        - name: HF_HOME
          value: /tmp/hf_home
      image: 'quay.io/redhat-ai-dev/vllm-openai-ubi9@sha256:b8f4ad3cb...'
  volumes:
    - emptyDir:
        medium: Memory
        sizeLimit: 2Gi
      name: shm
```

### Flexible Model Storage Backends

The InferenceService template supports three storage modes via conditional logic -- `uri` (Hugging Face download), `s3` (S3 bucket), and `pvc` (PersistentVolumeClaim). The default uses a Hugging Face URI to download the AWQ-quantized model at deploy time:

```yaml
# From charts/vllm/templates/inferenceservice.yaml
{{- if eq .Values.model.storage.type "s3" }}
storageUri: {{ .Values.model.storage.s3Bucket | quote }}
{{- else if eq .Values.model.storage.type "pvc" }}
storageUri: pvc://{{ .Values.model.storage.pvcName }}
{{- else if eq .Values.model.storage.type "uri" }}
storageUri: {{ .Values.model.storage.uri | quote }}
{{- end }}
```

```yaml
# From charts/vllm/values.yaml
storage:
  type: uri
  uri: "hf://Qwen/Qwen2.5-7B-Instruct-AWQ"
  s3Bucket: ""
  pvcName: ""
```

### AWQ Quantization for 24GB GPUs

The default vLLM runtime args configure AWQ 4-bit quantization with memory-conservative settings to fit within a 24GB GPU. The `--enforce_eager` flag disables CUDA graph capture and `--gpu-memory-utilization=0.90` caps VRAM usage:

```yaml
# From charts/vllm/values.yaml
runtime:
  args:
    - --quantization
    - awq
    - --max-model-len=8192
    - --enforce_eager
    - --gpu-memory-utilization
    - "0.90"
    - --max-num-seqs
    - "4"
    - --task=generate
    - --trust_remote_code
```

### Optional OAuth Proxy Authentication

When `security.enableAuth: true`, the InferenceService is annotated with `security.opendatahub.io/enable-auth: "true"` to trigger RHOAI's oauth-proxy sidecar injection. A post-install Helm hook Job patches the oauth-proxy container to add `--upstream-timeout` for long-running inference requests:

```yaml
# From charts/vllm/templates/oauth-proxy-patch-job.yaml
annotations:
  "helm.sh/hook": post-install,post-upgrade
  "helm.sh/hook-weight": "10"
  "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
```

The Job uses `oc get deployment` + `jq` to find the predictor deployment, check if oauth-proxy exists, and patch it idempotently. It includes a dedicated ServiceAccount, Role, and RoleBinding scoped to `apps/deployments` with get/list/patch/update verbs.

### ServiceAccount with Token Secret for API Access

The chart creates a ServiceAccount, Role, and RoleBinding that grant `get` access to the InferenceService resource, plus a `kubernetes.io/service-account-token` Secret for downstream consumers to authenticate:

```yaml
# From charts/vllm/templates/token-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: default-name-{{ .Values.model.name }}-sa
  annotations:
    kubernetes.io/service-account.name: {{ .Values.model.name }}-sa
type: kubernetes.io/service-account-token
```

### Umbrella Chart Integration with LLM Mode Switching

The vLLM chart is deployed as a conditional dependency in the `peoplemesh-umbrella` chart, gated by `vllm.enabled`. The parent application switches between local vLLM, Ollama, or external LLM endpoints via an `llm.mode` value:

```yaml
# From peoplemesh-umbrella/Chart.yaml
dependencies:
  - name: vllm
    version: 0.1.0
    repository: "file://../charts/vllm"
    condition: vllm.enabled
```

```yaml
# From peoplemesh-umbrella/values.yaml
vllm:
  enabled: false  # Disabled by default - use Ollama instead
```

The downstream application discovers the vLLM endpoint via the KServe predictor service naming convention:

```yaml
# From charts/peoplemesh/values.yaml
llm:
  mode: ollama  # Options: ollama, vllm, external
  vllm:
    serviceName: peoplemesh-llm-predictor
    modelName: peoplemesh-llm
```

## Configuration

- **Environment variables:**
  - `HF_HOME` - Hugging Face cache directory (set to `/tmp/hf_home` in ServingRuntime)

- **Helm values:**
  - `model.name` - Model name used for all resource naming (default: `peoplemesh-llm`)
  - `model.displayName` - Display name shown in OpenShift AI dashboard (default: `Peoplemesh LLM`)
  - `model.storage.type` - Storage backend: `uri`, `s3`, or `pvc` (default: `uri`)
  - `model.storage.uri` - Hugging Face URI for model download (default: `hf://Qwen/Qwen2.5-7B-Instruct-AWQ`)
  - `model.runtime.name` - ServingRuntime resource name (default: `peoplemesh-vllm-runtime`)
  - `model.runtime.args` - vLLM serving arguments including quantization, max-model-len, and memory config
  - `model.resources` - GPU and compute resource requests/limits (default: 1 GPU, 8-12Gi memory)
  - `model.scaling.minReplicas` / `maxReplicas` - Replica bounds (default: 1/1)
  - `route.enabled` - Enable OpenShift route creation (default: `true`)
  - `route.timeout` - HAProxy route timeout (default: `600s`)
  - `route.oauthProxyUpstreamTimeout` - OAuth proxy upstream timeout (default: `10m`)
  - `security.enableAuth` - Enable OAuth proxy authentication (default: `false`)

- **RHOAI annotations:**
  - `opendatahub.io/accelerator-name: migrated-gpu` - GPU accelerator profile name
  - `opendatahub.io/apiProtocol: REST` - REST API protocol
  - `opendatahub.io/runtime-version: v0.11.0` - vLLM runtime version
  - `opendatahub.io/serving-runtime-scope: global` - Global scope runtime
  - `opendatahub.io/template-name: vllm-cuda-runtime-0-11-0` - Template identifier
  - `opendatahub.io/dashboard: "true"` - Makes resources visible in OpenShift AI dashboard
  - `serving.kserve.io/deploymentMode: RawDeployment` - KServe raw deployment mode (no Knative)

## Known Gotchas

- **OAuth-proxy patch Job races with RHOAI sidecar injection:** The post-install Job waits up to 10 minutes for the predictor deployment, then checks for the oauth-proxy container. If RHOAI's webhook has not yet injected the sidecar, the Job skips the patch and exits 0 with a warning: `"WARNING: oauth-proxy container not found in deployment. Skipping patch."`. Found in `charts/vllm/templates/oauth-proxy-patch-job.yaml` lines 49-52.

- **`--enforce_eager` and `--max-num-seqs=4` trade throughput for memory:** The default args disable CUDA graph capture (`--enforce_eager`) and limit concurrent sequences to 4 (`--max-num-seqs=4`), which reduces peak memory usage but lowers inference throughput. This is necessary to fit the AWQ-quantized 7B model within a 24GB GPU with `--gpu-memory-utilization=0.90`. Found in `charts/vllm/values.yaml` runtime args.

- **`automountServiceAccountToken: false` on predictor spec:** The InferenceService sets `automountServiceAccountToken: false` on the predictor, which prevents the default service account token from being mounted inside the model-serving container. Found in `charts/vllm/templates/inferenceservice.yaml` line 25.

- **vLLM disabled by default in umbrella chart:** The umbrella chart sets `vllm.enabled: false` by default in favor of Ollama for easier CPU-only deployment. Users must explicitly enable vLLM with `--set vllm.enabled=true` and set `peoplemesh.llm.mode=vllm`. Found in `peoplemesh-umbrella/values.yaml` line 147.

- **`serving.knative.dev/progress-deadline` annotation on predictor spec:** Despite using RawDeployment mode (not Knative), the InferenceService predictor annotations include `serving.knative.dev/progress-deadline` set to the oauth-proxy upstream timeout value. Found in `charts/vllm/templates/inferenceservice.yaml` line 52.

- **Both `nvidia.com/gpu` and `g5-gpu` tolerations required:** The InferenceService includes tolerations for both the generic NVIDIA GPU taint (`nvidia.com/gpu`) and the AWS g5 instance-specific taint (`g5-gpu`). Both are needed to schedule on GPU nodes in typical OpenShift clusters with GPU taints. Found in `charts/vllm/templates/inferenceservice.yaml` lines 45-49.

## Testing Notes

- Deploy as part of umbrella: `helm install peoplemesh peoplemesh-umbrella/ --set vllm.enabled=true --set peoplemesh.llm.mode=vllm --namespace peoplemesh --create-namespace`
- Deploy standalone: `helm install vllm charts/vllm/ --namespace peoplemesh`
- Verify InferenceService readiness: `oc get inferenceservice peoplemesh-llm -n <namespace>`
- Check model endpoint responds at `peoplemesh-llm-predictor:8080/v1` within the cluster
- If OAuth enabled, verify the patch Job completed: `oc get jobs -n <namespace> | grep oauth-proxy-patch`
- GPU node required with at least 24GB VRAM (A10G or equivalent)

## Related Patterns

- Model Serving (`model-serving.md`) -- covers multi-model and single-model vLLM KServe patterns from other quickstarts
- vLLM CPU Runtime (`vllm-cpu-runtime.md`) -- CPU-only vLLM with KServe Standard (Knative) deployment mode
- Helm subchart wiring for model endpoint discovery (deployment pattern)
