---
name: chunker-service
description: "gRPC sentence chunker for FMS Guardrails Orchestrator — splits text for detector evaluation"
summary: "Provides sentence-level text splitting as a standalone gRPC microservice (port 8085) for the FMS Guardrails Orchestrator (fms-orchestr8), enabling detectors (HAP, prompt injection, regex_competitor, language detection) to evaluate user and LLM text at sentence granularity within the TrustyAI guardrails stack on RHOAI. Deploy alongside any TrustyAI guardrails stack using fms-orchestr8 — it is the sole chunker instance referenced via chunker_id: sentence by all detectors in the fms-orchestr8-config-nlp ConfigMap; no alternative chunker types are documented. Deployed as a raw Kubernetes Deployment+ClusterIP Service (no Helm subchart or values.yaml overrides) with image quay.io/rh-ee-mmisiura/chunkers:v2.0 on gRPC port 8085, no env vars, no volume mounts, and hardcoded resource limits (2 CPU/2Gi, requests 1 CPU/1Gi); register under chunkers.sentence.service.hostname: chunker-service. No liveness or readiness probes are defined so Kubernetes cannot detect unresponsiveness and the orchestrator silently fails; single replica with no HPA creates a bottleneck since all four detectors depend on it for every request."
metadata:
  type: component
tags:
  tech_stack: [grpc, kubernetes]
  ai_pattern: [guardrails, chunking]
  platform: [openshift, rhoai, trustyai]
source_examples:
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "Sentence chunker service consumed by FMS Guardrails Orchestrator to split text before detector evaluation"
    approach: "A"
---

# Chunker Service

## Overview

The chunker service is a standalone gRPC microservice that performs sentence-level text splitting for the FMS Guardrails Orchestrator (fms-orchestr8). It breaks user input and LLM output into sentence-level chunks so that individual guardrail detectors (HAP, prompt injection, language detection) can evaluate text at sentence granularity. It is deployed as a simple Kubernetes Deployment alongside the TrustyAI guardrails stack on RHOAI.

## Tech Stack & Dependencies

- **Runtime:** Pre-built container image (`quay.io/rh-ee-mmisiura/chunkers:v2.0`)
- **Container image:** `quay.io/rh-ee-mmisiura/chunkers:v2.0`
- **Protocol:** gRPC on port 8085
- **Key dependencies:** Consumed by the GuardrailsOrchestrator CR via the `fms-orchestr8-config-nlp` ConfigMap
- **Helm subchart:** None — deployed as a raw Deployment + Service template in the parent chart

## Key Patterns

### Standalone gRPC Deployment

The chunker is deployed as a minimal Kubernetes Deployment with a ClusterIP Service. It has no Helm value overrides, no environment variables, and no volume mounts — it is entirely self-contained.

```yaml
# chart/templates/chunker.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: chunker-service
  labels:
    app: chunker-service
    app.kubernetes.io/component: chunker
spec:
  replicas: 1
  selector:
    matchLabels:
      app: chunker-service
  template:
    spec:
      containers:
      - name: chunker
        image: quay.io/rh-ee-mmisiura/chunkers:v2.0
        ports:
        - containerPort: 8085
          name: grpc
          protocol: TCP
```

### Orchestrator Integration via ConfigMap

The chunker is wired into the FMS Guardrails Orchestrator through the `fms-orchestr8-config-nlp` ConfigMap. It is registered under the `chunkers` key with type `sentence`, and every detector references it by `chunker_id: sentence`.

```yaml
# chart/templates/fms-orchestr8-config-nlp.yaml
chunkers:
  sentence:
    type: sentence
    service:
        hostname: chunker-service
        port: 8085
detectors:
  hap:
    type: text_contents
    service:
      hostname: guardrails-detector-ibm-hap-predictor
      port: 8000
    chunker_id: sentence
    default_threshold: 0.5
```

All four detectors in this quickstart (regex_competitor, hap, prompt_injection, language_detection) reference `chunker_id: sentence`, meaning every detector relies on this single chunker instance.

## Configuration

- **Environment variables:** None — the container runs with no env var configuration
- **Config files:** None within the chunker itself; the orchestrator ConfigMap (`fms-orchestr8-config-nlp`) defines how the orchestrator connects to it
- **Helm values:** No `values.yaml` overrides exist for the chunker — the image, port, and resources are hardcoded in the template

## Known Gotchas

- **Hardcoded image and resources:** Unlike the detector components which expose `values.yaml` overrides for GPU toggling and resource tuning, the chunker has no configurable Helm values. The image tag (`v2.0`), CPU/memory limits (`2`/`2Gi`), and requests (`1`/`1Gi`) are all hardcoded directly in `chart/templates/chunker.yaml`.
- **No health or readiness probes:** The Deployment does not define any liveness or readiness probes, so Kubernetes cannot automatically detect if the chunker becomes unresponsive. The orchestrator will fail to process text if the chunker is down.
- **Single replica:** Deployed with `replicas: 1` and no HPA, making it a potential bottleneck under high load since all detectors depend on it for sentence splitting.

## Testing Notes

- Verify the chunker pod is running: the pod should be `1/1 Ready` with no restarts
- Test indirectly by sending a message through the Lemonade Stand chat UI — if detectors work (blocking profanity, prompt injection, non-English input), the chunker is functioning
- Check orchestrator logs for errors referencing `chunker-service:8085` if detectors fail to respond

## Related Patterns

- `components/guardrails-orchestrator.md` — the GuardrailsOrchestrator CR that consumes this chunker
- `components/prompt-injection-detector.md` — one of the detectors that depends on sentence chunking
- `components/hate-and-profanity-detector.md` — another detector that depends on sentence chunking
