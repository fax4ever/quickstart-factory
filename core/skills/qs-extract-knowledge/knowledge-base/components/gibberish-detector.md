---
name: gibberish-detector
description: "HuggingFace-based gibberish text detector deployed via KServe with TrustyAI runtime on RHOAI"
summary: "Deploys a HuggingFace text classification model as a KServe InferenceService in RawDeployment mode on RHOAI to filter nonsensical text before it reaches the main LLM, operating as one detector in a multi-layer TrustyAI GuardrailsOrchestrator pipeline alongside prompt-injection and hate/profanity detectors. Use when building a TrustyAI guardrails pipeline needing input/output gibberish filtering — each detector shares the odh-trustyai-hf-detector-runtime-rhel9 image but requires its own ServingRuntime and InferenceService differentiated by OCI modelcar storageUri (e.g., oci://quay.io/mmurakam/model-cars:gibberish-text-detector-v0.1.1). Register in the fms-orchestr8-config-nlp ConfigMap as type text_contents with whole_doc_chunker and default_threshold 0.35 (more sensitive than the 0.5 used by other detectors), and enable input/output scanning in the fms-orchestr8-config-gateway ConfigMap under the \"all\" route. The detectors.useGpu Helm value is all-or-nothing across all detectors, the ServingRuntime's 2Gi memory-backed emptyDir at /dev/shm counts against the pod's 4Gi-request/8Gi-limit memory budget, and automountServiceAccountToken is explicitly disabled restricting Kubernetes API access."
metadata:
  type: component
tags:
  tech_stack: [python, uvicorn, huggingface]
  ai_pattern: [guardrails]
  platform: [kserve, rhoai, openshift, trustyai]
  data_layer: []
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Gibberish text detector as one of multiple safety detectors behind TrustyAI GuardrailsOrchestrator"
    approach: "A"
---

# Gibberish Detector

## Overview

The gibberish detector is a HuggingFace text classification model deployed as a KServe InferenceService on RHOAI. It identifies nonsensical or random text inputs before they reach the main LLM, serving as one layer in a multi-detector guardrails pipeline coordinated by the TrustyAI GuardrailsOrchestrator. The model runs on the TrustyAI HuggingFace detector runtime and can operate on CPU or GPU.

## Tech Stack & Dependencies

- **Runtime:** Python / Uvicorn (via `odh-trustyai-hf-detector-runtime-rhel9` container image)
- **Container image:** `quay.io/modh/odh-trustyai-hf-detector-runtime-rhel9@sha256:d1c099a1913cc6d5b99bf28fd8f89d7b6486176f78f561d80248a0e90916f9ad`
- **Model artifact:** `oci://quay.io/mmurakam/model-cars:gibberish-text-detector-v0.1.1` (OCI modelcar format)
- **Key dependencies:** KServe (InferenceService + ServingRuntime), TrustyAI GuardrailsOrchestrator
- **Helm subchart:** None (standalone templates within the `guardrailing-llms` Helm chart v1.0.0)

## Key Patterns

### KServe InferenceService with RawDeployment Mode

The gibberish detector is deployed as a KServe InferenceService using `RawDeployment` mode (bypassing Knative). The model is loaded from an OCI modelcar storage URI and served via a named ServingRuntime.

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  annotations:
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
      runtime: gibberish-detector
      storageUri: oci://quay.io/mmurakam/model-cars:gibberish-text-detector-v0.1.1
```

### TrustyAI HuggingFace Detector ServingRuntime

Each detector gets its own ServingRuntime instance (even though they share the same container image and model format). The runtime uses `uvicorn` to serve a Python `app:app` ASGI application on port 8000, with a shared-memory volume for model inference.

```yaml
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
      image: 'quay.io/modh/odh-trustyai-hf-detector-runtime-rhel9@sha256:...'
  volumes:
    - emptyDir:
        medium: Memory
        sizeLimit: 2Gi
      name: shm
```

### Orchestrator Integration via ConfigMap

The gibberish detector is registered in the `fms-orchestr8-config-nlp` ConfigMap so the TrustyAI GuardrailsOrchestrator knows how to reach it. The detector is typed as `text_contents` and uses the `whole_doc_chunker` strategy.

```yaml
detectors:
  gibberish:
    type: text_contents
    service:
      hostname: gibberish-detector-predictor.{{ .Release.Namespace }}.svc.cluster.local
      port: 8000
    chunker_id: whole_doc_chunker
    default_threshold: 0.35
```

### Gateway Routing Configuration

The gateway ConfigMap (`fms-orchestr8-config-gateway`) controls which detectors run on input vs. output. The gibberish detector is enabled for both input and output scanning.

```yaml
- name: gibberish
  input: true
  output: true
  detector_params: {}
```

It is included in the `all` route alongside regex, hap, and prompt_injection detectors.

## Configuration

- **Environment variables:**
  - `MODEL_DIR=/mnt/models` -- where KServe mounts the downloaded model
  - `HF_HOME=/tmp/hf_home` -- HuggingFace cache directory (writable tmpdir)
- **Helm values:**
  - `detectors.gibberish.storageUri` -- OCI URI for the model artifact (default: `oci://quay.io/mmurakam/model-cars:gibberish-text-detector-v0.1.1`)
  - `detectors.gibberish.threshold` -- Detection sensitivity threshold (default: `0.35`)
  - `detectors.gibberish.port` -- Service port (default: `8000`)
  - `detectors.useGpu` -- When `true`, adds `nvidia.com/gpu: 1` resource requests/limits to all detectors

## Known Gotchas

- **Threshold is lower than other detectors:** The gibberish detector uses a default threshold of `0.35` compared to `0.5` for prompt injection and hate/profanity detectors, as set in `helm/values.yaml` lines 33 and 36-42. This means it is more sensitive by default.
- **Shared runtime image across all detectors:** All three HuggingFace detectors (gibberish, prompt injection, hate/profanity) use the exact same container image (`odh-trustyai-hf-detector-runtime-rhel9`) but each has its own ServingRuntime and InferenceService resource, differentiated only by the `storageUri` pointing to different model artifacts.
- **GPU toggle is all-or-nothing:** The `detectors.useGpu` Helm value applies to all detectors simultaneously -- there is no per-detector GPU toggle. When enabled, every detector requests `nvidia.com/gpu: 1` in both requests and limits.
- **Memory-backed shared memory volume:** The ServingRuntime mounts a 2Gi `emptyDir` with `medium: Memory` at `/dev/shm`, which counts against the pod memory limit. The predictor requests 4Gi memory with an 8Gi limit.
- **Service account token disabled:** `automountServiceAccountToken: false` is explicitly set on the predictor, restricting the pod from accessing the Kubernetes API.

## Testing Notes

- After deployment, verify the pod is running with 2/2 containers ready (the KServe sidecar + the detector container): `gibberish-detector-predictor-*` should show `2/2 Running`
- The detector is accessible within the cluster at `gibberish-detector-predictor.<namespace>.svc.cluster.local:8000`
- Test via the TrustyAI GuardrailsOrchestrator gateway or directly via the predictor service endpoint
- The RHOAI dashboard shows the detector under the project's deployed models (label `opendatahub.io/dashboard: 'true'`)

## Related Patterns

- The gibberish detector follows the same deployment pattern as `prompt-injection-detector` and `ibm-hate-and-profanity-detector` in the same quickstart
- Coordinated by the TrustyAI `GuardrailsOrchestrator` custom resource (`gorch-sample`)
- The main LLM (`llama-32-3b-instruct`) uses a separate vLLM-based ServingRuntime, unlike the HuggingFace detector runtime used here
