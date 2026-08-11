---
name: helm-olm-subscription-crd-lookup-securityoperator
description: Helm chart managing full OLM operator lifecycle with live CRD lookup to conditionally render custom CR
summary: "Solves deploying an OLM-managed operator and its custom resource from a single Helm chart when the CRD only registers after CSV installation, using a two-phase install/upgrade workflow with live `lookup` to conditionally render the CR. Use when a Helm chart must own both the OLM Subscription/OperatorGroup and a CR whose CRD does not exist at first install; `securityOperator.waitForCrd: true` enables the lookup guard, `operator.subscriptionEnabled` toggles the Subscription, and `operator.operatorGroupAllNamespaces` controls AllNamespaces vs OwnNamespace OperatorGroup mode. Critical pattern: use `lookup \"apiextensions.k8s.io/v1\" \"CustomResourceDefinition\" \"\" $crdName` instead of `.Capabilities.APIVersions` which Helm silently omits for newly registered API groups on upgrade; namespaces carry `helm.sh/resource-policy: keep` and registry secrets replicate across operator and moderator namespaces via `range tuple`. Gotchas: `moderator.baseUrl` and `moderator.license` are required values that fail Helm explicitly if missing, namespaces survive `helm uninstall` requiring manual `oc delete project`, and GPU tolerations must be merged via `inference.kubeaiGpuTolerations.enabled` or model pods stay Pending on tainted OpenShift nodes with `nvidia.com/gpu=true`."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [guardrails]
  platform: [openshift]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "Helm chart deploys OLM Subscription, OperatorGroup, Namespaces, regcred Secrets, SecurityOperator CR with live CRD lookup"
    approach: "A"
---

# Helm OLM Subscription with CRD Lookup for SecurityOperator

## Overview

This pattern uses a single Helm chart to manage the entire OLM operator lifecycle: creating namespaces, deploying an OperatorGroup and Subscription, waiting for the operator to register its CRD, and then conditionally rendering a custom resource (SecurityOperator). The key mechanism is a live `lookup` call that checks whether the CRD exists at install time, enabling a two-phase Helm install workflow.

## Pattern Description

The `f5-ai-security` Helm chart deploys the F5 AI Security Operator via OLM by rendering an OperatorGroup and Subscription in the operator namespace. Because the operator's CRD (`securityoperators.ai.security.f5.com`) only becomes available after the CSV is installed, the chart uses `lookup` to check for CRD existence at render time. On the first `helm install`, the SecurityOperator CR template is skipped (CRD not yet registered). After the CSV succeeds and registers the CRD, a second `helm upgrade` renders and applies the SecurityOperator CR. The chart manages four namespaces (operator, moderator, prefect, inference) and deploys registry secrets across them.

## Implementation

### SecurityOperator CR with Live CRD Lookup

The chart uses `lookup` instead of `.Capabilities.APIVersions` because Helm sometimes misses newly registered API groups on upgrade:

```yaml
# deploy/helm/f5-ai-security/templates/40-security-operator.yaml
{{- if .Values.securityOperator.enabled }}
{{- $crdName := "securityoperators.ai.security.f5.com" }}
{{- $crd := lookup "apiextensions.k8s.io/v1" "CustomResourceDefinition" "" $crdName }}
{{- if or (not .Values.securityOperator.waitForCrd) $crd }}
apiVersion: ai.security.f5.com/v1alpha1
kind: SecurityOperator
metadata:
  name: {{ .Values.securityOperator.name }}
  namespace: {{ $modNs }}
spec:
  registryAuth:
    enabled: true
    existingSecret: {{ .Values.registry.secretName | quote }}
  postgresql:
    enabled: true
  moderator:
    enabled: true
    values:
      env:
        CAI_MODERATOR_BASE_URL: {{ $base | quote }}
{{- end }}
{{- end }}
```

### OLM Subscription Template

```yaml
# deploy/helm/f5-ai-security/templates/20-subscription.yaml
{{- if .Values.operator.subscriptionEnabled }}
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {{ .Values.operator.name }}
  namespace: {{ .Values.productNamespaces.operator }}
spec:
  channel: {{ .Values.operator.channel | quote }}
  installPlanApproval: {{ .Values.operator.installPlanApproval }}
  name: {{ .Values.operator.name }}
  source: {{ .Values.operator.source | quote }}
  sourceNamespace: {{ .Values.operator.sourceNamespace | quote }}
  startingCSV: {{ .Values.operator.startingCSV | quote }}
{{- end }}
```

### OperatorGroup with AllNamespaces Mode

The F5 AI Security operator v0.8.x CSV supports only AllNamespaces install mode, so the OperatorGroup must have an empty spec:

```yaml
# deploy/helm/f5-ai-security/templates/10-operator-group.yaml
{{- if .Values.operator.operatorGroupAllNamespaces }}
spec: {}
{{- else }}
spec:
  targetNamespaces:
    - {{ .Values.productNamespaces.operator }}
{{- end }}
```

### Multi-Namespace Resource Distribution

Namespaces are created with `helm.sh/resource-policy: keep` to survive Helm uninstall, and registry secrets are replicated to both operator and moderator namespaces:

```yaml
# deploy/helm/f5-ai-security/templates/30-secret-regcred.yaml
{{- range tuple $op $mod }}
---
apiVersion: v1
kind: Secret
metadata:
  name: {{ $.Values.registry.secretName }}
  namespace: {{ . }}
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: {{ $doc | toJson | quote }}
{{- end }}
```

## Configuration

- **Key settings:** `securityOperator.waitForCrd: true` (default) enables the CRD lookup guard; `operator.subscriptionEnabled` toggles OLM Subscription; `operator.operatorGroupAllNamespaces` controls AllNamespaces vs OwnNamespace mode
- **Defaults:** Operator channel is `stable`, source is `certified-operators`, install plan approval is `Automatic`; four product namespaces default to `f5-ai-sec`, `cai-moderator`, `prefect`, `f5-ai-sec-inference`
- **Dependencies:** Requires OLM (Operator Lifecycle Manager) on the cluster; the `certified-operators` CatalogSource must contain the `f5-ai-security-operator` package

## Gotchas

- The comment in `40-security-operator.yaml` explicitly warns against using `.Capabilities.APIVersions` for CRD detection: "Helm often omits newly registered API groups on upgrade, so the SecurityOperator manifest is skipped even after CSV Succeeded"
- `securityOperator.moderator.baseUrl` and `securityOperator.moderator.license` are both `required` values -- Helm will fail with explicit error messages if either is missing (see `40-security-operator.yaml` lines 12-13)
- Namespaces use `helm.sh/resource-policy: keep` annotation, so `helm uninstall` does not delete them -- explicit `oc delete project` is needed for cleanup (see `00-namespaces.yaml` line 8)
- The `securityOperator.inference.kubeaiGpuTolerations.enabled` flag merges GPU tolerations into the operator's inference Helm values because F5 defaults may omit tolerations on some profiles (e.g., `nvidia-gpu-a10g`), leaving model pods Pending on OpenShift GPU nodes with `nvidia.com/gpu=true` taint (see `values.yaml` lines 58-63)

## Related Patterns

- `helm-scc-pre-apply-sed-placeholder-adoption.md` -- pre-applying the inference model SCC that the operator SA cannot create
- `makefile-two-phase-helm-crd-wait-scc-preapply.md` -- Makefile target that orchestrates the two-phase Helm install
- `openshift-scc-anyuid-rolebinding.md` -- SCC bindings for operator service accounts
