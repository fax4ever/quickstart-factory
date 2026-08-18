---
name: kserve-vllm-device-keyed-gpu-xeon-values
description: KServe vLLM charts with device-keyed values.yaml sections for GPU and Xeon CPU resource/image/scheduling
summary: "Solves deploying KServe vLLM model serving across both NVIDIA GPU and Intel Xeon CPU hardware from a single Helm chart by organizing images, resources, nodeSelector, tolerations, affinity, and env vars (CUDA_VISIBLE_DEVICES for GPU, VLLM_CPU_KVCACHE_SPACE for Xeon) under device-type keys in one values.yaml, resolved via Helm index function from a top-level device value. Use when a vLLM serving chart on RHOAI/KServe must support GPU (sha256-digest quay.io image, nvidia.com/gpu: 1, 16Gi memory, --gpu_memory_utilization=0.95) and Xeon CPU (internal registry vLLM-xeon image, 16 CPUs, 32Gi memory) deployments switchable at install time via --set device=xeon through the DEVICE env var, eliminating separate value files or Helm profiles. Both ServingRuntime and InferenceService templates use index .Values.<section> $device to select device-specific configuration including resources and tolerations; InferenceService references OCI modelcar storage (oci://quay.io/redhat-ai-services/modelcar-catalog); OTel tracing flags (otlp-traces-endpoint, collect-detailed-traces) are conditionally injected via servingRuntime.tracing.enabled. Gotchas: Xeon image must be pre-imported into the cluster's internal registry openshift namespace; Xeon nodeSelector/tolerations are commented out by default requiring cluster-specific customization; GPU uses digest image references while Xeon uses tags causing upgrade confusion; --gpu_memory_utilization is conditionally GPU-only to avoid Xeon GPU allocation errors."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, vllm]
  ai_pattern: [model-serving]
  platform: [kserve, openshift, rhoai]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-kickstart/llama-stack-observability"
    notes: "llama3.2-3b and llama-guard charts use device-keyed values for gpu/xeon image, resources, tolerations, nodeSelector, affinity"
    approach: "A"
---

# KServe vLLM Charts with Device-Keyed GPU/Xeon Values

## Overview

This pattern structures Helm values for KServe vLLM model serving charts using device-type keys (gpu, xeon) to organize image references, resource requests/limits, node selectors, tolerations, and affinity rules. A single `device` value toggles the entire deployment configuration between GPU and Intel Xeon CPU deployments without separate value files or Helm profiles.

## Pattern Description

Instead of using separate values files or Helm profiles for GPU vs CPU deployments, all device-specific configuration is organized under device-type keys within a single values.yaml. The templates use Helm's `index` function to select the correct section based on a top-level `device` value. This applies consistently across image selection, resource allocation, scheduling constraints, and runtime arguments. The pattern enables switching between GPU and Xeon CPU inference with a single `--set device=xeon` override.

## Implementation

### Device-Keyed Values Structure

Each configuration dimension has separate sections keyed by device type:

```yaml
# helm/03-ai-services/llama3.2-3b/values.yaml
device: "gpu"  # Options: gpu, xeon

image:
  gpu:
    repository: "quay.io/rcarrata/vllm-otlp-tracing@sha256"
    tag: "16f83f585..."
    chatTemplate: "/app/data/template/tool_chat_template_llama3.2_json.jinja"
    env:
      CUDA_VISIBLE_DEVICES: "0"
  xeon:
    repository: 'image-registry.openshift-image-registry.svc:5000/openshift/vllm-xeon-opentelemetry'
    tag: "v0.14.1-ubi9"
    chatTemplate: "/app/data/template/tool_chat_template_llama3.2_json.jinja"
    env:
      VLLM_CPU_KVCACHE_SPACE: "16"

resources:
  gpu:
    requests:
      nvidia.com/gpu: 1
      memory: 16Gi
      cpu: 2
    limits:
      nvidia.com/gpu: 1
      memory: 24Gi
      cpu: 4
  xeon:
    requests:
      cpu: 16
      memory: 32Gi
    limits:
      cpu: 32
      memory: 64Gi
```

### Template Selection via index Function

Templates resolve the active device section using Helm's `index` built-in:

```yaml
# helm/03-ai-services/llama3.2-3b/templates/servingruntime.yaml
{{- $device := lower (.Values.device | default "gpu") }}
{{- $image := index .Values.image $device }}
{{- $resources := index .Values.resources $device }}

spec:
  containers:
  - name: kserve-container
    image: {{ (index $image "repository") }}:{{ (index $image "tag") }}
    args:
    {{- if eq $device "gpu" }}
    - --gpu_memory_utilization={{ .Values.model.gpuMemoryUtilization | default 0.95 }}
    {{- end }}
    resources:
      {{- toYaml $resources | nindent 6 }}
```

### Device-Keyed Scheduling Configuration

Node selectors, tolerations, and affinity follow the same device-keyed pattern:

```yaml
# helm/03-ai-services/llama3.2-3b/values.yaml
nodeSelector:
  gpu:
    nvidia.com/gpu.present: "true"
# xeon:
#   intel.com/cpu-gen: "spr"

tolerations:
  gpu:
  - effect: NoSchedule
    operator: Exists

affinity:
  gpu:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: nvidia.com/gpu.present
            operator: In
            values: ["true"]
```

### InferenceService with Device-Keyed Resources

The InferenceService template also uses the device-keyed resources:

```yaml
# helm/03-ai-services/llama3.2-3b/templates/inferenceservice.yaml
spec:
  {{- $device := lower (.Values.device | default "gpu") }}
  {{- $resources := index .Values.resources $device }}
  {{- $tolerations := index .Values.tolerations $device }}
  predictor:
    model:
      resources:
        {{- toYaml $resources | nindent 8 }}
      storageUri: "oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct"
    {{- if $tolerations }}
    tolerations:
      {{- toYaml $tolerations | nindent 6 }}
    {{- end }}
```

### OTel Tracing Toggle in ServingRuntime

The vLLM container args conditionally include tracing flags:

```yaml
# helm/03-ai-services/llama3.2-3b/templates/servingruntime.yaml
    {{- if .Values.servingRuntime.tracing.enabled }}
    - --otlp-traces-endpoint
    - {{ .Values.servingRuntime.tracing.otlpTracesEndpoint }}
    - --collect-detailed-traces
    - {{ .Values.servingRuntime.tracing.collectDetailedTraces | quote }}
    {{- end }}
```

## Configuration

- **Key settings:** `device` (gpu or xeon) is the primary toggle; `servingRuntime.tracing.enabled` controls OTel integration; `model.maxModelLen` controls context window; `inferenceService.storageUri` references the OCI modelcar image
- **Defaults:** Device defaults to gpu; tracing enabled by default pointing to `otel-collector-collector.observability-hub.svc.cluster.local:4317`; GPU resources request 1 nvidia.com/gpu with 16Gi memory; Xeon resources request 16 CPUs with 32Gi memory
- **Dependencies:** KServe with vLLM support; nvidia.com/gpu resource available for GPU mode; for Xeon mode, the vLLM-xeon image must be pre-built in the internal registry (`image-registry.openshift-image-registry.svc:5000/openshift/vllm-xeon-opentelemetry`)

## Gotchas

- The GPU image uses a sha256 digest reference (`quay.io/rcarrata/vllm-otlp-tracing@sha256:...`) for reproducibility, while the Xeon image uses a tag (`v0.14.1-ubi9`) -- mixing digest and tag references can cause confusion during upgrades (see `helm/03-ai-services/llama3.2-3b/values.yaml`)
- The Xeon image is pulled from the internal OpenShift registry (`image-registry.openshift-image-registry.svc:5000`), requiring the image to be pre-imported into the cluster's openshift namespace (see `helm/03-ai-services/llama3.2-3b/values.yaml`)
- Xeon node selector and tolerations are commented out in values.yaml, requiring users to uncomment and customize for their cluster's CPU node labeling strategy (see values.yaml comments mentioning `intel.com/cpu-gen: "spr"`)
- The `--gpu_memory_utilization` flag is conditionally added only for GPU device type; omitting it for Xeon avoids vLLM attempting to allocate GPU memory (see `helm/03-ai-services/llama3.2-3b/templates/servingruntime.yaml`)
- The deploy script passes `--set device="$DEVICE"` at install time, allowing the DEVICE env var to override the values.yaml default (see `scripts/deploy-ai-workloads.sh`)

## Related Patterns

- `otel-sidecar-inject-vllm-model-metrics.md` -- OTel sidecar that collects metrics/traces from these vLLM pods
- `helm-uwm-podmonitor-vllm.md` -- PodMonitors that scrape metrics from these vLLM model pods
