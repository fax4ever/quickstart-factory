---
name: model-serving
description: "Helm charts deploying vLLM models as KServe InferenceServices in RawDeployment mode on RHOAI (multi-model MIG or single-model OAuth)"
summary: "Deploys vLLM models as KServe InferenceServices in RawDeployment mode on RHOAI via Helm with two approaches: Approach A (aml-rag-nvidia) serves multiple models (LLM, embedding, reranking, VLM) from a single chart using a values map range loop with NVIDIA MIG GPU slicing, FP8 quantization (~200GB to ~70GB VRAM), Red Hat registry image (registry.redhat.io vllm-cuda-rhel9), Jinja2 chat templates via ConfigMap, flexible storage (URI/PVC/S3/hf://), multi-node topology, scale-to-zero, and HF_TOKEN for gated models; Approach B (data-governance-co-pilot) deploys a single model per chart on whole GPUs (nvidia.com/gpu) with community vLLM image (quay.io/redhat-ai-dev), OAuth proxy auth via post-install Helm hook Job, AWQ 4-bit quantization for 24GB GPUs, vLLM built-in --tool-call-parser (hermes for Qwen3, mistral for Nemotron), and no HF token required. Use Approach A for multi-model RAG pipelines on MIG GPUs needing per-model slice sizing (3g.47gb for LLMs with tensor parallelism, 1g.12gb for embedding/reranking) and optional multi-node/scale-to-zero; use Approach B for single-model deployments on standard whole GPUs requiring OAuth proxy authentication with route timeouts (600s HAProxy, 10m upstream) and independent deployment lifecycle. Downstream consumers discover models via `<model-name>-predictor:8080/v1` with `--served-model-name` matching the full HF model ID; Approach A defines models in values.yaml `models` map with `id`, `enabled`, `resources` (MIG slice types), and `args` (e.g., --tensor-parallel-size=2) using a shared ServingRuntime; Approach B configures `model.storage.type` (uri/s3/pvc), `model.runtime.args` for quantization and tool-calling, and `security.enableAuth` for OAuth proxy injection with `security.opendatahub.io/enable-auth` annotation. ConfigMap `lookup` in Approach A prevents chat template updates on `helm upgrade` (must delete manually); Approach B's OAuth proxy patch Job races with RHOAI sidecar injection and exits 0 with warning if oauth-proxy container not found; Nemotron requires `--mamba-ssm-cache-dtype float32` and `--enforce_eager` for its Mamba/SSM hybrid architecture; `--enforce_eager` and `--max-num-seqs=4` trade throughput for memory on 24GB GPUs; multiNode topology values (pipelineParallelSize, tensorParallelSize) have no defaults and require `--set`."
metadata:
  type: component
tags:
  tech_stack: [vllm, kserve, helm, oauth-proxy]
  ai_pattern: [model-serving, rag, embeddings, agents]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: []
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Multi-model vLLM serving (LLM, embedding, reranking, VLM) with NVIDIA MIG GPU slicing via standalone Helm chart"
    approach: "A"
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Single-model-per-chart KServe vLLM deployment with OAuth authentication, post-install oauth-proxy timeout patching, and dedicated ServingRuntime pinned by image digest"
    approach: "B"
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

---

## Approach B: Single-Model KServe with OAuth Proxy (from data-governance-co-pilot)

### When to Use

Use this approach when deploying a single LLM model per Helm chart on a standard whole GPU (not MIG-partitioned), when OAuth-proxy authentication is required for the inference endpoint, and when each model needs independent deployment lifecycle. The data-governance-co-pilot quickstart uses two instances of this pattern: `nemotron-model` (NVIDIA Nemotron Nano 9B v2, no quantization, Mistral tool-call parser) and `qwen3-model` (Qwen3-14B-AWQ, AWQ 4-bit quantization, Hermes tool-call parser).

### Differences from Approach A

- **Single-model chart** instead of a multi-model values map with range loop
- **Whole GPU** (`nvidia.com/gpu: 1`) instead of MIG slice types
- **Optional AWQ 4-bit quantization** (qwen3-model uses `--quantization awq`; nemotron-model runs unquantized with `--mamba-ssm-cache-dtype float32`)
- **OAuth proxy authentication** using `security.opendatahub.io/enable-auth` annotation and a post-install Helm hook Job to patch the oauth-proxy container's upstream timeout
- **Community vLLM image** (`quay.io/redhat-ai-dev/vllm-openai-ubi9`) instead of Red Hat registry image
- **vLLM built-in tool-call parsers** (`--tool-call-parser hermes`, `--reasoning-parser qwen3`) instead of custom Jinja2 chat templates from ConfigMap
- **No HuggingFace token** required (public model from `hf://Qwen/Qwen3-14B-AWQ`)
- **ServiceAccount with token Secret** for API access instead of no-auth mode

### Single-Model InferenceService

The chart creates one InferenceService directly (no range loop). The model storage type is selected via conditional logic supporting `uri`, `s3`, and `pvc` backends:

```yaml
# From helm/qwen3-model/templates/inferenceservice.yaml
spec:
  predictor:
    model:
      args:
         {{- toYaml .Values.model.runtime.args | nindent 8 }}
      modelFormat:
        name: vLLM
      runtime: {{ .Values.model.runtime.name }}
      {{- if eq .Values.model.storage.type "s3" }}
      storageUri: {{ .Values.model.storage.s3Bucket | quote }}
      {{- else if eq .Values.model.storage.type "pvc" }}
      storageUri: pvc://{{ .Values.model.storage.pvcName }}
      {{- else if eq .Values.model.storage.type "uri" }}
      storageUri: {{ .Values.model.storage.uri | quote }}
      {{- end }}
```

### AWQ Quantization for 24GB GPUs

The default values use AWQ 4-bit quantization to fit a 14B parameter model on a single A10G GPU with 24GB VRAM. The `--enforce_eager` flag disables CUDA graph capture to further reduce memory usage:

```yaml
# From helm/qwen3-model/values.yaml
model:
  storage:
    uri: "hf://Qwen/Qwen3-14B-AWQ"
  runtime:
    args:
      - --quantization
      - awq
      - --max-model-len=32768
      - --enforce_eager
      - --gpu-memory-utilization
      - "0.95"
      - --max-num-seqs
      - "4"
```

### Tool Calling and Reasoning Parsers

Instead of mounting custom Jinja2 chat templates via a ConfigMap (Approach A), this approach uses vLLM's built-in `--tool-call-parser` and `--reasoning-parser` flags. The `hermes` parser is compatible with Qwen3 for OpenAI-style function calling:

```yaml
# From helm/qwen3-model/values.yaml
    args:
      - --enable-auto-tool-choice
      - --tool-call-parser
      - hermes
      - --reasoning-parser
      - qwen3
```

### OAuth Proxy Authentication via Helm Hook

When `security.enableAuth: true`, the InferenceService is annotated with `security.opendatahub.io/enable-auth: "true"`, which causes RHOAI to inject an oauth-proxy sidecar. A post-install Helm hook Job patches the oauth-proxy container to add `--upstream-timeout` for long-running inference requests:

```yaml
# From helm/qwen3-model/templates/inferenceservice.yaml
annotations:
  security.opendatahub.io/enable-auth: "true"
  security.opendatahub.io/oauth-proxy-upstream-timeout: {{ .Values.route.oauthProxyUpstreamTimeout | quote }}
  serving.kserve.io/deploymentMode: RawDeployment
```

The patch Job waits for the predictor deployment, checks for the oauth-proxy container, then patches it:

```yaml
# From helm/qwen3-model/templates/oauth-proxy-patch-job.yaml
annotations:
  "helm.sh/hook": post-install,post-upgrade
  "helm.sh/hook-weight": "10"
  "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
```

The Job uses `oc get deployment` + `jq` to patch the oauth-proxy container args, adding `--upstream-timeout` only if not already present. It includes its own ServiceAccount, Role, and RoleBinding scoped to `apps/deployments` get/list/patch/update.

### Route Timeout Configuration

The chart configures long timeouts on both the OpenShift route and the oauth-proxy upstream for LLM inference requests that can take minutes:

```yaml
# From helm/qwen3-model/values.yaml
route:
  enabled: true
  timeout: "600s"
  oauthProxyUpstreamTimeout: "10m"
```

These are applied as annotations on the InferenceService:

```yaml
# From helm/qwen3-model/templates/inferenceservice.yaml
haproxy.router.openshift.io/timeout: {{ .Values.route.timeout | quote }}
haproxy.router.openshift.io/timeout-tunnel: {{ .Values.route.timeout | quote }}
```

### GPU Tolerations

The InferenceService spec includes tolerations for both generic NVIDIA GPU taints and AWS g5 instance taints:

```yaml
# From helm/qwen3-model/templates/inferenceservice.yaml
tolerations:
  - effect: NoSchedule
    key: nvidia.com/gpu
    operator: Exists
  - effect: NoSchedule
    key: g5-gpu
    operator: Exists
```

### ServingRuntime with Community vLLM Image

The ServingRuntime uses a community vLLM image pinned by digest and exposes Prometheus metrics. The vLLM runtime version annotation is `v0.11.0`:

```yaml
# From helm/qwen3-model/templates/servingruntime.yaml
containers:
  - args:
      - '--port=8080'
      - '--model=/mnt/models'
      - '--served-model-name={{ "{{.Name}}" }}'
    command:
      - python
      - '-m'
      - vllm.entrypoints.openai.api_server
    image: 'quay.io/redhat-ai-dev/vllm-openai-ubi9@sha256:b8f4ad3cb...'
```

### Configuration (Approach B)

- **Environment variables:**
  - `HF_HOME` - Hugging Face cache directory (set to `/tmp/hf_home` in ServingRuntime)

- **Helm values:**
  - `model.name` - Model name used for all resource naming (default: `qwen3-14b`)
  - `model.storage.type` - Storage backend: `uri`, `s3`, or `pvc` (default: `uri`)
  - `model.storage.uri` - Hugging Face URI for model download (default: `hf://Qwen/Qwen3-14B-AWQ`)
  - `model.runtime.args` - vLLM serving arguments including quantization and tool-calling config
  - `model.resources` - GPU and compute resource requests/limits
  - `model.scaling.minReplicas` / `maxReplicas` - Replica bounds (default: 1/1)
  - `route.enabled` - Enable OpenShift route creation
  - `route.timeout` - HAProxy route timeout (default: `600s`)
  - `route.oauthProxyUpstreamTimeout` - OAuth proxy upstream timeout (default: `10m`)
  - `security.enableAuth` - Enable OAuth proxy authentication (default: `true`)

- **Makefile targets (from `helm/Makefile`):**
  - `nemotron-model-install` / `qwen3-model-install` - Deploy and wait for model readiness (calls deploy + wait)
  - `nemotron-model-deploy` / `qwen3-model-deploy` - Start Helm install (non-blocking)
  - `nemotron-model-uninstall` / `qwen3-model-uninstall` - Helm uninstall
  - The top-level `install` target selects model via `MODEL=nemotron` or `MODEL=qwen3` when `DEPLOY_MODEL=true`

### Known Gotchas (Approach B)

- **NOTES.txt references wrong model name:** The `NOTES.txt` file says "NVIDIA Nemotron Nano 9B v2 model has been deployed!" but the chart deploys Qwen3-14B. This is a copy-paste artifact from the nemotron-model chart. Found in `helm/qwen3-model/templates/NOTES.txt` line 1.

- **OAuth-proxy patch Job may race with RHOAI sidecar injection:** The post-install Job waits up to 10 minutes for the predictor deployment to appear, but the oauth-proxy sidecar is injected by RHOAI's webhook. If the webhook is slow, the Job may find the deployment without the oauth-proxy container and skip the patch (exits 0 with warning). Found in `helm/qwen3-model/templates/oauth-proxy-patch-job.yaml`: `if ! ... jq -e ... select(.name=="oauth-proxy") ... echo "WARNING: oauth-proxy container not found"`.

- **`--enforce_eager` trades throughput for memory:** The `--enforce_eager` flag in the default vLLM args disables CUDA graph capture, which reduces peak memory usage but lowers throughput. This is necessary to fit the AWQ-quantized model within 24GB VRAM with `--gpu-memory-utilization=0.95`. Found in `helm/qwen3-model/values.yaml` comments: `# Note: AWQ quantization enabled for 24GB GPU compatibility`.

- **`--max-num-seqs=4` limits concurrent requests:** The default limits concurrent sequences to 4, which may cause queueing under moderate load. This is a memory-saving trade-off for 24GB GPUs. Found in `helm/qwen3-model/values.yaml` runtime args.

- **Model download time is 10-15 minutes:** The Makefile target `qwen3-model-wait` has a 15-minute timeout (900 seconds). The Qwen3-14B-AWQ model (~7GB) is downloaded from HuggingFace at deploy time. Found in `helm/Makefile`: `if [ $$elapsed -gt 900 ]`.

- **Nemotron requires Mistral tool-call parser and is MCP-Direct only:** The NVIDIA Nemotron Nano 9B v2 model uses a custom `<TOOLCALL>` tag format that maps to the `mistral` tool-call parser in vLLM (`--tool-call-parser mistral`). This is only compatible with MCP-Direct mode, not Llama Stack mode, as noted in `helm/DEPLOYMENT_MODES.md`: "Compatible Modes: MCP-Direct only".

- **Nemotron requires `--mamba-ssm-cache-dtype float32` and `--enforce_eager`:** The Nemotron Nano 9B v2 has a Mamba/SSM hybrid architecture that requires explicit cache dtype and eager execution. The `--enforce_eager` flag disables CUDA graph capture, reducing throughput but enabling SSM support. Found in `helm/nemotron-model/values.yaml` runtime args.

### Testing Notes (Approach B)

- Deploy with `make qwen3-model-install NAMESPACE=your-namespace` from the `helm/` directory
- Verify InferenceService readiness: `oc get inferenceservice qwen3-14b -n <namespace>`
- Check OAuth proxy was patched: `oc get deployment qwen3-14b-predictor -o json | jq '.spec.template.spec.containers[] | select(.name=="oauth-proxy") | .args'`
- Get the route endpoint: `oc get route qwen3-14b -n <namespace> -o jsonpath='{.spec.host}'`
- Test with authentication token: `oc sa get-token default -n <namespace>`

---

## Choosing Between Approaches

| Criteria | Approach A (aml-rag-nvidia) | Approach B (data-governance-co-pilot) |
|----------|-----------|-----------|
| Number of models | Multiple models in one chart (range loop) | Single model per chart |
| GPU type | NVIDIA MIG slices (e.g., 3g.47gb, 1g.12gb) | Whole GPU (nvidia.com/gpu) |
| Quantization | FP8 (for 49B+ models) | AWQ 4-bit (qwen3) or none (nemotron 9B) |
| Authentication | No auth / service account list | OAuth proxy with Helm hook patch Job |
| Tool calling | Custom Jinja2 chat templates via ConfigMap | vLLM built-in `--tool-call-parser` / `--reasoning-parser` |
| vLLM image | Red Hat registry (`registry.redhat.io`) | Community (`quay.io/redhat-ai-dev`) |
| HF token | Required (gated models) | Not required (public model) |
| Multi-node | Supported (`workerSpec`) | Not supported |
| Best for | Multi-model RAG pipelines with MIG GPUs | Single-model deployments on standard GPUs with auth |
