---
name: helm-llamastack-crd-inline-milvus-rag-configmap
description: LlamaStackDistribution CR with inline Milvus vector_io, sentence-transformers embeddings, and file-search via Helm ConfigMap
summary: "Deploys a LlamaStackDistribution CR linked via userConfig.configMapName to a Helm ConfigMap containing full config.yaml that wires remote vLLM inference (base URL from model.name + release namespace at port 8080/HTTP with VLLM_API_TOKEN_1=\"fake\"), inline sentence-transformers embeddings (granite-embedding-125m-english, dim 768), inline Milvus (embedded SQLite-backed at milvus.db) for vector I/O, and inline file-search tool runtime -- providing self-contained RAG without an external vector database. Use when deploying a RAG-capable Llama Stack playground needing vector search, embeddings, and file-search in a single pod; prefer remote-only providers (helm-llamastack-crd-mcp-remote-providers) when memory is constrained or an external vector DB already exists. Critical config: both CR and ConfigMap live in the same playground.yaml template; the CR uses the rh-dev distribution with network.allowedFrom.namespaces restricting traffic to the release namespace; pre-registered models map provider IDs with Milvus as default_provider_id for vector_stores and granite-embedding-125m-english as default_embedding_model. Requires 12Gi memory limit because inline Milvus and sentence-transformers load in-process; Llama Stack's own ${env.VAR:=default} variable expansion is distinct from Helm templating; the seed Job and any client (e.g., AnythingLLM) must run in the same namespace due to the allowedFrom network restriction."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, llama-stack, vllm]
  ai_pattern: [rag, model-serving]
  platform: [openshift, rhoai]
  data_layer: [milvus]
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "LlamaStackDistribution CR with full inline config.yaml ConfigMap: Milvus vector_io, sentence-transformers embeddings, remote vLLM inference, file-search tool, SQLite storage backends"
    approach: "A"
---

# Llama Stack Distribution CR with Inline Milvus RAG ConfigMap

## Overview

This pattern deploys a Llama Stack Distribution via the `LlamaStackDistribution` CRD with its entire configuration (providers, storage backends, registered models, vector store defaults) templated as a Helm ConfigMap. Unlike patterns that use remote-only providers, this approach inlines Milvus for vector I/O, sentence-transformers for embeddings, and file-search for tool runtime alongside remote vLLM for inference -- providing a self-contained RAG-capable playground with no external vector database.

## Pattern Description

The Helm chart creates two resources: a ConfigMap containing a full Llama Stack `config.yaml` with all provider wiring, and a `LlamaStackDistribution` CR that references the ConfigMap. The config wires eight provider categories inline: remote vLLM for LLM inference, inline sentence-transformers for embeddings, inline Milvus (embedded mode using SQLite-backed file) for vector storage, inline localfs for file storage, inline builtin for responses, remote HuggingFace for datasets, inline basic/llm-as-judge for scoring, and inline file-search plus remote MCP for tool runtime. All SQLite databases and the Milvus DB file are stored under `/opt/app-root/src/.llama/distributions/rh/`.

## Implementation

### Config.yaml ConfigMap

The ConfigMap contains the full Llama Stack configuration with Helm template references for dynamic values:

```yaml
# helm/templates/playground.yaml (ConfigMap excerpt)
apiVersion: v1
kind: ConfigMap
metadata:
  name: llama-stack-config
data:
  config.yaml: |-
    version: "2"
    distro_name: rh
    apis:
    - responses
    - datasetio
    - files
    - inference
    - safety
    - scoring
    - tool_runtime
    - vector_io
    providers:
      inference:
      - provider_id: sentence-transformers
        provider_type: inline::sentence-transformers
        config: {}
      - provider_id: vllm-{{ .Values.model.name }}
        provider_type: remote::vllm
        config:
          base_url: http://{{ .Values.model.name }}-predictor.{{ .Release.Namespace }}.svc.cluster.local:8080/v1
          max_tokens: ${env.VLLM_MAX_TOKENS:=4096}
          tls_verify: ${env.VLLM_TLS_VERIFY:=false}
      vector_io:
      - provider_id: milvus
        provider_type: inline::milvus
        config:
          db_path: /opt/app-root/src/.llama/distributions/rh/milvus.db
```

### Registered Models with Embedding Dimensions

The config pre-registers both the embedding model and the LLM with provider mappings:

```yaml
# helm/templates/playground.yaml (ConfigMap excerpt, continued)
    registered_resources:
      models:
      - provider_id: sentence-transformers
        model_id: sentence-transformers/ibm-granite/granite-embedding-125m-english
        provider_model_id: ibm-granite/granite-embedding-125m-english
        model_type: embedding
        metadata:
          embedding_dimension: 768
      - provider_id: vllm-{{ .Values.model.name }}
        model_id: {{ .Values.model.name }}
        model_type: llm
    vector_stores:
      default_provider_id: milvus
      default_embedding_model:
        provider_id: sentence-transformers
        model_id: ibm-granite/granite-embedding-125m-english
```

### LlamaStackDistribution CR

```yaml
# helm/templates/playground.yaml (CR)
apiVersion: llamastack.io/v1alpha1
kind: LlamaStackDistribution
metadata:
  name: lsd-genai-playground
spec:
  network:
    allowedFrom:
      namespaces:
        - {{ .Release.Namespace }}
    exposeRoute: false
  replicas: 1
  server:
    containerSpec:
      command:
        - /bin/sh
        - -c
        - llama stack run /etc/llama-stack/config.yaml
      env:
        - name: VLLM_TLS_VERIFY
          value: "false"
        - name: VLLM_MAX_TOKENS
          value: {{ .Values.model.maxOutputTokens | quote }}
        - name: VLLM_API_TOKEN_1
          value: fake
      name: llama-stack
      port: 8321
      resources:
        limits:
          cpu: "2"
          memory: 12Gi
        requests:
          cpu: 250m
          memory: 500Mi
    distribution:
      name: rh-dev
    userConfig:
      configMapName: llama-stack-config
```

## Configuration

- **Key settings:** `model.name` sets the vLLM provider ID and inference URL; `model.maxOutputTokens` controls `VLLM_MAX_TOKENS`; the vLLM base URL is constructed from the model name and release namespace; embedding model is hardcoded to `ibm-granite/granite-embedding-125m-english` with dimension 768
- **Defaults:** Llama Stack requests 250m CPU / 500Mi memory, limits 2 CPU / 12Gi (12Gi is needed for inline Milvus and sentence-transformers); `exposeRoute: false` keeps the endpoint cluster-internal; `VLLM_API_TOKEN_1` is set to `fake` since auth is disabled on the InferenceService
- **Dependencies:** Requires the Llama Stack Operator (provides `llamastack.io/v1alpha1` CRD); requires the KServe InferenceService to be running at the constructed URL; the `rh-dev` distribution image must include Milvus and sentence-transformers packages

## Gotchas

- The Llama Stack config uses `${env.VARIABLE:=default}` syntax for environment variable substitution with defaults -- this is Llama Stack's own variable expansion, not Helm templating (see `helm/templates/playground.yaml` config.yaml section)
- Memory limit is 12Gi because inline Milvus and inline sentence-transformers both load into the same process -- the embedding model (`granite-embedding-125m-english`) alone requires several GB of memory (see `helm/templates/playground.yaml` CR resources)
- The `network.allowedFrom.namespaces` on the CR restricts network access to only the release namespace -- this means the seed Job and AnythingLLM (if trying to reach Llama Stack) must be in the same namespace (see `helm/templates/playground.yaml` CR spec)
- The vLLM base URL uses port 8080 (HTTP) rather than 8443 (HTTPS) because `security.opendatahub.io/enable-auth: 'false'` is set on the InferenceService and `tls_verify` defaults to `false` (see `helm/templates/playground.yaml` config.yaml inference provider)
- Both the ConfigMap and the CR are in the same template file (`playground.yaml`) separated by `---` -- this ensures they are deployed as a unit since the CR references the ConfigMap by name (see `helm/templates/playground.yaml`)

## Related Patterns

- `helm-llamastack-crd-mcp-remote-providers.md` -- alternative pattern using all-remote providers (remote vLLM + remote MCP) instead of inline Milvus/sentence-transformers
- `helm-seed-job-dual-curl-python-rag-ingestion.md` -- the seed Job that populates the Milvus vector store created by this Llama Stack instance
- `kserve-vllm-cpu-oci-modelcar-no-gpu.md` -- the vLLM InferenceService that Llama Stack connects to for LLM inference
