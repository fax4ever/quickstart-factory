---
name: helm-post-init-scaler-job-hook
description: Helm post-install hook Job that waits for init completion then scales a Deployment to target replicas
summary: "Delays scaling a Deployment until an initialization Job completes, avoiding resource contention during setup — e.g., LlamaStack starts at 1 replica for model/tool registration, then scales to targetReplicas (default 2) after init finishes. Use when a Deployment must remain at minimal replicas during a Helm post-install init phase (asset registration, DB migration) and only scale up after init succeeds; pairs with helm-init-job-multi-service-wait-chain for the init Job it depends on. Helm hook Job (post-install/post-upgrade, hook-weight \"10\", backoffLimit 3) uses bitnami/kubectl to poll init Job completion with TIMEOUT_SECONDS (600s default) then runs kubectl scale and kubectl wait; gated by llamastack.postInitScaling.enabled (default false) and auto-enabled via Makefile when REPLICA_COUNT is set, requires dedicated ServiceAccount with RBAC for get/watch Jobs and patch/scale Deployments. Scaler exits with error on init job failure to prevent scaling a broken deployment, hook-delete-policy before-hook-creation is required to avoid Job name collisions on upgrade, and the scaler verifies final replica count post-scale for confirmation logging."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [agents, model-serving]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Post-init scaler Job waits for init job then scales LlamaStack deployment from 1 to N replicas"
    approach: "A"
---

# Helm Post-Init Scaler Job Hook

## Overview

This pattern uses a Helm post-install/post-upgrade hook Job to delay scaling a Deployment until an initialization Job completes. The LlamaStack deployment starts with 1 replica (to avoid resource contention during registration), and after the init job finishes registering assets, a scaler Job uses `kubectl scale` and `kubectl wait` to bring the Deployment up to the target replica count.

## Pattern Description

The scaler Job is gated by a `llamastack.postInitScaling.enabled` flag in values.yaml. It uses `bitnami/kubectl:latest` to poll the init Job's completion status, then scales the target Deployment. Helm hook annotations ensure it runs after the main chart resources are installed. A dedicated ServiceAccount and RBAC (Role + RoleBinding) grant the Job permissions to get/watch Jobs and patch/get Deployments within its namespace.

## Implementation

### Scaler Job Template

```yaml
# helm/templates/llama-stack-post-init-scaler-job.yaml (excerpt)
{{- if .Values.llamastack.postInitScaling.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "self-service-agent.fullname" . }}-llama-stack-post-init-scaler
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "10"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  backoffLimit: 3
  template:
    spec:
      serviceAccountName: {{ include "self-service-agent.fullname" . }}-llama-stack-scaler
      containers:
      - name: scale-deployment
        image: bitnami/kubectl:latest
        env:
        - name: INIT_JOB_NAME
          value: "self-service-agent-init"
        - name: DEPLOYMENT_NAME
          value: "llamastack"
        - name: TARGET_REPLICAS
          value: {{ .Values.llamastack.postInitScaling.targetReplicas | quote }}
        - name: TIMEOUT_SECONDS
          value: "600"
        command:
        - /bin/bash
        - -c
        - |
          set -e
          # Poll init job completion
          while true; do
            job_status=$(kubectl get job "$INIT_JOB_NAME" -n "$NAMESPACE" \
              -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')
            if [ "$job_status" = "True" ]; then break; fi
            sleep 10
          done
          kubectl scale deployment "$DEPLOYMENT_NAME" -n "$NAMESPACE" \
            --replicas=$TARGET_REPLICAS
          kubectl wait --for=condition=available --timeout=300s \
            deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE"
{{- end }}
```

### Values Configuration

```yaml
# helm/values.yaml (excerpt)
llamastack:
  postInitScaling:
    enabled: false
    targetReplicas: 2
```

### Makefile Integration

The Makefile auto-enables post-init scaling when `REPLICA_COUNT` is set:

```makefile
# Makefile (excerpt)
helm_replica_count_args = \
    $(if $(REPLICA_COUNT),--set llamastack.postInitScaling.enabled=true,) \
    $(if $(REPLICA_COUNT),--set llamastack.postInitScaling.targetReplicas=$(REPLICA_COUNT),)
```

## Configuration

- **Key settings:** `llamastack.postInitScaling.enabled` toggles the scaler; `llamastack.postInitScaling.targetReplicas` sets the desired count; `TIMEOUT_SECONDS` (600s default) controls how long to wait for the init job
- **Defaults:** Disabled by default; set `REPLICA_COUNT` on the Makefile command line to auto-enable with that count
- **Dependencies:** Requires RBAC (Role + RoleBinding) for the scaler ServiceAccount to get/watch Jobs and patch/scale Deployments in the namespace (see `helm/templates/llama-stack-post-init-scaler-rbac.yaml`)

## Gotchas

- The scaler Job checks for init job failure and exits with error if the init job fails, preventing scaling of a broken deployment (see `helm/templates/llama-stack-post-init-scaler-job.yaml`)
- The `helm.sh/hook-delete-policy: before-hook-creation` ensures old scaler Jobs are cleaned up before a new one runs on upgrade, avoiding name collisions
- The scaler verifies the final replica count after scaling by reading `spec.replicas` from the deployment, providing a confirmation log line

## Related Patterns

- `helm-init-job-multi-service-wait-chain.md` -- init job patterns that the scaler depends on
