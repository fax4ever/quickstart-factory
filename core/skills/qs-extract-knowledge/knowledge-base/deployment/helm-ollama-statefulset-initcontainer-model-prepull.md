---
name: helm-ollama-statefulset-initcontainer-model-prepull
description: Ollama StatefulSet with initContainer that starts server in background to pull models before main container, GPU toggle via condition
summary: "Solves the Ollama deployment problem where `ollama pull` requires a running local server by using a Helm-templated StatefulSet initContainer that starts Ollama in the background, iterates over `.Values.models` (e.g., granite4:3b, granite-embedding:30m) checking existence via `ollama list | grep -q` to skip re-downloads, then kills the server before exiting. Use when deploying Ollama on OpenShift with pre-loaded models on a shared PVC via volumeClaimTemplate; `gpu.enabled` toggles `nvidia.com/gpu` resource requests on both initContainer and main container while GPU node tolerations (g5-gpu, nvidia.com/gpu) remain always present. Critical config: set `OLLAMA_MODELS` and `HOME` env vars to the mounted PVC path (`/var/lib/ollama`) for OpenShift non-root compatibility; `persistence.size` (default 50Gi) with optional `persistence.storageClass` must accommodate all models; model names must exactly match `ollama list` output format (e.g., `granite4:3b` not `granite4`). Gotchas: the background server must be explicitly killed (`kill $OLLAMA_PID; wait $OLLAMA_PID || true`) before initContainer exit or the pod hangs; GPU is held during the network I/O-bound pull phase wasting resources; both initContainer and main container require the same Ollama image with the `ollama` CLI binary."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [model-serving, embeddings]
  platform: [openshift]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Ollama StatefulSet with pull-models initContainer that starts/stops Ollama server, pulls granite4:3b and granite-embedding:30m, conditional GPU via gpu.enabled flag, OpenShift non-root HOME workaround"
    approach: "A"
---

# Ollama StatefulSet with InitContainer Model Pre-Pull

## Overview

This pattern deploys Ollama as a Kubernetes StatefulSet with a PVC for model storage and an initContainer that pre-pulls models before the main container starts serving. The initContainer starts the Ollama server in the background, pulls the required models, and shuts down the server, ensuring models are ready when the main container begins. A `gpu.enabled` flag conditionally adds GPU resource requests.

## Pattern Description

Ollama requires its server process to be running in order to pull models (the `ollama pull` command sends an API request to the local server). The initContainer solves this by temporarily running the server, performing all model pulls, then shutting it down. The main container then starts with pre-loaded models on a shared PVC. This avoids long startup delays when the main container would otherwise need to pull models on first request. The pattern also handles OpenShift's non-root requirement by setting `OLLAMA_MODELS` and `HOME` to a writable mounted volume.

## Implementation

### InitContainer with Background Server and Model Pull

```yaml
# charts/ollama/templates/statefulset.yaml (excerpt)
initContainers:
  - name: pull-models
    image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
    env:
      # Set Ollama directories to writable mounted volume (OpenShift runs as non-root)
      - name: OLLAMA_MODELS
        value: /var/lib/ollama/models
      - name: HOME
        value: /var/lib/ollama
    command:
      - /bin/sh
      - -c
      - |
        set -e
        echo "Starting Ollama in background..."
        /bin/ollama serve &
        OLLAMA_PID=$!

        echo "Waiting for Ollama to be ready..."
        until ollama list >/dev/null 2>&1; do
          echo "Waiting for Ollama API..."
          sleep 2
        done
        echo "Ollama is ready!"

        {{- range .Values.models }}
        echo "Checking/pulling model: {{ . }}"
        if ollama list | grep -q "{{ . }}"; then
          echo "Model {{ . }} already exists, skipping pull"
        else
          echo "Pulling model: {{ . }}"
          ollama pull {{ . }}
        fi
        {{- end }}

        echo "All models ready!"
        kill $OLLAMA_PID
        wait $OLLAMA_PID || true
    volumeMounts:
      - name: ollama-data
        mountPath: /var/lib/ollama
```

### Conditional GPU Resource Requests

```yaml
# charts/ollama/templates/statefulset.yaml (resource section, used in both initContainer and container)
resources:
  requests:
    cpu: {{ .Values.resources.requests.cpu }}
    memory: {{ .Values.resources.requests.memory }}
    {{- if .Values.gpu.enabled }}
    nvidia.com/gpu: "1"
    {{- end }}
  limits:
    cpu: {{ .Values.resources.limits.cpu }}
    memory: {{ .Values.resources.limits.memory }}
    {{- if .Values.gpu.enabled }}
    nvidia.com/gpu: "1"
    {{- end }}
```

### GPU Tolerations Always Present

```yaml
# charts/ollama/values.yaml (excerpt)
gpu:
  enabled: false

# Tolerations for GPU nodes - always present, allows scheduling on GPU nodes
# These are harmless when gpu.enabled=false (pod won't request GPU anyway)
tolerations:
  - key: g5-gpu
    operator: Exists
    effect: NoSchedule
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
```

### Configurable Model List

```yaml
# charts/ollama/values.yaml (excerpt)
models:
  - granite4:3b
  - granite-embedding:30m
```

### StatefulSet with PVC for Model Persistence

```yaml
# charts/ollama/templates/statefulset.yaml (excerpt)
volumeClaimTemplates:
  - metadata:
      name: ollama-data
    spec:
      accessModes: ["ReadWriteOnce"]
      {{- if .Values.persistence.storageClass }}
      storageClassName: {{ .Values.persistence.storageClass }}
      {{- end }}
      resources:
        requests:
          storage: {{ .Values.persistence.size }}
```

## Configuration

- **Key settings:** `models` list defines which models to pre-pull; `gpu.enabled` toggles GPU resource requests; `persistence.size` (default: 50Gi) must be large enough for all models
- **Defaults:** CPU-only mode (gpu.enabled: false); granite4:3b chat model and granite-embedding:30m embedding model; 50Gi PVC; tolerations for GPU nodes always present (harmless when GPU not requested)
- **Dependencies:** The initContainer and main container share the same PVC via volumeClaimTemplate; Ollama image must include the `ollama` CLI binary

## Gotchas

- The initContainer runs the same image as the main container and starts the Ollama server in the background (`/bin/ollama serve &`); the server must be killed explicitly before the initContainer exits or the pod will hang (see `charts/ollama/templates/statefulset.yaml` lines 69-70)
- The `ollama list | grep -q` check for existing models prevents re-downloading on pod restarts, but model names must exactly match the format returned by `ollama list` (e.g., `granite4:3b` not just `granite4`) (see `charts/ollama/templates/statefulset.yaml` lines 58-65)
- OpenShift runs containers as non-root with an arbitrary UID; setting `OLLAMA_MODELS` and `HOME` to the mounted PVC path (`/var/lib/ollama`) ensures Ollama can write model files without root access (see `charts/ollama/templates/statefulset.yaml` lines 38-41)
- GPU tolerations are always present regardless of `gpu.enabled` -- this is intentional so pods can schedule on GPU-tainted nodes even in CPU mode; the GPU resource request is what actually allocates a GPU (see `charts/ollama/values.yaml` lines 43-49 comment)
- The GPU resource request is applied to both the initContainer and main container; this means a GPU is held during the model pull phase even though Ollama's pull operation primarily uses network I/O (see `charts/ollama/templates/statefulset.yaml` resource blocks)

## Related Patterns

- `helm-umbrella-all-local-file-ref-conditional-deps.md` -- the umbrella chart that includes this Ollama subchart
- `helm-minio-initcontainer-hf-model-download.md` -- similar initContainer pattern but for downloading models from HuggingFace to MinIO
