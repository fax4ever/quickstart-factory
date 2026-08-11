---
name: hate-and-profanity-detector
description: "IBM Granite Guardian HAP detector served via TrustyAI HF runtime on KServe for content moderation"
summary: "Screens both user inputs and LLM outputs for hate, profanity, and inappropriate language using IBM granite-guardian-hap-38m (38M params) served via TrustyAI HF detector runtime (quay.io/modh/odh-trustyai-hf-detector-runtime-rhel9) on KServe RawDeployment with uvicorn on port 8000, orchestrated by TrustyAI GuardrailsOrchestrator alongside prompt-injection, gibberish, and regex/PII detectors. Use as the \"hap\" detector in the orchestrator pipeline when bidirectional content moderation is needed (input: true, output: true in fms-orchestr8-config-gateway ConfigMap) — distinct from prompt-injection which scans input only; registers with type text_contents and whole_doc_chunker in fms-orchestr8-config-nlp ConfigMap, threshold tunable via detectors.hateAndProfanity.threshold (default 0.5). Model loads from OCI modelcar URI (oci://quay.io/mmurakam/model-cars:granite-guardian-hap-38m-v0.1.0) into /mnt/models with HF_HOME=/tmp/hf_home to avoid permission issues; requires shared-memory emptyDir volume (medium: Memory, sizeLimit: 2Gi) for PyTorch model loading; verify deployment with 2/2 containers ready and test via gateway /all/ route. InferenceService is named \"ibm-hate-and-profanity-detector\" but orchestrator hostname must match KServe pattern ibm-hate-and-profanity-detector-predictor.<namespace>.svc.cluster.local; pinned to 1 replica with no autoscaling so moderation is unavailable during restarts; all three HF detectors share the same image digest so updates affect all simultaneously; GPU optional (detectors.useGpu: false) — runs on CPU with 4Gi request/8Gi limit."
metadata:
  type: component
tags:
  tech_stack: [python, uvicorn, huggingface]
  ai_pattern: [guardrails, model-serving]
  platform: [kserve, rhoai, openshift, trustyai]
  data_layer: []
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Hate and profanity detector using granite-guardian-hap-38m model with TrustyAI orchestrator"
    approach: "A"
---

# Hate and Profanity Detector

## Overview

The hate-and-profanity detector (HAP) is a content moderation model server that screens both user inputs and LLM outputs for inappropriate, hateful, or profane language. It runs the IBM `granite-guardian-hap-38m` model via the TrustyAI HuggingFace detector runtime on KServe, and is orchestrated by the TrustyAI GuardrailsOrchestrator alongside other safety detectors (prompt injection, gibberish, regex/PII).

## Tech Stack & Dependencies

- **Runtime:** Python (uvicorn serving a FastAPI-style app via TrustyAI HF detector runtime)
- **Container image:** `quay.io/modh/odh-trustyai-hf-detector-runtime-rhel9@sha256:d1c099a1913cc6d5b99bf28fd8f89d7b6486176f78f561d80248a0e90916f9ad`
- **Model artifact:** `oci://quay.io/mmurakam/model-cars:granite-guardian-hap-38m-v0.1.0` (OCI modelcar format)
- **Key dependencies:** KServe (InferenceService + ServingRuntime), TrustyAI GuardrailsOrchestrator, guardrails gateway
- **Helm subchart:** None (standalone templates within the guardrailing-llms chart)

## Key Patterns

### KServe RawDeployment with Dedicated ServingRuntime

The detector uses KServe's `RawDeployment` mode (not serverless/Knative) with a dedicated ServingRuntime that pairs with the InferenceService. The model is loaded from an OCI modelcar URI into `/mnt/models`.

```yaml
# From helm/templates/inferenceservice-detectors.yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  annotations:
    openshift.io/display-name: ibm-hate-and-profanity-detector
    serving.kserve.io/deploymentMode: RawDeployment
  name: ibm-hate-and-profanity-detector
  labels:
    networking.kserve.io/visibility: exposed
    opendatahub.io/dashboard: 'true'
spec:
  predictor:
    automountServiceAccountToken: false
    maxReplicas: 1
    minReplicas: 1
    model:
      modelFormat:
        name: guardrails-detector-hf-runtime
      runtime: ibm-hate-and-profanity-detector
      storageUri: {{ .Values.detectors.hateAndProfanity.storageUri }}
```

### Shared HuggingFace Detector Runtime Image

All detectors (gibberish, prompt-injection, HAP) share the same container image and runtime configuration pattern. The ServingRuntime uses uvicorn to serve a Python app on port 8000, with the model directory mounted at `/mnt/models` and a shared-memory volume for model operations.

```yaml
# From helm/templates/servingruntime-detectors.yaml
spec:
  containers:
    - args:
        - '--workers=1'
        - '--host=0.0.0.0'
        - '--port=8000'
        - '--log-config=/common/log_conf.yaml'
      command:
        - uvicorn
        - 'app:app'
      env:
        - name: MODEL_DIR
          value: /mnt/models
        - name: HF_HOME
          value: /tmp/hf_home
      image: 'quay.io/modh/odh-trustyai-hf-detector-runtime-rhel9@sha256:...'
  volumes:
    - emptyDir:
        medium: Memory
        sizeLimit: 2Gi
      name: shm
```

### Orchestrator Integration as HAP Detector

The detector registers in the TrustyAI orchestrator config under the key `hap` with `type: text_contents`. It uses a `whole_doc_chunker` strategy (analyzing the full text as a single unit) and is applied to both input and output via the gateway config.

```yaml
# From helm/templates/configmaps.yaml (fms-orchestr8-config-nlp)
detectors:
  hap:
    type: text_contents
    service:
      hostname: ibm-hate-and-profanity-detector-predictor.{{ .Release.Namespace }}.svc.cluster.local
      port: 8000
    chunker_id: whole_doc_chunker
    default_threshold: 0.5
```

```yaml
# From helm/templates/configmaps.yaml (fms-orchestr8-config-gateway)
detectors:
  - name: hap
    input: true
    output: true
    detector_params: {}
```

### Bidirectional Content Scanning

The HAP detector is configured with `input: true` and `output: true` in the gateway config, meaning it scans both user prompts and LLM responses. This is distinct from the prompt-injection detector which only scans input (`input: true, output: false`).

## Configuration

- **Environment variables:**
  - `MODEL_DIR=/mnt/models` - Where KServe mounts the model artifact
  - `HF_HOME=/tmp/hf_home` - HuggingFace cache directory (set to tmp to avoid permission issues)
- **Config files:**
  - `fms-orchestr8-config-nlp` ConfigMap - Registers the detector with hostname, port, threshold
  - `fms-orchestr8-config-gateway` ConfigMap - Controls which detectors apply to input/output
- **Helm values:**
  - `detectors.hateAndProfanity.storageUri` - OCI URI for the granite-guardian-hap-38m model (default: `oci://quay.io/mmurakam/model-cars:granite-guardian-hap-38m-v0.1.0`)
  - `detectors.hateAndProfanity.threshold` - Detection confidence threshold (default: `0.5`)
  - `detectors.hateAndProfanity.port` - Service port (default: `8000`)
  - `detectors.useGpu` - Toggle GPU allocation for all detectors (default: `false`)

## Known Gotchas

- The detector InferenceService name is prefixed with `ibm-` (`ibm-hate-and-profanity-detector`) but the orchestrator config key is just `hap` -- the hostname in the orchestrator config must match the KServe-generated service name pattern: `ibm-hate-and-profanity-detector-predictor.<namespace>.svc.cluster.local`.
- GPU is optional for detectors (`detectors.useGpu: false` by default) unlike the main LLM which requires a GPU. The granite-guardian-hap-38m model is small enough (38M parameters) to run on CPU with 4Gi memory request / 8Gi limit.
- All three HF-based detectors share the same container image digest, so they always deploy the same runtime version. Any image update affects all detectors simultaneously.
- The shared-memory volume (`/dev/shm`) is mounted as an emptyDir with `medium: Memory` and `sizeLimit: 2Gi` -- this is required for PyTorch model loading and will consume node RAM.
- The detector is pinned to exactly 1 replica (`minReplicas: 1, maxReplicas: 1`), so there is no autoscaling. If the detector pod goes down, content moderation is unavailable until it restarts.

## Testing Notes

- After deployment, verify the pod is running with 2/2 containers ready: `ibm-hate-and-profanity-detector-predictor-*`
- Test content moderation by sending a message with profanity through the gateway `/all/` route -- the response should return an empty `choices` array with a `warning` and `detections` containing a `sequence_classifier` detection from the `hap` detector (as demonstrated in `docs/healthcare-guardrails.ipynb`).
- The detection threshold (default 0.5) can be tuned via `detectors.hateAndProfanity.threshold` in values.yaml.

## Related Patterns

- Other detectors in the same architecture: gibberish-detector, prompt-injection-detector, regex detector
- TrustyAI GuardrailsOrchestrator (coordinates all detectors)
- KServe InferenceService + ServingRuntime deployment pattern
