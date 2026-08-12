---
name: kserve-oauth-proxy-timeout-patch-job
description: Helm post-install Job that patches oauth-proxy upstream-timeout on KServe predictor deployments
summary: "Patches the oauth-proxy sidecar's --upstream-timeout on KServe predictor deployments via a Helm post-install/post-upgrade Job, solving the lack of native timeout configuration when security.enableAuth: true injects the proxy with a default too short for long-running LLM inference. Use when KServe InferenceServices with oauth-proxy need extended timeouts for model serving; the Job complements InferenceService annotations (security.opendatahub.io/oauth-proxy-upstream-timeout, haproxy.router.openshift.io/timeout, haproxy.router.openshift.io/timeout-tunnel) which alone do not configure the sidecar container args. The Job (hook-weight \"10\", hook-delete-policy: before-hook-creation/hook-succeeded, backoffLimit: 10) uses openshift/cli:latest to poll up to 10 minutes for <model-name>-predictor, then injects --upstream-timeout via oc get/jq/oc apply, with RBAC (ServiceAccount, Role, RoleBinding) at hook-weight \"5\" pre-install, route.oauthProxyUpstreamTimeout defaulting to 10m, and route.timeout to 600s. The oc get|jq|oc apply pipeline replaces the full deployment spec risking concurrent KServe controller overwrites, the fixed <model-name>-predictor naming requires duplicate Job templates per model chart (e.g., nemotron-model and qwen3-model), and the Job silently exits 0 if no oauth-proxy container or --upstream-timeout already exists (idempotency guards)."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, vllm]
  ai_pattern: [model-serving]
  platform: [kserve, vllm, rhoai, openshift]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Post-install Job patches oauth-proxy --upstream-timeout=10m on both nemotron and qwen3 model predictor deployments"
    approach: "A"
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Same pattern in vllm subchart: post-install Job at hook-weight 10 patches oauth-proxy --upstream-timeout=10m on peoplemesh-llm-predictor, conditional on security.enableAuth, with idempotency checks for container existence and existing timeout arg"
    approach: "A"
---

# KServe OAuth-Proxy Timeout Patch Job

## Overview

This pattern uses a Helm post-install/post-upgrade Job to patch the `--upstream-timeout` argument into the `oauth-proxy` sidecar container that OpenShift AI / KServe automatically injects into InferenceService predictor deployments. This is necessary because KServe-managed deployments do not expose a direct way to configure the oauth-proxy sidecar's timeout, and the default timeout is too short for long-running LLM inference requests.

## Pattern Description

When `security.enableAuth: true` is set on a KServe InferenceService, OpenShift AI injects an `oauth-proxy` sidecar container into the predictor deployment. This sidecar has no built-in mechanism to configure its upstream timeout. The pattern creates a Kubernetes Job (as a Helm hook) that waits for the predictor deployment to exist, then uses `oc get/jq/oc apply` to inject `--upstream-timeout=10m` into the oauth-proxy container's args array. The Job includes its own ServiceAccount, Role, and RoleBinding for the required RBAC permissions.

## Implementation

### The Patch Job

```yaml
# helm/nemotron-model/templates/oauth-proxy-patch-job.yaml
{{- if .Values.security.enableAuth }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Values.model.name }}-oauth-proxy-patch
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "10"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: 10
  template:
    spec:
      serviceAccountName: {{ .Values.model.name }}-patch-sa
      restartPolicy: OnFailure
      containers:
        - name: patch-oauth-proxy
          image: image-registry.openshift-image-registry.svc:5000/openshift/cli:latest
          command:
            - /bin/bash
            - -c
            - |
              set -e
              # Wait up to 10 minutes for the deployment to exist
              for i in {1..60}; do
                if oc get deployment {{ .Values.model.name }}-predictor \
                    -n {{ .Release.Namespace }} &>/dev/null; then
                  break
                fi
                sleep 10
              done
              # Skip if oauth-proxy container not found
              if ! oc get deployment {{ .Values.model.name }}-predictor \
                  -n {{ .Release.Namespace }} -o json | \
                  jq -e '.spec.template.spec.containers[] | select(.name=="oauth-proxy")' \
                  &>/dev/null; then
                exit 0
              fi
              # Skip if already configured
              if oc get deployment {{ .Values.model.name }}-predictor \
                  -n {{ .Release.Namespace }} -o json | \
                  jq -e '... | select(contains("--upstream-timeout"))' &>/dev/null; then
                exit 0
              fi
              # Patch: inject --upstream-timeout argument
              oc get deployment {{ .Values.model.name }}-predictor \
                  -n {{ .Release.Namespace }} -o json | \
                jq '.spec.template.spec.containers |= map(
                  if .name == "oauth-proxy"
                  then .args += ["--upstream-timeout={{ .Values.route.oauthProxyUpstreamTimeout }}"]
                  else . end)' | \
                oc apply -f -
{{- end }}
```

### RBAC for the Patch Job

The Job requires a dedicated ServiceAccount with permission to get, patch, and update deployments:

```yaml
# helm/nemotron-model/templates/oauth-proxy-patch-job.yaml (RBAC section)
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ .Values.model.name }}-patch-role
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "5"
    "helm.sh/hook-delete-policy": before-hook-creation
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "patch", "update"]
  - apiGroups: ["apps"]
    resources: ["deployments/status"]
    verbs: ["get"]
```

### InferenceService Timeout Annotations

The InferenceService itself also carries timeout annotations that affect the route and serving layers:

```yaml
# helm/nemotron-model/templates/inferenceservice.yaml (annotations)
annotations:
  security.opendatahub.io/oauth-proxy-upstream-timeout: {{ .Values.route.oauthProxyUpstreamTimeout | quote }}
  haproxy.router.openshift.io/timeout: {{ .Values.route.timeout | quote }}
  haproxy.router.openshift.io/timeout-tunnel: {{ .Values.route.timeout | quote }}
```

## Configuration

- **Key settings:** `route.oauthProxyUpstreamTimeout` (default `10m`), `route.timeout` (default `600s`), `security.enableAuth` (default `true`)
- **Defaults:** The Job is only created when `security.enableAuth` is true; the hook-delete-policy removes succeeded jobs and cleans up before re-creation
- **Dependencies:** Requires the OpenShift internal registry image `openshift/cli:latest` and the predictor deployment to be created by KServe (may take 5-10 minutes)

## Gotchas

- The Job waits up to 10 minutes for the predictor deployment to appear (`60 iterations * 10s sleep`), but if KServe fails to create the deployment, the Job exhausts its `backoffLimit: 10` and fails (see `helm/nemotron-model/templates/oauth-proxy-patch-job.yaml`)
- The predictor deployment name follows the KServe convention `<model-name>-predictor` -- this is not configurable and is determined by KServe, not the chart (see `helm/nemotron-model/templates/oauth-proxy-patch-job.yaml`)
- The patch uses `oc get ... -o json | jq ... | oc apply -f -` which replaces the entire deployment spec -- any concurrent modifications by KServe's controller could be overwritten (see `helm/nemotron-model/templates/oauth-proxy-patch-job.yaml`)
- Both nemotron-model and qwen3-model charts contain identical copies of this patch Job template (see `helm/qwen3-model/templates/oauth-proxy-patch-job.yaml`)
- The RBAC resources use `helm.sh/hook-weight: "5"` (pre-install) while the Job uses weight `"10"` (post-install), ensuring RBAC exists before the Job runs

## Related Patterns

- `openshift-oauth-proxy-sidecar.md` -- background on how oauth-proxy is injected into KServe deployments
- `makefile-feature-flag-conditional-deploy-model-extract.md` -- the Makefile that triggers model deployment and extracts config from the resulting InferenceService
