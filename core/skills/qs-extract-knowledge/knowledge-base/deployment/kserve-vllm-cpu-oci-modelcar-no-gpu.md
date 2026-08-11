---
name: kserve-vllm-cpu-oci-modelcar-no-gpu
description: KServe ServingRuntime and InferenceService deploying vLLM on CPU-only nodes with OCI modelcar and KV cache tuning
summary: "Deploys vLLM in CPU-only mode via KServe ServingRuntime (vllm-cpu-rhel9 image, 90s model load timeout) and InferenceService with OCI modelcar storage (storageUri: oci://) instead of PVC/S3, enabling function calling (--enable-auto-tool-choice --tool-call-parser hermes) with configurable --max-model-len (default 2048) and --served-model-name. Use when serving small LLMs on CPU nodes without GPU -- requires OpenShift Serverless and Service Mesh operators; cluster-local visibility keeps endpoint internal with RHOAI auth disabled for in-cluster consumers like AnythingLLM or Llama Stack. VLLM_CPU_KVCACHE_SPACE controls CPU KV cache allocation and appears in both CRDs -- InferenceService value (4GB) overrides ServingRuntime (2GB); resources default to 2-8 CPU cores and 8Gi memory with single-replica serving. OCI modelcar makes model directory read-only (must set HF_HOME=/tmp/hf_home), the vLLM CPU image requires Intel x86 with AVX512 (e.g., AWS m6i.4xlarge), and container-build-oci-modelcar-hf-download.md covers building the consumed modelcar image."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, vllm]
  ai_pattern: [model-serving]
  platform: [kserve, vllm, rhoai, openshift]
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "CPU-only vLLM ServingRuntime with tool-choice parsing, OCI modelcar storage, and VLLM_CPU_KVCACHE_SPACE tuning"
    approach: "A"
---

# KServe vLLM CPU-Only with OCI Modelcar Storage

## Overview

This pattern deploys vLLM in CPU-only mode via KServe ServingRuntime and InferenceService, with no GPU requirement. The model is loaded from an OCI modelcar image (container image holding only model weights) rather than a PVC or S3-backed storage. CPU-specific environment variables tune the KV cache for systems without GPU memory.

## Pattern Description

Two KServe CRDs work together: a ServingRuntime that defines the vLLM CPU container with model serving arguments and CPU-specific configuration, and an InferenceService that references the runtime and the OCI model image. The ServingRuntime uses the Red Hat AI Infrastructure `vllm-cpu-rhel9` image which is compiled for Intel CPUs. The InferenceService uses `storageUri: oci://` to pull model weights from a container registry as a modelcar sidecar, rather than downloading from S3 or a PVC.

## Implementation

### ServingRuntime for vLLM CPU

```yaml
# helm/templates/servingruntime.yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  annotations:
    opendatahub.io/accelerator-name: ""
    opendatahub.io/recommended-accelerators: ""
    opendatahub.io/template-display-name: vLLM CPU (x86) ServingRuntime for KServe
    opendatahub.io/template-name: vllm-cpu
  name: vllm-cpu
  labels:
    opendatahub.io/dashboard: "true"
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
      ports:
        - containerPort: 8080
          name: http1
          protocol: TCP
  multiModel: false
  supportedModelFormats:
    - autoSelect: true
      name: vLLM
```

### InferenceService with OCI Modelcar

```yaml
# helm/templates/inferenceservice.yaml (excerpt)
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  annotations:
    security.opendatahub.io/enable-auth: 'false'
    serving.kserve.io/deploymentMode: Standard
    opendatahub.io/hardware-profile-name: default-profile
    opendatahub.io/connections: tinyllama-10-on-quayio
  name: {{ .Values.model.name }}
  labels:
    networking.knative.dev/visibility: cluster-local
spec:
  predictor:
    maxReplicas: 1
    minReplicas: 1
    model:
      modelFormat:
        name: vLLM
      resources:
        limits:
          cpu: {{ .Values.resources.inference.limits.cpu | quote }}
          memory: {{ .Values.resources.inference.limits.memory | quote }}
        requests:
          cpu: {{ .Values.resources.inference.requests.cpu | quote }}
          memory: {{ .Values.resources.inference.requests.memory | quote }}
      runtime: vllm-cpu
      storageUri: {{ .Values.model.storageUri | quote }}
      env:
        - name: HF_HOME
          value: /tmp/hf_home
        - name: VLLM_CPU_KVCACHE_SPACE
          value: "4"
```

## Configuration

- **Key settings:** `VLLM_CPU_KVCACHE_SPACE` (set to `2` in ServingRuntime, `4` in InferenceService) controls how much memory in GB is allocated for KV cache on CPU; `--max-model-len` (default 2048 from values.yaml) limits context length; `--enable-auto-tool-choice` and `--tool-call-parser hermes` enable function calling
- **Defaults:** CPU requests 2 cores / 8Gi memory, limits 8 cores / 8Gi; `maxReplicas: 1` and `minReplicas: 1` for single-replica serving; `builtInAdapter.modelLoadingTimeoutMillis: 90000` (90s model load timeout); `deploymentMode: Standard` uses Knative/Serverless
- **Dependencies:** Red Hat OpenShift Serverless and Service Mesh operators (for Standard/Knative deployment mode); KServe with OCI modelcar support; the vLLM CPU image `registry.redhat.io/rhaii/vllm-cpu-rhel9` pinned by digest

## Gotchas

- The `VLLM_CPU_KVCACHE_SPACE` env var appears in both the ServingRuntime (value `"2"`) and the InferenceService (value `"4"`) -- the InferenceService value takes precedence at pod level since it is set on the model container directly (see `helm/templates/servingruntime.yaml` and `helm/templates/inferenceservice.yaml`)
- `HF_HOME` is set to `/tmp/hf_home` in the InferenceService to avoid writing to the model directory, which is read-only when using OCI modelcar storage (see `helm/templates/inferenceservice.yaml`)
- The `networking.knative.dev/visibility: cluster-local` label on the InferenceService keeps the model endpoint internal to the cluster -- it is not exposed via a Route (see `helm/templates/inferenceservice.yaml`)
- The `security.opendatahub.io/enable-auth: 'false'` annotation disables RHOAI authentication on the model endpoint, allowing in-cluster services (AnythingLLM, Llama Stack) to connect without tokens (see `helm/templates/inferenceservice.yaml`)
- The vLLM CPU image is compiled for Intel x86 CPUs (preferably with AVX512) -- the README notes `m6i.4xlarge` as a good AWS instance type (see README.md)

## Related Patterns

- `container-build-oci-modelcar-hf-download.md` -- the Containerfile that builds the OCI modelcar image consumed by this InferenceService
- `helm-flat-chart-direct-crd-templating.md` -- the flat chart structure containing these KServe templates
