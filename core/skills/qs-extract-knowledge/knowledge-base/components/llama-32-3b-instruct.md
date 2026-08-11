---
name: llama-32-3b-instruct
description: "KServe vLLM InferenceService for Llama 3.2 3B with OCI modelcar storage and tool-calling for guardrails pipelines"
summary: "Serves Llama 3.2 3B Instruct via KServe vLLM RawDeployment with OCI modelcar storage (oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct), eliminating HuggingFace token requirements and providing an OpenAI-compatible chat completions backend on port 8080 for TrustyAI GuardrailsOrchestrator safety pipelines. Use when deploying a tool-calling-capable LLM as the chat_generation backend (wired via <name>-predictor.<namespace>.svc.cluster.local) in a TrustyAI multi-detector pipeline with /all/ (regex, hap, prompt_injection, gibberish detectors) and /passthrough/ routes -- requires 1 NVIDIA GPU (24GiB+ vRAM), RHOAI operator with KServe, and the managed vLLM image pinned by digest. Helm values conditionally toggle vLLM args (enableAutoToolChoice, toolCallParser: llama3_json, chatTemplate: /app/data/template/tool_chat_template_llama3.2_json.jinja, maxModelLen: 32768, maxNumSeqs: 8) while the ServingRuntime requires a Memory-backed emptyDir at /dev/shm (2Gi sizeLimit) and HF_HOME=/tmp/hf_home. Critical gotcha: InferenceService template hardcodes --max-model-len=20000, --dtype=half, and --gpu-memory-utilization=0.95 overriding ServingRuntime values.yaml settings, dual vLLM image digests exist between template default and values.yaml fallback, and the chatTemplate path references a Jinja2 file baked into the container -- updating the vLLM image without that template breaks startup."
metadata:
  type: component
tags:
  tech_stack: [vllm, kserve, helm]
  ai_pattern: [model-serving, guardrails]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: []
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Llama 3.2 3B Instruct served via KServe vLLM with OCI modelcar storage, tool-calling support, and TrustyAI guardrails orchestrator integration"
    approach: "A"
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
