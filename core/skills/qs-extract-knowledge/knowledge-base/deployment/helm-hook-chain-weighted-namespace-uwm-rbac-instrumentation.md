---
name: helm-hook-chain-weighted-namespace-uwm-rbac-instrumentation
description: Chain of 5+ weighted Helm hook Jobs for namespace creation, UWM enablement, RBAC setup, and instrumentation
summary: "Orchestrates cross-namespace OpenShift infrastructure setup — user workload monitoring + Alertmanager enablement (patching cluster-monitoring-config), namespace creation, OpenTelemetry Python auto-instrumentation annotation, and Loki/Korrel8r RBAC binding — via a chain of 5+ weighted Helm hook Jobs running inline bash scripts on ose-cli with securityContext.runAsNonRoot and seccompProfile RuntimeDefault. Use when an umbrella Helm chart must perform imperative cluster operations (ConfigMap patching, namespace creation, RBAC binding) in strict order before and after subchart installation; prefer helm-hook-configmap-mounted-script-jobs when scripts are complex enough to warrant ConfigMap-mounted files instead of inline bash. Each Job's RBAC (SA + ClusterRole + CRB) is created at weight N-5 relative to the Job itself; pre-install hooks run at weights -20 to -5 (UWM enabler patches cluster-monitoring-config, namespace-setup uses lookup-free approach to create namespaces from global.observabilityNamespace/lokiNamespace/korrel8rNamespace, instrumentation-patcher annotates namespace) and post-install hooks at +5 to +10 bind Loki collector SA to operator-managed ClusterRoles via oc apply with hook-delete-policy: before-hook-creation,hook-succeeded for idempotency. Instrumentation patcher MUST be pre-install (not post-install) or application pods start uninstrumented requiring manual restart; Loki RBAC uses oc apply instead of Helm template rendering to avoid ownership conflicts during make-install-to-operator transitions; namespaces must have helm.sh/resource-policy: keep to persist after Helm uninstall; cluster-logging operator must have already created the ClusterRoles that Loki RBAC binds to."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, opentelemetry]
  ai_pattern: []
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "5 hook Jobs with weights -15 to +10 for namespace setup, UWM enablement, instrumentation patching, Loki RBAC, and Korrel8r RBAC"
    approach: "A"
---

# Helm Hook Chain with Weighted Namespace, UWM, RBAC, and Instrumentation Jobs

## Overview

This pattern uses a chain of Helm pre-install and post-install hook Jobs with `helm.sh/hook-weight` annotations to orchestrate cross-namespace infrastructure setup in a specific order. Each Job creates its own ServiceAccount and RBAC resources as hook-scoped resources, then runs inline bash scripts using the `ose-cli` image. The chain handles namespace creation, user workload monitoring enablement, OpenTelemetry instrumentation annotation, and Loki/Korrel8r RBAC binding.

## Pattern Description

The aiobs-stack umbrella chart uses 5+ hook Jobs that run inline bash scripts (not ConfigMap-mounted scripts) to perform imperative cluster operations. Each Job follows a consistent structure: ServiceAccount + ClusterRole + ClusterRoleBinding (at weight N-5) and the Job itself (at weight N). The hooks are split into pre-install (infrastructure must exist before subcharts deploy) and post-install (RBAC bindings must reference resources created by subcharts). All use `hook-delete-policy: before-hook-creation,hook-succeeded` for idempotency.

## Implementation

### Hook Weight Ordering

The hooks execute in this order:

| Weight | Phase | Job Name | Purpose |
|--------|-------|----------|---------|
| -20 | pre-install | uwm-enabler (RBAC) | Create SA, ClusterRole, CRB for UWM enabler |
| -15 | pre-install | uwm-enabler (Job) | Enable user workload monitoring + Alertmanager |
| -10 | pre-install | instrumentation-patcher (RBAC) | Create SA for namespace annotation |
| -5 | pre-install | namespace-setup (Job) | Create required namespaces |
| -5 | pre-install | instrumentation-patcher (Job) | Annotate namespace for Python auto-instrumentation |
| +5 | post-install | loki-rbac-creator (RBAC) | Create SA for Loki RBAC |
| +10 | post-install | loki-rbac-creator (Job) | Create Loki collector RBAC bindings |
| +10 | post-install | loki-korrel8r-rbac (Job) | Add Korrel8r/MCP SA to logging CRB |

### UWM Enabler Job (pre-install, weight -15)

Enables user workload monitoring and Alertmanager by patching cluster-scoped ConfigMaps:

```yaml
# deploy/helm/aiobs-stack/templates/uwm-enabler-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Release.Name }}-uwm-enabler
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "-15"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: {{ .Release.Name }}-uwm-enabler
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: enabler
        image: registry.redhat.io/openshift4/ose-cli:latest
        command:
        - /bin/bash
        - -c
        - |
          set -e
          # Check if user workload monitoring is already enabled
          if oc get configmap cluster-monitoring-config -n openshift-monitoring \
             -o jsonpath='{.data.config\.yaml}' 2>/dev/null | grep -q "enableUserWorkload: true"; then
            echo "User workload monitoring already enabled - skipping"
          else
            oc apply -f - <<EOF
          apiVersion: v1
          kind: ConfigMap
          metadata:
            name: cluster-monitoring-config
            namespace: openshift-monitoring
          data:
            config.yaml: |
              enableUserWorkload: true
          EOF
          fi
```

### Namespace Setup Job (pre-install, weight -5)

Creates required namespaces for infrastructure subcharts:

```yaml
# deploy/helm/aiobs-stack/templates/namespace-hook-job.yaml
# Uses lookup-free approach because lookup doesn't work reliably in Helm operators
containers:
- name: namespace-creator
  image: registry.redhat.io/openshift4/ose-cli:latest
  command:
  - /bin/bash
  - -c
  - |
    set -euo pipefail
    create_namespace_if_missing() {
      local ns_name="$1"
      local description="$2"
      if kubectl get namespace "$ns_name" &>/dev/null; then
        echo "Namespace '$ns_name' already exists"
      else
        cat <<EOF | kubectl apply -f -
    apiVersion: v1
    kind: Namespace
    metadata:
      name: $ns_name
      labels:
        app.kubernetes.io/managed-by: {{ .Release.Service }}
      annotations:
        helm.sh/resource-policy: keep
    EOF
      fi
    }
    create_namespace_if_missing "{{ .Values.global.observabilityNamespace }}" "..."
    create_namespace_if_missing "{{ .Values.global.korrel8rNamespace }}" "..."
    create_namespace_if_missing "{{ .Values.global.lokiNamespace }}" "..."
```

### Instrumentation Patcher Job (pre-install, weight -5)

Annotates the namespace for Python auto-instrumentation. Must run as pre-install to avoid race condition where pods start without instrumentation:

```yaml
# deploy/helm/aiobs-stack/templates/instrumentation-patcher-job.yaml
# CRITICAL: Must run as pre-install (not post-install)
# Execution order:
#   1. pre-install weight -10: Instrumentation resource created
#   2. pre-install weight -5:  THIS JOB - annotates namespace
#   3. main install weight 0:  Application pods created (WITH instrumentation)
containers:
- name: patcher
  image: registry.redhat.io/openshift4/ose-cli:latest
  command:
  - /bin/bash
  - -c
  - |
    set -e
    oc annotate namespace {{ .Release.Namespace }} \
      instrumentation.opentelemetry.io/inject-python="true" --overwrite
```

### Loki RBAC Creator Job (post-install, weight +10)

Creates Loki collector RBAC via `oc apply` to avoid Helm ownership conflicts when transitioning from make install to operator:

```yaml
# deploy/helm/aiobs-stack/templates/loki-rbac-job.yaml
containers:
- name: rbac-creator
  image: registry.redhat.io/openshift4/ose-cli:latest
  command:
  - /bin/bash
  - -c
  - |
    set -e
    # ClusterRoles already exist - managed by cluster-logging operator
    # Only create ServiceAccount and ClusterRoleBindings
    for role in collect-application-logs collect-infrastructure-logs \
                collect-audit-logs logging-collector-logs-writer; do
      cat <<EOF | oc apply -f -
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRoleBinding
    metadata:
      name: $role
      labels:
        app.kubernetes.io/managed-by: Helm
      annotations:
        meta.helm.sh/release-name: {{ .Release.Name }}
    roleRef:
      apiGroup: rbac.authorization.k8s.io
      kind: ClusterRole
      name: $role
    subjects:
    - kind: ServiceAccount
      name: collector
      namespace: openshift-logging
    EOF
    done
```

## Configuration

- **Key settings:** `global.observabilityNamespace` (default: observability-hub), `global.lokiNamespace` (default: openshift-logging), `global.korrel8rNamespace` (default: openshift-cluster-observability-operator), `instrumentation.enabled` (default: true)
- **Defaults:** All pre-install Jobs run unconditionally; the instrumentation patcher is gated by `instrumentation.enabled`
- **Dependencies:** Requires `ose-cli` image from `registry.redhat.io/openshift4/ose-cli:latest`; cluster-logging operator must have created the ClusterRoles that the Loki RBAC job binds to

## Gotchas

- The instrumentation patcher MUST run as pre-install, not post-install -- if it ran post-install, pods would start without instrumentation and require a manual restart (documented in the template comments)
- Loki RBAC uses `oc apply` (not Helm template rendering) to avoid ownership conflicts when transitioning between `make install` and operator-based deployment -- existing resources created by `make install` can be adopted by the operator
- The namespace setup Job uses `helm.sh/resource-policy: keep` annotation on created namespaces so they persist after Helm uninstall
- Hook RBAC resources (ServiceAccount, ClusterRole, ClusterRoleBinding) are created at weight N-5 relative to their Job to ensure they exist before the Job starts

## Related Patterns

- `helm-hook-configmap-mounted-script-jobs.md` -- similar pattern using ConfigMap-mounted scripts instead of inline bash
- `helm-operator-umbrella-all-local-singleton-validation.md` -- the umbrella chart consuming these hooks
