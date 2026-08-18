---
name: hate-and-profanity-detector
description: "IBM Granite Guardian HAP detector served via TrustyAI HF runtime on KServe for content moderation"
summary: "Screens both user inputs and LLM outputs for hate, profanity, and inappropriate language using IBM granite-guardian-hap models served via TrustyAI HF detector runtime on KServe RawDeployment with uvicorn on port 8000, orchestrated by TrustyAI GuardrailsOrchestrator alongside prompt-injection, gibberish, and regex/PII detectors. Two approaches — Approach A (guardrailing-llms) uses granite-guardian-hap-38m (38M params) from OCI modelcar URI with digest-pinned RHOAI image, 1 worker, whole_doc_chunker, shared GPU toggle, and shared-memory emptyDir volume for higher reproducibility; Approach B (lemonade-stand-assistant) uses granite-guardian-hap-125m (125M params) from MinIO S3 with HF CLI download initContainer (50Gi PVC), community :latest image, 4 workers, sentence chunker, and per-detector GPU/resources for potentially better accuracy — both provide bidirectional scanning (input: true, output: true) unlike prompt-injection which is input-only, threshold tunable via detectors.hateAndProfanity.threshold (default 0.5). Registers as \"hap\" with type text_contents in fms-orchestr8-config-nlp ConfigMap; requires HF_HOME=/tmp/hf_home and MODEL_DIR=/mnt/models; Approach A needs shared-memory emptyDir (medium: Memory, sizeLimit: 2Gi) for PyTorch model loading; verify deployment with 2/2 containers ready and test via gateway /all/ route. Orchestrator hostname must match KServe-generated pattern (ibm-hate-and-profanity-detector-predictor.<namespace>.svc.cluster.local for A, guardrails-detector-ibm-hap-predictor for B); all HF detectors share the same image digest so updates affect all simultaneously; pinned to 1 replica with no autoscaling means moderation unavailable during restarts; Approach B's MinIO uses hardcoded keys (THEACCESSKEY/THESECRETKEY) and floating :latest tag reducing reproducibility; GPU optional — runs on CPU with 4Gi request/8Gi limit."
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
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "HAP detector using granite-guardian-hap-125m model with MinIO S3 storage and sentence chunking"
    approach: "B"
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

---

## Approach B: MinIO S3 Model Storage with Sentence Chunking (from lemonade-stand-assistant)

### When to Use

When deploying the HAP detector with models stored in MinIO S3 rather than OCI modelcar URIs, using the larger `granite-guardian-hap-125m` model (125M parameters), and when sentence-level chunking is preferred over whole-document analysis.

### Differences from Approach A

- **Model**: `granite-guardian-hap-125m` (125M params) instead of `granite-guardian-hap-38m` (38M params)
- **Model storage**: MinIO S3 with KServe data connection secret instead of OCI modelcar URI
- **Container image**: `quay.io/trustyai/guardrails-detector-huggingface-runtime:latest` (tag-based, community image) instead of digest-pinned RHOAI product image
- **Chunker strategy**: `sentence` chunker instead of `whole_doc_chunker`
- **Workers**: 4 uvicorn workers instead of 1
- **GPU toggle**: Per-detector (`detectors.hap.useGpu`) instead of shared (`detectors.useGpu`)
- **Resource config**: Per-detector resource blocks (`detectors.hap.resources`) instead of shared defaults
- **No shared-memory volume**: No emptyDir `/dev/shm` volume mount
- **Orchestrator hostname**: Short service name (`guardrails-detector-ibm-hap-predictor`) instead of FQDN

### KServe RawDeployment with MinIO Storage

The detector uses KServe RawDeployment mode like Approach A, but models are stored in MinIO S3 referenced via a KServe `storage.key` pointing to a data connection secret, with the model path as a subdirectory.

```yaml
# From chart/templates/ibm-hap-detector.yaml
spec:
  predictor:
    automountServiceAccountToken: false
    maxReplicas: 1
    minReplicas: 1
    model:
      modelFormat:
        name: guardrails-detector-huggingface
      runtime: guardrails-detector-runtime-hap
      storage:
        key: minio-data-connection-detector-models
        path: granite-guardian-hap-125m
```

### Model Download via MinIO InitContainer

Models are downloaded from HuggingFace into a MinIO-backed PVC using an initContainer with `huggingface-cli download`, then served via a MinIO container. Both HAP and prompt-injection models are downloaded in the same initContainer.

```yaml
# From chart/templates/minio-storage-models.yaml
initContainers:
  - name: download-model
    image: quay.io/rgeada/llm_downloader:latest
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

### ServingRuntime with 4 Workers

The runtime uses 4 uvicorn workers (vs 1 in Approach A) and does not include a shared-memory volume.

```yaml
# From chart/templates/ibm-hap-detector.yaml
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
      env:
        - name: MODEL_DIR
          value: /mnt/models
        - name: HF_HOME
          value: /tmp/hf_home
      image: quay.io/trustyai/guardrails-detector-huggingface-runtime:latest
```

### Orchestrator Integration with Sentence Chunking

The detector registers in the fms-orchestr8-config-nlp ConfigMap using `sentence` chunker (splitting text into sentences before classification) instead of whole-document analysis. The hostname uses KServe's short-name predictor pattern.

```yaml
# From chart/templates/fms-orchestr8-config-nlp.yaml
detectors:
  hap:
    type: text_contents
    service:
      hostname: guardrails-detector-ibm-hap-predictor
      port: 8000
    chunker_id: sentence
    default_threshold: 0.5
```

### Per-Detector GPU Toggle and Resources

Each detector has its own `useGpu` toggle and resource block, allowing independent GPU allocation. When GPU is enabled, an `nvidia.com/gpu: '1'` resource and toleration are conditionally added.

```yaml
# From chart/values.yaml
detectors:
  hap:
    useGpu: false
    resources:
      requests:
        cpu: '1'
        memory: 4Gi
      limits:
        cpu: '2'
        memory: 8Gi
```

### Configuration

- **Environment variables:** Same as Approach A (`MODEL_DIR=/mnt/models`, `HF_HOME=/tmp/hf_home`)
- **Config files:** `fms-orchestr8-config-nlp` ConfigMap (no separate gateway config -- uses TrustyAI GuardrailsOrchestrator CR)
- **Helm values:**
  - `detectors.hap.useGpu` - Per-detector GPU toggle (default: `false`)
  - `detectors.hap.resources.requests.cpu` / `memory` - CPU and memory requests (default: `1` / `4Gi`)
  - `detectors.hap.resources.limits.cpu` / `memory` - CPU and memory limits (default: `2` / `8Gi`)

### Known Gotchas

- The MinIO data connection secret (`minio-data-connection-detector-models`) uses base64-encoded values with hardcoded access/secret keys (`THEACCESSKEY`/`THESECRETKEY`) -- these must be changed for production deployments.
- The MinIO PVC requests 50Gi of storage for both detector models, which is shared between HAP and prompt-injection models.
- The container image uses a floating `:latest` tag rather than a pinned digest, meaning deployments are not reproducible across different pull times.
- The InferenceService name (`guardrails-detector-ibm-hap`) differs from Approach A's naming (`ibm-hate-and-profanity-detector`), so the orchestrator hostname pattern also differs: `guardrails-detector-ibm-hap-predictor` vs `ibm-hate-and-profanity-detector-predictor`.
- The `granite-guardian-hap-125m` model is 3x larger than the 38M model in Approach A, requiring more memory but potentially providing better detection accuracy.

---

## Choosing Between Approaches

| Criteria | Approach A (guardrailing-llms) | Approach B (lemonade-stand-assistant) |
|----------|-------------------------------|---------------------------------------|
| Model | granite-guardian-hap-38m (38M params) | granite-guardian-hap-125m (125M params) |
| Model storage | OCI modelcar URI | MinIO S3 with HF download initContainer |
| Container image | Digest-pinned RHOAI product image | Tag-based community image (`:latest`) |
| Chunking strategy | whole_doc_chunker | sentence chunker |
| Workers | 1 | 4 |
| GPU config | Shared toggle for all detectors | Per-detector toggle |
| Shared memory volume | Yes (emptyDir 2Gi) | No |
| Reproducibility | High (pinned digest + OCI) | Lower (floating tag + HF download) |
| Gateway config | Separate gateway ConfigMap (input/output control) | GuardrailsOrchestrator CR (no gateway) |
