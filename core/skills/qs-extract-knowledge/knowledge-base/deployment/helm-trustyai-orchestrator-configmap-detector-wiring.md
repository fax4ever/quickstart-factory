---
name: helm-trustyai-orchestrator-configmap-detector-wiring
description: TrustyAI GuardrailsOrchestrator CRD with ConfigMap-based detector routing and threshold configuration
summary: "Deploys TrustyAI GuardrailsOrchestrator CRD (trustyai.opendatahub.io/v1alpha1) as an LLM proxy with two ConfigMap-based detector-wiring approaches: Approach A (3 ConfigMaps -- NLP with FQDN hostnames/whole_doc_chunker/chat_generation LLM key/thresholds gibberish 0.35 and HAP/promptInjection 0.5, gateway with per-detector input/output scanning and all/passthrough route profiles on port 8032, image with pinned digests; enableGuardrailsGateway: true) vs Approach B (1 NLP ConfigMap with short hostnames/sentence chunker on port 8085/openai LLM key with dynamic endpoint defaulting/Lingua language detection at 0.88 replacing gibberish/regex_competitor patterns; enableGuardrailsGateway: false, OTel gRPC enabled, auxiliary image ConfigMap with :latest tags). Choose A when you need the vLLM-compatible gateway with client-selectable route profiles (\"all\" for full detector coverage, \"passthrough\" to bypass all guardrails) and whole-document scanning; choose B for direct orchestrator access with sentence-level chunking, language detection instead of gibberish detection, and flexible external-model endpoint override. Both set enableBuiltInDetectors: true (regex sidecar on 127.0.0.1:8080) alongside external KServe detectors (HAP, prompt injection) that must share the orchestrator's namespace for DNS resolution; the NLP ConfigMap wires each detector to its KServe predictor endpoint with configurable thresholds and replicas in values.yaml. Gotchas: prompt_injection scans input only (output: false) in both approaches, detector hostnames follow KServe's <inferenceservice-name>-predictor convention requiring manual update if names change, Approach A's passthrough route bypasses all guardrails, and Approach B's short hostnames (no namespace suffix) only resolve when detectors are co-located in the same namespace."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [guardrails]
  platform: [kserve, rhoai, openshift]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "GuardrailsOrchestrator CRD with 3 ConfigMaps wiring 4 detectors (regex, HAP, prompt injection, gibberish) plus gateway routes"
    approach: "A"
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "GuardrailsOrchestrator CRD with 1 ConfigMap wiring 4 detectors (regex, HAP, prompt injection, lingua) -- no gateway, sentence chunker, dynamic LLM endpoint"
    approach: "B"
---

# TrustyAI GuardrailsOrchestrator with ConfigMap-Based Detector Wiring

## Overview

This pattern deploys the TrustyAI GuardrailsOrchestrator using its custom resource definition (`trustyai.opendatahub.io/v1alpha1`) and configures detector routing through separate ConfigMaps. The orchestrator acts as a proxy between clients and the LLM, routing requests through multiple safety detectors before and after LLM generation.

## Pattern Description

The deployment uses three ConfigMaps to configure the orchestrator: one for the NLP service mesh (detector hostnames, ports, thresholds), one for the gateway routing rules (which detectors apply to input vs output, named routes), and one for container image references (gateway and regex detector images). The `GuardrailsOrchestrator` custom resource references these ConfigMaps by name and enables built-in detectors (regex) alongside external KServe-hosted detectors.

## Implementation

### GuardrailsOrchestrator CRD

The CRD is minimal -- it delegates all configuration to named ConfigMaps:

```yaml
# helm/templates/guardrails-orchestrator.yaml
apiVersion: trustyai.opendatahub.io/v1alpha1
kind: GuardrailsOrchestrator
metadata:
  name: gorch-sample
  namespace: {{ .Release.Namespace }}
spec:
  enableBuiltInDetectors: true
  enableGuardrailsGateway: true
  guardrailsGatewayConfig: fms-orchestr8-config-gateway
  orchestratorConfig: fms-orchestr8-config-nlp
  otelExporter: {}
  replicas: {{ .Values.orchestrator.replicas }}
```

### NLP Orchestrator ConfigMap (Detector Service Mesh)

Wires each detector to its KServe predictor endpoint using in-cluster DNS. The LLM is referenced as the `chat_generation` service:

```yaml
# helm/templates/configmaps.yaml (fms-orchestr8-config-nlp)
data:
  config.yaml: |
    chat_generation:
      service:
        hostname: {{ .Values.mainLLM.name }}-predictor.{{ .Release.Namespace }}.svc.cluster.local
        port: {{ .Values.mainLLM.port }}
    detectors:
      regex:
        type: text_contents
        service:
            hostname: "127.0.0.1"
            port: {{ .Values.detectors.regex.port }}
        chunker_id: whole_doc_chunker
        default_threshold: 0.5
      hap:
        type: text_contents
        service:
          hostname: ibm-hate-and-profanity-detector-predictor.{{ .Release.Namespace }}.svc.cluster.local
          port: {{ .Values.detectors.hateAndProfanity.port }}
        chunker_id: whole_doc_chunker
        default_threshold: {{ .Values.detectors.hateAndProfanity.threshold }}
```

### Gateway ConfigMap (Routing Rules)

Defines which detectors apply to input vs output, and named routes for selective detector application:

```yaml
# helm/templates/configmaps.yaml (fms-orchestr8-config-gateway)
data:
  config.yaml: |
    orchestrator:
      host: "localhost"
      port: {{ .Values.orchestrator.port }}
    detectors:
      - name: regex
        input: true
        output: true
        detector_params:
          regex:
            - email
            - ssn
      - name: hap
        input: true
        output: true
        detector_params: {}
      - name: prompt_injection
        input: true
        output: false
        detector_params: {}
      - name: gibberish
        input: true
        output: true
        detector_params: {}
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

### Image Reference ConfigMap

Pins container image digests for the gateway and built-in regex detector:

```yaml
# helm/templates/configmaps.yaml (gorch-regex-gateway-image-config)
data:
  GatewayImage: 'quay.io/repository/trustyai/vllm-orchestrator-gateway@sha256:c511b386...'
  regexDetectorImage: 'quay.io/repository/trustyai/regex-detector@sha256:8c9ee944...'
```

## Configuration

- **Key settings:** Detector thresholds are configurable in `values.yaml` per detector (`detectors.gibberish.threshold: 0.35`, `detectors.promptInjection.threshold: 0.5`, `detectors.hateAndProfanity.threshold: 0.5`); orchestrator port defaults to `8032`; orchestrator replicas default to `1`
- **Defaults:** `enableBuiltInDetectors: true` enables the regex detector as a sidecar on localhost; `enableGuardrailsGateway: true` enables the vLLM-compatible gateway proxy; `otelExporter: {}` disables OpenTelemetry export
- **Dependencies:** Requires TrustyAI operator installed on the cluster (provides the `trustyai.opendatahub.io/v1alpha1` CRD); all detector InferenceServices must be deployed in the same namespace for in-cluster DNS resolution

## Gotchas

- The regex detector runs as a built-in sidecar on `127.0.0.1:8080` (same pod as the orchestrator) while all other detectors are external KServe services reached via cluster DNS -- this split is configured in the NLP ConfigMap where `regex.service.hostname` is `"127.0.0.1"` while others use `<name>-predictor.{{ .Release.Namespace }}.svc.cluster.local` (see `helm/templates/configmaps.yaml`)
- The `prompt_injection` detector has `output: false` in the gateway config, meaning it only scans user input, not LLM responses -- all other detectors scan both directions (see `helm/templates/configmaps.yaml` fms-orchestr8-config-gateway)
- Detector hostnames in the NLP ConfigMap use the KServe predictor naming convention `<inferenceservice-name>-predictor`, which is automatically created by KServe -- if the InferenceService names change, these hostnames must be updated manually (see `helm/templates/configmaps.yaml` fms-orchestr8-config-nlp)
- The `routes` section defines named route profiles (`all` and `passthrough`) that clients can select at request time -- `passthrough` has no detectors, bypassing all guardrails (see `helm/templates/configmaps.yaml` fms-orchestr8-config-gateway)

---

## Approach B: Simplified Orchestrator with Sentence Chunker and No Gateway (from lemonade-stand-assistant)

### When to Use

When deploying the TrustyAI orchestrator without the vLLM-compatible gateway (direct orchestrator access), with a sentence-level text chunker service and a language detection detector (Lingua) instead of a gibberish detector.

### Differences from Approach A

- Uses only 1 ConfigMap (NLP config) instead of 3 -- no gateway ConfigMap and no image config ConfigMap
- Sets `enableGuardrailsGateway: false` (no gateway proxy) vs Approach A's `enableGuardrailsGateway: true`
- Uses a separate `chunker-service` (sentence chunker on port 8085 via gRPC) referenced as `chunker_id: sentence` instead of `whole_doc_chunker`
- Includes a `language_detection` detector via Lingua (custom container, not KServe) instead of a gibberish detector
- LLM endpoint is dynamic via `{{ .Values.model.endpoint | default "llama-32-predictor" }}` allowing external MaaS bypass
- Detector hostnames use short names (e.g., `guardrails-detector-ibm-hap-predictor`) instead of FQDN with namespace
- References the LLM under the `openai` key (not `chat_generation`)

### NLP ConfigMap

```yaml
# chart/templates/fms-orchestr8-config-nlp.yaml
data:
  config.yaml: |
    chunkers:
      sentence:
        type: sentence
        service:
            hostname: chunker-service
            port: 8085
    openai:
      service:
        hostname: {{ .Values.model.endpoint | default "llama-32-predictor" }}
        port: {{ .Values.model.port | default "8080" }}
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
      prompt_injection:
        type: text_contents
        service:
          hostname: prompt-injection-detector-predictor
          port: 8000
        chunker_id: sentence
        default_threshold: 0.5
      language_detection:
        type: text_contents
        service:
          hostname: lingua-detector
          port: 8080
        chunker_id: sentence
        default_threshold: 0.88
```

### GuardrailsOrchestrator CRD

```yaml
# chart/templates/guardrails-orchestrator.yaml
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

### Auxiliary Image ConfigMap

Instead of an image config for gateway and regex detector, uses a simpler ConfigMap for just two images:

```yaml
# chart/templates/configmap_auxiliary_images.yaml
data:
  regexDetectorImage: 'quay.io/trustyai/regex-detector:latest'
  vllmGatewayImage: 'quay.io/trustyai/vllm-orchestrator-gateway:latest'
```

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Gateway | Enabled (`enableGuardrailsGateway: true`) with named routes | Disabled (`enableGuardrailsGateway: false`) |
| ConfigMaps | 3 (NLP, gateway, image) | 1 (NLP) + 1 auxiliary image |
| Chunker | `whole_doc_chunker` (built-in) | `sentence` via external `chunker-service` on port 8085 |
| Language detection | Not present | Lingua detector at threshold 0.88 |
| Gibberish detection | Present | Not present |
| LLM key | `chat_generation` | `openai` |
| LLM endpoint | Templated FQDN | Dynamic with `| default` for external model bypass |
| Detector hostnames | FQDN with namespace (`<name>-predictor.{{ .Release.Namespace }}.svc.cluster.local`) | Short names (`<name>-predictor`) |
| Route profiles | `all` and `passthrough` routes | No routes (no gateway) |
| OTel | Disabled (`otelExporter: {}`) | Enabled (`otelExporter.otlpProtocol: grpc`) |

## Related Patterns

- `kserve-rawdeployment-detector-fleet-gpu-toggle.md` -- the detector InferenceServices that the orchestrator routes to
- `helm-flat-chart-direct-crd-templating.md` -- the chart structure containing this orchestrator deployment
- `helm-conditional-llm-bypass-external-model.md` -- the conditional LLM bypass that makes the orchestrator endpoint dynamic (Approach B)
- `helm-minio-initcontainer-hf-model-download.md` -- the model storage that feeds detector InferenceServices in Approach B
