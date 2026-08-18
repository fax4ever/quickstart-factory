---
name: helm-argocd-tenant-bootstrap-rbac
description: Separate bootstrap Helm chart creating ArgoCD Application CR and ClusterRole for tenant self-service RAG deployment
summary: "Solves cluster-admin delegation of quickstart deployment to tenants via GitOps by providing a tenant/bootstrap/ Helm chart that creates an ArgoCD Application CR (pointing to the quickstart Helm chart with inlined values) and optionally a ClusterRole/ClusterRoleBinding granting the ArgoCD controller fine-grained RBAC for standard resources plus OpenShift/RHOAI CRDs (routes, notebooks, datasciencepipelinesapplications). Approach A (RAG) creates both Application CR and ClusterRole/ClusterRoleBinding (toggled by rbac.enabled) granting gitops.applicationControllerServiceAccount scoped namespace verbs (get/list/watch/create) plus full CRUD on workload resources and CRDs; Approach B (multimodal-compliance-monitor) creates only an Application CR using source.helm.parameters for per-tenant overrides (runtimeType openvino, kserve.gpu.enabled \"false\" as defensive override) alongside source.helm.values, with explicit releaseName (ppe-{{ tenant.name }}) affecting service DNS and Route hosts -- choose B when ArgoCD already has sufficient permissions. Both approaches use automated sync with prune:false/selfHeal:false, CreateNamespace=true, and retry limit 30 with exponential backoff (5s base, 2x factor, 5m max), conditionally rendered via {{ if .Values.rag/ppe -}} so omitting the conditional key silently skips Application CR creation. Common gotchas: prune:false means removed Helm chart resources require manual cleanup, source.helm.parameters override source.helm.values in Approach B, destination.namespace must be quoted ('{{ .Values.rag.namespace }}') to prevent YAML interpretation issues, and the 30-retry exponential backoff is sized for slow CRD-dependent resources like InferenceServices."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, argocd]
  ai_pattern: [rag, multimodal, model-serving]
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "tenant/bootstrap/ chart creates ArgoCD Application CR pointing to RAG Helm chart + ClusterRole/ClusterRoleBinding for ArgoCD controller with CRD-specific permissions (routes, notebooks, datasciencepipelinesapplications)"
    approach: "A"
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "tenant/bootstrap/ chart creates ArgoCD Application CR with source.helm.parameters overrides (runtimeType, GPU toggle) and inlined values block; no ClusterRole/ClusterRoleBinding"
    approach: "B"
---

# ArgoCD Tenant Bootstrap Helm Chart with RBAC

## Overview

This pattern provides a separate Helm chart (`tenant/bootstrap/`) that bootstraps a GitOps-managed deployment by creating an ArgoCD Application CR pointing to the main quickstart Helm chart, along with a ClusterRole and ClusterRoleBinding granting the ArgoCD application controller permission to manage the CRDs required by the quickstart.

## Pattern Description

The bootstrap chart is installed once by a cluster admin to enable tenant self-service. It creates two resources: an ArgoCD Application CR that points to the quickstart's Helm chart in a Git repo (with values inlined), and a ClusterRole with fine-grained RBAC permissions covering standard Kubernetes resources plus OpenShift/RHOAI-specific CRDs (routes, notebooks, datasciencepipelinesapplications). The Application CR uses automated sync with retry backoff but disables prune and selfHeal for safety.

## Implementation

### ArgoCD Application CR

The Application CR references the RAG Helm chart from its Git repository and inlines values from the bootstrap chart's own values:

```yaml
# tenant/bootstrap/templates/application-rag.yaml
{{ if .Values.rag -}}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {{ .Values.tenant.name }}
  namespace: {{ .Values.gitops.namespace }}
spec:
  project: default
  source:
    repoURL: {{ .Values.rag.git.url }}
    targetRevision: {{ .Values.rag.git.revision }}
    path: {{ .Values.rag.git.path }}
    helm:
      values: |
{{ toYaml .Values.rag.values | nindent 12 }}
  destination:
    server: https://kubernetes.default.svc
    namespace: '{{ .Values.rag.namespace }}'
  syncPolicy:
    automated:
      prune: false
      selfHeal: false
    syncOptions:
      - CreateNamespace=true
    retry:
      limit: 30
      backoff:
        duration: "5s"
        factor: 2
        maxDuration: "5m"
{{- end }}
```

### ClusterRole with CRD-Specific Permissions

The ClusterRole grants the ArgoCD controller access to both standard Kubernetes resources and OpenShift/RHOAI-specific CRDs:

```yaml
# tenant/bootstrap/templates/rbac-argocd-controller.yaml
{{- if .Values.rbac.enabled -}}
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ .Values.rbac.clusterRoleName }}
rules:
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "list", "watch", "create"]
  - apiGroups: [""]
    resources: ["configmaps", "persistentvolumeclaims", "secrets",
                "serviceaccounts", "services"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["route.openshift.io"]
    resources: ["routes"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["kubeflow.org"]
    resources: ["notebooks"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["datasciencepipelinesapplications.opendatahub.io"]
    resources: ["datasciencepipelinesapplications"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
{{- end }}
```

## Configuration

- **Key settings:** `tenant.name` (Application CR name), `gitops.namespace` (ArgoCD namespace), `rag.git.url`/`revision`/`path` (Helm chart location), `rag.namespace` (target deployment namespace), `rbac.enabled`/`clusterRoleName`, `gitops.applicationControllerServiceAccount`
- **Defaults:** Sync policy has `prune: false` and `selfHeal: false`; retry limit is 30 with exponential backoff (5s to 5m)
- **Dependencies:** Requires ArgoCD installed in the cluster; the referenced Git repo must be accessible from the cluster

## Gotchas

- The Application CR is conditionally rendered (`{{ if .Values.rag -}}`) -- if `rag` values are not provided, no Application is created
- The `prune: false` setting means ArgoCD will not delete resources that are removed from the Helm chart, which prevents accidental data loss but requires manual cleanup
- The ClusterRole includes `namespaces: create` permission, allowing ArgoCD to create the target namespace via `CreateNamespace=true` sync option
- The retry policy with 30 retries and exponential backoff (5s base, 2x factor, 5m max) accommodates slow CRD-dependent resources like InferenceServices that may take several minutes to reconcile
- The `destination.namespace` is quoted (`'{{ .Values.rag.namespace }}'`) to prevent YAML interpretation issues if the namespace contains special characters

---

## Approach B: Application CR with Helm Parameters Override, No RBAC (from multimodal-compliance-monitor)

### When to Use

When the ArgoCD controller already has sufficient permissions (no custom CRDs beyond standard KServe) and the bootstrap only needs to create an Application CR with helm parameter overrides for runtime type and GPU configuration. No ClusterRole or ClusterRoleBinding is needed.

### Differences from Approach A

- No ClusterRole or ClusterRoleBinding -- assumes ArgoCD controller already has required permissions
- Uses `source.helm.parameters` for individual `--set` overrides alongside `source.helm.values` for bulk values
- Application CR is conditionally rendered via `{{ if .Values.ppe -}}` (using `ppe` key instead of `rag`)
- Includes `releaseName` in the source.helm block to control the Helm release name

### Application CR with Parameters + Values

The Application CR uses both `source.helm.parameters` (for per-tenant overrides) and `source.helm.values` (for bulk inlined values):

```yaml
# tenant/bootstrap/templates/application-ppe.yaml
{{ if .Values.ppe -}}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {{ .Values.tenant.name }}
  namespace: {{ .Values.gitops.namespace }}
spec:
  source:
    repoURL: {{ .Values.ppe.git.url }}
    targetRevision: {{ .Values.ppe.git.revision }}
    path: {{ .Values.ppe.git.path }}
    helm:
      releaseName: "ppe-{{ .Values.tenant.name }}"
      parameters:
        - name: openshift.sharedHost
          value: "ppe-{{ .Values.tenant.name }}-{{ .Values.ppe.namespace }}.{{ .Values.deployer.domain }}"
        - name: modelServing.runtimeType
          value: openvino
        - name: modelServing.kserve.gpu.enabled
          value: "false"
      values: |
{{ toYaml .Values.ppe.values | nindent 12 }}
  syncPolicy:
    automated:
      prune: false
      selfHeal: false
    syncOptions:
      - CreateNamespace=true
    retry:
      limit: 30
      backoff:
        duration: "5s"
        factor: 2
        maxDuration: "5m"
{{- end }}
```

### Gotchas (Approach B)

- The `parameters` block overrides values set in the `values` block -- the comment in the template notes "Helm --set overrides spec.source.helm.values: OVMS (CPU) path, not KServe/Triton"
- The `modelServing.kserve.gpu.enabled: "false"` parameter is documented as "Redundant if runtimeType stays openvino; protects if runtimeType is ever switched to kserve" -- a defensive override
- The `releaseName` field constructs tenant-prefixed names (`ppe-{{ .Values.tenant.name }}`), which affects service DNS names and Route hosts throughout the deployment
- Unlike Approach A, there is no `rbac.enabled` toggle because no RBAC resources are created

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| RBAC bootstrapping | ClusterRole + ClusterRoleBinding for CRDs | None (relies on existing ArgoCD permissions) |
| Helm value mechanism | `source.helm.values` only | `source.helm.parameters` + `source.helm.values` |
| Conditional key | `{{ if .Values.rag -}}` | `{{ if .Values.ppe -}}` |
| Release naming | Default | Explicit `releaseName` with tenant prefix |
| CRD permissions | Routes, Notebooks, DSPipelines | Not managed |

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- the Helm chart that Approach A's ArgoCD Application CR deploys
- `helm-umbrella-mixed-remote-local-committed-deps.md` -- the Helm chart (Approach C) that Approach B's ArgoCD Application CR deploys
