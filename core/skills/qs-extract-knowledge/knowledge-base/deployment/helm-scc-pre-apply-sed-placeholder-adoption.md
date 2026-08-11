---
name: helm-scc-pre-apply-sed-placeholder-adoption
description: Pre-applied cluster-scoped SCC with sed placeholder substitution and Helm ownership annotations for operator adoption
summary: "Solves deploying a cluster-scoped OpenShift SecurityContextConstraints when the operator's controller-manager ServiceAccount lacks SCC create permissions, as seen in the F5 AI Security operator whose KubeAI inference component requires root-capable model pods via runAsUser: RunAsAny. Use when an operator-managed Helm release needs a pre-existing cluster-scoped SCC that it cannot create itself -- the SCC is pre-applied via Makefile sed -e \"s|...|...|g\" | oc apply before helm install, with Helm adoption annotations (meta.helm.sh/release-name, meta.helm.sh/release-namespace, managed-by: Helm label) so the release imports it rather than failing with \"exists and cannot be imported.\" Critical pattern: SCC YAML stored in extras/ with __PLACEHOLDER__ variables for namespace and release name, companion RBAC template grants operator SA patch/update but not create on the named SCC (f5-ai-sec-inference-models), and controllerManagerRbac.inferenceModelsSccName in values.yaml must exactly match the SCC metadata.name. Common gotcha: omitting meta.helm.sh/release-* annotations or managed-by: Helm label causes helm install to fail on the pre-existing SCC; the oc get scc restricted-v2 guard skips the step on non-OpenShift clusters, and SKIP_F5_INFERENCE_SCC=1 disables it entirely."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [guardrails]
  platform: [openshift]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "SCC pre-applied via oc apply with sed placeholders; Helm annotations enable operator's inference release to adopt it"
    approach: "A"
---

# Pre-Applied SCC with sed Placeholders and Helm Adoption

## Overview

This pattern solves the problem of an operator needing a cluster-scoped SecurityContextConstraints resource that its own ServiceAccount lacks permission to create. The SCC is stored as a Helm-annotated YAML file with shell-variable placeholders, pre-applied by the Makefile via `sed | oc apply` before the operator reconciles, and adopted by the operator's Helm release through matching `meta.helm.sh/release-name` and `meta.helm.sh/release-namespace` annotations.

## Pattern Description

The F5 AI Security operator's inference component (KubeAI) deploys model pods that need to run as root, requiring a custom SCC. The operator's controller-manager ServiceAccount cannot create SecurityContextConstraints on OpenShift. The solution: store the SCC definition in `extras/openshift-inference-models-scc.yaml` with `__PLACEHOLDER__` variables, apply it with `sed` substitution in the Makefile, and annotate it with the operator's Helm release name so the operator's `helm install` can import (adopt) it rather than failing with "exists and cannot be imported."

## Implementation

### SCC Template with Placeholders and Helm Annotations

```yaml
# deploy/helm/f5-ai-security/extras/openshift-inference-models-scc.yaml
apiVersion: security.openshift.io/v1
kind: SecurityContextConstraints
metadata:
  name: f5-ai-sec-inference-models
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: __F5_INFERENCE_HELM_RELEASE_NAME__
    meta.helm.sh/release-namespace: __F5_INFERENCE_HELM_RELEASE_NAMESPACE__
allowPrivilegeEscalation: false
readOnlyRootFilesystem: false
runAsUser:
  type: RunAsAny
seLinuxContext:
  type: MustRunAs
seccompProfiles:
  - runtime/default
requiredDropCapabilities:
  - ALL
users:
  - system:serviceaccount:__F5_INFERENCE_NAMESPACE__:f5-ai-sec-inference-models
```

### Makefile sed Substitution and Application

```makefile
# deploy/helm/Makefile (install-f5-ai-security, lines 689-699)
if [ "$(SKIP_F5_INFERENCE_SCC)" != "1" ] && oc get scc restricted-v2 >/dev/null 2>&1; then \
    INFER_SCC="$(CURDIR)/$(F5_AI_SECURITY_CHART)/extras/openshift-inference-models-scc.yaml"; \
    if [ -f "$$INFER_SCC" ]; then \
        sed -e "s|__F5_INFERENCE_NAMESPACE__|$(F5_INFERENCE_NS)|g" \
            -e "s|__F5_INFERENCE_HELM_RELEASE_NAME__|$(F5_INFERENCE_HELM_RELEASE)|g" \
            -e "s|__F5_INFERENCE_HELM_RELEASE_NAMESPACE__|$(F5_INFERENCE_NS)|g" \
            "$$INFER_SCC" | oc apply -f -; \
    fi; \
fi;
```

### Controller-Manager RBAC for SCC Patching

The companion RBAC template grants the operator's controller-manager SA permission to patch and update (but not create) the pre-applied SCC:

```yaml
# deploy/helm/f5-ai-security/templates/56-controller-manager-rbac.yaml (excerpt)
rules:
  - apiGroups: ["security.openshift.io"]
    resources: ["securitycontextconstraints"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["security.openshift.io"]
    resources: ["securitycontextconstraints"]
    resourceNames:
      - {{ .Values.controllerManagerRbac.inferenceModelsSccName | quote }}
    verbs: ["patch", "update"]
```

## Configuration

- **Key settings:** `SKIP_F5_INFERENCE_SCC` (default 0, set to 1 to skip); `F5_INFERENCE_NS` (default `f5-ai-sec-inference`); `F5_INFERENCE_HELM_RELEASE` (default `f5-ai-sec-inference`); `controllerManagerRbac.inferenceModelsSccName` in values.yaml (must match the SCC metadata.name)
- **Defaults:** The SCC name `f5-ai-sec-inference-models` must match what the operator's inference Helm chart expects; `runAsUser: RunAsAny` allows root containers
- **Dependencies:** Requires cluster-admin privileges for `oc apply` of the SCC; the OpenShift `restricted-v2` SCC check confirms the cluster is OpenShift (not vanilla K8s)

## Gotchas

- The file comment explains the adoption requirement: "Helm ownership must match the operator-managed release `f5-ai-sec-inference` in the inference namespace, or Helm fails with 'exists and cannot be imported into the current release'" (see `extras/openshift-inference-models-scc.yaml` lines 6-7)
- The SCC is only applied when `restricted-v2` SCC exists (`oc get scc restricted-v2`), which is an OpenShift-specific check -- this prevents the step from running on vanilla Kubernetes where SCCs do not exist
- The `values.yaml` field `controllerManagerRbac.inferenceModelsSccName` must be kept in sync with the SCC file's `metadata.name` (see `values.yaml` line 85: "Must match extras/openshift-inference-models-scc.yaml metadata.name")
- The `app.kubernetes.io/managed-by: Helm` label and `meta.helm.sh/release-*` annotations are critical for Helm adoption -- without them, the operator's `helm install` would fail because the SCC already exists but is not recognized as part of any Helm release

## Related Patterns

- `makefile-two-phase-helm-crd-wait-scc-preapply.md` -- the Makefile target that orchestrates this pre-application step
- `helm-olm-subscription-crd-lookup-securityoperator.md` -- the chart that needs this SCC to be pre-applied
- `openshift-scc-anyuid-rolebinding.md` -- other SCC grant patterns for different service accounts
