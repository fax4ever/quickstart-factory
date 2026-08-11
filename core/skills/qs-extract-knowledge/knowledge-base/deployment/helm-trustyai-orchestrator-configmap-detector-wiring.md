---
name: helm-trustyai-orchestrator-configmap-detector-wiring
description: TrustyAI GuardrailsOrchestrator CRD with ConfigMap-based detector routing and threshold configuration
summary: "Deploys TrustyAI GuardrailsOrchestrator CRD (trustyai.opendatahub.io/v1alpha1) as an LLM proxy routing requests through four safety detectors -- regex (email/ssn patterns), HAP, prompt injection, gibberish -- configured via three ConfigMaps: NLP config (detector hostnames/ports/thresholds with whole_doc_chunker wired to KServe predictor endpoints, LLM referenced as chat_generation), gateway config (per-detector input/output scanning direction and named route profiles), and image config (pinned container digests for gateway and regex detector). Use when deploying multiple TrustyAI detectors with per-detector directional scanning control and client-selectable route profiles (\"all\" for full detector coverage, \"passthrough\" to bypass all guardrails at request time) behind a vLLM-compatible gateway. The CRD sets enableBuiltInDetectors: true (regex sidecar on 127.0.0.1:8080) and enableGuardrailsGateway: true (gateway on port 8032, otelExporter disabled); the NLP ConfigMap wires each detector to its KServe predictor endpoint via in-cluster DNS with configurable thresholds in values.yaml (gibberish: 0.35, promptInjection/HAP: 0.5) and configurable replicas. Regex detector runs as a localhost sidecar while HAP, prompt injection, and gibberish are external KServe InferenceServices that must be in the same namespace for DNS resolution; detector hostnames use KServe's <inferenceservice-name>-predictor convention requiring manual update if InferenceService names change, and prompt_injection only scans input not output unlike all other detectors."
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

## Related Patterns

- `kserve-rawdeployment-detector-fleet-gpu-toggle.md` -- the detector InferenceServices that the orchestrator routes to
- `helm-flat-chart-direct-crd-templating.md` -- the chart structure containing this orchestrator deployment
