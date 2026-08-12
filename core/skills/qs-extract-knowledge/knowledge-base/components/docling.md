---
name: docling
description: "Docling document parsing service for CV/PDF import with CPU/GPU toggle via Helm subchart"
summary: "Docling wraps upstream docling-serve as a conditional Helm subchart (toggled by docling.enabled in umbrella chart via file://../charts/docling) providing HTTP document parsing for CV/PDF import on port 5001, with liveness/readiness probes at /health (30s/10s initial delays), optional web UI via docling.enableUI, and defaults of 500m/1Gi request, 2000m/4Gi limit, 1 replica (production uses 2). Use when quickstarts need structured data extraction from uploaded documents -- a single gpu.enabled boolean swaps the image from docling-serve-cpu to docling-serve (GPU variant, no suffix), injects nvidia.com/gpu: 1 resource requests, and leverages pre-configured GPU tolerations; the docling.image.repository value is ignored when GPU is enabled due to hardcoded image swap in the deployment template. Backend discovers docling via ConfigMap-injected QUARKUS_DOCLING_BASE_URL (cluster-internal service URL, e.g. http://<service>.<namespace>.svc.cluster.local:5001) and requires CV_IMPORT_PROVIDER=docling to route imports correctly. Critical gotchas: mismatched CV_IMPORT_PROVIDER causes silent import failures, GPU pods stay Pending indefinitely without NVIDIA nodes (nvidia.com/gpu: 1 is a hard scheduling requirement), and when only one GPU exists prioritize Ollama over Docling since LLM inference benefits more from GPU acceleration than document parsing."
metadata:
  type: component
tags:
  tech_stack: [docling, python]
  ai_pattern: [data-pipeline, multimodal]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Docling-serve deployed as a standalone Helm subchart with CPU/GPU image swap and health probes"
    approach: "A"
---

# Docling

## Overview

Docling is a document parsing service used for CV/PDF import in AI Quickstarts. It wraps the upstream [docling-serve](https://github.com/docling-project/docling-serve) project as a standalone Helm subchart, providing an HTTP API for document extraction. In the peoplemesh quickstart it powers the CV import pipeline, converting uploaded PDF/document files into structured data consumed by the application backend.

## Tech Stack & Dependencies
- **Runtime:** Python (upstream docling-serve container)
- **Container image:** `quay.io/docling-project/docling-serve-cpu:latest` (CPU) or `quay.io/docling-project/docling-serve:latest` (GPU)
- **Key dependencies:** NVIDIA GPU (optional, for accelerated parsing); backend must set `CV_IMPORT_PROVIDER=docling` and `DOCLING_BASE_URL` to connect
- **Helm subchart:** `charts/docling` v0.1.0, conditionally enabled via `docling.enabled` in umbrella chart

## Key Patterns

### CPU/GPU Image Swap

The deployment template switches the container image based on a single boolean flag, avoiding separate chart configurations for CPU and GPU modes.

```yaml
# charts/docling/templates/deployment.yaml
containers:
  - name: {{ .Values.applicationName }}
    {{- if .Values.gpu.enabled }}
    image: quay.io/docling-project/docling-serve:latest
    {{- else }}
    image: {{ .Values.docling.image.repository }}:{{ .Values.docling.image.tag }}
    {{- end }}
```

When `gpu.enabled=true`, the chart also injects `nvidia.com/gpu: "1"` into both resource requests and limits.

### Pre-configured GPU Tolerations

GPU node tolerations are included by default in values.yaml so users never need to configure them manually. The tolerations are harmless when GPU is disabled because the pod does not request GPU resources.

```yaml
# charts/docling/values.yaml
tolerations:
  - key: g5-gpu
    operator: Exists
    effect: NoSchedule
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
```

### Health Probes on /health Endpoint

The deployment configures both liveness and readiness probes against docling-serve's built-in `/health` endpoint, with staggered initial delays to allow model loading time.

```yaml
# charts/docling/templates/deployment.yaml
livenessProbe:
  httpGet:
    path: /health
    port: {{ .Values.docling.service.targetPort }}
  initialDelaySeconds: 30
  periodSeconds: 10
readinessProbe:
  httpGet:
    path: /health
    port: {{ .Values.docling.service.targetPort }}
  initialDelaySeconds: 10
  periodSeconds: 5
```

### Conditional Subchart in Umbrella Chart

Docling is wired as a conditional dependency in the umbrella chart, toggled by a single `docling.enabled` flag.

```yaml
# peoplemesh-umbrella/Chart.yaml
dependencies:
  - name: docling
    version: 0.1.0
    repository: "file://../charts/docling"
    condition: docling.enabled
```

### Backend Integration via ConfigMap

The consuming application discovers docling through a Kubernetes-internal service URL injected via ConfigMap, gated on the same `docling.enabled` flag.

```yaml
# charts/peoplemesh/templates/config-map.yaml
{{- if .Values.docling.enabled }}
QUARKUS_DOCLING_BASE_URL: "http://{{ .Values.docling.serviceName }}.{{ .Release.Namespace }}.svc.cluster.local:{{ .Values.docling.port }}"
{{- end }}
```

## Configuration
- **Environment variables:**
  - `DOCLING_SERVE_ENABLE_UI` -- enables the built-in web UI at `/ui` (set from `docling.enableUI` Helm value)
- **Helm values:**
  - `gpu.enabled` (bool, default `false`) -- switches image to GPU variant and requests `nvidia.com/gpu: 1`
  - `docling.image.repository` / `docling.image.tag` -- CPU image reference (default `quay.io/docling-project/docling-serve-cpu:latest`)
  - `docling.service.port` / `docling.service.targetPort` -- service port (default `5001`)
  - `docling.enableUI` (bool, default `true`) -- enable the docling web UI
  - `docling.replicas` (int, default `1`) -- replica count; production example uses `2`
  - `docling.resources` -- CPU/memory requests and limits (default: 500m/1Gi request, 2000m/4Gi limit)
  - `docling.tolerations` -- pre-configured GPU node tolerations

## Known Gotchas
- **CPU vs GPU image naming:** The CPU image is `docling-serve-cpu` while the GPU image is `docling-serve` (no suffix). The image swap is hardcoded in the deployment template rather than driven from values, so the `docling.image.repository` value is ignored when `gpu.enabled=true` (see `charts/docling/templates/deployment.yaml` lines 27-30).
- **CV import provider must match:** The backend's `CV_IMPORT_PROVIDER` must be set to `docling` (not `local`) when docling is deployed, and `DOCLING_BASE_URL` must point to the correct service. Mismatches cause silent CV import failures (per `docs/DEPLOYMENT-NOTES.md`).
- **Pod Pending with GPU enabled but no GPU nodes:** Setting `gpu.enabled=true` without available NVIDIA GPUs causes the pod to stay in Pending state indefinitely because `nvidia.com/gpu: 1` becomes a hard scheduling requirement (per `docs/GPU-SIMPLIFIED.md`).
- **GPU priority:** When only one GPU is available, the docs recommend prioritizing Ollama over Docling (`ollama.gpu.enabled=true`, `docling.gpu.enabled=false`) because LLM inference gains more from GPU acceleration than document parsing (per `docs/GPU-SIMPLIFIED.md`).

## Testing Notes
- Verify docling pod is Running: `oc get pods -n <namespace> | grep docling`
- Check health endpoint: `oc exec -it deployment/docling -n <namespace> -- curl http://localhost:5001/health`
- Verify GPU allocation (if enabled): `oc describe pod <docling-pod> -n <namespace> | grep nvidia.com/gpu`
- Confirm backend connectivity by verifying `QUARKUS_DOCLING_BASE_URL` is set in the peoplemesh ConfigMap

## Related Patterns
- Umbrella chart wiring: `peoplemesh-umbrella/Chart.yaml`
- GPU configuration pattern: shared with the ollama subchart via the same `gpu.enabled` flag convention
