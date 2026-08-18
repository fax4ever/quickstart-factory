---
name: kserve-rawdeployment-detector-fleet-gpu-toggle
description: Multiple KServe InferenceServices with shared TrustyAI detector runtime and conditional GPU via single toggle
summary: "Deploys a fleet of KServe RawDeployment InferenceServices — TrustyAI HF safety detectors (gibberish, prompt-injection/deberta-v3, HAP/granite-guardian) plus a vLLM LLM — with conditional GPU allocation enabling the same Helm chart to target CPU-only or GPU clusters. Approach A uses a single `detectors.useGpu` toggle with OCI modelcar URIs and all detectors in one template (pinned image digests); Approach B provides per-detector `detectors.<name>.useGpu` toggles with MinIO S3 storage (`storage.key`+`storage.path`), separate template files with `helm.sh/weight` ordering, per-detector resource limits, and tag-based images — for MIG GPU slicing see `kserve-multi-model-mig-gpu-slicing.md`, for orchestrator wiring see `helm-trustyai-orchestrator-configmap-detector-wiring.md`. All detectors share the same TrustyAI HF runtime image with per-detector `threshold` values, services pinned at `minReplicas: 1`/`maxReplicas: 1` with `automountServiceAccountToken: false`, and `/dev/shm` emptyDir (`medium: Memory`, `sizeLimit: 2Gi`) on each ServingRuntime for PyTorch inference. Three identical ServingRuntimes (same image digest) must be defined separately (one per detector) rather than shared; vLLM args in `inferenceservice-llm.yaml` (e.g., `--max-model-len=20000`) silently override conflicting values from `values.yaml` (`maxModelLen: 32768`); LLM tolerations are configurable via `mainLLM.tolerations` but detector node affinity is not templated."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, vllm]
  ai_pattern: [guardrails, model-serving]
  platform: [kserve, vllm, rhoai, openshift]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "3 detector InferenceServices (gibberish, prompt injection, HAP) sharing the same TrustyAI HF runtime image with optional GPU toggle, plus 1 vLLM LLM InferenceService"
    approach: "A"
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "2 detector InferenceServices (HAP, prompt injection) with per-detector GPU toggles, MinIO S3 storage instead of OCI modelcar, separate template files per detector"
    approach: "B"
---

# KServe RawDeployment Detector Fleet with GPU Toggle

## Overview

This pattern deploys multiple KServe InferenceServices in RawDeployment mode, each serving a different safety detection model but sharing the same container runtime image. A single boolean flag (`detectors.useGpu`) conditionally adds GPU resources to all detectors at once, allowing the same chart to deploy on CPU-only or GPU-enabled clusters.

## Pattern Description

Three detector InferenceServices (gibberish, prompt injection, hate-and-profanity) are defined individually in a single template file. Each uses the `guardrails-detector-hf-runtime` model format paired with a dedicated ServingRuntime that runs the TrustyAI Hugging Face detector runtime. Despite serving different models (loaded via OCI modelcar URIs), all three ServingRuntimes use the identical container image. A separate InferenceService deploys the main LLM (Llama 3.2 3B Instruct) with vLLM, which always requires a GPU.

## Implementation

### Detector InferenceServices with Conditional GPU

All three detectors follow the same structure. GPU resources are conditionally injected via a single values flag:

```yaml
# helm/templates/inferenceservice-detectors.yaml (gibberish-detector excerpt)
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  annotations:
    openshift.io/display-name: gibberish-detector
    serving.kserve.io/deploymentMode: RawDeployment
  name: gibberish-detector
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
          {{- if .Values.detectors.useGpu }}
          nvidia.com/gpu: '1'
          {{- end }}
      runtime: gibberish-detector
      storageUri: {{ .Values.detectors.gibberish.storageUri }}
```

### Shared Detector ServingRuntime

All three detectors use identical ServingRuntimes (same image, same args, same volume mounts) -- only the name and display-name differ:

```yaml
# helm/templates/servingruntime-detectors.yaml (excerpt)
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  annotations:
    opendatahub.io/template-name: guardrails-detector-huggingface-runtime
  name: gibberish-detector
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
      image: 'quay.io/modh/odh-trustyai-hf-detector-runtime-rhel9@sha256:d1c099a1...'
      name: kserve-container
      volumeMounts:
        - mountPath: /dev/shm
          name: shm
  volumes:
    - emptyDir:
        medium: Memory
        sizeLimit: 2Gi
      name: shm
```

### OCI Modelcar Storage URIs

Each detector model is loaded via an OCI modelcar URI, keeping model weights out of the container image:

```yaml
# helm/values.yaml (detector storage URIs)
detectors:
  useGpu: false
  gibberish:
    storageUri: "oci://quay.io/mmurakam/model-cars:gibberish-text-detector-v0.1.1"
    threshold: 0.35
  promptInjection:
    storageUri: "oci://quay.io/mmurakam/model-cars:deberta-v3-base-prompt-injection-v2-v0.1.0"
    threshold: 0.5
  hateAndProfanity:
    storageUri: "oci://quay.io/mmurakam/model-cars:granite-guardian-hap-38m-v0.1.0"
    threshold: 0.5
```

### Main LLM InferenceService (Always GPU)

The vLLM LLM InferenceService always requests a GPU and includes GPU tolerations:

```yaml
# helm/templates/inferenceservice-llm.yaml (excerpt)
spec:
  predictor:
    model:
      args:
        - '--dtype=half'
        - '--max-model-len=20000'
        - '--gpu-memory-utilization=0.95'
        - '--enable-chunked-prefill'
        - '--enable-auto-tool-choice'
        - '--tool-call-parser=llama3_json'
        - '--chat-template=/app/data/template/tool_chat_template_llama3.2_json.jinja'
      modelFormat:
        name: vLLM
      resources:
        limits:
          nvidia.com/gpu: '1'
        requests:
          nvidia.com/gpu: '1'
      runtime: {{ .Values.mainLLM.name }}
      storageUri: {{ .Values.mainLLM.storageUri }}
```

## Configuration

- **Key settings:** `detectors.useGpu` (default `false`) controls GPU allocation for all 3 detectors; each detector has an individual `storageUri` and `threshold`; LLM tolerations are configurable via `mainLLM.tolerations`
- **Defaults:** Detectors run on CPU with 1-2 CPU cores and 4-8Gi memory; LLM runs on GPU with 4-8 CPU cores and 8-10Gi memory; all services pinned at `minReplicas: 1`, `maxReplicas: 1`
- **Dependencies:** KServe with RawDeployment mode support; TrustyAI HF detector runtime image available at `quay.io/modh/odh-trustyai-hf-detector-runtime-rhel9`; OCI modelcar images accessible from the cluster

## Gotchas

- All three detector ServingRuntimes use the exact same container image digest (`quay.io/modh/odh-trustyai-hf-detector-runtime-rhel9@sha256:d1c099a1...`) but are defined as three separate ServingRuntime resources rather than sharing one -- each InferenceService references its own `runtime:` by name (see `helm/templates/servingruntime-detectors.yaml`)
- The LLM InferenceService has hardcoded vLLM args (`--enable-chunked-prefill`, `--enable-auto-tool-choice`, etc.) in `inferenceservice-llm.yaml` while the corresponding ServingRuntime in `servingruntime-llm.yaml` also conditionally adds the same args from values -- the InferenceService-level args take precedence at runtime
- The LLM's `--max-model-len=20000` in the InferenceService does not match `maxModelLen: 32768` in values.yaml because values.yaml drives the ServingRuntime args, not the InferenceService args (see `helm/templates/inferenceservice-llm.yaml` vs `helm/values.yaml`)
- The `/dev/shm` emptyDir with `medium: Memory` and `sizeLimit: 2Gi` is defined on each ServingRuntime to provide shared memory for model inference -- this is a common KServe pattern for PyTorch-based models (see `helm/templates/servingruntime-detectors.yaml`)
- All services use `serving.kserve.io/deploymentMode: RawDeployment` which bypasses Knative/serverless scaling and deploys as standard Kubernetes Deployments (see annotations on all InferenceService resources)

---

## Approach B: Per-Detector GPU Toggles with MinIO S3 Storage (from lemonade-stand-assistant)

### When to Use

When each detector needs independent GPU control (one on GPU, another on CPU) and detector model weights are served from MinIO via S3 data connection rather than OCI modelcar URIs.

### Differences from Approach A

- Per-detector GPU toggles (`detectors.hap.useGpu`, `detectors.promptInjection.useGpu`) instead of a single global `detectors.useGpu`
- Per-detector resource configuration in values.yaml (separate CPU/memory for each detector) instead of shared defaults
- Models loaded from MinIO S3 storage (`storage.key` + `storage.path`) instead of OCI modelcar URIs (`storageUri: oci://...`)
- Each detector is in a separate template file (`ibm-hap-detector.yaml`, `prompt-injection-detector.yaml`) instead of combined
- Each template contains both ServingRuntime and InferenceService (2 resources per file) instead of separate runtime and service files
- Only 2 detectors (HAP and prompt injection) instead of 3 (no gibberish detector)
- LLM InferenceService is conditionally deployed via `{{ if not .Values.model }}`
- Uses `helm.sh/weight` annotations for resource ordering (weight `0` for ServingRuntimes, `1` for InferenceServices)

### Per-Detector GPU Toggle

```yaml
# chart/templates/ibm-hap-detector.yaml (InferenceService excerpt)
spec:
  predictor:
    model:
      resources:
        limits:
          cpu: {{ .Values.detectors.hap.resources.limits.cpu }}
          memory: {{ .Values.detectors.hap.resources.limits.memory }}
          {{- if .Values.detectors.hap.useGpu }}
          nvidia.com/gpu: '1'
          {{- end }}
        requests:
          cpu: {{ .Values.detectors.hap.resources.requests.cpu }}
          memory: {{ .Values.detectors.hap.resources.requests.memory }}
          {{- if .Values.detectors.hap.useGpu }}
          nvidia.com/gpu: '1'
          {{- end }}
      runtime: guardrails-detector-runtime-hap
      storage:
        key: minio-data-connection-detector-models
        path: granite-guardian-hap-125m
    {{- if .Values.detectors.hap.useGpu }}
    tolerations:
      - effect: NoSchedule
        key: nvidia.com/gpu
        operator: Exists
    {{- end }}
```

### Per-Detector Values Structure

```yaml
# chart/values.yaml
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

### MinIO S3 Storage Reference

Detectors reference models via an S3 data connection Secret and path, not OCI URIs:

```yaml
# chart/templates/ibm-hap-detector.yaml
storage:
  key: minio-data-connection-detector-models
  path: granite-guardian-hap-125m

# chart/templates/prompt-injection-detector.yaml
storage:
  key: minio-data-connection-detector-models
  path: deberta-v3-base-prompt-injection-v2
```

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| GPU control | Single `detectors.useGpu` for all detectors | Per-detector `hap.useGpu`, `promptInjection.useGpu` |
| Model storage | OCI modelcar URIs (`storageUri: oci://...`) | MinIO S3 (`storage.key` + `storage.path`) |
| Resource config | Shared defaults across detectors | Per-detector CPU/memory in values.yaml |
| Template layout | All detectors in one template file | One template file per detector |
| Number of detectors | 3 (gibberish, prompt injection, HAP) | 2 (HAP, prompt injection) |
| Runtime images | Pinned digest (`@sha256:...`) | Tag-based (`quay.io/trustyai/guardrails-detector-huggingface-runtime:latest`) |
| Resource ordering | No weight annotations | `helm.sh/weight` for phased deployment |

## Related Patterns

- `helm-trustyai-orchestrator-configmap-detector-wiring.md` -- the orchestrator that routes traffic through these detectors
- `kserve-multi-model-mig-gpu-slicing.md` -- alternative pattern using a range loop and MIG GPU slicing for multi-model KServe deployment
- `helm-minio-initcontainer-hf-model-download.md` -- the MinIO storage that provides model weights for Approach B
- `helm-conditional-llm-bypass-external-model.md` -- the conditional LLM deployment used alongside Approach B
