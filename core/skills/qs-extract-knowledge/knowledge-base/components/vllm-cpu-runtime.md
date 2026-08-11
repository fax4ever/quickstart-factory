---
name: vllm-cpu-runtime
description: "KServe ServingRuntime running vLLM on x86 CPU with OCI modelcar storage, no GPU required, for lightweight inference on RHOAI"
summary: "Deploys vLLM inference on Intel x86 CPUs (AVX512 preferred) without GPUs via a KServe ServingRuntime (v1alpha1) in Standard/Knative deployment mode, loading models through OCI modelcar storage (oci:// URI) with the Red Hat certified vllm-cpu-rhel9 image as a standalone Helm chart. Use for lightweight CPU-only model serving when GPUs are unavailable; unlike GPU-based RawDeployment mode, Standard mode requires both Red Hat OpenShift Service Mesh and Serverless operators installed. Enables tool calling via --enable-auto-tool-choice with Hermes parser; downstream consumers discover the endpoint at <model-name>-predictor.<namespace>.svc.cluster.local:8080/v1; resources default to 2-8 CPU / 8Gi memory with VLLM_CPU_KVCACHE_SPACE controlling KV cache size. VLLM_CPU_KVCACHE_SPACE is set to \"2\" in ServingRuntime but overridden to \"4\" in InferenceService (IS value wins at runtime); LD_PRELOAD=/usr/lib64/libomp.so improves vLLM but breaks pyarrow (list both if needed); security.opendatahub.io/enable-auth is explicitly false; modelLoadingTimeoutMillis is 90s for CPU-based loading."
metadata:
  type: component
tags:
  tech_stack: [vllm, kserve, helm]
  ai_pattern: [model-serving, agents]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: []
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "CPU-only vLLM ServingRuntime with TinyLlama via OCI modelcar, KServe Standard deployment mode, tool-calling enabled"
    approach: "A"
---

# vLLM CPU Runtime

## Overview

The vLLM CPU runtime is a KServe ServingRuntime that runs vLLM inference on x86 CPUs without any GPU. It is deployed as a `ServingRuntime` (`serving.kserve.io/v1alpha1`) paired with a `InferenceService` (`v1beta1`) in KServe Standard (Knative-based) deployment mode. In the llm-cpu-serving quickstart it serves TinyLlama loaded from an OCI container image (modelcar pattern), targeting environments where GPUs are unavailable or unnecessary.

## Tech Stack & Dependencies

- **Runtime:** KServe ServingRuntime (v1alpha1) with vLLM, KServe Standard deployment mode (Knative)
- **Container image:** `registry.redhat.io/rhaii/vllm-cpu-rhel9` (Red Hat certified, pinned by digest)
- **Key dependencies:** RHOAI/OpenShift AI operator, Red Hat OpenShift Service Mesh, Red Hat OpenShift Serverless (required for Standard/Knative deployment mode)
- **Helm subchart:** None (standalone chart `vllm-cpu` v1.0.0)
- **Target hardware:** Intel x86 CPUs (preferably AVX512-capable), no GPU

## Key Patterns

### CPU-Only ServingRuntime with Tool Calling

The ServingRuntime uses the `v1alpha1` API and configures vLLM for CPU inference with auto tool choice and the Hermes tool-call parser. The `modelLoadingTimeoutMillis` is set to 90000 (90 seconds) to account for CPU-based model loading:

```yaml
# From helm/templates/servingruntime.yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  annotations:
    opendatahub.io/template-name: vllm-cpu
    openshift.io/display-name: vLLM CPU (x86) ServingRuntime for KServe
  name: vllm-cpu
spec:
  builtInAdapter:
    modelLoadingTimeoutMillis: 90000
  containers:
    - args:
        - --model
        - /mnt/models
        - --port
        - "8080"
        - --max-model-len
        - {{ .Values.model.maxModelLen | quote }}
        - '--served-model-name'
        - {{ .Values.model.name }}
        - '--enable-auto-tool-choice'
        - '--tool-call-parser'
        - 'hermes'
      image: {{ .Values.images.vllmRuntime }}
      name: kserve-container
      env:
        - name: VLLM_CPU_KVCACHE_SPACE
          value: "2"
```

### OCI Modelcar Storage

Instead of downloading models from Hugging Face at deploy time, this quickstart uses the OCI modelcar pattern. The model is pre-packaged as an OCI container image and referenced via `oci://` URI. A data connection Secret stores the URI for KServe:

```yaml
# From helm/values.yaml
model:
  storageUri: "oci://quay.io/rh-aiservices-bu/tinyllama:1.0"
  name: "tinyllama"
  maxModelLen: 2048
```

```yaml
# From helm/templates/modelcar-dataconnection.yaml
kind: Secret
metadata:
  name: tinyllama-10-on-quayio
  annotations:
    opendatahub.io/connection-type-ref: uri-v1
data:
  URI: b2NpOi8vcXVheS5pby9yaC1haXNlcnZpY2VzLWJ1L3RpbnlsbGFtYToxLjA=
```

### KServe Standard (Knative) Deployment Mode

Unlike GPU-based model serving which typically uses `RawDeployment` mode, this component uses KServe Standard deployment mode (Knative-based). The InferenceService sets cluster-local visibility and references the `vllm-cpu` runtime:

```yaml
# From helm/templates/inferenceservice.yaml
metadata:
  annotations:
    serving.kserve.io/deploymentMode: Standard
  labels:
    networking.knative.dev/visibility: cluster-local
spec:
  predictor:
    maxReplicas: 1
    minReplicas: 1
    model:
      modelFormat:
        name: vLLM
      runtime: vllm-cpu
      storageUri: {{ .Values.model.storageUri | quote }}
```

### CPU Resource Profile

The InferenceService requests CPU and memory only, with no GPU resources. The default profile requests 2 CPUs with a limit of 8, and 8Gi memory:

```yaml
# From helm/values.yaml
resources:
  inference:
    requests:
      cpu: "2"
      memory: "8Gi"
    limits:
      cpu: "8"
      memory: "8Gi"
```

### Downstream Service Discovery

Downstream consumers (AnythingLLM workbench) discover the vLLM endpoint via KServe's predictor service naming convention (`<model-name>-predictor:8080`). The connection is wired through a Secret:

```yaml
# From helm/templates/anythingllm-secret.yaml
stringData:
  LOCAL_AI_BASE_PATH: "http://{{ .Values.model.name }}-predictor.{{ .Release.Namespace }}.svc.cluster.local:8080/v1"
```

## Configuration

- **Environment variables:**
  - `VLLM_CPU_KVCACHE_SPACE` - CPU KV cache size in GB. Set to `"2"` in ServingRuntime, overridden to `"4"` in InferenceService
  - `HF_HOME` - Hugging Face cache directory (set to `/tmp/hf_home` in InferenceService)
  - `LD_PRELOAD` - Optional: set to `/usr/lib64/libomp.so` to override default jemalloc for better vLLM performance (documented in README, not set by default)

- **Helm values:**
  - `images.vllmRuntime` - vLLM CPU container image (default: `registry.redhat.io/rhaii/vllm-cpu-rhel9@sha256:...`)
  - `model.storageUri` - OCI URI for the model image (default: `oci://quay.io/rh-aiservices-bu/tinyllama:1.0`)
  - `model.name` - Model name used for InferenceService naming and `--served-model-name` (default: `tinyllama`)
  - `model.maxModelLen` - Maximum model context length passed to vLLM `--max-model-len` (default: `2048`)
  - `model.maxOutputTokens` - Maximum output tokens (default: `512`, used by Llama Stack playground)
  - `resources.inference.requests.cpu` / `limits.cpu` - CPU allocation (default: 2 request / 8 limit)
  - `resources.inference.requests.memory` / `limits.memory` - Memory allocation (default: 8Gi)
  - `storageClassName` - Storage class for PVCs (default: `gp3-csi`)

- **RHOAI annotations:**
  - `opendatahub.io/accelerator-name: ""` - Explicitly empty (no GPU accelerator)
  - `opendatahub.io/recommended-accelerators: ""` - No recommended accelerators
  - `opendatahub.io/apiProtocol: REST` - REST API protocol
  - `opendatahub.io/runtime-version: v0.18.0` - vLLM runtime version
  - `opendatahub.io/serving-runtime-scope: global` - Global scope runtime

## Known Gotchas

- **`VLLM_CPU_KVCACHE_SPACE` set in two places with different values:** The ServingRuntime sets `VLLM_CPU_KVCACHE_SPACE` to `"2"` while the InferenceService sets it to `"4"`. The InferenceService value takes precedence at pod runtime. Found in `helm/templates/servingruntime.yaml` (line 36) and `helm/templates/inferenceservice.yaml` (line 44).

- **LD_PRELOAD jemalloc vs libomp trade-off:** The README documents that the default `LD_PRELOAD` in the vllm-cpu-rhel9 image sets jemalloc for pyarrow compatibility. Setting `LD_PRELOAD` to `/usr/lib64/libomp.so` overrides jemalloc and improves vLLM performance, but degrades pyarrow usage. If both are needed, both libraries should be listed in `LD_PRELOAD`. Found in README under "(Optional) Configure LD_PRELOAD".

- **Intel x86 with optional AVX512:** The README notes this image is compiled for Intel CPUs. AVX512 is preferred for running compressed models but is optional. Found in README: "This version is compiled for Intel CPU's (preferably with AVX512 enabled)".

- **Standard deployment mode requires Service Mesh and Serverless:** Unlike `RawDeployment` mode used by GPU-based model serving, the KServe Standard mode here requires both Red Hat OpenShift Service Mesh and Red Hat OpenShift Serverless operators to be installed. Found in README under "Minimum software requirements".

- **`security.opendatahub.io/enable-auth` is set to `false`:** Authentication is explicitly disabled on the InferenceService. Found in `helm/templates/inferenceservice.yaml` (line 8): `security.opendatahub.io/enable-auth: 'false'`.

## Testing Notes

- Deploy with `helm install ${PROJECT} helm/ --namespace ${PROJECT}` after creating the namespace with `oc new-project`
- Wait for pods: the predictor pod should show `2/2` ready containers (model container + queue-proxy sidecar from Knative)
- Verify model endpoint responds at `<model-name>-predictor:8080/v1` within the cluster
- Minimum hardware: 2 CPU cores, 4Gi memory, 5Gi storage (from README)
- Recommended hardware: 32 cores, 64Gi memory for production workloads (from README)
- Uninstall with `helm uninstall ${PROJECT} --namespace ${PROJECT}`

## Related Patterns

- Model Serving (GPU-based vLLM with KServe in RawDeployment mode)
- KServe InferenceService with modelcar/OCI storage (deployment pattern)
- Llama Stack playground integration (architecture pattern)
