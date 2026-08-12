---
name: helm-limitrange-ephemeral-storage-namespace-defaults
description: Helm-managed LimitRange setting default and max ephemeral storage limits for all containers in namespace
summary: "Deploys a Kubernetes LimitRange resource named storage-limitrange via Helm to enforce namespace-wide default, min, and max ephemeral-storage limits on all containers, preventing runaway disk usage from ML workloads that download large models or datasets at runtime. Use when containers in a namespace need consistent ephemeral-storage guardrails without per-pod configuration — single approach with hardcoded template values (no values.yaml parameterization), sourced from the product-recommender-system quickstart. Template at helm/<chart>/templates/limitrange-storage.yaml sets Container-type limits of max: 50Gi, default: 15Gi, defaultRequest: 1Gi, min: 100Mi with namespace via {{ .Release.Namespace }}; changing limits requires direct template edits. The 15Gi default limit applies to ALL containers including initContainers and sidecars (potentially over-provisioning lightweight containers), and only ephemeral-storage is covered — CPU and memory limits must be set separately per-container in the Deployment spec via values.yaml."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  platform: [openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "LimitRange for ephemeral storage with 50Gi max, 15Gi default, 1Gi default request, 100Mi min for all containers"
    approach: "A"
---

# Helm LimitRange for Ephemeral Storage Namespace Defaults

## Overview

Deploys a Kubernetes LimitRange resource via Helm to set namespace-wide default, min, and max ephemeral storage limits for all containers. This prevents pods from consuming excessive ephemeral storage on nodes, which is important for ML workloads that may download large models or datasets at runtime.

## Pattern Description

The LimitRange is deployed as part of the main application Helm chart and applies to all containers in the release namespace. It sets a generous 50Gi max with 15Gi default limit and 1Gi default request, providing headroom for ML model downloads and training data while preventing runaway disk usage.

## Implementation

### LimitRange Template

```yaml
# helm/product-recommender-system/templates/limitrange-storage.yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: storage-limitrange
  namespace: {{ .Release.Namespace }}
spec:
  limits:
  - max:
      ephemeral-storage: "50Gi"
    min:
      ephemeral-storage: "100Mi"
    default:
      ephemeral-storage: "15Gi"
    defaultRequest:
      ephemeral-storage: "1Gi"
    type: Container
```

## Configuration

- **Key settings:** `max: 50Gi`, `default: 15Gi`, `defaultRequest: 1Gi`, `min: 100Mi` -- all for ephemeral-storage on Container type
- **Defaults:** Values are hardcoded in the template with no values.yaml overrides
- **Dependencies:** None; applies automatically to all pods in the namespace

## Gotchas

- The LimitRange has no values.yaml parameterization, so changing limits requires editing the template directly.
- The 15Gi default limit applies to ALL containers in the namespace, including initContainers and sidecars, which may be too generous for lightweight containers but necessary for ML containers downloading models.
- This only covers ephemeral storage, not CPU or memory -- those are set per-container in the Deployment spec via `values.yaml`.

## Related Patterns

- `helm-hook-initcontainer-psql-table-existence-poll.md` — containers in this namespace that inherit these ephemeral storage limits
