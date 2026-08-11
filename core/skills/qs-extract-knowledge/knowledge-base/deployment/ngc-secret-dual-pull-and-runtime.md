---
name: ngc-secret-dual-pull-and-runtime
description: Single NGC API key secret serving as both dockerconfigjson for image pulls and runtime env vars
summary: "Solves the need for a single Kubernetes Secret that combines nvcr.io dockerconfigjson image-pull authentication (username $oauthtoken) with NGC_API_KEY and NVIDIA_API_KEY runtime data keys, eliminating separate secrets for NVIDIA registry pulls and cloud API access. Use when deploying NGC-dependent workloads (NV-Ingest, RAG server) that need both nvcr.io container pulls and NVIDIA API calls from one API key — the Helm template is created via --set nvidiaApiKey.password=$NGC_API_KEY with conditional guard on nvidiaApiKey.create/name/password. Critical config: NV-Ingest subchart must set ngcApiSecret.create: false and ngcImagePullSecret.create: false to prevent redundant secrets and uses extraEnvFrom for injection; pods consume the secret both as imagePullSecrets and via secretKeyRef env vars for NGC_API_KEY/NVIDIA_API_KEY. Gotchas: .dockerconfigjson is double base64-encoded (Helm b64enc plus YAML data-field encoding), adding extra data keys to a dockerconfigjson-typed Secret is non-standard but Kubernetes allows it, and the YAML anchor &ngc-secret-name is only visible within its defining chart so other charts (frontend, rag-server) must hardcode the secret name \"ngc-api\"."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  platform: [openshift]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "NGC secret provides dockerconfigjson for nvcr.io pulls plus NGC_API_KEY and NVIDIA_API_KEY env vars"
    approach: "A"
---

# NGC Secret: Dual-Purpose Pull and Runtime

## Overview

This pattern creates a single Kubernetes Secret that serves two purposes: it acts as a `dockerconfigjson` image pull secret for pulling NVIDIA container images from `nvcr.io`, and it stores `NGC_API_KEY` and `NVIDIA_API_KEY` as data keys for runtime use by containers that call NVIDIA cloud APIs. This avoids maintaining separate secrets for registry authentication and API access.

## Pattern Description

NVIDIA's NGC registry (`nvcr.io`) uses API keys for authentication, with `$oauthtoken` as the username. The same API key is needed at runtime by services like NV-Ingest that call NVIDIA cloud APIs (YOLOX, OCR, etc.). Rather than creating two secrets, this pattern embeds both the Docker config JSON and the raw API key values in a single `kubernetes.io/dockerconfigjson`-typed Secret. The key is passed via `--set nvidiaApiKey.password=$NGC_API_KEY` at install time.

## Implementation

### Secret Template

```yaml
# charts/ingest/templates/nvidia-api-key-secret.yaml
{{- $nak := .Values.nvidiaApiKey | default dict }}
{{- if and $nak.create $nak.name $nak.password }}
{{- $auth := printf "%s:%s" $nak.username $nak.password | b64enc }}
{{- $config := printf "{\"auths\":{\"%s\":{\"username\":\"%s\",\"password\":\"%s\",\"auth\":\"%s\"}}}" $nak.registry $nak.username $nak.password $auth }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ $nak.name }}
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: {{ $config | b64enc | quote }}
  NGC_API_KEY: {{ $nak.password | b64enc | quote }}
  NVIDIA_API_KEY: {{ $nak.password | b64enc | quote }}
{{- end }}
```

### Values Configuration

```yaml
# charts/ingest/values.yaml (excerpt)
nvidiaApiKey:
  create: true
  name: &ngc-secret-name "ngc-api"
  password: ""  # Set via --set nvidiaApiKey.password=$NGC_API_KEY
  registry: "nvcr.io"
  username: "$oauthtoken"
```

### Consumption as Image Pull Secret

```yaml
# charts/ingest/values.yaml (excerpt)
nv-ingest:
  imagePullSecrets:
    - name: *ngc-secret-name
  ngcApiSecret:
    create: false   # Don't create a separate NGC secret
  ngcImagePullSecret:
    create: false   # Use parent chart's secret instead
```

### Consumption as Runtime Env Vars

The RAG server extracts API keys from the same secret via `secretKeyRef`:

```yaml
# charts/rag-server/templates/deployment.yaml (excerpt)
env:
- name: NGC_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.imagePullSecret.name }}
      key: NGC_API_KEY
- name: NVIDIA_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.imagePullSecret.name }}
      key: NVIDIA_API_KEY
```

## Configuration

- **Key settings:** `nvidiaApiKey.password` must be set at install time; `nvidiaApiKey.name` uses a YAML anchor (`&ngc-secret-name`) referenced by all charts via `*ngc-secret-name`
- **Defaults:** Secret creation enabled by default; registry defaults to `nvcr.io`; username defaults to `$oauthtoken` (NGC OAuth pattern)
- **Dependencies:** A valid NGC API key from `https://ngc.nvidia.com/`; the secret must be created before NV-Ingest and RAG server Deployments start

## Gotchas

- The secret stores `NGC_API_KEY` and `NVIDIA_API_KEY` as additional data keys inside a `kubernetes.io/dockerconfigjson`-typed secret; this is technically non-standard but Kubernetes allows extra keys in any secret type
- The Docker config JSON is double base64-encoded: once by Helm's `b64enc` for the JSON structure, and once by the YAML `data:` field encoding
- NV-Ingest subchart settings `ngcApiSecret.create: false` and `ngcImagePullSecret.create: false` prevent the subchart from creating its own redundant secrets; it uses `extraEnvFrom` to inject the parent chart's secret instead
- The YAML anchor `&ngc-secret-name` defined in the ingest chart's values.yaml is not visible to other charts (frontend, rag-server); those charts reference the secret name directly as `ngc-api` in their `imagePullSecret.name` values

## Related Patterns

- `helm-nv-ingest-ngc-remote-subchart.md` -- the NV-Ingest subchart that consumes this secret for both image pulls and API access
