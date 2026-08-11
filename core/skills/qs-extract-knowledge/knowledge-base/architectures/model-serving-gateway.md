---
name: model-serving-gateway
description: Direct model inference behind KServe with vLLM in Standard or RawDeployment mode, consumed by downstream services
summary: "Deploys an LLM (e.g., TinyLlama-1.1B or Llama 3.2 3B) behind KServe using a vLLM ServingRuntime as a shared inference gateway exposing an OpenAI-compatible API at port 8080, consumed by downstream services including AnythingLLM (LocalAI provider with LanceDB RAG), Llama Stack (remote::vllm provider), and RHOAI Playground. Approach A (KServe Standard/Knative, CPU-only, hermes tool-call-parser, --max-model-len 2048) suits multi-consumer gateways on CPU nodes (Intel AVX512/m6i.4xlarge preferred) but requires Service Mesh + Serverless operators; Approach B (RawDeployment mode, GPU/Xeon dual-device via Helm device value, llama3_json parser with Jinja2 chat template, --max-model-len 65000, OTel tracing via --otlp-traces-endpoint) avoids Knative prerequisites and adds observability. Critical config: InferenceService sets networking.knative.dev/visibility: cluster-local with security.opendatahub.io/enable-auth: false; OCI modelcar storage referenced via Data Connection Secret (opendatahub.io/connection-type-ref: uri-v1); ServingRuntime configures --enable-auto-tool-choice with device-specific VLLM_CPU_KVCACHE_SPACE and resource limits (GPU: nvidia.com/gpu: 1, 24Gi limit; Xeon: 16 CPU, 64Gi limit). Gotchas: VLLM_CPU_KVCACHE_SPACE in InferenceService (\"4\") silently overrides ServingRuntime (\"2\"); LD_PRELOAD=/usr/lib64/libomp.so improves vLLM CPU performance but breaks pyarrow; Approach B's Xeon image requires a custom BuildConfig for OTel packages unlike the GPU image which bundles them; Approach A requires Service Mesh + Serverless as KServe Standard mode prerequisites."
metadata:
  type: architecture
tags:
  tech_stack: [vllm, python, opentelemetry]
  ai_pattern: [model-serving]
  platform: [kserve, vllm, rhoai, openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "vLLM on CPU (no GPU) serving TinyLlama-1.1B via KServe ServingRuntime + InferenceService with OCI modelcar storage, consumed by AnythingLLM (LocalAI provider) and Llama Stack (remote::vllm provider)"
    approach: "A"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "vLLM on GPU serving Llama 3.2 3B via KServe RawDeployment mode with OTel tracing, dual device support (GPU/Xeon), consumed by Llama Stack as remote::vllm provider"
    approach: "B"
---

# Model Serving Gateway

## Overview

This architecture deploys a large language model behind KServe using vLLM as the serving runtime, exposing an OpenAI-compatible REST API on a cluster-internal endpoint. Multiple downstream services (chat interfaces, orchestration frameworks, playgrounds) connect to this single model endpoint, making the model server a shared gateway for inference. The pattern separates model deployment (KServe ServingRuntime + InferenceService) from model consumption, allowing different frontends and middleware to share one model instance.

## Data Flow

1. Model weights are stored as an OCI image (modelcar pattern) on a container registry (e.g., `quay.io`)
2. KServe InferenceService references the OCI storage URI and the vLLM CPU ServingRuntime
3. KServe pulls the model image and launches vLLM with CPU-specific settings (kv-cache size, memory allocator)
4. vLLM serves an OpenAI-compatible API at `http://{model-name}-predictor.{namespace}.svc.cluster.local:8080/v1`
5. Downstream services connect to this endpoint using their native OpenAI-compatible client integrations
6. Requests flow through Knative/Istio service mesh (cluster-local visibility, no external route)

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| KServe controller | OCI registry (quay.io) | HTTPS | Pull modelcar image containing model weights |
| KServe controller | vLLM container | Kubernetes | Launch and manage serving pod |
| AnythingLLM | vLLM predictor | REST (port 8080, OpenAI-compatible) | Chat completions via LocalAI provider |
| Llama Stack Distribution | vLLM predictor | REST (port 8080, OpenAI-compatible) | Inference via remote::vllm provider |
| RHOAI Dashboard (Playground) | vLLM predictor | REST (port 8080, OpenAI-compatible) | Interactive chat via built-in playground UI |

## Key Integration Points

### KServe ServingRuntime with CPU-Specific vLLM Configuration

The ServingRuntime defines the vLLM container with CPU-specific arguments and environment variables, including tool-calling support and kv-cache sizing.

```yaml
# helm/templates/servingruntime.yaml (lines 1-42)
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  annotations:
    opendatahub.io/apiProtocol: REST
    opendatahub.io/template-display-name: vLLM CPU (x86) ServingRuntime for KServe
  name: vllm-cpu
spec:
  containers:
    - args:
        - --model
        - /mnt/models
        - --port
        - "8080"
        - --max-model-len
        - "2048"
        - '--served-model-name'
        - tinyllama
        - '--enable-auto-tool-choice'
        - '--tool-call-parser'
        - 'hermes'
      image: registry.redhat.io/rhaii/vllm-cpu-rhel9@sha256:...
      env:
        - name: VLLM_CPU_KVCACHE_SPACE
          value: "2"
```

### OCI Modelcar Storage for Model Weights

The InferenceService references the model via an OCI storage URI, using the modelcar pattern where model weights are packaged as a container image with no runtime dependencies.

```yaml
# helm/templates/inferenceservice.yaml (lines 24-45)
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  annotations:
    serving.kserve.io/deploymentMode: Standard
  name: tinyllama
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
        requests:
          cpu: "2"
          memory: "8Gi"
        limits:
          cpu: "8"
          memory: "8Gi"
      runtime: vllm-cpu
      storageUri: "oci://quay.io/rh-aiservices-bu/tinyllama:1.0"
```

### AnythingLLM Consuming vLLM via LocalAI Provider

AnythingLLM connects to the vLLM endpoint using the LocalAI provider, configured via environment variables injected from a Kubernetes Secret. The `VECTOR_DB: lancedb` setting enables AnythingLLM's built-in RAG with LanceDB.

```yaml
# helm/templates/anythingllm-secret.yaml (lines 9-23)
kind: Secret
apiVersion: v1
metadata:
  name: tinyllama-vllm-cpu
data:
  EMBEDDING_ENGINE: bmF0aXZl           # "native"
  LLM_PROVIDER: bG9jYWxhaQ==           # "localai"
  LOCAL_AI_MODEL_PREF: dGlueWxsYW1h    # "tinyllama"
  LOCAL_AI_MODEL_TOKEN_LIMIT: NTEy      # "512"
  VECTOR_DB: bGFuY2VkYg==              # "lancedb"
stringData:
  LOCAL_AI_BASE_PATH: "http://tinyllama-predictor.{{ .Release.Namespace }}.svc.cluster.local:8080/v1"
```

### Llama Stack Consuming vLLM via remote::vllm Provider

The Llama Stack Distribution connects to the same vLLM endpoint via the `remote::vllm` provider, configured in a ConfigMap. It also registers a separate `sentence-transformers` provider for embeddings.

```yaml
# helm/templates/playground.yaml (ConfigMap llama-stack-config, lines 27-33)
providers:
  inference:
  - provider_id: sentence-transformers
    provider_type: inline::sentence-transformers
    config: {}
  - provider_id: vllm-tinyllama
    provider_type: remote::vllm
    config:
      api_token: ${env.VLLM_API_TOKEN_1:=fake}
      base_url: http://tinyllama-predictor.{{ .Release.Namespace }}.svc.cluster.local:8080/v1
      max_tokens: ${env.VLLM_MAX_TOKENS:=4096}
```

### Data Connection Secret for OCI Model URI

A separate Secret provides the OCI storage URI as a Data Connection, which the InferenceService references via the `opendatahub.io/connections` annotation to resolve the `storageUri`.

```yaml
# helm/templates/modelcar-dataconnection.yaml (lines 1-13)
kind: Secret
apiVersion: v1
metadata:
  name: tinyllama-10-on-quayio
  annotations:
    opendatahub.io/connection-type-ref: uri-v1
data:
  URI: b2NpOi8vcXVheS5pby9yaC1haXNlcnZpY2VzLWJ1L3RpbnlsbGFtYToxLjA=
  # decodes to: oci://quay.io/rh-aiservices-bu/tinyllama:1.0
```

## Prompt / Chain Patterns

The model serving gateway itself has no prompt logic -- it exposes the raw model. Prompt structure is defined by the downstream consumers:

- **AnythingLLM**: Uses a configurable workspace system prompt (set via the anythingllm-seed-job), configured as an HR assistant for U.S. financial services.
- **Llama Stack / RHOAI Playground**: Uses the Playground UI's built-in prompt configuration, with optional RAG knowledge tab.
- **Tool calling**: The ServingRuntime enables `--enable-auto-tool-choice` with `--tool-call-parser hermes`, allowing downstream consumers to use OpenAI-compatible function calling through the vLLM endpoint.

## Gotchas

- The `VLLM_CPU_KVCACHE_SPACE` environment variable is set in both the ServingRuntime (value `"2"`) and the InferenceService (value `"4"`) in `servingruntime.yaml` line 35 and `inferenceservice.yaml` line 44. The InferenceService value overrides the ServingRuntime value at the container level.
- The default `LD_PRELOAD` in the vLLM CPU image sets `jemalloc` for pyarrow compatibility. The README (lines 97-110) notes that setting `LD_PRELOAD` to `/usr/lib64/libomp.so` overrides this and improves vLLM performance, but may break pyarrow usage.
- The InferenceService is configured with `networking.knative.dev/visibility: cluster-local`, meaning no external Route is created. All consumers must be within the cluster. The `security.opendatahub.io/enable-auth: 'false'` annotation disables authentication on the model endpoint.
- This quickstart is compiled for Intel CPUs. The README (line 62) notes that AVX512 support is preferred for running compressed models. AWS `m6i.4xlarge` instances are referenced as a working hardware profile.
- The model serving pattern requires OpenShift Service Mesh and OpenShift Serverless as prerequisites (README lines 69-70), which are dependencies of KServe's Standard deployment mode.

## Related Architectures

- [rag-pipeline](rag-pipeline.md) -- Both AnythingLLM and Llama Stack consume this model endpoint to power their respective RAG capabilities

---

## Approach B: GPU + OTel-Instrumented vLLM with RawDeployment Mode (from lls-observability)

### When to Use

Use Approach B when deploying GPU-accelerated models with OpenTelemetry tracing instrumentation, when KServe RawDeployment mode is preferred over Knative Standard mode (avoids Service Mesh and Serverless operator dependencies), or when dual-device support (GPU and CPU/Xeon) is needed from the same Helm chart.

### Differences from Approach A

| Aspect | Approach A | Approach B |
|--------|-----------|-----------|
| KServe deployment mode | Standard (Knative) | RawDeployment |
| Device | CPU only | GPU (default) or Xeon CPU |
| Tracing | None | OpenTelemetry via `--otlp-traces-endpoint` |
| Networking | Knative cluster-local visibility | Direct Service with OpenShift Route |
| Prerequisites | Service Mesh + Serverless operators | None (RawDeployment bypasses Knative) |
| Model | TinyLlama-1.1B | Llama 3.2 3B Instruct |
| Tool calling parser | hermes | llama3_json |
| max-model-len | 2048 | 65000 |
| vLLM image | registry.redhat.io/rhaii/vllm-cpu-rhel9 | quay.io/rcarrata/vllm-otlp-tracing (GPU) or custom BuildConfig image (Xeon) |

### KServe RawDeployment with GPU and OTel Tracing

The InferenceService uses `serving.kserve.io/deploymentMode: RawDeployment`, which creates a standard Kubernetes Deployment instead of a Knative Service. This avoids the Service Mesh and Serverless prerequisites.

```yaml
# helm/03-ai-services/llama3.2-3b/templates/inferenceservice.yaml (lines 1-14)
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: llama3-2-3b
  annotations:
    serving.knative.openshift.io/enablePassthrough: 'true'
    sidecar.istio.io/inject: 'true'
    sidecar.istio.io/rewriteAppHTTPProbers: 'true'
    serving.kserve.io/deploymentMode: RawDeployment
  finalizers:
    - serving.kserve.io/inferenceservice-finalizer
spec:
  predictor:
    model:
      runtime: llama3-2-3b
      storageUri: "oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct"
```

### Dual Device Support (GPU/Xeon) in a Single Chart

The Helm chart selects image, resources, node selectors, tolerations, and affinity based on a `device` value ("gpu" or "xeon"), allowing the same chart to deploy on GPU or CPU nodes.

```yaml
# helm/03-ai-services/llama3.2-3b/values.yaml (lines 4-24)
device: "gpu"  # Options: gpu, xeon
image:
  gpu:
    repository: "quay.io/rcarrata/vllm-otlp-tracing@sha256"
    tag: "16f83f5858fcc04bd56ea785126c04af823e8aacbeabb9db963f86d252178189"
    chatTemplate: "/app/data/template/tool_chat_template_llama3.2_json.jinja"
    env:
      CUDA_VISIBLE_DEVICES: "0"
  xeon:
    repository: 'image-registry.openshift-image-registry.svc:5000/openshift/vllm-xeon-opentelemetry'
    tag: "v0.14.1-ubi9"
    chatTemplate: "/app/data/template/tool_chat_template_llama3.2_json.jinja"
    env:
      VLLM_CPU_KVCACHE_SPACE: "16"
```

The ServingRuntime template uses Helm `index` to look up device-specific values:

```yaml
# helm/03-ai-services/llama3.2-3b/templates/servingruntime.yaml (lines 2-4)
{{- $device := lower (.Values.device | default "gpu") }}
{{- $image := index .Values.image $device }}
{{- $resources := index .Values.resources $device }}
```

### Llama Stack Consuming vLLM via remote::vllm Provider

Llama Stack connects to the vLLM predictor as a `remote::vllm` provider, configured in its run-config ConfigMap. Multiple inference providers share the same Llama Stack instance.

```yaml
# helm/03-ai-services/llama-stack/templates/configmap.yaml (lines 23-30)
providers:
  inference:
  - provider_id: vllm-inference
    provider_type: remote::vllm
    config:
      url: ${env.VLLM_URL:http://localhost:8000/v1}
      max_tokens: ${env.VLLM_MAX_TOKENS:4096}
      api_token: ${env.VLLM_API_TOKEN:fake}
      tls_verify: ${env.VLLM_TLS_VERIFY:true}
```

### Gotchas (Approach B)

- The GPU vLLM image (`quay.io/rcarrata/vllm-otlp-tracing`) already includes OpenTelemetry packages, but the Xeon CPU image does not. CPU deployments require building a custom `vllm-xeon-opentelemetry` image via an OpenShift BuildConfig (`helm/vllm-xeon-opentelemetry-build-config.yaml`).
- GPU resources request `nvidia.com/gpu: 1` with 16Gi memory request and 24Gi limit, while Xeon requests 16 CPU cores with 32Gi memory request and 64Gi limit (`helm/03-ai-services/llama3.2-3b/values.yaml` lines 104-116).
- The `--max-model-len=65000` is significantly higher than Approach A's 2048, reflecting the larger model's context window. This requires substantially more memory.
- The chat template for tool calling is mounted from a ConfigMap as a Jinja2 file (`tool_chat_template_llama3.2_json.jinja`) and referenced via `--chat-template` and `--tool-call-parser llama3_json` instead of Approach A's `--tool-call-parser hermes`.

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| GPU availability | Not needed (CPU only) | Required (default), CPU fallback available |
| Cluster prerequisites | Service Mesh + Serverless operators | None (RawDeployment) |
| Observability needs | No tracing | Full OTel distributed tracing |
| Model size | Small (TinyLlama 1.1B) | Medium (Llama 3.2 3B) |
| Deployment complexity | Higher (Knative stack) | Lower (standard Deployment) |
| Multi-consumer gateway | Yes (AnythingLLM + Llama Stack + Playground) | Single consumer (Llama Stack) |
| Tool calling | Hermes format | Llama 3 JSON format |

## Related Architectures

- [llm-observability-pipeline](llm-observability-pipeline.md) -- Approach B's OTel tracing feeds into the full observability pipeline with Tempo and Grafana
