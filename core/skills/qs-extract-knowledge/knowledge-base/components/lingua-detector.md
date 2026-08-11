---
name: lingua-detector
description: "Rule-based language detection service using Lingua library, deployed as a guardrails detector for enforcing language compliance"
summary: "Lingua is a rule-based language detection service deployed as a standalone Kubernetes Deployment + ClusterIP Service (not KServe) within FMS Orchestr8 guardrails pipelines to enforce language compliance (e.g., English-only) on both user input and LLM output. Use when adding language enforcement to a guardrails pipeline -- unlike HAP and prompt injection detectors that require KServe InferenceServices and GPU, Lingua is lightweight and rule-based, needing only a standard Deployment with no model-serving infrastructure. Register as `language_detection` with type `text_contents` in the `fms-orchestr8-config-nlp` ConfigMap, wire through the sentence chunker with a 0.88 default threshold, expose /health on port 8080 with `LOG_LEVEL` env var; image is `quay.io/ckavili/lingua-language-detector:0.0.25`. The container image is from a personal Quay.io repo (not official Red Hat), resources are hardcoded in `chart/templates/lingua.yaml` (not parameterized in values.yaml unlike HAP/prompt injection detectors), the 0.88 threshold is set in the orchestrator ConfigMap not the Deployment, and the topology spread constraint (`maxSkew: 2`, `ScheduleAnyway`) is unique among detectors."
metadata:
  type: component
tags:
  tech_stack: [lingua, rust]
  ai_pattern: [guardrails, language-detection]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "Lingua language detector deployed as a guardrails detector within FMS Orchestr8 pipeline for English-only enforcement"
    approach: "A"
---

# Lingua Language Detector

## Overview

Lingua is a rule-based language detection service deployed as a standalone Kubernetes Deployment, used within guardrails pipelines to enforce language compliance (e.g., English-only). Unlike the ML-based HAP or prompt injection detectors that run as KServe InferenceServices, Lingua is a lightweight containerized service registered as a `text_contents` detector in the FMS Orchestr8 orchestrator configuration. It validates both user input and LLM output to ensure they stay within the allowed language.

## Tech Stack & Dependencies
- **Runtime:** Pre-built container image (`quay.io/ckavili/lingua-language-detector:0.0.25`)
- **Container image:** `quay.io/ckavili/lingua-language-detector:0.0.25`
- **Key dependencies:** FMS Guardrails Orchestrator (registers lingua-detector as a `text_contents` detector), Chunker service (chunking is applied before detection)
- **Helm subchart:** None -- deployed as a raw Deployment + Service in the parent chart templates

## Key Patterns

### Standalone Deployment (Not KServe)

Unlike other detectors in the guardrails pipeline (HAP, prompt injection) that use KServe InferenceServices, lingua-detector is deployed as a standard Kubernetes Deployment with a ClusterIP Service. This is because it is rule-based, not model-based, so it does not need GPU or model-serving infrastructure.

```yaml
kind: Deployment
apiVersion: apps/v1
metadata:
  name: lingua-detector
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: lingua-detector
          image: 'quay.io/ckavili/lingua-language-detector:0.0.25'
          ports:
            - containerPort: 8080
          env:
            - name: LOG_LEVEL
              value: INFO
```

### FMS Orchestr8 Detector Registration

Lingua is registered as a `text_contents` type detector in the FMS Orchestr8 configuration ConfigMap, using the `language_detection` detector ID. It is wired through the sentence chunker and uses a threshold of 0.88.

```yaml
detectors:
  language_detection:
    type: text_contents
    service:
      hostname: lingua-detector
      port: 8080
    chunker_id: sentence
    default_threshold: 0.88
```

### Bidirectional Detection (Input + Output)

The application code registers `language_detection` on both input and output detectors when calling the guardrails orchestrator, ensuring both user messages and LLM responses are checked for language compliance.

```python
"detectors": {
    "input": {
        "hap": {},
        "language_detection": {},
        "prompt_injection": {}
    },
    "output": {
        "hap": {},
        "regex_competitor": { "regex": ALL_REGEX_PATTERNS },
        "language_detection": {}
    }
}
```

### Health Probes

The service exposes a `/health` endpoint on port 8080 for both liveness and readiness probes. The readiness probe starts after 5 seconds, while the liveness probe starts after 10 seconds with a 30-second check interval.

```yaml
readinessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 30
```

## Configuration
- **Environment variables:**
  - `LOG_LEVEL` -- Controls logging verbosity (default: `INFO`)
- **Config files:** None -- configured via the FMS Orchestr8 ConfigMap (`fms-orchestr8-config-nlp`)
- **Helm values:** Not parameterized in `values.yaml` -- the image and resources are hardcoded in the Deployment template

## Known Gotchas
- Unlike HAP and prompt injection detectors, lingua-detector is NOT configurable via `values.yaml` for GPU toggle or resource overrides. Its resources are hardcoded in the Deployment template (`chart/templates/lingua.yaml`), while the other detectors have `values.yaml` entries under `detectors.hap` and `detectors.promptInjection`.
- The detection threshold of `0.88` is set in the FMS Orchestr8 ConfigMap, not in the Deployment itself. This is higher than the `0.5` threshold used by the HAP and prompt injection detectors.
- The topology spread constraint (`maxSkew: 2`, `whenUnsatisfiable: ScheduleAnyway`) is unique to this component among the detectors, spreading pods across nodes by hostname.
- The container image is sourced from a personal Quay.io repository (`quay.io/ckavili/`), not an official Red Hat or upstream registry.

## Testing Notes
- Verify the `/health` endpoint responds on port 8080 after deployment
- Send a non-English message through the guardrails orchestrator and confirm it is blocked with the `language_detection_input` response
- Check that non-English LLM output is also caught via the `language_detection_output` detector
- The blocked message in the app reads: "I can only communicate in English. Please rephrase your message in English."

## Related Patterns
- `guardrails-orchestrator.md` -- The FMS Orchestr8 orchestrator that coordinates lingua-detector with other detectors
- `hate-and-profanity-detector.md` -- HAP detector deployed via KServe (contrast with lingua's standalone Deployment)
- `prompt-injection-detector.md` -- Prompt injection detector deployed via KServe (contrast with lingua's standalone Deployment)
- `regex-detector.md` -- Another non-ML detector in the same guardrails pipeline
