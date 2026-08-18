---
name: prompt-injection-detector
description: "KServe-based prompt injection detector using TrustyAI HF runtime with DeBERTa model on RHOAI"
summary: "Classifies user inputs as prompt injection attacks using a DeBERTa v3 model served as a KServe InferenceService in RawDeployment mode (avoids Knative/Service Mesh) within a TrustyAI GuardrailsOrchestrator multi-detector pipeline on RHOAI. Approach A (guardrailing-llms) uses OCI modelcar storageUri with SHA256-pinned `odh-trustyai-hf-detector-runtime-rhel9` image, shared multi-document YAML template, global GPU toggle, 1 uvicorn worker, `whole_doc_chunker`, and 1CPU/4Gi requests; Approach B (lemonade-stand-assistant) uses MinIO S3 with HuggingFace download init container, per-detector template/GPU/resource control, 4 workers, `sentence` chunker, `:latest` tag, Prometheus `guardrail_detections_by_detector` metric, and 4CPU/16Gi requests -- choose A for minimal footprint and reproducibility, B for per-detector tuning and independent lifecycle management. Registers in `fms-orchestr8-config-nlp` ConfigMap as `text_contents` type with `default_threshold: 0.5`, gateway routes to input-only scanning, runtime runs `uvicorn app:app` on port 8000 with `MODEL_DIR=/mnt/models`, `HF_HOME=/tmp/hf_home`, `automountServiceAccountToken: false`, and minReplicas/maxReplicas both 1. Approach A's shared multi-document YAML (`inferenceservice-detectors.yaml`) risks modifying sibling detectors and SHA256 digest must be updated across all three ServingRuntimes simultaneously; Approach B uses hardcoded MinIO credentials (`THEACCESSKEY`/`THESECRETKEY`), re-downloads models from HuggingFace Hub on every pod restart, and `:latest` tag causes non-reproducible deployments; both produce `sequence_classifier` detections tested only via the orchestrator `/all/` route."
metadata:
  type: component
tags:
  tech_stack: [kserve, uvicorn, huggingface, deberta, minio, fastapi]
  ai_pattern: [guardrails, model-serving]
  platform: [kserve, rhoai, openshift, trustyai]
  data_layer: [minio]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Prompt injection detector deployed as KServe InferenceService with TrustyAI HF detector runtime, orchestrated by GuardrailsOrchestrator"
    approach: "A"
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "Prompt injection detector with MinIO-backed model storage, per-detector GPU toggle, dedicated template file, and sentence-level chunking"
    approach: "B"
---

# Prompt Injection Detector

## Overview

The prompt injection detector is a KServe InferenceService that uses a fine-tuned DeBERTa v3 model to classify user inputs as potential prompt injection attacks. It runs as part of a multi-detector guardrails pipeline orchestrated by TrustyAI's GuardrailsOrchestrator on RHOAI. The detector operates on CPU by default (with optional GPU support) and is deployed via a dedicated ServingRuntime that uses the TrustyAI Hugging Face detector runtime image.

## Tech Stack & Dependencies

- **Runtime:** Uvicorn serving a Python app (`uvicorn app:app`) with 1 worker
- **Container image:** `quay.io/modh/odh-trustyai-hf-detector-runtime-rhel9` (pinned by SHA256 digest)
- **Model artifact:** `oci://quay.io/mmurakam/model-cars:deberta-v3-base-prompt-injection-v2-v0.1.0` (OCI modelcar format)
- **Key dependencies:** KServe (InferenceService + ServingRuntime), TrustyAI GuardrailsOrchestrator, OpenShift AI with KServe enabled
- **Helm subchart:** None (standalone templates in the guardrailing-llms chart)

## Key Patterns

### KServe RawDeployment Mode

The detector uses KServe's `RawDeployment` mode rather than serverless, which avoids the Knative/Service Mesh dependency and keeps the pod always running. This is set via annotation on the InferenceService.

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
  name: prompt-injection-detector
  labels:
    networking.kserve.io/visibility: exposed
    opendatahub.io/dashboard: 'true'
spec:
  predictor:
    automountServiceAccountToken: false
    maxReplicas: 1
    minReplicas: 1
```

### Shared ServingRuntime Pattern

All detectors (prompt injection, gibberish, hate/profanity) share the same container image and ServingRuntime template (`guardrails-detector-hf-runtime`), differentiated only by their model artifact (`storageUri`) and name. The ServingRuntime uses a `modelFormat` name that links the InferenceService to the correct runtime.

```yaml
# ServingRuntime (serving.kserve.io/v1alpha1)
spec:
  containers:
    - command:
        - uvicorn
        - 'app:app'
      args:
        - '--workers=1'
        - '--host=0.0.0.0'
        - '--port=8000'
      env:
        - name: MODEL_DIR
          value: /mnt/models
        - name: HF_HOME
          value: /tmp/hf_home
  supportedModelFormats:
    - autoSelect: true
      name: guardrails-detector-hf-runtime
```

### OCI ModelCar Storage

The model is pulled from an OCI registry using the modelcar pattern rather than S3/PVC storage. This is configured via the `storageUri` field in values.yaml.

```yaml
# values.yaml
detectors:
  promptInjection:
    storageUri: "oci://quay.io/mmurakam/model-cars:deberta-v3-base-prompt-injection-v2-v0.1.0"
    threshold: 0.5
    port: 8000
```

### Shared Memory Volume for Model Loading

Each detector ServingRuntime mounts a memory-backed emptyDir at `/dev/shm` to support model loading operations that require shared memory.

```yaml
volumes:
  - emptyDir:
      medium: Memory
      sizeLimit: 2Gi
    name: shm
```

### Optional GPU Support via Helm Templating

GPU allocation for detectors is controlled by a single `useGpu` toggle in values.yaml. When enabled, each detector requests 1 NVIDIA GPU. By default, detectors run on CPU only.

```yaml
resources:
  limits:
    cpu: '2'
    memory: 8Gi
    {{- if .Values.detectors.useGpu }}
    nvidia.com/gpu: '1'
    {{- end }}
  requests:
    cpu: '1'
    memory: 4Gi
```

### Orchestrator Integration

The prompt injection detector registers with the TrustyAI GuardrailsOrchestrator via the `fms-orchestr8-config-nlp` ConfigMap. It is configured as a `text_contents` type detector with a `whole_doc_chunker` and a default threshold of 0.5.

```yaml
# ConfigMap: fms-orchestr8-config-nlp
detectors:
  prompt_injection:
    type: text_contents
    service:
      hostname: prompt-injection-detector-predictor.{{ .Release.Namespace }}.svc.cluster.local
      port: 8000
    chunker_id: whole_doc_chunker
    default_threshold: 0.5
```

### Gateway Routing — Input-Only Detection

In the gateway configuration (`fms-orchestr8-config-gateway`), the prompt injection detector is applied to inputs only (not outputs), since prompt injection is an input-side concern. Other detectors like HAP and gibberish scan both input and output.

```yaml
# ConfigMap: fms-orchestr8-config-gateway
detectors:
  - name: prompt_injection
    input: true
    output: false
    detector_params: {}
```

## Configuration

- **Environment variables:**
  - `MODEL_DIR=/mnt/models` — where KServe mounts the model artifact
  - `HF_HOME=/tmp/hf_home` — writable Hugging Face cache directory (avoids read-only filesystem issues)
- **Helm values:**
  - `detectors.promptInjection.storageUri` — OCI URI for the DeBERTa prompt injection model
  - `detectors.promptInjection.threshold` — detection confidence threshold (default: `0.5`)
  - `detectors.promptInjection.port` — service port (default: `8000`)
  - `detectors.useGpu` — toggle GPU allocation for all detectors (default: `false`)
- **Resource defaults:** 1 CPU / 4Gi memory (requests), 2 CPU / 8Gi memory (limits)

## Known Gotchas

- **All three detectors share one YAML template file** (`inferenceservice-detectors.yaml`): the prompt injection detector is defined as the second document in a multi-document YAML. Editing one detector's spec risks accidentally modifying sibling detectors in the same file.
- **GPU toggle is global for all detectors:** the `detectors.useGpu` flag applies to all three detectors at once (gibberish, prompt injection, hate/profanity). There is no per-detector GPU toggle. This was added in commit `8bbfc16` to address GPU scheduling needs.
- **Container image is pinned by SHA256 digest** across all three detector ServingRuntimes. When updating the TrustyAI HF detector runtime image, all three ServingRuntimes in `servingruntime-detectors.yaml` must be updated together.
- **`HF_HOME` set to `/tmp/hf_home`:** The Hugging Face home is redirected to a writable temp directory because the container filesystem is read-only by default.

## Testing Notes

- After deployment, verify the pod is running with 2/2 containers ready: `prompt-injection-detector-predictor-<hash>`
- The detector is exercised via the orchestrator gateway's `/all/` route, not called directly. Send a prompt injection attempt (e.g., "Ignore all previous instructions...") through the gateway and confirm the response returns empty `choices` with a `detections` entry from the prompt injection detector.
- The detector produces `sequence_classifier` detection types in the response when a prompt injection is detected.

## Related Patterns

- `architectures/guardrails-pipeline.md` — overall multi-detector orchestration architecture
- `deployment/helm-guardrails.md` — Helm chart deployment patterns for this quickstart

---

## Approach B: MinIO-Backed Model Storage with Per-Detector Configuration (from lemonade-stand-assistant)

### When to Use

When you need per-detector resource tuning and GPU control, prefer downloading models from HuggingFace Hub into MinIO rather than using OCI modelcar images, or want each detector in its own Helm template file for independent lifecycle management.

### Differences from Approach A

- **Model storage:** Uses MinIO S3 storage with an init container that downloads the model from HuggingFace Hub, instead of OCI modelcar `storageUri`.
- **Template layout:** Each detector has its own dedicated Helm template file (`prompt-injection-detector.yaml`) rather than sharing a multi-document YAML.
- **Per-detector GPU toggle:** Each detector has an independent `detectors.promptInjection.useGpu` flag instead of a single global `detectors.useGpu`.
- **Per-detector resource specs:** Each detector has its own `resources.requests` and `resources.limits` block in `values.yaml`.
- **Worker count:** Runs 4 uvicorn workers (`--workers 4`) instead of 1.
- **Chunking:** Orchestrator config uses `sentence` chunker instead of `whole_doc_chunker`.
- **Container image:** Uses `quay.io/trustyai/guardrails-detector-huggingface-runtime:latest` (tag-based) rather than the Red Hat-maintained image pinned by SHA256 digest.
- **No shared memory volume:** Does not mount a memory-backed emptyDir at `/dev/shm`.

### Dedicated ServingRuntime and InferenceService

The prompt injection detector has its own ServingRuntime and InferenceService in a single template file. The ServingRuntime is named distinctly to avoid collision with other detectors.

```yaml
# chart/templates/prompt-injection-detector.yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  name: guardrails-detector-runtime-prompt-injection
spec:
  containers:
    - args:
        - '--workers'
        - '4'
        - '--host'
        - 0.0.0.0
        - '--port'
        - '8000'
        - '--log-config'
        - /common/log_conf.yaml
      command:
        - uvicorn
        - 'app:app'
      image: quay.io/trustyai/guardrails-detector-huggingface-runtime:latest
```

### MinIO Model Storage with HuggingFace Download Init Container

Models are downloaded from HuggingFace Hub into a MinIO instance via an init container in the `minio-storage-guardrail-detectors` Deployment. The InferenceService references the model via a MinIO data connection secret.

```yaml
# chart/templates/minio-storage-models.yaml (init container)
initContainers:
  - name: download-model
    command:
      - bash
      - -c
      - |
        models=(
          ibm-granite/granite-guardian-hap-125m
          protectai/deberta-v3-base-prompt-injection-v2
        )
        for model in "${models[@]}"; do
          /tmp/venv/bin/huggingface-cli download $model \
            --local-dir /mnt/models/huggingface/$(basename $model)
        done
```

```yaml
# InferenceService storage reference
spec:
  predictor:
    model:
      runtime: guardrails-detector-runtime-prompt-injection
      storage:
        key: minio-data-connection-detector-models
        path: deberta-v3-base-prompt-injection-v2
```

### Per-Detector Resource and GPU Configuration

Each detector has independent resource requests/limits and GPU toggle in `values.yaml`, allowing fine-grained resource allocation.

```yaml
# chart/values.yaml
detectors:
  promptInjection:
    useGpu: false
    resources:
      requests:
        cpu: '4'
        memory: 16Gi
      limits:
        cpu: '8'
        memory: 24Gi
```

Resource defaults are significantly higher than Approach A (4 CPU / 16Gi vs 1 CPU / 4Gi requests) due to running 4 uvicorn workers.

### Orchestrator Integration with Sentence Chunking

The detector registers in the same `fms-orchestr8-config-nlp` ConfigMap but uses a `sentence` chunker (via a separate chunker service) instead of the `whole_doc_chunker` used in Approach A.

```yaml
# chart/templates/fms-orchestr8-config-nlp.yaml
detectors:
  prompt_injection:
    type: text_contents
    service:
      hostname: prompt-injection-detector-predictor
      port: 8000
    chunker_id: sentence
    default_threshold: 0.5
```

### Application-Level Integration

The FastAPI application integrates the prompt injection detector as an input-only detector in the orchestrator request payload, with user-friendly blocking messages and per-detector metrics tracking.

```python
# lemonade-stand-app/app_fastapi.py
"detectors": {
    "input": {
        "hap": {},
        "language_detection": {},
        "prompt_injection": {}
    },
    "output": {
        "hap": {},
        "regex_competitor": {"regex": ALL_REGEX_PATTERNS},
        "language_detection": {}
    }
}
```

When a prompt injection is detected, the application displays a specific error message and applies CSS styling for visual differentiation:

```python
# lemonade-stand-app/app_fastapi.py
DETECTOR_MESSAGES = {
    "prompt_injection_input": "Your message appears to contain instructions that try to override the system rules.",
    "prompt_injection_output": "The response was blocked for containing suspicious instructions.",
}
```

### Monitoring

The Grafana dashboard tracks prompt injection detections via a Prometheus metric:

```json
{
  "expr": "sum(guardrail_detections_by_detector{detector=\"prompt_injection\"})",
  "legendFormat": "Jailbreak"
}
```

## Configuration (Approach B)

- **Environment variables:**
  - `MODEL_DIR=/mnt/models` — where KServe mounts the model artifact
  - `HF_HOME=/tmp/hf_home` — writable Hugging Face cache directory
- **Helm values:**
  - `detectors.promptInjection.useGpu` — per-detector GPU toggle (default: `false`)
  - `detectors.promptInjection.resources.requests.cpu` — CPU request (default: `4`)
  - `detectors.promptInjection.resources.requests.memory` — memory request (default: `16Gi`)
  - `detectors.promptInjection.resources.limits.cpu` — CPU limit (default: `8`)
  - `detectors.promptInjection.resources.limits.memory` — memory limit (default: `24Gi`)
- **Resource defaults:** 4 CPU / 16Gi memory (requests), 8 CPU / 24Gi memory (limits)

## Known Gotchas (Approach B)

- **MinIO uses default credentials in the template:** The `minio-storage-guardrail-detectors` Deployment uses hardcoded `THEACCESSKEY` / `THESECRETKEY` values. The corresponding Secret (`minio-data-connection-detector-models`) stores base64-encoded versions of these same credentials. These are demo-only values found in `chart/templates/minio-storage-models.yaml`.
- **Init container downloads models on every pod restart:** The HuggingFace download init container runs on each pod creation, re-downloading models from the Hub. This can be slow and depends on external network connectivity, unlike Approach A's OCI modelcar which is pulled by the container runtime.
- **Container image uses `:latest` tag:** The ServingRuntime image `quay.io/trustyai/guardrails-detector-huggingface-runtime:latest` is not pinned by digest, which can lead to non-reproducible deployments if the image changes upstream.
- **Higher resource requirements:** The 4-worker configuration requires 4x CPU / 16Gi memory requests, which is 4x the CPU and 4x the memory of Approach A defaults. The quickstart prerequisite notes minimum 7 vCPU / 30 GiB across all components.

---

## Choosing Between Approaches

| Criteria | Approach A (guardrailing-llms) | Approach B (lemonade-stand-assistant) |
|----------|-------------------------------|---------------------------------------|
| Model storage | OCI modelcar (registry pull) | MinIO S3 (HuggingFace Hub download) |
| Image pinning | SHA256 digest (reproducible) | `:latest` tag |
| Template layout | Shared multi-document YAML | Separate file per detector |
| GPU control | Global toggle for all detectors | Per-detector toggle |
| Resource control | Shared defaults | Per-detector resource specs |
| Uvicorn workers | 1 | 4 |
| Chunking strategy | whole_doc_chunker | sentence chunker |
| Shared memory volume | Yes (2Gi emptyDir) | No |
| Network dependency | None (OCI pull) | Requires HuggingFace Hub access at deploy time |
| Resource footprint | 1 CPU / 4Gi requests | 4 CPU / 16Gi requests |
