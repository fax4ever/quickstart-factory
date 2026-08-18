---
name: guardrails-orchestrator
description: TrustyAI GuardrailsOrchestrator proxy coordinating safety detectors in front of an LLM on RHOAI
summary: "The GuardrailsOrchestrator CRD (trustyai.opendatahub.io/v1alpha1) proxies LLM traffic through configurable safety detectors -- regex PII, HAP, prompt-injection, gibberish/lingua -- on RHOAI, with Approach A using gateway routing via dual ConfigMaps and route paths (/all/, /passthrough/) on port 8090, and Approach B using direct orchestrator access on port 8032 via /api/v2/chat/completions-detection with per-request detector selection in the JSON payload. Use Approach A (enableGuardrailsGateway: true) when multiple apps need route-selectable safety levels with OCI ModelCar storage and 3-container orchestrator pods; use Approach B when a single app needs simpler deployment with MinIO model storage (storage.key), client-side regex pre-filtering, a separate chunker service on port 8085, and lingua language detection instead of gibberish (2-container pod). Critical config: enableBuiltInDetectors: true runs the regex sidecar at 127.0.0.1:8080 inside the orchestrator pod while ML detectors deploy as KServe InferenceServices in RawDeployment mode with per-detector thresholds (gibberish 0.35, HAP/prompt-injection 0.5) in the NLP ConfigMap; detectors.useGpu defaults false and needs 3 extra GPUs when true. Gotchas: gateway port 8090 is implicit (not in values.yaml or CRD spec), gateway/regex images are SHA-pinned in a ConfigMap not Helm values, prompt-injection is input-only, DeBERTa prompt-injection detector needs 4 CPU/16Gi on CPU mode, and Approach B requires HTTPS for internal traffic (TLS verification disabled) and may produce duplicate SSE chunks needing client-side dedup."
metadata:
  type: component
tags:
  tech_stack: [trustyai, kserve, vllm, helm, fastapi, minio]
  ai_pattern: [guardrails, model-serving]
  platform: [rhoai, openshift, kserve]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "TrustyAI GuardrailsOrchestrator CRD with gateway routing, regex/HAP/prompt-injection/gibberish detectors"
    approach: "A"
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "TrustyAI GuardrailsOrchestrator CRD without gateway, direct orchestrator access, MinIO model storage, lingua language detector, client-side regex pre-filtering"
    approach: "B"
---

# Guardrails Orchestrator

## Overview

The GuardrailsOrchestrator is a TrustyAI custom resource that acts as a proxy between clients and an LLM, routing requests through a configurable chain of safety detectors before and after the model generates a response. It uses a gateway pattern to apply multiple detector policies (PII regex, hate/profanity, prompt injection, gibberish) declaratively via ConfigMaps, and is deployed as a Kubernetes-native CRD (`trustyai.opendatahub.io/v1alpha1`) on RHOAI.

## Tech Stack & Dependencies

- **Runtime:** TrustyAI orchestrator (fms-orchestr8) with built-in detector sidecar support
- **Container images:** Gateway image `quay.io/repository/trustyai/vllm-orchestrator-gateway`, regex detector image `quay.io/repository/trustyai/regex-detector` (pinned by SHA in ConfigMap `gorch-regex-gateway-image-config`)
- **Key dependencies:** KServe InferenceServices for detector models, vLLM ServingRuntime for main LLM, OpenShift Service Mesh
- **Helm chart:** Standalone Helm chart (not a subchart); `guardrailing-llms` v1.0.0, `apiVersion: v2`

## Key Patterns

### GuardrailsOrchestrator CRD

The orchestrator is deployed via a TrustyAI-specific CRD rather than a standard Deployment or StatefulSet. The `enableBuiltInDetectors` flag activates a regex detector sidecar running on localhost, while `enableGuardrailsGateway` adds a gateway proxy that applies detector chains per route.

```yaml
apiVersion: trustyai.opendatahub.io/v1alpha1
kind: GuardrailsOrchestrator
metadata:
  name: gorch-sample
spec:
  enableBuiltInDetectors: true
  enableGuardrailsGateway: true
  guardrailsGatewayConfig: fms-orchestr8-config-gateway
  orchestratorConfig: fms-orchestr8-config-nlp
  otelExporter: {}
  replicas: {{ .Values.orchestrator.replicas }}
```

### Dual ConfigMap Configuration

Two ConfigMaps drive the orchestrator behavior. The NLP config (`fms-orchestr8-config-nlp`) maps each detector to its KServe InferenceService hostname and threshold. The gateway config (`fms-orchestr8-config-gateway`) defines which detectors apply on input vs output and declares named routes.

```yaml
# NLP config: detector-to-service wiring
detectors:
  regex:
    type: text_contents
    service:
      hostname: "127.0.0.1"    # built-in sidecar
      port: 8080
  hap:
    type: text_contents
    service:
      hostname: ibm-hate-and-profanity-detector-predictor.<ns>.svc.cluster.local
      port: 8000
    default_threshold: 0.5
```

```yaml
# Gateway config: route-level detector policies
detectors:
  - name: regex
    input: true
    output: true
    detector_params:
      regex:
        - email
        - ssn
  - name: prompt_injection
    input: true
    output: false
routes:
  - name: all
    detectors: [regex, hap, prompt_injection, gibberish]
  - name: passthrough
    detectors:
```

### Gateway Route-Based Access

Clients call the orchestrator gateway using route-named URL paths. The `/all/` route applies every configured detector; the `/passthrough/` route skips all detectors. This pattern allows different applications to choose their own safety level by selecting different routes.

```python
# From healthcare-guardrails.ipynb
guardrails_gateway_endpoint = f'{guardrails_orchestrator_route}/all/v1/chat/completions'
response = post(guardrails_gateway_endpoint, json=payload)
```

The gateway service endpoint is `http://gorch-sample-service.<namespace>.svc.cluster.local:8090`.

### Detector InferenceServices with Shared Runtime

All three ML-based detectors (gibberish, prompt-injection, hate-and-profanity) share the same container image and ServingRuntime template (`guardrails-detector-hf-runtime`) but are deployed as separate KServe InferenceServices. Each uses `RawDeployment` mode with `automountServiceAccountToken: false`.

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
  labels:
    networking.kserve.io/visibility: exposed
    opendatahub.io/dashboard: 'true'
spec:
  predictor:
    automountServiceAccountToken: false
    model:
      modelFormat:
        name: guardrails-detector-hf-runtime
      runtime: gibberish-detector
      storageUri: oci://quay.io/mmurakam/model-cars:gibberish-text-detector-v0.1.1
```

### OCI ModelCar Storage

All models (LLM and detectors) use OCI container registry URIs as their `storageUri` rather than S3 or PVC-based storage. This "ModelCar" pattern bundles model weights into container images.

```yaml
# Detector models
storageUri: "oci://quay.io/mmurakam/model-cars:gibberish-text-detector-v0.1.1"
storageUri: "oci://quay.io/mmurakam/model-cars:deberta-v3-base-prompt-injection-v2-v0.1.0"
storageUri: "oci://quay.io/mmurakam/model-cars:granite-guardian-hap-38m-v0.1.0"

# Main LLM
storageUri: "oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct"
```

## Configuration

- **Environment variables:**
  - `MODEL_DIR=/mnt/models` -- detector ServingRuntime model path
  - `HF_HOME=/tmp/hf_home` -- HuggingFace cache directory (both detectors and LLM)
- **Config files:**
  - `fms-orchestr8-config-nlp` ConfigMap -- detector service hostnames, ports, thresholds, chunker settings
  - `fms-orchestr8-config-gateway` ConfigMap -- detector input/output flags, regex patterns (email, ssn), named routes
  - `gorch-regex-gateway-image-config` ConfigMap -- pinned SHA digests for gateway and regex detector images
- **Helm values:**
  - `orchestrator.replicas` (default: `1`) -- number of orchestrator pod replicas
  - `orchestrator.port` (default: `8032`) -- orchestrator internal port (gateway listens on `8090`)
  - `detectors.useGpu` (default: `false`) -- toggle GPU requests on detector InferenceServices
  - `detectors.<name>.threshold` -- per-detector confidence threshold (gibberish: `0.35`, prompt-injection: `0.5`, HAP: `0.5`)
  - `detectors.<name>.storageUri` -- OCI model URI per detector
  - `mainLLM.enableAutoToolChoice` / `mainLLM.toolCallParser` -- vLLM tool-calling config for the backend LLM

## Known Gotchas

- **Regex detector runs as a built-in sidecar at 127.0.0.1:** Unlike the ML detectors which are separate InferenceServices, the regex detector is a built-in sidecar within the orchestrator pod itself (enabled by `enableBuiltInDetectors: true`). Its NLP config uses `hostname: "127.0.0.1"` with port `8080`, while ML detectors use cluster-internal service DNS names on port `8000`. This asymmetry is easy to overlook when debugging detector connectivity.
- **Detectors default to CPU-only:** The `detectors.useGpu` flag was added in a later fix (commit `8bbfc16`) and defaults to `false`. Without it, all three detector InferenceServices run on CPU only. Setting `useGpu: true` adds `nvidia.com/gpu: '1'` to both requests and limits for every detector, which requires 3 additional GPUs beyond the 1 GPU the LLM needs.
- **Gateway and orchestrator images are pinned by SHA in a ConfigMap, not in values.yaml:** The gateway and regex detector container images are specified in the `gorch-regex-gateway-image-config` ConfigMap rather than in Helm values, making them harder to override at install time without patching the ConfigMap template.
- **Gateway port 8090 is implicit:** The orchestrator pod exposes the gateway on port `8090` (as used in the notebook: `gorch-sample-service.<ns>.svc.cluster.local:8090`), but this port is not explicitly set in the Helm values or CRD spec. The internal orchestrator port `8032` (from `orchestrator.port`) is a different port used for the NLP backend communication.
- **Prompt injection detector is input-only:** In the gateway config, `prompt_injection` has `input: true` and `output: false`, meaning it only scans user prompts, not model responses. The other detectors (regex, hap, gibberish) scan both input and output.
- **Three containers per orchestrator pod:** The `gorch-sample` pod runs with `3/3` containers (orchestrator, gateway, regex-detector sidecar), as shown in the README expected output. Health checks and debugging need to account for all three containers.

## Testing Notes

- Verify all pods reach Running state; the orchestrator pod should show `3/3` ready containers (orchestrator + gateway + regex sidecar)
- The workbench notebook (`docs/healthcare-guardrails.ipynb`) provides four built-in test cases: normal query (should pass), SSN PII detection (regex blocks), profanity detection (HAP blocks), and prompt injection (injection detector blocks)
- When a detector blocks a request, `choices` is empty in the response and `warning`/`detections` fields contain which detector triggered and why
- The `/passthrough/` route can be used for debugging to bypass all detectors and confirm the LLM itself is responding correctly
- Check detector InferenceService logs individually since each is a separate pod; the orchestrator logs show routing decisions but not detector internals

## Related Patterns

- KServe InferenceService and ServingRuntime patterns (see `model-serving.md`)
- vLLM model serving with tool calling (see `llm-service.md`)

---

## Approach B: Gateway-Less Direct Orchestrator (from lemonade-stand-assistant)

### When to Use

Use when you want the simplest possible orchestrator deployment without gateway routing. Clients connect directly to the orchestrator service on port 8032 via its `/api/v2/chat/completions-detection` endpoint. Suited for single-app deployments where route-based detector selection is unnecessary and where detector models are stored in MinIO rather than OCI ModelCar registries.

### Differences from Approach A

- **No gateway:** `enableGuardrailsGateway: false` -- the orchestrator pod runs without a gateway sidecar, reducing from 3 containers to 2 (orchestrator + regex sidecar)
- **Single ConfigMap:** Only the NLP config (`fms-orchestr8-config-nlp`) is needed; no gateway route config
- **Direct port 8032 access:** Clients connect to `guardrails-orchestrator-service:8032` instead of the gateway on port 8090
- **MinIO model storage:** Detector models use `storage.key` referencing a MinIO data connection instead of OCI `storageUri`
- **Different detector set:** Uses lingua (language detection) instead of gibberish; four detectors total: regex, HAP, prompt-injection, lingua
- **Client-side pre-filtering:** The FastAPI app runs local regex checks before sending to the orchestrator, reducing orchestrator load
- **Per-request detector selection:** The app specifies which detectors to use per request in the JSON payload rather than relying on gateway routes

### GuardrailsOrchestrator CRD (No Gateway)

The orchestrator CRD disables the gateway and uses only the NLP config ConfigMap. A finalizer is added for cleanup.

```yaml
apiVersion: trustyai.opendatahub.io/v1alpha1
kind: GuardrailsOrchestrator
metadata:
  name: guardrails-orchestrator
  finalizers:
    - trustyai.opendatahub.io/gorch-finalizer
spec:
  enableBuiltInDetectors: true
  enableGuardrailsGateway: false
  orchestratorConfig: fms-orchestr8-config-nlp
  otelExporter:
    otlpProtocol: grpc
  replicas: 1
```

### Single NLP ConfigMap with Chunker

The NLP config wires detectors plus a sentence chunker service. All detectors reference `chunker_id: sentence` for text splitting. The regex detector still uses the built-in sidecar at `127.0.0.1:8080`.

```yaml
# fms-orchestr8-config-nlp ConfigMap
chunkers:
  sentence:
    type: sentence
    service:
      hostname: chunker-service
      port: 8085
detectors:
  regex_competitor:
    type: text_contents
    service:
      hostname: "127.0.0.1"
      port: 8080
    chunker_id: sentence
    default_threshold: 0.5
  hap:
    type: text_contents
    service:
      hostname: guardrails-detector-ibm-hap-predictor
      port: 8000
    chunker_id: sentence
    default_threshold: 0.5
```

### MinIO-Based Detector Model Storage

Instead of OCI ModelCar URIs, detector InferenceServices reference models stored in MinIO via a data connection secret key. The `storage.key` field points to a pre-configured MinIO data connection.

```yaml
spec:
  predictor:
    model:
      modelFormat:
        name: guardrails-detector-huggingface
      runtime: guardrails-detector-runtime-hap
      storage:
        key: minio-data-connection-detector-models
        path: granite-guardian-hap-125m
```

### Client-Side Regex Pre-Filtering

The FastAPI app runs regex patterns locally before forwarding to the orchestrator. This catches obvious violations without consuming orchestrator resources. The same regex patterns are still sent for output detection.

```python
# From lemonade-stand-app/app_fastapi.py
ORCHESTRATOR_HOST = os.getenv("GUARDRAILS_ORCHESTRATOR_SERVICE_SERVICE_HOST", "localhost")
ORCHESTRATOR_PORT = os.getenv("GUARDRAILS_ORCHESTRATOR_SERVICE_SERVICE_PORT", "8080")

# Direct orchestrator endpoint (no gateway routes)
API_URL = f"https://{ORCHESTRATOR_HOST}:{ORCHESTRATOR_PORT}/api/v2/chat/completions-detection"
```

The app specifies detectors per-request in the payload rather than relying on gateway routes:

```python
# From lemonade-stand-app/app_fastapi.py
payload = {
    "model": VLLM_MODEL,
    "messages": [...],
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
}
```

### Separate Chunker Service

A standalone sentence chunker runs as its own Deployment on port 8085, unlike Approach A where chunking configuration is embedded in the NLP config without a separate service.

```yaml
# chunker.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: chunker-service
spec:
  containers:
  - name: chunker
    image: quay.io/rh-ee-mmisiura/chunkers:v2.0
    ports:
    - containerPort: 8085
      name: grpc
      protocol: TCP
```

### Lingua Language Detection Detector

Instead of a gibberish detector, this approach uses a lingua-based language detection service that enforces English-only responses. Deployed as a plain Deployment (not KServe InferenceService).

```yaml
# lingua.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: lingua-detector
spec:
  containers:
  - name: lingua-detector
    image: 'quay.io/ckavili/lingua-language-detector:0.0.25'
    ports:
    - containerPort: 8080
```

### Detector Resource Configurability via Helm Values

Detector resource requests/limits and GPU toggle are managed through Helm values, making them easy to override at install time.

```yaml
# values.yaml
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
```

### Configuration

- **Environment variables:**
  - `GUARDRAILS_ORCHESTRATOR_SERVICE_SERVICE_HOST` -- orchestrator hostname (used by the app to connect)
  - `GUARDRAILS_ORCHESTRATOR_SERVICE_SERVICE_PORT` -- orchestrator port, default `8032`
  - `MODEL_DIR=/mnt/models` -- detector ServingRuntime model path
  - `HF_HOME=/tmp/hf_home` -- HuggingFace cache directory
- **Config files:**
  - `fms-orchestr8-config-nlp` ConfigMap -- detector service hostnames, ports, thresholds, chunker settings
  - `guardrails-orchestrator-config` ConfigMap -- auxiliary image references for regex detector and vLLM gateway
- **Helm values:**
  - `detectors.hap.useGpu` / `detectors.promptInjection.useGpu` -- toggle GPU requests per detector
  - `detectors.hap.resources` / `detectors.promptInjection.resources` -- CPU/memory limits per detector
  - `model.endpoint` -- LLM endpoint hostname in the NLP config (default `llama-32-predictor`)
  - `model.port` -- LLM endpoint port (default `8080`)

### Known Gotchas

- **HTTPS required for internal communication:** The app always uses HTTPS to talk to the orchestrator (`https://{host}:{port}`), even for internal cluster traffic. It disables TLS verification for self-signed certificates. This is specific to port 8032 direct access, unlike Approach A's gateway on 8090.
- **Duplicate SSE chunks from orchestrator:** The app includes deduplication logic (`content_stripped and full_response.rstrip().endswith(content_stripped)`) because the orchestrator sometimes sends overlapping chunks in the SSE stream. This is noted in a code comment: "upstream orchestrator sometimes sends overlapping chunks."
- **Prompt injection detector needs 4 CPU / 16Gi memory on CPU:** The DeBERTa-v3-based prompt injection detector is significantly more resource-hungry than the HAP detector (4 CPU/16Gi vs 1 CPU/4Gi in requests). This asymmetry is not obvious and can cause scheduling failures on constrained clusters.
- **Auxiliary images in separate ConfigMap:** The regex detector and vLLM gateway images are specified in `guardrails-orchestrator-config` ConfigMap rather than in Helm values, similar to Approach A's SHA-pinning pattern.

### Testing Notes

- The orchestrator pod should show `2/2` ready containers (orchestrator + regex sidecar) since there is no gateway container
- Test by sending a message containing fruit names (other than lemon) -- the local regex pre-filter should block it before reaching the orchestrator
- The app exposes `/metrics` in Prometheus format for guardrails counters (detections by type, local regex blocks, total requests)
- Use the `/health` endpoint on the app (port 8080) to verify readiness

---

## Choosing Between Approaches

| Criteria | Approach A (Gateway) | Approach B (Direct) |
|----------|---------------------|---------------------|
| Gateway routing | Yes -- multiple routes (`/all/`, `/passthrough/`) for different safety levels | No -- single endpoint, detectors specified per-request in payload |
| Orchestrator pod containers | 3 (orchestrator + gateway + regex sidecar) | 2 (orchestrator + regex sidecar) |
| Client connection | Gateway port 8090 with route paths | Direct port 8032, `/api/v2/chat/completions-detection` |
| Model storage | OCI ModelCar (`storageUri: oci://...`) | MinIO data connection (`storage.key`) |
| Detector set | regex, HAP, prompt-injection, gibberish | regex, HAP, prompt-injection, lingua (language detection) |
| ConfigMaps needed | 2 (NLP + gateway) | 1 (NLP only) |
| Client-side filtering | None -- all filtering in orchestrator | Local regex pre-filter in app before orchestrator |
| Chunker service | Configured in NLP config only | Separate chunker Deployment + Service |
| Multi-app support | Yes -- different apps use different routes | No -- single app talks directly to orchestrator |
| Complexity | Higher (gateway config, routes, 3 containers) | Lower (single ConfigMap, 2 containers) |
