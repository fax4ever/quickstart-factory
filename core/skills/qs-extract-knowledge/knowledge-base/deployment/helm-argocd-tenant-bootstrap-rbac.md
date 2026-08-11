---
name: helm-argocd-tenant-bootstrap-rbac
description: Separate bootstrap Helm chart creating ArgoCD Application CR and ClusterRole for tenant self-service RAG deployment
summary: "Solves cluster-admin delegation of RAG quickstart deployment to tenants via GitOps by providing a tenant/bootstrap/ Helm chart that creates an ArgoCD Application CR (pointing to the quickstart Helm chart with inlined values) and a ClusterRole/ClusterRoleBinding granting the ArgoCD controller fine-grained RBAC for standard resources plus OpenShift/RHOAI CRDs (routes, notebooks, datasciencepipelinesapplications). Use when a cluster admin needs one-time bootstrap to enable tenant self-service ArgoCD-managed deployment with CRD-specific permissions — the ClusterRole scopes namespaces to get/list/watch/create (supporting CreateNamespace=true sync option) while granting full CRUD on workload resources, bound to gitops.applicationControllerServiceAccount. The Application CR is conditionally rendered via {{ if .Values.rag -}}, uses automated sync with prune:false and selfHeal:false, CreateNamespace=true, and retry limit 30 with exponential backoff (5s base, 2x factor, 5m max) configured through tenant.name, gitops.namespace, and rag.git.url/revision/path values. Common gotchas: prune:false means removed Helm chart resources require manual cleanup, the 30-retry exponential backoff is sized for slow CRD-dependent resources like InferenceServices, destination.namespace must be quoted ('{{ .Values.rag.namespace }}') to prevent YAML interpretation issues, and omitting rag values silently skips Application CR creation."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, argocd]
  ai_pattern: [rag]
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "tenant/bootstrap/ chart creates ArgoCD Application CR pointing to RAG Helm chart + ClusterRole/ClusterRoleBinding for ArgoCD controller with CRD-specific permissions (routes, notebooks, datasciencepipelinesapplications)"
    approach: "A"
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

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- the Helm chart that this ArgoCD Application CR deploys
