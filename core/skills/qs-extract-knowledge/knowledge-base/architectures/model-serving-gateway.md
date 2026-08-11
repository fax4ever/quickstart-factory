---
name: model-serving-gateway
description: Direct model inference behind KServe with vLLM, consumed by multiple downstream services via OpenAI-compatible API
summary: "Deploys an LLM (e.g., TinyLlama-1.1B) behind KServe using a vLLM CPU ServingRuntime with OCI modelcar storage (quay.io), exposing an OpenAI-compatible API at port 8080 as a shared inference gateway consumed by AnythingLLM (LocalAI provider with LanceDB RAG), Llama Stack (remote::vllm provider with sentence-transformers embeddings), and RHOAI Playground. Use when multiple downstream consumers need a single cluster-internal model endpoint with tool-calling support (--enable-auto-tool-choice --tool-call-parser hermes) on CPU nodes (Intel AVX512 preferred, e.g., AWS m6i.4xlarge) -- no external Route is created via Knative/Istio cluster-local visibility. Critical config: InferenceService sets networking.knative.dev/visibility: cluster-local with security.opendatahub.io/enable-auth: false; model weights referenced via Data Connection Secret (opendatahub.io/connection-type-ref: uri-v1); ServingRuntime configures --max-model-len 2048 and VLLM_CPU_KVCACHE_SPACE for CPU memory sizing. Gotchas: VLLM_CPU_KVCACHE_SPACE in InferenceService (\"4\") silently overrides ServingRuntime (\"2\"); LD_PRELOAD=/usr/lib64/libomp.so improves vLLM CPU performance but breaks pyarrow; requires OpenShift Service Mesh and Serverless as KServe Standard mode prerequisites."
metadata:
  type: architecture
tags:
  tech_stack: [vllm, python]
  ai_pattern: [model-serving]
  platform: [kserve, vllm, rhoai, openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "vLLM on CPU (no GPU) serving TinyLlama-1.1B via KServe ServingRuntime + InferenceService with OCI modelcar storage, consumed by AnythingLLM (LocalAI provider) and Llama Stack (remote::vllm provider)"
    approach: "A"
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
