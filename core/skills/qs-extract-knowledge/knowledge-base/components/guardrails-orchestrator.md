---
name: guardrails-orchestrator
description: TrustyAI GuardrailsOrchestrator proxy coordinating safety detectors in front of an LLM on RHOAI
summary: "The GuardrailsOrchestrator CRD (trustyai.opendatahub.io/v1alpha1) proxies LLM traffic through configurable safety detectors -- regex PII, HAP, prompt-injection, gibberish -- using dual ConfigMaps: NLP config wires each detector to its KServe InferenceService hostname/port/threshold, while gateway config declares per-route detector chains with input/output flags (prompt_injection is input-only). Use when adding declarative, route-selectable safety layers in front of a vLLM-served model on RHOAI; clients hit gateway port 8090 with route paths (/all/ applies every detector, /passthrough/ bypasses all) and detectors share a single ServingRuntime in RawDeployment mode using OCI ModelCar storageUri. Critical config: enableBuiltInDetectors: true runs the regex sidecar at 127.0.0.1:8080 inside the orchestrator pod while ML detectors are separate InferenceServices on port 8000; tune per-detector thresholds via detectors.<name>.threshold (gibberish 0.35, prompt-injection/HAP 0.5) and toggle GPU with detectors.useGpu (default false, needs 3 extra GPUs). Gotchas: orchestrator pod must show 3/3 containers (orchestrator + gateway + regex-sidecar), gateway/regex images are SHA-pinned in a ConfigMap not Helm values making overrides harder, gateway port 8090 is implicit (not in values.yaml or CRD spec), and the internal orchestrator port 8032 is unrelated to the gateway endpoint."
metadata:
  type: component
tags:
  tech_stack: [trustyai, kserve, vllm, helm]
  ai_pattern: [guardrails, model-serving]
  platform: [rhoai, openshift, kserve]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "TrustyAI GuardrailsOrchestrator CRD with gateway routing, regex/HAP/prompt-injection/gibberish detectors"
    approach: "A"
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
