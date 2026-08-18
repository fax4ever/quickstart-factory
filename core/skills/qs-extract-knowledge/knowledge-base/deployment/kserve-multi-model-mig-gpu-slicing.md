---
name: kserve-multi-model-mig-gpu-slicing
description: Helm-templated KServe InferenceServices deploying multiple models on MIG-partitioned GPU slices
summary: "Deploys multiple AI models (LLM, VLM, embedding, reranking) as separate KServe InferenceServices on NVIDIA MIG-partitioned GPU slices via a Helm range loop over a models map, generating per-model resources with specific MIG device types like nvidia.com/mig-3g.47gb and nvidia.com/mig-1g.12gb instead of dedicating full GPUs. Use when co-locating multiple models on a single physical GPU with isolated compute and memory guarantees in RawDeployment mode — large models like the 49B Nemotron use --tensor-parallel-size=2 across two 3g.47gb slices (92GB) while smaller embedding models fit on single 1g.12gb slices; each model entry has an enabled flag for selective deployment and downloads via storageUri: hf:// with a huggingface-secret. Critical pattern: a shared ServingRuntime references the Red Hat AI-certified vLLM image (registry.redhat.io/rhaiis-preview/vllm-cuda-rhel9) with /dev/shm emptyDir for shared memory, chat template ConfigMap guarded by Helm lookup to prevent overwrites and loaded via .Files.Get, and singleNode serving topology. MIG resource types in requests must exactly match the node partitioning configured via GPU Operator MIG Manager, tensor-parallel-size requires all MIG slices on the same physical GPU, helm template dry-runs always render the lookup-guarded ConfigMap since lookup returns empty during template rendering, and the image field is image.image not image.repository."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, vllm]
  ai_pattern: [model-serving, rag, embeddings, multimodal]
  platform: [kserve, vllm, rhoai, openshift]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "4 models (LLM, VLM, embedding, reranking) each requesting specific MIG slice sizes via KServe InferenceService"
    approach: "A"
---

# KServe Multi-Model MIG GPU Slicing

## Overview

This pattern deploys multiple AI models as separate KServe InferenceServices, each requesting specific NVIDIA MIG (Multi-Instance GPU) slice sizes rather than full GPUs. A single Helm chart iterates over a `models` map in `values.yaml` to generate one InferenceService per model, with per-model resource requests for MIG device types like `nvidia.com/mig-3g.47gb` and `nvidia.com/mig-1g.12gb`.

## Pattern Description

Instead of dedicating entire GPUs to each model, MIG partitions a single physical GPU into isolated instances with guaranteed memory and compute. The Helm chart uses a `range` loop over `.Values.models` to template multiple InferenceService resources from one template file. Each model entry specifies its own MIG resource type, replica count, and vLLM arguments. A shared ServingRuntime defines the vLLM container configuration. The pattern also supports tensor parallelism across multiple MIG slices for larger models.

## Implementation

### Templated InferenceService Loop

A single template file generates one InferenceService per enabled model entry:

```yaml
# charts/model-serving/templates/inferenceservice.yaml
{{- range $modelName, $model := .Values.models }}
{{- if $model.enabled }}
---
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
  name: {{ $modelName }}
spec:
  predictor:
    minReplicas: {{ $model.minReplicas | default $root.Values.scaling.minReplicas }}
    model:
      args:
        - --served-model-name={{ $model.id }}
        {{- with $model.args }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      modelFormat:
        name: vLLM
      resources:
        {{- toYaml $model.resources | nindent 8 }}
      storageUri: hf://{{ $model.id }}
{{- end }}
{{- end }}
```

### Per-Model MIG Resource Requests

Each model requests a specific MIG slice type. The 49B LLM requires two 3g.47gb slices for tensor parallelism, while smaller models fit on single 1g.12gb slices:

```yaml
# charts/model-serving/values.yaml (excerpt)
models:
  nim-llm:
    id: nvidia/Llama-3_3-Nemotron-Super-49B-v1_5-FP8
    enabled: true
    resources:
      limits:
        # FP8 model fits on 2x 3g.47gb MIG slices (2x 46GB = 92GB)
        nvidia.com/mig-3g.47gb: "2"
      requests:
        nvidia.com/mig-3g.47gb: "2"
    args:
      # Tensor parallel across 2 MIG slices
      - --tensor-parallel-size=2
      - --max-num-seqs=32

  nemoretriever-embedding-ms:
    id: nvidia/llama-nemotron-embed-1b-v2
    resources:
      limits:
        # Embedding model fits on 1x 1g.12gb MIG slice (10.75GB)
        nvidia.com/mig-1g.12gb: "1"
      requests:
        nvidia.com/mig-1g.12gb: "1"
```

### Shared ServingRuntime

All models use a single ServingRuntime that configures the vLLM container, chat template volumes, and shared memory:

```yaml
# charts/model-serving/templates/servingruntime.yaml (excerpt)
spec:
  containers:
    - name: kserve-container
      image: {{ .Values.image.image }}:{{ .Values.image.tag }}
      volumeMounts:
        - mountPath: /dev/shm
          name: shm
        - mountPath: /chat-templates
          name: chat-templates
  volumes:
    - name: shm
      emptyDir:
        medium: Memory
        sizeLimit: {{ .Values.servingRuntime.shmSize }}
    - name: chat-templates
      configMap:
        name: vllm-chat-templates
```

### Chat Template ConfigMap with Lookup Guard

The ConfigMap containing vLLM chat templates uses a Helm `lookup` function to avoid overwriting an existing ConfigMap:

```yaml
# charts/model-serving/templates/configmap.yaml
{{- $existingConfigMap := lookup "v1" "ConfigMap" .Release.Namespace "vllm-chat-templates" }}
{{- if not $existingConfigMap }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: vllm-chat-templates
data:
  tool_chat_template_llama3.2_json.jinja: |-
{{ .Files.Get "files/tool_chat_template_llama3.2_json.jinja" | indent 4 }}
{{- end }}
```

## Configuration

- **Key settings:** Each model in `models:` map has `id` (HuggingFace model ID), `enabled` flag, `resources` with MIG device types, and `args` for vLLM CLI arguments
- **Defaults:** `deploymentMode: RawDeployment` (not serverless); `servingTopology: singleNode`; models default to `storageUri: hf://{{ $model.id }}` when no explicit storage is configured
- **Dependencies:** NVIDIA GPU Operator with MIG Manager enabled and nodes labeled with `nvidia.com/mig.config`; a HuggingFace secret (`huggingface-secret`) for model downloads; GPU tolerations (`nvidia.com/gpu: NoSchedule`)

## Gotchas

- MIG resource types like `nvidia.com/mig-3g.47gb` must match the actual MIG partitioning configured on the nodes via the GPU Operator's MIG Manager (see `gpu-operator-clusterpolicy-mig-mixed.md`)
- The 49B LLM uses `--tensor-parallel-size=2` to split across two MIG slices, requiring both slices to be on the same physical GPU
- The `vllm-chat-templates` ConfigMap uses `lookup` to check existence, which means `helm template` (dry-run) will always create it since lookup returns empty during template rendering
- The `image.image` field (not `image.repository`) points to `registry.redhat.io/rhaiis-preview/vllm-cuda-rhel9` -- this is the Red Hat AI-certified vLLM image, not the upstream vLLM image

## Related Patterns

- `gpu-operator-clusterpolicy-mig-mixed.md` -- the ClusterPolicy that partitions GPUs into MIG slices consumed by these InferenceServices
