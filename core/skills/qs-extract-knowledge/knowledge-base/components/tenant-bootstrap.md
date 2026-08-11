---
name: tenant-bootstrap
description: Helm chart that creates an ArgoCD Application for tenant-scoped GitOps deployment of a quickstart
summary: "Provisions an ArgoCD Application CR for tenant-scoped GitOps deployment of a quickstart Helm chart, serving as the third layer in the RHDP onboarding flow (infra, platform, tenant), with creation conditionally gated by `{{ if .Values.rag }}` — setting rag to empty skips it entirely. Use when wiring a quickstart into ArgoCD with Helm value passthrough (`rag.values` piped via `toYaml` into `spec.source.helm.values`) and git source (`rag.git.url`/`revision`/`path`); enable `rbac.enabled` to grant the ArgoCD controller in `gitops.namespace` (default openshift-gitops) permissions for RHOAI-specific CRDs (kubeflow.org notebooks, datasciencepipelinesapplications.opendatahub.io). Critical config: `tenant.name` becomes the Application name, automated sync sets `CreateNamespace=true` with 30-retry exponential backoff (5s/factor-2/max-5m), but `prune: false` and `selfHeal: false` require manual orphan cleanup. RBAC ClusterRole produces harmless warnings on non-RHOAI clusters missing those CRDs, and the aggressive 30-retry backoff can mask persistent sync failures for extended periods before surfacing errors."
metadata:
  type: component
tags:
  tech_stack: [helm, argocd]
  ai_pattern: []
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Tenant bootstrap chart creating an ArgoCD Application that deploys the RAG quickstart with Helm value passthrough and optional RBAC for the ArgoCD controller"
    approach: "A"
---

# Tenant Bootstrap

## Overview

Tenant Bootstrap is a lightweight Helm chart that provisions an ArgoCD `Application` custom resource for tenant-scoped GitOps deployment of a quickstart. It sits within a three-layer RHDP onboarding structure (`infra/bootstrap`, `platform/bootstrap`, `tenant/bootstrap`) and is responsible for wiring the quickstart's main Helm chart into ArgoCD with the correct git source, target namespace, Helm values passthrough, and optional RBAC grants for the ArgoCD application controller.

## Tech Stack & Dependencies

- **Runtime:** Helm chart (apiVersion v2, type: application)
- **Container image:** None (pure Kubernetes manifest chart)
- **Key dependencies:** ArgoCD (`argoproj.io/v1alpha1` Application CRD), the quickstart's main Helm chart (referenced by git URL/path)
- **Helm subchart:** None (standalone chart)

## Key Patterns

### Conditional ArgoCD Application Creation

The entire Application manifest is guarded by `{{ if .Values.rag }}`, making deployment optional by setting the `rag` values block to empty. The Application points to the quickstart's Helm chart in git and passes Helm values through using `toYaml`.

```yaml
# tenant/bootstrap/templates/application-rag.yaml
{{ if .Values.rag -}}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {{ .Values.tenant.name }}
  namespace: {{ .Values.gitops.namespace }}
spec:
  source:
    repoURL: {{ .Values.rag.git.url }}
    targetRevision: {{ .Values.rag.git.revision }}
    path: {{ .Values.rag.git.path }}
    helm:
      values: |
{{ toYaml .Values.rag.values | nindent 12 }}
{{- end }}
```

### Helm Values Passthrough

The bootstrap chart accepts nested Helm values under `rag.values` and passes them through to the downstream quickstart chart via the ArgoCD Application's `spec.source.helm.values`. This allows tenant-specific overrides (e.g., enabling/disabling subcharts, setting API keys) without forking the quickstart chart.

```yaml
# tenant/bootstrap/values.yaml
rag:
  namespace: rag
  git:
    url: https://github.com/rh-ai-quickstart/RAG.git
    revision: main
    path: deploy/helm/rag
  values:
    llm-service:
      enabled: false
      secret:
        hf_token: ""
    llama-stack:
      secrets:
        TAVILY_SEARCH_API_KEY: "paste-your-key-here"
```

### Automated Sync with Retry Backoff

The ArgoCD Application uses automated sync with retry backoff for resilience, but disables prune and selfHeal to avoid unintended resource deletion during initial onboarding.

```yaml
# tenant/bootstrap/templates/application-rag.yaml
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
```

### Optional RBAC for ArgoCD Controller

When `rbac.enabled` is true, the chart creates a ClusterRole and ClusterRoleBinding granting the ArgoCD application controller ServiceAccount permissions to manage the resources the quickstart needs (namespaces, deployments, statefulsets, jobs, routes, notebooks, data science pipelines).

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
  - apiGroups: ["kubeflow.org"]
    resources: ["notebooks"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["datasciencepipelinesapplications.opendatahub.io"]
    resources: ["datasciencepipelinesapplications"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
{{- end }}
```

### Three-Layer RHDP Onboarding Structure

The tenant bootstrap chart is designed as the third step in a layered onboarding flow documented in `docs/RHDP_Onboarding.md`:

1. `infra/bootstrap` provisions operators and cluster prerequisites
2. `platform/bootstrap` applies platform-level CRs and UI plugins
3. `tenant/bootstrap` creates the ArgoCD Application for the quickstart

This separation keeps infrastructure, platform, and tenant/app team responsibilities distinct.

## Configuration

- **Environment variables:** None (pure Helm chart)
- **Config files:** None
- **Helm values:**
  - `deployer.domain` / `deployer.apiUrl` / `deployer.guid` -- cluster-specific deployer settings
  - `tenant.name` -- tenant identifier, used as the ArgoCD Application name
  - `tenant.user.name` / `tenant.user.password` -- tenant user credentials
  - `gitops.namespace` -- namespace where ArgoCD runs (default: `openshift-gitops`)
  - `gitops.applicationControllerServiceAccount` -- ArgoCD controller SA name (default: `openshift-gitops-argocd-application-controller`)
  - `rbac.enabled` -- whether to create ClusterRole/ClusterRoleBinding (default: `false`)
  - `rbac.clusterRoleName` -- name for the RBAC resources (default: `argocd-rag-bootstrap-manager`)
  - `rag.namespace` -- target namespace for the quickstart (default: `rag`)
  - `rag.git.url` / `rag.git.revision` / `rag.git.path` -- git source for the quickstart Helm chart
  - `rag.values.*` -- nested values passed through to the downstream quickstart chart

## Known Gotchas

- **Setting rag to empty disables deployment:** The ArgoCD Application template is guarded by `{{ if .Values.rag }}`. As the `values.yaml` comment notes ("Set to empty to NOT create workspaces"), setting `rag:` to null or removing it entirely skips Application creation.
- **prune and selfHeal are both false:** The sync policy disables automatic pruning and self-healing. This is intentional for onboarding scenarios where manual review of deletions is preferred, but means orphaned resources must be cleaned up manually if the chart source changes.
- **Retry limit is aggressive:** The sync retry is configured with 30 attempts and exponential backoff (5s base, factor 2, max 5m). This handles transient issues during initial cluster setup but can mask persistent failures for a long time before giving up.
- **RBAC includes RHOAI-specific API groups:** The ClusterRole includes rules for `kubeflow.org` (notebooks) and `datasciencepipelinesapplications.opendatahub.io` (DSP). These are RHOAI-specific and will produce harmless RBAC warnings on clusters without these CRDs installed.
- **CreateNamespace sync option:** The `CreateNamespace=true` sync option means ArgoCD will create the target namespace if it does not exist. This requires the ArgoCD controller to have namespace creation permissions, which the optional RBAC ClusterRole provides.

## Testing Notes

- Verify the ArgoCD Application was created: `kubectl get applications -n openshift-gitops`
- Check sync status: `kubectl get application <tenant-name> -n openshift-gitops -o jsonpath='{.status.sync.status}'`
- Verify the target namespace was created: `kubectl get namespace <rag-namespace>`
- If RBAC is enabled, verify ClusterRole exists: `kubectl get clusterrole <clusterRoleName>`
- Check ArgoCD UI for sync errors and retry attempts

## Related Patterns

- Deployment KB files covering Helm subchart wiring for the downstream quickstart chart
- RBAC patterns for ArgoCD controller permissions on RHOAI clusters
