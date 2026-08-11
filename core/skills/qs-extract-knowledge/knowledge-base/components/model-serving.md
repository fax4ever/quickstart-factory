---
name: model-serving
description: "Helm chart deploying multiple vLLM models as KServe InferenceServices with MIG GPU slicing and RawDeployment mode"
summary: "Deploys multiple vLLM models (LLM, embedding, reranking, VLM) as KServe InferenceServices in RawDeployment mode on RHOAI via a standalone Helm chart, providing the inference backbone for RAG pipelines with NVIDIA MIG GPU slicing. Use this self-contained model-serving chart (not the ai-architecture-charts llm-service subchart) when deploying multiple models with per-model MIG slice sizing (3g.47gb for large LLMs with tensor parallelism, 1g.12gb for embedding/reranking), flexible storage backends (URI, PVC, S3, HuggingFace hf:// fallback), singleNode or multiNode topologies, and optional scale-to-zero. Define models in the values.yaml `models` map with `id`, `enabled`, `resources` (MIG slice types like nvidia.com/mig-3g.47gb), and `args` (e.g., --tensor-parallel-size=2); the template range loop creates one InferenceService per enabled model with a shared ServingRuntime (registry.redhat.io vllm-cuda-rhel9) mounting Jinja2 chat templates from a ConfigMap and HF_TOKEN from huggingface-secret. The ConfigMap uses Helm `lookup` so `helm upgrade` will not update chat templates unless manually deleted; `--served-model-name` must match the full HF model ID (e.g., nvidia/Llama-3_3-Nemotron-Super-49B-v1_5-FP8); downstream consumers discover models via `<model-name>-predictor:8080/v1`; multiNode topology values (pipelineParallelSize, tensorParallelSize) have no defaults and require `--set`; FP8 quantization reduces 49B LLM VRAM from ~200GB to ~70GB on 2x 3g.47gb slices."
metadata:
  type: component
tags:
  tech_stack: [vllm, kserve, helm]
  ai_pattern: [model-serving, rag, embeddings]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: []
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Multi-model vLLM serving (LLM, embedding, reranking, VLM) with NVIDIA MIG GPU slicing via standalone Helm chart"
    approach: "A"
---

# Model Serving

## Overview

The model-serving component is a standalone Helm chart that deploys multiple vLLM-based models as KServe InferenceService resources in RawDeployment mode on RHOAI. In the aml-rag-nvidia quickstart, it serves four distinct models (LLM, embedding, reranking, and VLM) on NVIDIA MIG GPU slices, providing the inference backbone for a RAG pipeline. Unlike the `llm-service` subchart from ai-architecture-charts, this chart is self-contained and uses a `models` map in values.yaml to define all model configurations directly.

## Tech Stack & Dependencies

- **Runtime:** KServe InferenceService (RawDeployment mode) with vLLM serving runtime
- **Container image:** `registry.redhat.io/rhaiis-preview/vllm-cuda-rhel9:voxtral-realtime-1770305414`
- **Key dependencies:** RHOAI/OpenShift AI operator, NVIDIA GPU nodes with MIG support, Hugging Face token for gated models
- **Helm subchart:** None (standalone chart, `model-serving` v0.1.0)

## Key Patterns

### Multi-Model Deployment via Values Map

All models are defined in a `models` map in values.yaml. The InferenceService template iterates over this map, creating one InferenceService per enabled model. Each model specifies its own resource requests, vLLM args, and GPU type.

```yaml
# From charts/model-serving/values.yaml
models:
  nim-llm:
    id: nvidia/Llama-3_3-Nemotron-Super-49B-v1_5-FP8
    enabled: true
    minReplicas: 1
    resources:
      limits:
        nvidia.com/mig-3g.47gb: "2"
      requests:
        nvidia.com/mig-3g.47gb: "2"
    args:
      - --tensor-parallel-size=2
      - --max-num-seqs=32
      - --trust-remote-code
```

The template range loop creates separate InferenceService resources:

```yaml
# From charts/model-serving/templates/inferenceservice.yaml
{{- range $modelName, $model := .Values.models }}
{{- if $model.enabled }}
---
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
  name: {{ $modelName }}
```

### NVIDIA MIG GPU Slicing

Models are sized to specific MIG slice profiles rather than whole GPUs. The 49B LLM uses two 3g.47gb slices with tensor parallelism, while the embedding and reranking models each fit on a single 1g.12gb slice.

```yaml
# From charts/model-serving/values.yaml — LLM (2x 3g.47gb MIG)
nim-llm:
    resources:
      limits:
        nvidia.com/mig-3g.47gb: "2"
    args:
      - --tensor-parallel-size=2

# Embedding model (1x 1g.12gb MIG)
nemoretriever-embedding-ms:
    resources:
      limits:
        nvidia.com/mig-1g.12gb: "1"
```

### Flexible Model Storage Backends

The InferenceService template supports three storage modes (URI, PVC, S3) with a default fallback to Hugging Face download:

```yaml
# From charts/model-serving/templates/inferenceservice.yaml
{{- with $model.storage }}
{{- if eq (lower .mode) "uri" }}
storageUri: {{ .uri }}
{{- else if eq (lower .mode) "pvc" }}
storageUri: pvc://{{ .pvcName }}/{{ .path }}
{{- else if eq (lower .mode) "s3"}}
storage:
  key: {{ .s3.key }}
  path: {{ .s3.path }}
{{- end }}
{{- else }}
{{/* Default: Use HuggingFace URI */}}
storageUri: hf://{{ $model.id }}
{{- end }}
```

### ServingRuntime with Chat Templates

A shared ServingRuntime runs vLLM with configurable command and args. It mounts custom Jinja2 chat templates from a ConfigMap for tool-calling support:

```yaml
# From charts/model-serving/templates/servingruntime.yaml
volumes:
  - name: shm
    emptyDir:
      medium: Memory
      sizeLimit: {{ .Values.servingRuntime.shmSize }}
  - name: chat-templates
    configMap:
      name: vllm-chat-templates
```

The configmap template uses `lookup` to avoid overwriting an existing ConfigMap:

```yaml
# From charts/model-serving/templates/configmap.yaml
{{- $existingConfigMap := lookup "v1" "ConfigMap" .Release.Namespace "vllm-chat-templates" }}
{{- if not $existingConfigMap }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: vllm-chat-templates
data:
  tool_chat_template_llama3.2_json.jinja: |-
{{ .Files.Get "files/tool_chat_template_llama3.2_json.jinja" | indent 4 }}
```

### Multi-Node Topology Support

The chart supports both singleNode and multiNode serving topologies. In multiNode mode, the InferenceService gets `workerSpec` with pipeline and tensor parallel sizes, and autoscaling is delegated externally:

```yaml
# From charts/model-serving/templates/inferenceservice.yaml
{{- if eq $root.Values.servingTopology "multiNode" }}
serving.kserve.io/autoscalerClass: external
{{- end }}
...
{{- if eq $root.Values.servingTopology "multiNode" }}
workerSpec:
  pipelineParallelSize: {{ $root.Values.multiNode.pipelineParallelSize }}
  tensorParallelSize: {{ $root.Values.multiNode.tensorParallelSize }}
{{- end }}
```

### KServe Endpoint Configuration

The chart supports external route creation and optional authentication with service account-based access control:

```yaml
# From charts/model-serving/values.yaml
endpoint:
  externalRoute:
    enabled: true
  auth:
    enabled: false
    serviceAccounts: []
```

## Configuration

- **Environment variables:**
  - `HF_HOME` - Hugging Face cache directory (set to `/tmp/hf_home` in the ServingRuntime)
  - `HF_HUB_OFFLINE` - Set to `"0"` to allow model downloads from Hugging Face Hub
  - `HF_TOKEN` - Hugging Face token for gated model access (from `huggingface-secret` Secret)

- **Helm values:**
  - `deploymentMode` - KServe deployment mode (default: `RawDeployment`)
  - `servingTopology` - `singleNode` or `multiNode` topology
  - `image.image` / `image.tag` - vLLM container image and tag
  - `secret.hf_token` - Hugging Face token (creates `huggingface-secret` when set)
  - `models.<name>.id` - Hugging Face model identifier
  - `models.<name>.enabled` - Enable/disable individual models
  - `models.<name>.resources` - GPU and compute resource requests/limits
  - `models.<name>.args` - Per-model vLLM arguments (e.g., `--tensor-parallel-size`, `--max-num-seqs`)
  - `scaling.stopped` - Set to `true` to stop model server (scale to zero)
  - `scaling.minReplicas` / `scaling.maxReplicas` - Autoscaling bounds
  - `servingRuntime.shmSize` - Shared memory emptyDir size (default: `2Gi`)
  - `servingRuntime.useExisting` - Use a pre-existing ServingRuntime instead of creating one
  - `tolerations` - GPU node tolerations (default tolerates `nvidia.com/gpu` NoSchedule)

- **Config files:**
  - `charts/model-serving/files/tool_chat_template_llama3.2_json.jinja` - Llama 3.2 JSON tool-calling chat template
  - `charts/model-serving/files/tool_chat_template_llama3.2_pythonic.jinja` - Llama 3.2 Pythonic tool-calling chat template
  - `charts/model-serving/files/tool_chat_template_qwen.jinja` - Qwen tool-calling chat template

## Known Gotchas

- **ConfigMap lookup prevents overwrite on upgrade:** The `configmap.yaml` template uses Helm `lookup` to check for an existing `vllm-chat-templates` ConfigMap. If one already exists in the namespace, the chart reuses it as-is with `toYaml $existingConfigMap`. This means `helm upgrade` will not update chat templates if they were previously deployed -- you must delete the ConfigMap manually first.

- **Served model name must match the model ID:** The InferenceService template sets `--served-model-name={{ $model.id }}`, which means consumers must use the full Hugging Face model identifier (e.g., `nvidia/Llama-3_3-Nemotron-Super-49B-v1_5-FP8`) when calling the API. This is wired from `charts/model-serving/templates/inferenceservice.yaml`: `args: - --served-model-name={{ $model.id }}`.

- **KServe predictor naming convention for service discovery:** KServe creates a service named `<model-name>-predictor` for each InferenceService. Downstream consumers (rag-server, ingest) reference models using this pattern, e.g., `nim-llm-predictor:8080/v1`. This is visible in `charts/rag-server/values.yaml`: `APP_LLM_SERVERURL: "http://nim-llm-predictor:8080/v1"`.

- **Reranking model requires explicit chat template and tool-call parser:** The `nemoretriever-ranking-ms` model has specific vLLM args for tool-calling that differ from other models: `--chat-template=/chat-templates/tool_chat_template_llama3.2_json.jinja --tool-call-parser=llama3_json --enable-auto-tool-choice`. These are in `charts/model-serving/values.yaml` under the model's args.

- **FP8 quantization reduces VRAM by ~65%:** The values.yaml comments note that the FP8-quantized 49B LLM needs ~70GB instead of ~200GB, fitting on 2x 3g.47gb MIG slices (92GB total). This is from the comment: `# Using FP8 quantized model - requires ~70GB instead of ~200GB`.

- **multiNode values not defined in values.yaml:** The `multiNode.pipelineParallelSize` and `multiNode.tensorParallelSize` values are referenced in the InferenceService template but have no defaults in values.yaml. They must be provided via `--set` when using `servingTopology: multiNode`.

## Testing Notes

- Deploy with `helm install model-serving ./charts/model-serving --set secret.hf_token=$HF_TOKEN --namespace rag --create-namespace` (from README)
- Verify InferenceService readiness: each enabled model should create a separate InferenceService resource
- Check GPU scheduling: pods require specific MIG slice types (`nvidia.com/mig-3g.47gb`, `nvidia.com/mig-1g.12gb`)
- Confirm model endpoints respond at `<model-name>-predictor:8080/v1` for downstream consumers
- Uninstall with `helm uninstall model-serving -n rag`

## Related Patterns

- KServe InferenceService with vLLM (architecture pattern)
- NVIDIA MIG GPU partitioning for multi-model serving (deployment pattern)
- Helm subchart wiring for model endpoint discovery (deployment pattern)
