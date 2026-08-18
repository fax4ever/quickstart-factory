---
name: llama-32-3b-instruct
description: "KServe vLLM InferenceService for Llama 3.2 3B with OCI modelcar storage, tool-calling, tracing, and GPU/CPU modes"
summary: "Serves Llama 3.2 3B Instruct via KServe vLLM RawDeployment with OCI modelcar storage (oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct), eliminating HuggingFace token requirements and providing an OpenAI-compatible chat completions backend on port 8080 with tool-calling (llama3_json parser, enableAutoToolChoice) across three deployment patterns for guardrails pipelines, high-concurrency demos, and observable Llama Stack applications. Use Approach A (guardrailing-llms) for production workloads needing tunable Helm-conditional vLLM args (enableChunkedPrefill, maxModelLen: 32768, maxNumSeqs: 8), digest-pinned images, always-on replicas wired as chat_generation backend via <name>-predictor.<namespace>.svc.cluster.local, and TrustyAI GuardrailsOrchestrator with /all/ and /passthrough/ detector routes; Approach B (lemonade-stand-assistant) for high-concurrency demos needing conditional self-hosted/MaaS toggle ({{ if not .Values.model }}), scale-to-zero (minReplicas: 0), hardcoded high-throughput args (384 seqs, 4096 context, 12288 batched tokens), tag-based rhoai-2.19-cuda image, and 20Gi memory; Approach C (lls-observability) for observable Llama Stack deployments needing GPU/Xeon dual-device toggle via device-keyed maps, OpenTelemetry tracing via custom vLLM image with otlpTracesEndpoint to OTEL Collector, ConfigMap-mounted chat template via Helm Files.Get, NetworkPolicy restricting ingress to openshift-ingress + llama-stack, and standalone Helm chart supporting 24Gi GPU or 64Gi Xeon (VLLM_CPU_KVCACHE_SPACE=16) resource profiles. All approaches require 1 NVIDIA GPU (GPU mode) and Memory-backed /dev/shm emptyDir (2Gi sizeLimit); A drives args from values.yaml with HF_HOME=/tmp/hf_home and chatTemplate baked into the container at /app/data/template/tool_chat_template_llama3.2_json.jinja; B splits serving args in ServingRuntime and tool-calling args in InferenceService with VLLM_CONFIG_ROOT=/tmp and served-model-name \"llama32\"; C uses served-model-name \"llama3-2-3b\" with 50Gi PVC model cache and per-device env maps. A's InferenceService hardcodes --max-model-len=20000 overriding values.yaml 32768 and has dual vLLM image digests between template default and values.yaml fallback; B's MaaS toggle skips all deployment when any model sub-key is set without validating required fields and its tag-based image may drift across RHOAI releases; C's Xeon image requires a pre-built ImageStream in the openshift namespace, its maxModelLen default of 65000 may exceed memory capacity, and runAsNonRoot: false may conflict with restricted SCCs."
metadata:
  type: component
tags:
  tech_stack: [vllm, kserve, helm, opentelemetry]
  ai_pattern: [model-serving, guardrails]
  platform: [kserve, vllm, rhoai, openshift, openvino]
  data_layer: []
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Llama 3.2 3B Instruct served via KServe vLLM with OCI modelcar storage, tool-calling support, and TrustyAI guardrails orchestrator integration"
    approach: "A"
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "Llama 3.2 3B Instruct with conditional self-hosted/MaaS toggle, hardcoded high-throughput vLLM args, scale-to-zero, and tag-based RHOAI vLLM image for guardrails demo"
    approach: "B"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Llama 3.2 3B Instruct with GPU/Xeon dual-device toggle, OpenTelemetry tracing via custom vLLM image, ConfigMap-mounted chat template, and network policies for Llama Stack integration"
    approach: "C"
---

# Llama 3.2 3B Instruct Model Server

## Overview

The Llama 3.2 3B Instruct model server is a KServe InferenceService running vLLM in RawDeployment mode, deployed as the main LLM backend in the guardrailing-llms quickstart. It serves the Llama 3.2 3B Instruct model from an OCI modelcar image and exposes an OpenAI-compatible chat completions API. The model sits behind the TrustyAI GuardrailsOrchestrator, which routes requests through multiple safety detectors before and after inference.

## Tech Stack & Dependencies

- **Runtime:** KServe InferenceService (RawDeployment mode) with vLLM serving runtime
- **Container image:** `quay.io/modh/vllm@sha256:db766445a1e3455e1bf7d16b008f8946fcbe9f277377af7abb81ae358805e7e2` (RHOAI managed vLLM image, pinned by digest)
- **Key dependencies:** RHOAI/OpenShift AI operator with KServe enabled, 1x NVIDIA GPU with 24GiB+ vRAM, TrustyAI GuardrailsOrchestrator for downstream safety routing
- **Helm subchart:** None (templates embedded directly in the top-level `helm/` chart, `guardrailing-llms` v1.0.0)

## Key Patterns

### OCI Modelcar Storage URI

Instead of downloading from HuggingFace (`hf://`) or referencing a PVC, the model is delivered as a pre-packaged OCI container image. KServe pulls the model weights directly from the container registry, removing the need for a HuggingFace token or external storage setup.

```yaml
# From helm/values.yaml
mainLLM:
  name: llama-32-3b-instruct
  storageUri: "oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct"
```

```yaml
# From helm/templates/inferenceservice-llm.yaml
      storageUri: {{ .Values.mainLLM.storageUri }}
```

All models in this quickstart (LLM and detectors) use the same OCI modelcar pattern, e.g., `oci://quay.io/mmurakam/model-cars:gibberish-text-detector-v0.1.1` for detectors (from `helm/values.yaml`).

### Conditional ServingRuntime Feature Flags

The ServingRuntime template uses Helm conditionals to toggle vLLM feature flags from values.yaml, keeping the runtime definition flexible. Each vLLM feature (auto tool choice, chunked prefill, tool-call parser, chat template, max model length, max num seqs) is independently enabled:

```yaml
# From helm/templates/servingruntime-llm.yaml
    - args:
        - '--port=8080'
        - '--model=/mnt/models'
        - '--served-model-name={{`{{.Name}}`}}'
        {{- if .Values.mainLLM.enableAutoToolChoice }}
        - '--enable-auto-tool-choice'
        {{- end }}
        {{- if .Values.mainLLM.toolCallParser }}
        - '--tool-call-parser'
        - {{ .Values.mainLLM.toolCallParser }}
        {{- end }}
        {{- if .Values.mainLLM.chatTemplate }}
        - '--chat-template'
        - {{ .Values.mainLLM.chatTemplate }}
        {{- end }}
```

### Tool-Calling Configuration for Llama 3.2

The model is configured with vLLM's Llama 3 JSON tool-call parser and a custom Jinja2 chat template, enabling OpenAI-compatible function calling through the guardrails gateway:

```yaml
# From helm/values.yaml
mainLLM:
  enableAutoToolChoice: true
  enableChunkedPrefill: true
  toolCallParser: llama3_json
  chatTemplate: /app/data/template/tool_chat_template_llama3.2_json.jinja
  maxModelLen: 32768
  maxNumSeqs: 8
```

The chat template path (`/app/data/template/...`) is baked into the vLLM container image rather than mounted from a ConfigMap.

### Shared Memory Volume for vLLM

The ServingRuntime mounts a Memory-backed emptyDir at `/dev/shm` for vLLM's internal tensor operations and IPC. This is required for vLLM to function correctly on Kubernetes where `/dev/shm` defaults to 64MB:

```yaml
# From helm/templates/servingruntime-llm.yaml
  volumes:
    - emptyDir:
        medium: Memory
        sizeLimit: 2Gi
      name: shm
```

### TrustyAI Orchestrator Integration

The LLM predictor is wired as the `chat_generation` backend in the TrustyAI GuardrailsOrchestrator config. The orchestrator routes requests through safety detectors before forwarding to the LLM, and checks detector results on the LLM response before returning to the client:

```yaml
# From helm/templates/configmaps.yaml (fms-orchestr8-config-nlp)
    chat_generation:
      service:
        hostname: {{ .Values.mainLLM.name }}-predictor.{{ .Release.Namespace }}.svc.cluster.local
        port: {{ .Values.mainLLM.port }}
```

The gateway routes determine which detectors apply to input vs output. The `/all/` route applies all detectors to both directions:

```yaml
# From helm/templates/configmaps.yaml (fms-orchestr8-config-gateway)
    routes:
      - name: all
        detectors:
          - regex
          - hap
          - prompt_injection
          - gibberish
      - name: passthrough
        detectors:
```

## Configuration

- **Environment variables:**
  - `HF_HOME` - Hugging Face cache directory (set to `/tmp/hf_home` in the ServingRuntime container env, from `helm/templates/servingruntime-llm.yaml`)

- **Helm values:**
  - `mainLLM.name` - InferenceService and ServingRuntime resource name (default: `llama-32-3b-instruct`)
  - `mainLLM.storageUri` - OCI modelcar URI for model weights (default: `oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct`)
  - `mainLLM.image` - vLLM container image with digest pin (default in ServingRuntime: `quay.io/modh/vllm@sha256:0d55...`)
  - `mainLLM.port` - Serving port (default: `8080`)
  - `mainLLM.enableAutoToolChoice` - Enable vLLM auto tool choice (default: `true`)
  - `mainLLM.enableChunkedPrefill` - Enable chunked prefill for better throughput (default: `true`)
  - `mainLLM.toolCallParser` - Tool call parser type (default: `llama3_json`)
  - `mainLLM.chatTemplate` - Path to Jinja2 chat template inside the container (default: `/app/data/template/tool_chat_template_llama3.2_json.jinja`)
  - `mainLLM.maxModelLen` - Maximum model context length (default: `32768`)
  - `mainLLM.maxNumSeqs` - Maximum concurrent sequences (default: `8`)
  - `mainLLM.tolerations` - GPU node tolerations (default: tolerates `nvidia.com/gpu` NoSchedule)

## Known Gotchas

- **Hardcoded InferenceService args conflict with ServingRuntime values:** The InferenceService template (`helm/templates/inferenceservice-llm.yaml`) has hardcoded vLLM args (`--dtype=half`, `--max-model-len=20000`, `--gpu-memory-utilization=0.95`, `--enable-chunked-prefill`, `--enable-auto-tool-choice`, `--tool-call-parser=llama3_json`, `--chat-template=...`) while the ServingRuntime template (`helm/templates/servingruntime-llm.yaml`) generates the same args conditionally from values.yaml (e.g., `maxModelLen: 32768`). The InferenceService model args override the ServingRuntime container args in KServe, so the hardcoded `--max-model-len=20000` takes precedence over the values.yaml setting of `32768`. Changing values.yaml alone will not change the effective max model length.

- **Dual vLLM image defaults in ServingRuntime template:** The ServingRuntime template has a default image in the template itself (`quay.io/modh/vllm@sha256:0d55419f...`) via `{{ .Values.mainLLM.image | default "quay.io/modh/vllm@sha256:0d55..." }}`, and values.yaml specifies a different digest (`sha256:db766445...`). The values.yaml image takes precedence, but if `mainLLM.image` is removed from values.yaml, the template falls back to a different (potentially older) digest. Found in `helm/templates/servingruntime-llm.yaml` line 53 and `helm/values.yaml` line 9.

- **Chat template path assumes baked-in container content:** The `chatTemplate` value (`/app/data/template/tool_chat_template_llama3.2_json.jinja`) references a file inside the vLLM container image, not a mounted ConfigMap. If the vLLM image is updated to a version that does not include this template file, the model server will fail to start. Found in `helm/values.yaml` line 16.

- **GPU resource requests differ between InferenceService and README:** The InferenceService requests 4 CPU / 8Gi memory (from `helm/templates/inferenceservice-llm.yaml`) but README states minimum hardware as 8+ CPU cores total and 16Gi+ RAM total across all components. The LLM pod alone requests 1 GPU, 4 CPU, and 8Gi. Found in `README.md` lines 53-58 and `helm/templates/inferenceservice-llm.yaml` lines 31-37.

## Testing Notes

- Deploy with `helm install guardrails-demo helm/ --namespace guardrails-demo` (from `README.md`)
- The LLM pod name follows the pattern `llama-32-3b-instruct-predictor-<hash>` and should show 2/2 READY containers (from `README.md` pod listing)
- Verify model endpoint via the TrustyAI gateway: `POST http://gorch-sample-service.<namespace>.svc.cluster.local:8090/all/v1/chat/completions` with `{"model": "llama-32-3b-instruct", "messages": [...]}` (from `docs/healthcare-guardrails.ipynb`)
- The `/all/` route applies all detectors; the `/passthrough/` route skips detectors for direct model access (from `helm/templates/configmaps.yaml`)

## Related Patterns

- TrustyAI GuardrailsOrchestrator for multi-detector safety pipelines (architecture pattern)
- OCI modelcar images for air-gapped model distribution (deployment pattern)
- KServe InferenceService with vLLM in RawDeployment mode (see `model-serving.md`)

---

## Approach B: Conditional Self-Hosted/MaaS with High-Throughput Tuning (from lemonade-stand-assistant)

### When to Use

Use this approach when deploying Llama 3.2 3B Instruct as the LLM backend for a high-concurrency demo or event scenario, where the model should be conditionally deployed only when no external MaaS endpoint is configured. The lemonade-stand-assistant quickstart uses this pattern to serve Llama 3.2 behind an fms-orchestr8 guardrails pipeline with scale-to-zero, high batch throughput (384 concurrent sequences), and a short context window (4096 tokens).

### Differences from Approach A

- **Conditional deployment toggle:** The entire template is wrapped in `{{ if not .Values.model }}` -- if a MaaS endpoint is configured in `values.yaml`, the ServingRuntime and InferenceService are not created at all
- **Hardcoded vLLM args:** All vLLM serving parameters are hardcoded directly in the template YAML rather than driven by Helm values with conditionals
- **Tag-based image:** Uses `quay.io/modh/vllm:rhoai-2.19-cuda` (tag-based) instead of a digest-pinned image, following RHOAI release cadence
- **Scale-to-zero:** InferenceService sets `minReplicas: 0` for idle resource savings
- **High-throughput tuning:** 384 max concurrent sequences and 12288 max batched tokens with 4096 context window, optimized for short-response demo traffic
- **Split arg placement:** Serving params (dtype, gpu-memory-utilization, chunked-prefill, max-model-len) in ServingRuntime; tool-calling params (enable-auto-tool-choice, tool-call-parser) in InferenceService predictor model args
- **VLLM_CONFIG_ROOT env var:** Set to `/tmp` in the ServingRuntime container env
- **Higher memory allocation:** 20Gi memory limit on predictor (vs 8Gi in Approach A)

### Conditional Self-Hosted vs MaaS Toggle

The entire model deployment is conditional on `values.yaml`. When `.Values.model` is populated (with `name`, `endpoint`, `port`, `api_key`), the template is skipped and the application connects to an external model-as-a-service endpoint instead:

```yaml
# From chart/templates/llm-llama32.yaml
{{ if not .Values.model }}
---
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
...
{{- end }}
```

```yaml
# From chart/values.yaml — MaaS configuration (empty = deploy self-hosted)
model: {}
  # name: my-model
  # endpoint: my-maas-instance
  # port: 443
  # api_key: my-api-key
```

The downstream application (`lemonade-stand-app`) uses the same toggle to determine the model name and predictor hostname:

```yaml
# From chart/templates/lemonade-stand-app.yaml
- name: VLLM_MODEL
  value: {{ .Values.model.name | default "llama32" }}
```

```yaml
# From chart/templates/fms-orchestr8-config-nlp.yaml
    openai:
      service:
        hostname: {{ .Values.model.endpoint | default "llama-32-predictor" }}
        port: {{ .Values.model.port | default "8080" }}
```

### High-Throughput Demo vLLM Configuration

The ServingRuntime is tuned for high-concurrency, short-response demo traffic with all args hardcoded:

```yaml
# From chart/templates/llm-llama32.yaml (ServingRuntime)
    - args:
        - '--dtype=half'
        - '--gpu-memory-utilization=0.95'
        - '--enable-chunked-prefill'
        - '--port=8080'
        - '--model=/mnt/models'
        - '--served-model-name=llama32'
        - '--max-model-len'
        - '4096'
        - '--max-num-seqs'
        - '384'
        - '--max-num-batched-tokens'
        - '12288'
```

Tool-calling args are placed separately in the InferenceService predictor model section, keeping the ServingRuntime focused on serving configuration:

```yaml
# From chart/templates/llm-llama32.yaml (InferenceService)
    model:
      args:
        - '--enable-auto-tool-choice'
        - '--tool-call-parser=llama3_json'
```

### Scale-to-Zero with Resource Allocation

The InferenceService enables scale-to-zero for idle GPU savings, with higher memory allocation than Approach A to accommodate the high batch throughput:

```yaml
# From chart/templates/llm-llama32.yaml (InferenceService)
  predictor:
    maxReplicas: 1
    minReplicas: 0
    model:
      resources:
        limits:
          cpu: '4'
          memory: 20Gi
          nvidia.com/gpu: '1'
        requests:
          cpu: '1'
          memory: 8Gi
          nvidia.com/gpu: '1'
```

### Configuration (Approach B)

- **Environment variables:**
  - `VLLM_CONFIG_ROOT` - vLLM config directory (set to `/tmp` in ServingRuntime, from `chart/templates/llm-llama32.yaml`)

- **Helm values:**
  - `model` - Empty object `{}` to deploy self-hosted; populate with `name`, `endpoint`, `port`, `api_key` to use external MaaS (from `chart/values.yaml`)

- **Hardcoded template values (not overridable via values.yaml):**
  - `--served-model-name=llama32` - Model name for OpenAI-compatible API
  - `--max-model-len=4096` - Short context window for demo traffic
  - `--max-num-seqs=384` - High concurrent sequence limit
  - `--max-num-batched-tokens=12288` - High batch token limit
  - `--dtype=half` - FP16 precision
  - `--gpu-memory-utilization=0.95` - Aggressive GPU memory usage
  - `modelLoadingTimeoutMillis: 90000` - 90-second model loading timeout

### Known Gotchas (Approach B)

- **All vLLM args are hardcoded in the template:** Unlike Approach A which uses Helm conditionals from values.yaml, this approach hardcodes all vLLM serving parameters directly in `chart/templates/llm-llama32.yaml`. Changing max-model-len, max-num-seqs, or dtype requires editing the template file itself, not values.yaml.

- **Served model name mismatch with Approach A:** The served model name is `llama32` (from `--served-model-name=llama32` in the template), while Approach A uses the KServe `{{.Name}}` template variable. The downstream app references this name via `VLLM_MODEL` env var defaulting to `llama32` (from `chart/templates/lemonade-stand-app.yaml`).

- **MaaS toggle uses empty object check:** The conditional `{{ if not .Values.model }}` is true when `model: {}` (the default). Setting any sub-key under `model` (even just `name`) causes the entire self-hosted deployment to be skipped. There is no validation that all required MaaS fields are populated. Found in `chart/templates/llm-llama32.yaml` line 1 and `chart/values.yaml` lines 2-6.

- **Tag-based image may drift across RHOAI releases:** The vLLM image `quay.io/modh/vllm:rhoai-2.19-cuda` uses a release tag rather than a digest pin. Upgrading the RHOAI release requires updating this tag manually in the template. Found in `chart/templates/llm-llama32.yaml` line 36.

### Testing Notes (Approach B)

- Deploy with `helm install lemonade-stand-assistant chart/ --namespace <namespace>` 
- With default `model: {}`, the ServingRuntime and InferenceService are created; verify with `oc get servingruntime llama-32` and `oc get inferenceservice llama-32`
- The predictor service is `llama-32-predictor` on port 8080, wired as the default in `fms-orchestr8-config-nlp` ConfigMap
- To test MaaS mode, set `model.endpoint` in values.yaml and verify that no ServingRuntime or InferenceService resources are created
- The model server may take time to start due to the 90-second `modelLoadingTimeoutMillis` and OCI image pull

---

---

## Approach C: GPU/Xeon Dual-Device with OpenTelemetry Tracing (from lls-observability)

### When to Use

Use this approach when deploying Llama 3.2 3B Instruct as the inference backend for a Llama Stack application where observability (distributed tracing) is a first-class concern, or when the deployment must support both NVIDIA GPU and Intel Xeon CPU-only nodes via a single chart with a device toggle. The lls-observability quickstart uses this pattern to serve the model behind Llama Stack with full OpenTelemetry trace export to an OTEL Collector.

### Differences from Approach A

- **GPU/Xeon dual-device toggle:** A single `device` value (`gpu` or `xeon`) selects the container image, environment variables, resource requests, node selectors, tolerations, and affinity rules -- all indexed from device-keyed maps in values.yaml
- **Custom vLLM image with OTLP tracing:** Uses `quay.io/rcarrata/vllm-otlp-tracing` (GPU) or internal registry `vllm-xeon-opentelemetry` (Xeon) instead of the standard `quay.io/modh/vllm` RHOAI image -- these images have OpenTelemetry instrumentation baked in
- **ConfigMap-mounted chat template:** The Jinja2 chat template is stored as a Helm `Files.Get` resource in a ConfigMap and volume-mounted into the container, rather than relying on the chat template being baked into the container image
- **Standalone Helm chart:** Full independent chart with Chart.yaml, _helpers.tpl, and its own service account, vs templates embedded in a top-level chart
- **Network policies:** Ingress restricted to openshift-ingress namespace and llama-stack pods
- **PVC for model cache:** 50Gi persistent volume at `/root/.cache` for HuggingFace model cache
- **S3 data connection:** Optional Secret for S3-compatible object storage to back the KServe model source

### GPU/Xeon Dual-Device Toggle

The chart uses a `device` value to index into device-keyed maps for images, resources, node selectors, tolerations, and affinity. Switching from GPU to Xeon requires only changing `device: "xeon"` in values.yaml:

```yaml
# From helm/03-ai-services/llama3.2-3b/values.yaml
device: "gpu"  # Options: gpu, xeon
image:
  gpu:
    repository: "quay.io/rcarrata/vllm-otlp-tracing@sha256"
    tag: "16f83f5858fcc04bd56ea785126c04af823e8aacbeabb9db963f86d252178189"
    chatTemplate: "/app/data/template/tool_chat_template_llama3.2_json.jinja"
    env:
      CUDA_VISIBLE_DEVICES: "0"
      HF_HOME: "/root/.cache/huggingface"
  xeon:
    repository: 'image-registry.openshift-image-registry.svc:5000/openshift/vllm-xeon-opentelemetry'
    tag: "v0.14.1-ubi9"
    chatTemplate: "/app/data/template/tool_chat_template_llama3.2_json.jinja"
    env:
      HOME: /tmp
      XDG_CACHE_HOME: /tmp/.cache
      VLLM_CACHE_ROOT: /tmp/.cache/vllm
      VLLM_CPU_KVCACHE_SPACE: "16"
```

The template resolves the device at render time:

```yaml
# From helm/03-ai-services/llama3.2-3b/templates/servingruntime.yaml
{{- $device := lower (.Values.device | default "gpu") }}
{{- $image := index .Values.image $device }}
{{- $resources := index .Values.resources $device }}
```

Resource profiles differ significantly between devices:

```yaml
# From helm/03-ai-services/llama3.2-3b/values.yaml
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

### OpenTelemetry Tracing Integration

The ServingRuntime conditionally injects OTLP tracing flags and environment variables when `servingRuntime.tracing.enabled` is true. Traces are exported via gRPC to an OTEL Collector:

```yaml
# From helm/03-ai-services/llama3.2-3b/templates/servingruntime.yaml
    {{- if .Values.servingRuntime.tracing.enabled }}
    # tracing-specific flags and options
    - --otlp-traces-endpoint
    - {{ .Values.servingRuntime.tracing.otlpTracesEndpoint }}
    - --collect-detailed-traces
    - {{ .Values.servingRuntime.tracing.collectDetailedTraces | quote }}
    {{- end }}
    env:
    {{- if .Values.servingRuntime.tracing.enabled }}
    - name: OTEL_SERVICE_NAME
      value: {{ .Values.servingRuntime.tracing.serviceName | quote }}
    - name: OTEL_EXPORTER_OTLP_TRACES_INSECURE
      value: {{ .Values.servingRuntime.tracing.insecure | quote }}
    {{- end }}
```

```yaml
# From helm/03-ai-services/llama3.2-3b/values.yaml
servingRuntime:
  tracing:
    enabled: true
    otlpTracesEndpoint: "grpc://otel-collector-collector.observability-hub.svc.cluster.local:4317"
    collectDetailedTraces: "all"
    serviceName: "vllm-llama32b"
    insecure: true
```

### ConfigMap-Mounted Chat Template

Unlike Approaches A and B which rely on the chat template file being baked into the container image, this approach stores the Jinja2 template in a ConfigMap and volume-mounts it into the container. The template file is included via Helm `Files.Get`:

```yaml
# From helm/03-ai-services/llama3.2-3b/templates/configmap-chat-template.yaml
data:
  tool_chat_template_llama3.2_json.jinja: |
{{ .Files.Get "files/tool_chat_template_llama3.2_json.jinja" | nindent 4 }}
```

```yaml
# From helm/03-ai-services/llama3.2-3b/templates/servingruntime.yaml
    volumeMounts:
    - name: chat-template
      mountPath: {{ $chatTemplate | quote }}
      subPath: tool_chat_template_llama3.2_json.jinja
      readOnly: true
  volumes:
  - name: chat-template
    configMap:
      name: {{ include "llama3-2-3b.fullname" . }}-chat-template
      items:
      - key: tool_chat_template_llama3.2_json.jinja
        path: tool_chat_template_llama3.2_json.jinja
```

### Tool-Calling with vLLM Auto Tool Choice

The chart enables vLLM's built-in tool-calling support with the Llama 3 JSON parser, configured directly as ServingRuntime container args:

```yaml
# From helm/03-ai-services/llama3.2-3b/templates/servingruntime.yaml
    - --served-model-name=llama3-2-3b
    - --chat-template={{ $chatTemplate }}
    - --enable-auto-tool-choice
    - --tool-call-parser
    - llama3_json
```

### KServe RawDeployment with OCI Modelcar

The InferenceService uses the same RawDeployment mode and OCI modelcar storage as Approach A, with device-aware resource selection:

```yaml
# From helm/03-ai-services/llama3.2-3b/templates/inferenceservice.yaml
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
spec:
  {{- $device := lower (.Values.device | default "gpu") }}
  {{- $resources := index .Values.resources $device }}
  predictor:
    model:
      modelFormat:
        name: {{ .Values.inferenceService.modelFormat | default "vLLM" }}
      resources:
        {{- toYaml $resources | nindent 8 }}
      runtime: llama3-2-3b
      storageUri: {{ .Values.inferenceService.storageUri | default "oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct" }}
```

### Network Policy

The chart includes a network policy restricting ingress to the model server to traffic from the openshift-ingress namespace and pods labeled as llama-stack:

```yaml
# From helm/03-ai-services/llama3.2-3b/values.yaml
networkPolicy:
  enabled: true
  ingress:
    - from:
      - namespaceSelector:
          matchLabels:
            name: openshift-ingress
      ports:
      - protocol: TCP
        port: 8000
    - from:
      - podSelector:
          matchLabels:
            app.kubernetes.io/name: llama-stack
      ports:
      - protocol: TCP
        port: 8000
```

### Configuration (Approach C)

- **Environment variables (GPU mode):**
  - `CUDA_VISIBLE_DEVICES` - GPU device index (default: `"0"`, from `values.yaml` image.gpu.env)
  - `HF_HOME` - HuggingFace cache directory (overridden to `/tmp/hf_home` in ServingRuntime template, from `servingruntime.yaml`)
  - `OTEL_SERVICE_NAME` - OpenTelemetry service name (default: `"vllm-llama32b"`, from `values.yaml` servingRuntime.tracing)
  - `OTEL_EXPORTER_OTLP_TRACES_INSECURE` - Allow insecure OTLP export (default: `true`, from `values.yaml` servingRuntime.tracing)

- **Environment variables (Xeon mode):**
  - `HOME` - Home directory (set to `/tmp`, from `values.yaml` image.xeon.env)
  - `XDG_CACHE_HOME` - XDG cache directory (set to `/tmp/.cache`, from `values.yaml` image.xeon.env)
  - `VLLM_CACHE_ROOT` - vLLM cache root (set to `/tmp/.cache/vllm`, from `values.yaml` image.xeon.env)
  - `VLLM_CPU_KVCACHE_SPACE` - CPU KV cache size in GB (default: `"16"`, from `values.yaml` image.xeon.env)

- **Helm values:**
  - `device` - Device selector, `gpu` or `xeon` (default: `gpu`)
  - `model.name` - HuggingFace model ID (default: `meta-llama/Llama-3.2-3B-Instruct`)
  - `model.maxModelLen` - Maximum context length (default: `65000`)
  - `servingRuntime.tracing.enabled` - Enable OTLP tracing (default: `true`)
  - `servingRuntime.tracing.otlpTracesEndpoint` - OTEL Collector gRPC endpoint (default: `grpc://otel-collector-collector.observability-hub.svc.cluster.local:4317`)
  - `servingRuntime.tracing.collectDetailedTraces` - Trace detail level (default: `"all"`)
  - `servingRuntime.tensorParallelSize` - Tensor parallel size (default: `1`)
  - `persistence.size` - PVC size for model cache (default: `50Gi`)
  - `networkPolicy.enabled` - Enable network policy (default: `true`)
  - `inferenceService.storageUri` - OCI modelcar URI (default: `oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct`)

### Known Gotchas (Approach C)

- **HF_HOME env var is overridden in the template:** The values.yaml sets `HF_HOME: "/root/.cache/huggingface"` under `image.gpu.env`, but the ServingRuntime template hardcodes `HF_HOME` to `/tmp/hf_home` before iterating device-specific env vars (and skips any `HF_HOME` key from the device env map via `{{- if ne $key "HF_HOME" }}`). The values.yaml setting for HF_HOME is effectively ignored. Found in `servingruntime.yaml` lines 49-62.

- **GPU image uses sha256 in the repository field instead of tag:** The GPU image repository is `quay.io/rcarrata/vllm-otlp-tracing@sha256` and the tag field contains the digest hash. The template combines them as `repository:tag`, producing `quay.io/rcarrata/vllm-otlp-tracing@sha256:16f83f58...` which works but is unconventional -- the `@sha256` should be part of the tag or handled separately. Found in `values.yaml` lines 7-8 and `servingruntime.yaml` line 27.

- **Xeon image comes from internal OpenShift registry:** The Xeon image (`image-registry.openshift-image-registry.svc:5000/openshift/vllm-xeon-opentelemetry:v0.14.1-ubi9`) requires a pre-built ImageStream in the `openshift` namespace. This image is not publicly available and must be built and pushed to the internal registry before deploying in Xeon mode. Found in `values.yaml` line 15.

- **maxModelLen default of 65000 is very high for 3B model:** The `model.maxModelLen` default is set to `65000` in values.yaml, which may exceed the memory capacity on both GPU (24Gi limit) and Xeon (64Gi limit) configurations for a 3B parameter model, depending on quantization and batch size. Found in `values.yaml` line 52.

- **runAsNonRoot: false in podSecurityContext:** The pod security context sets `runAsNonRoot: false` (from `values.yaml` line 37), which may conflict with restricted SCCs on OpenShift. The GPU image likely needs root access for CUDA operations but this should be documented explicitly.

### Testing Notes (Approach C)

- Deploy with `helm install llama3-2-3b helm/03-ai-services/llama3.2-3b/ --namespace <namespace>` with appropriate values override for `device`
- The predictor service follows the KServe pattern `llama3-2-3b-predictor.<namespace>.svc.cluster.local` on port 80 (from OTEL Collector scrape config in `helm/02-observability/otel-collector/values.yaml`)
- The served model name is `llama3-2-3b` (hardcoded in `servingruntime.yaml` via `--served-model-name=llama3-2-3b`)
- Llama Stack connects to the model at `http://llama3-2-3b-predictor/v1` (from `helm/03-ai-services/llama-stack-instance/templates/configmap.yaml`)
- Verify tracing by checking the OTEL Collector for spans with service name `vllm-llama32b`
- For Xeon mode, ensure the `vllm-xeon-opentelemetry` ImageStream exists in the `openshift` namespace before deploying

---

## Choosing Between Approaches

| Criteria | Approach A (guardrailing-llms) | Approach B (lemonade-stand-assistant) | Approach C (lls-observability) |
|----------|-----------|-----------|-----------|
| vLLM args | Helm-conditional from values.yaml | Hardcoded in template | Mixed: some conditional (tracing), some hardcoded (tool-calling) |
| MaaS fallback | None (always self-hosted) | Conditional toggle via `{{ if not .Values.model }}` | None (always self-hosted) |
| Image pinning | Digest-pinned (`@sha256:...`) | Tag-based (`rhoai-2.19-cuda`) | Digest-pinned (GPU), tag-based (Xeon) |
| Scaling | Always-on (`minReplicas: 1`) | Scale-to-zero (`minReplicas: 0`) | Always-on (`minReplicas: 1`) |
| Context window | 32768 tokens (or hardcoded 20000) | 4096 tokens | 65000 tokens |
| Concurrent seqs | 8 | 384 | Not explicitly set |
| Memory limit | 8Gi | 20Gi | 24Gi (GPU) / 64Gi (Xeon) |
| CPU/GPU support | GPU only | GPU only | GPU and Xeon CPU via device toggle |
| Tracing | None | None | OpenTelemetry via custom vLLM image |
| Chat template | Baked into container image | Not configured | ConfigMap-mounted via Helm Files.Get |
| Network isolation | None | None | NetworkPolicy restricting to ingress + llama-stack |
| Chart structure | Embedded in top-level chart | Embedded in top-level chart | Standalone Helm chart |
| Config flexibility | High (values.yaml controls all args) | Low (must edit template to change args) | High (device-keyed maps, tracing toggles) |
| Best for | Production guardrails workloads | High-concurrency demo/event | Observable Llama Stack deployments on GPU or CPU |
