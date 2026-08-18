---
name: regex-detector
description: "TrustyAI built-in regex detector for PII pattern matching (email, SSN) via GuardrailsOrchestrator sidecar"
summary: "Provides pattern-based PII detection (email, SSN) for LLM input and output within the TrustyAI GuardrailsOrchestrator guardrails stack, running as a built-in sidecar rather than a standalone KServe InferenceService. Use as the regex-based PII detector (type `text_contents`, chunker `whole_doc_chunker`, default_threshold 0.5) when pattern matching suffices — unlike gibberish, prompt-injection, and hap detectors that require separate InferenceServices and ServingRuntimes, this detector needs only `enableBuiltInDetectors: true` and `enableGuardrailsGateway: true` on the GuardrailsOrchestrator CR, with three ConfigMaps: `fms-orchestr8-config-nlp` for endpoint/threshold, `fms-orchestr8-config-gateway` for input/output routing and pattern selection (email, ssn) across `all` vs `passthrough` routes, and `gorch-regex-gateway-image-config` for SHA256-pinned sidecar images. Critical config: the regex detector binds to 127.0.0.1 on Helm value `detectors.regex.port` (default 8080, not 8000 like KServe detectors) and its image is supplied via ConfigMap rather than storageUri. Common gotcha: the detector has no InferenceService so it will not appear as a separate pod — verify by checking the orchestrator pod shows 3/3 containers (orchestrator + gateway + regex-detector sidecars); port 8080 vs 8000 mismatch with other detectors causes silent routing failures if misconfigured."
metadata:
  type: component
tags:
  tech_stack: [trustyai, kserve]
  ai_pattern: [guardrails, pii-detection]
  platform: [rhoai, openshift, kserve]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Built-in regex detector for email and SSN PII detection within GuardrailsOrchestrator"
    approach: "A"
---

# Regex Detector

## Overview

The regex detector is a built-in detector component of the TrustyAI GuardrailsOrchestrator that performs pattern-based PII detection using regular expressions. Unlike the other detectors in the guardrails stack (gibberish, prompt injection, hate-and-profanity) which are deployed as standalone KServe InferenceServices, the regex detector runs as a sidecar within the orchestrator pod itself, binding to localhost. It is used in the guardrailing-llms quickstart to detect email addresses and Social Security Numbers in both input and output.

## Tech Stack & Dependencies

- **Runtime:** Container image from TrustyAI project
- **Container image:** `quay.io/repository/trustyai/regex-detector@sha256:8c9ee944d6a745f3036c5f14d03db30c15cfa928b984f33b5d96180602f4e1ab`
- **Key dependencies:** TrustyAI GuardrailsOrchestrator CR with `enableBuiltInDetectors: true`
- **Helm subchart:** None (deployed as part of the orchestrator via ConfigMap-driven image references)

## Key Patterns

### Built-in Detector (Sidecar on Localhost)

The regex detector is configured as a `text_contents` type detector bound to `127.0.0.1` in the orchestrator's NLP config, rather than being routed to a separate in-cluster service like the other detectors. This is defined in the `fms-orchestr8-config-nlp` ConfigMap:

```yaml
detectors:
  regex:
    type: text_contents
    service:
        hostname: "127.0.0.1"
        port: {{ .Values.detectors.regex.port }}
    chunker_id: whole_doc_chunker
    default_threshold: 0.5
```

In contrast, other detectors use cluster-internal DNS hostnames like `gibberish-detector-predictor.{{ .Release.Namespace }}.svc.cluster.local`.

### Image Reference via ConfigMap

The regex detector's container image is supplied to the orchestrator through a dedicated ConfigMap (`gorch-regex-gateway-image-config`) rather than via an InferenceService or ServingRuntime:

```yaml
kind: ConfigMap
apiVersion: v1
metadata:
  name: gorch-regex-gateway-image-config
data:
  GatewayImage: 'quay.io/repository/trustyai/vllm-orchestrator-gateway@sha256:c511b386d61a728acdfe8a1ac7a16b3774d072dd053718e5b9c5fab0f025ac3b'
  regexDetectorImage: 'quay.io/repository/trustyai/regex-detector@sha256:8c9ee944d6a745f3036c5f14d03db30c15cfa928b984f33b5d96180602f4e1ab'
```

This ConfigMap also carries the gateway image reference, bundling both sidecar images together.

### Gateway Detector Routing with PII Patterns

The gateway config (`fms-orchestr8-config-gateway`) controls which detectors apply to input vs output and specifies which regex patterns to activate. The regex detector is configured to scan both input and output for `email` and `ssn` patterns:

```yaml
detectors:
  - name: regex
    input: true
    output: true
    detector_params:
      regex:
        - email
        - ssn
```

### GuardrailsOrchestrator CR Enablement

The orchestrator CR must have `enableBuiltInDetectors: true` and `enableGuardrailsGateway: true` for the regex detector to be deployed as a sidecar:

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
```

## Configuration

- **Environment variables:** None directly on the regex detector; configuration is driven entirely through the orchestrator ConfigMaps
- **Config files:** Two ConfigMaps control behavior:
  - `fms-orchestr8-config-nlp` -- detector endpoint and threshold configuration
  - `fms-orchestr8-config-gateway` -- routing rules and pattern selection (email, ssn)
- **Helm values:**
  - `detectors.regex.port` (default `8080`) -- port the regex detector sidecar listens on
  - Note: port 8080 differs from the 8000 used by the KServe-based detectors

## Known Gotchas

- The regex detector listens on port 8080 while all other detectors (gibberish, prompt injection, hate-and-profanity) use port 8000. This is visible in `values.yaml` where `detectors.regex.port: 8080` vs the other detectors at `port: 8000`.
- The regex detector has no `storageUri` in values.yaml unlike other detectors, because it does not load a model -- its image is supplied via the `gorch-regex-gateway-image-config` ConfigMap instead.
- The regex detector does not have its own InferenceService or ServingRuntime. It is a built-in detector managed by the GuardrailsOrchestrator operator when `enableBuiltInDetectors: true` is set. This means it will not appear as a separate pod in `oc get pods` -- it runs inside the `gorch-sample` orchestrator pod (which shows 3/3 containers).
- Both container images in `gorch-regex-gateway-image-config` are pinned by sha256 digest, not by tag, ensuring reproducible deployments.

## Testing Notes

- After deployment, the orchestrator pod (`gorch-sample-*`) should show 3/3 containers running, indicating the gateway and regex detector sidecars started successfully alongside the orchestrator
- PII detection can be tested through the healthcare-guardrails notebook in the workbench, which demonstrates SSN and email detection scenarios
- The regex detector applies to routes named `all` in the gateway config, which includes all four detectors (regex, hap, prompt_injection, gibberish); a `passthrough` route is also defined for bypassing detection

## Related Patterns

- See guardrails orchestrator architecture for the overall TrustyAI orchestration layer
- See model-serving patterns for how the other detectors (gibberish, prompt-injection, hate-and-profanity) are deployed as KServe InferenceServices
