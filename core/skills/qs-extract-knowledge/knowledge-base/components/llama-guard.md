---
name: llama-guard
description: "Llama Guard 3-1B safety model served via vLLM on KServe with GPU/Xeon dual-device support and OTel tracing"
summary: "Deploys Meta's Llama-Guard-3-1B as a dedicated KServe InferenceService with vLLM ServingRuntime to provide content safety classification for Llama Stack's inline::llama-guard safety provider via a vllm-safety remote::vllm inference provider. Use when Llama Stack needs shield-based safety evaluation — a single device value (gpu|xeon) indexes parallel maps for images, resources, node selectors, and tolerations, with GPU using sha256-pinned quay.io/modh/vllm at gpuMemoryUtilization 0.40 (intentionally low for shared-GPU nodes) and Xeon requiring a pre-built vllm-xeon-opentelemetry image in the cluster's internal registry. InferenceService uses RawDeployment mode with OCI modelcar storage at /mnt/models (KServe standard path, not HuggingFace ID), OTel tracing enabled by default via gRPC to the cluster's OTel Collector, /dev/shm Memory-backed emptyDir for vLLM IPC, and Llama Stack wiring requires registering both model and shield under meta-llama/Llama-Guard-3-1B with predictor URL http://llama-guard-3-1b-predictor/v1. Readiness probe uses tcpSocket:8080 (not /health) because vLLM answers TCP before HTTP during model loading; runAsNonRoot: false may conflict with restricted SCCs despite dropping all capabilities; network policy (enabled by default) restricts access to pods labeled app.kubernetes.io/name: llama-stack; HF_HOME is deduped in the ServingRuntime template via a conditional skip to avoid duplication with static env vars."
metadata:
  type: component
tags:
  tech_stack: [vllm, kserve, helm, python]
  ai_pattern: [guardrails, model-serving]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: []
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Llama Guard 3-1B deployed as a KServe InferenceService with vLLM ServingRuntime, dual GPU/Xeon device selection, OCI modelcar storage, and OpenTelemetry tracing for the Llama Stack safety provider"
    approach: "A"
---

# Llama Guard

## Overview

Llama Guard is a safety/shield model (Meta's Llama-Guard-3-1B) deployed as a dedicated KServe InferenceService backed by a vLLM ServingRuntime. It provides content safety classification for the Llama Stack safety API, acting as the backend for the `inline::llama-guard` safety provider. The chart supports both NVIDIA GPU and Intel Xeon CPU inference through a `device` toggle that switches images, resources, node selectors, and tolerations.

## Tech Stack & Dependencies

- **Runtime:** vLLM inference server (OpenAI-compatible API on port 8080)
- **Container image (GPU):** `quay.io/modh/vllm` (sha256-pinned)
- **Container image (Xeon):** `image-registry.openshift-image-registry.svc:5000/openshift/vllm-xeon-opentelemetry:v0.14.1-ubi9`
- **Model:** `meta-llama/Llama-Guard-3-1B` via OCI modelcar (`oci://quay.io/rh-aiservices-bu/llama-guard-3-1b-modelcar:2.0.0`)
- **Key dependencies:** KServe (ServingRuntime + InferenceService CRDs), NVIDIA GPU or Intel Xeon 4th-gen+
- **Helm subchart:** Standalone chart at `helm/03-ai-services/llama-guard/` (not a subchart dependency)

## Key Patterns

### Dual-Device Selection (GPU vs Xeon)

The chart uses a single `device` value (`gpu` or `xeon`) to index into parallel maps for images, resources, node selectors, tolerations, and affinity. This avoids conditional duplication across templates.

```yaml
# values.yaml
device: gpu # Options: gpu, xeon
image:
  gpu:
    repository: "quay.io/modh/vllm@sha256"
    tag: "4f550996130e7d16cacb24ca9a2865e7cf51eddaab014ceaf31a1ea6ef86d4ec"
  xeon:
    repository: "image-registry.openshift-image-registry.svc:5000/openshift/vllm-xeon-opentelemetry"
    tag: "v0.14.1-ubi9"
resources:
  gpu:
    requests:
      nvidia.com/gpu: 1
      memory: 8Gi
      cpu: 4
  xeon:
    requests:
      cpu: 4
      memory: 16Gi
```

In templates, device-specific values are resolved via Go template indexing:

```yaml
# servingruntime.yaml
{{- $device := lower (.Values.device | default "gpu") }}
{{- $image := index .Values.image $device }}
{{- $resources := index .Values.resources $device }}
```

### KServe RawDeployment Mode with OCI Modelcar

The InferenceService uses `RawDeployment` mode (not serverless/Knative) and loads the model from an OCI modelcar artifact rather than S3/PVC storage.

```yaml
# inferenceservice.yaml
metadata:
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
    serving.knative.openshift.io/enablePassthrough: 'true'
    sidecar.istio.io/inject: 'true'
spec:
  predictor:
    model:
      modelFormat:
        name: vLLM
      runtime: llama-guard-3-1b
      storageUri: oci://quay.io/rh-aiservices-bu/llama-guard-3-1b-modelcar:2.0.0
```

### OpenTelemetry Tracing Integration

The ServingRuntime injects vLLM's native OTel tracing flags when `servingRuntime.tracing.enabled` is true. This enables distributed tracing across the Llama Stack request chain.

```yaml
# servingruntime.yaml (conditional tracing args)
{{- if .Values.servingRuntime.tracing.enabled }}
    - --otlp-traces-endpoint
    - {{ .Values.servingRuntime.tracing.otlpTracesEndpoint }}
    - --collect-detailed-traces
    - {{ .Values.servingRuntime.tracing.collectDetailedTraces | quote }}
{{- end }}
```

Default tracing values point to the cluster's OTel Collector:

```yaml
# values.yaml
tracing:
  enabled: true
  otlpTracesEndpoint: "grpc://otel-collector-collector.observability-hub.svc.cluster.local:4317"
  collectDetailedTraces: "all"
  serviceName: "vllm-llama-guard"
  insecure: true
```

### Llama Stack Safety Provider Wiring

Llama Stack connects to Llama Guard through two integration points: a `vllm-safety` inference provider (pointing at the KServe predictor URL) and an `inline::llama-guard` safety provider that uses it for shield evaluation.

```yaml
# llama-stack configmap (run.yaml)
providers:
  inference:
    - provider_id: vllm-safety
      provider_type: remote::vllm
      config:
        url: "http://llama-guard-3-1b-predictor/v1"
        max_tokens: 20000
  safety:
    - provider_id: llama-guard
      provider_type: inline::llama-guard
      config:
        excluded_categories: []
models:
  - model_id: meta-llama/Llama-Guard-3-1B
    provider_id: vllm-safety
    model_type: llm
shields:
  - shield_id: meta-llama/Llama-Guard-3-1B
```

### Shared Memory Volume for vLLM

The ServingRuntime mounts a `Memory`-backed emptyDir at `/dev/shm` for vLLM's inter-process communication, sized via `shmSizeLimit`.

```yaml
# servingruntime.yaml
volumes:
  - name: shm
    emptyDir:
      medium: Memory
      sizeLimit: {{ .Values.servingRuntime.shmSizeLimit | default "2Gi" }}
```

## Configuration

- **Environment variables:**
  - `HF_HOME` / `TRANSFORMERS_CACHE`: Set to `/tmp/hf_home` for writable model cache
  - `CUDA_VISIBLE_DEVICES`: GPU device index (GPU mode only, default `"0"`)
  - `VLLM_CPU_KVCACHE_SPACE`: CPU KV cache size in GB (Xeon mode only, default `4`)
  - `OTEL_SERVICE_NAME`: Tracing service name (default `vllm-llama-guard`)
  - `OTEL_EXPORTER_OTLP_TRACES_INSECURE`: Whether to skip TLS for OTLP export (default `true`)
- **Helm values:**
  - `device`: Toggle between `gpu` and `xeon` deployment profiles
  - `model.maxModelLen`: Context window length (default `24000`)
  - `model.gpuMemoryUtilization`: GPU memory fraction (default `0.40`, GPU only)
  - `model.dtype`: Data type (default `half`)
  - `servingRuntime.distributedExecutorBackend`: Multi-process backend (default `mp`)
  - `servingRuntime.modelLoadingTimeoutMillis`: Model load timeout (default `90000` / 90s)
  - `inferenceService.storageUri`: OCI modelcar URI
  - `networkPolicy.enabled`: Controls network policy creation (default `true`)

## Known Gotchas

- **GPU memory utilization set low:** The default `gpuMemoryUtilization` is `0.40` (commented out in values but applied via template default), which is conservative for a 1B model. This is intentional in the repo because the GPU is shared with the main Llama 3.2-3B inference model on the same node.
- **Xeon image uses internal registry:** The Xeon vLLM image (`image-registry.openshift-image-registry.svc:5000/openshift/vllm-xeon-opentelemetry`) is expected to be pre-built and pushed to the cluster's internal image registry, not pulled from an external registry.
- **Readiness probe uses tcpSocket, not HTTP:** Unlike the liveness probe which checks `/health`, the readiness probe uses `tcpSocket` on port 8080. This is because vLLM may respond to TCP before the HTTP health endpoint is ready during model loading.
- **Model path is `/mnt/models`:** The ServingRuntime args pass `--model=/mnt/models` which is the KServe-standard mount point where the modelcar contents are placed, not the HuggingFace model ID.
- **Network policy restricts access:** By default, only pods with label `app.kubernetes.io/name: llama-stack` and the OpenShift ingress namespace can reach llama-guard on port 8080.
- **`runAsNonRoot: false` in pod security context:** Despite setting `allowPrivilegeEscalation: false` and dropping all capabilities, the pod security context sets `runAsNonRoot: false`, which may conflict with restricted SCCs on OpenShift.
- **HF_HOME env dedup in template:** The servingruntime template explicitly skips `HF_HOME` from the device-specific env map because it's already set as a static env var, using `{{- if ne $key "HF_HOME" }}` to avoid duplication.

## Testing Notes

- Verify the InferenceService becomes ready: check for `llama-guard-3-1b` InferenceService in the namespace with `READY=True`
- Confirm the predictor URL is reachable from within the cluster at `http://llama-guard-3-1b-predictor/v1`
- Test safety classification by sending a prompt through Llama Stack's safety API and confirming shield evaluation results
- For Xeon deployments, verify the `vllm-xeon-opentelemetry` image exists in the internal registry before deploying

## Related Patterns

- Llama Stack safety provider configuration (see llama-stack-instance configmap)
- vLLM model serving pattern (shared with llama3.2-3b chart in same repo)
- OpenTelemetry tracing across the inference chain
