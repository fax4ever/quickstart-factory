---
name: prompt-injection-detector
description: "KServe-based prompt injection detector using TrustyAI HF runtime with DeBERTa model on RHOAI"
summary: "Classifies user inputs as prompt injection attacks using a DeBERTa v3 model served as a KServe InferenceService in RawDeployment mode (avoids Knative/Service Mesh), operating as one detector in a TrustyAI GuardrailsOrchestrator multi-detector pipeline on RHOAI with minReplicas/maxReplicas both 1. Use when deploying input-side guardrails alongside sibling detectors (gibberish, hate/profanity) that share the same `guardrails-detector-hf-runtime` ServingRuntime and `odh-trustyai-hf-detector-runtime-rhel9` container image (pinned by SHA256 digest), with each detector differentiated only by its OCI modelcar `storageUri`. Registers in the `fms-orchestr8-config-nlp` ConfigMap as `text_contents` type with `whole_doc_chunker` and default threshold 0.5, gateway routes it to input-only scanning, and the runtime runs `uvicorn app:app --workers=1` on port 8000 with `MODEL_DIR=/mnt/models`, `HF_HOME=/tmp/hf_home` for writable cache, a 2Gi memory-backed emptyDir at `/dev/shm`, and `automountServiceAccountToken: false`. All three detectors share one multi-document YAML template (`inferenceservice-detectors.yaml`) so editing one risks modifying siblings; the `detectors.useGpu` toggle is global with no per-detector GPU control; the container image SHA256 must be updated across all three ServingRuntimes simultaneously; and testing is done via the orchestrator `/all/` route (not directly) where detections appear as `sequence_classifier` type."
metadata:
  type: component
tags:
  tech_stack: [kserve, uvicorn, huggingface, deberta]
  ai_pattern: [guardrails, model-serving]
  platform: [kserve, rhoai, openshift, trustyai]
  data_layer: []
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Prompt injection detector deployed as KServe InferenceService with TrustyAI HF detector runtime, orchestrated by GuardrailsOrchestrator"
    approach: "A"
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
