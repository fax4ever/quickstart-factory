---
name: helm-mlflow-clusterrole-rhoai-pipeline-runner-rbac
description: ClusterRole for mlflow.kubeflow.org CRDs with dedicated ServiceAccount and optional DSPA pipeline-runner binding
summary: "Provisions Kubernetes RBAC for RHOAI 3.4+ MLflow CRD-based access -- a ClusterRole granting read/write on mlflow.kubeflow.org experiments, datasets, registeredmodels plus read-only and use on gatewayendpoints, a dedicated mlflow-client ServiceAccount, and an optional DSPA pipeline-runner ClusterRoleBinding for KFP pipeline pods. Use when mlflow.rbac.enabled=true (default) and Kagenti is not managing MLflow; skip entirely when kagenti.mlflow.autoManaged=true because the Kagenti controller discovers the mlflows.mlflow.opendatahub.io CR and auto-injects MLFLOW_TRACKING_URI via the kagenti.io/type=agent Deployment label. Critical config: mlflow.rbac.pipelineRunner.enabled (default false) adds a ClusterRoleBinding for the pipeline-runner-dspa SA; the API Deployment conditionally sets serviceAccountName to the mlflow-client SA; gatewayendpoints/use subresource access uses the create verb per Kubernetes convention. ClusterRole and ClusterRoleBinding are cluster-scoped so kubectl delete namespace orphans them while helm uninstall cleans up correctly; the Secret template MLflow env vars are also gated on not kagenti.mlflow.autoManaged, so switching to autoManaged mode removes both RBAC resources and env var injection."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [evaluation]
  platform: [rhoai, openshift]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "ClusterRole for mlflow.kubeflow.org CRDs (experiments, datasets, registeredmodels, gatewayendpoints), dedicated ServiceAccount, optional pipeline-runner ClusterRoleBinding for DSPA"
    approach: "A"
---

# MLflow RBAC ClusterRole for RHOAI 3.4+ with Pipeline Runner

## Overview

This pattern creates Kubernetes RBAC resources for applications to authenticate with the RHOAI 3.4+ MLflow server. It provisions a ClusterRole granting permissions on `mlflow.kubeflow.org` CRDs, a dedicated ServiceAccount for the API pod, and an optional ClusterRoleBinding for the DSPA pipeline-runner ServiceAccount to enable KFP pipeline pods to access MLflow.

## Pattern Description

RHOAI 3.4+ introduces MLflow as a managed service with Kubernetes CRD-based access control. Applications need RBAC permissions to interact with MLflow experiments, datasets, registered models, and gateway endpoints. This pattern creates the necessary RBAC stack and conditionally skips it when the Kagenti MLflow controller handles RBAC automatically via `kagenti.mlflow.autoManaged=true`.

## Implementation

### ClusterRole for MLflow CRDs

The ClusterRole grants fine-grained permissions on `mlflow.kubeflow.org` resources:

```yaml
# deploy/helm/mortgage-ai/templates/mlflow-rbac.yaml
{{- if and .Values.mlflow.rbac.enabled (not (dig "mlflow" "autoManaged" false .Values.kagenti)) }}
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ include "mortgage-ai.fullname" . }}-mlflow-integration
rules:
  - apiGroups: [mlflow.kubeflow.org]
    resources: [datasets, experiments, registeredmodels]
    verbs: [get, list, create, update]
  - apiGroups: [mlflow.kubeflow.org]
    resources: [gatewayendpoints]
    verbs: [get, list]
  - apiGroups: [mlflow.kubeflow.org]
    resources: [gatewayendpoints/use]
    verbs: [create]
```

### Dedicated ServiceAccount

A ServiceAccount is created specifically for MLflow client operations:

```yaml
# deploy/helm/mortgage-ai/templates/mlflow-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "mortgage-ai.fullname" . }}-mlflow-client
  namespace: {{ .Release.Namespace }}
```

### API Deployment ServiceAccount Selection

The API Deployment conditionally uses the mlflow-client ServiceAccount:

```yaml
# deploy/helm/mortgage-ai/templates/api-deployment.yaml (excerpt)
{{- if and .Values.mlflow.rbac.enabled (not (dig "mlflow" "autoManaged" false .Values.kagenti)) }}
serviceAccountName: {{ include "mortgage-ai.fullname" . }}-mlflow-client
{{- else }}
serviceAccountName: {{ include "mortgage-ai.serviceAccountName" . }}
{{- end }}
```

### Optional Pipeline Runner Binding

When DSPA is deployed in the same namespace, the pipeline-runner SA gets MLflow access:

```yaml
# deploy/helm/mortgage-ai/templates/mlflow-rbac.yaml
{{- if .Values.mlflow.rbac.pipelineRunner.enabled }}
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {{ include "mortgage-ai.fullname" . }}-pipeline-runner-mlflow
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: {{ include "mortgage-ai.fullname" . }}-mlflow-integration
subjects:
  - kind: ServiceAccount
    name: {{ .Values.mlflow.rbac.pipelineRunner.serviceAccountName }}
    namespace: {{ .Release.Namespace }}
{{- end }}
```

## Configuration

- **Key settings:** `mlflow.rbac.enabled` (default: true) toggles the entire RBAC stack; `mlflow.rbac.pipelineRunner.enabled` (default: false) adds the DSPA binding; `mlflow.rbac.pipelineRunner.serviceAccountName` (default: `pipeline-runner-dspa`) names the DSPA SA; `kagenti.mlflow.autoManaged` (default: false) skips all manual RBAC
- **Defaults:** The ClusterRole grants read/write on experiments, datasets, and registeredmodels, but read-only + use on gatewayendpoints; the pipeline-runner binding is disabled by default because DSPA may not be deployed
- **Dependencies:** RHOAI 3.4+ with MLflow enabled in the DataScienceCluster; `mlflow.kubeflow.org` CRDs must be installed; for autoManaged mode, Kagenti with MLflow controller support

## Gotchas

- The `gatewayendpoints/use` verb uses the `create` verb for subresource access -- this is the Kubernetes pattern for granting "use" permissions on subresources, not actual resource creation (see `deploy/helm/mortgage-ai/templates/mlflow-rbac.yaml` lines 28-36)
- The entire RBAC stack is conditional on both `mlflow.rbac.enabled` AND `not kagenti.mlflow.autoManaged` -- when the Kagenti MLflow controller is active, it discovers MLflow from the `mlflows.mlflow.opendatahub.io` CR and injects configuration automatically (see `deploy/helm/mortgage-ai/values.yaml` lines 217-225)
- The MLflow env vars in the Secret template are also conditional on `not kagenti.mlflow.autoManaged` -- the Kagenti controller injects `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_NAME`, etc. via the `kagenti.io/type=agent` label on the Deployment (see `deploy/helm/mortgage-ai/templates/secret.yaml` lines 68-75)
- ClusterRole and ClusterRoleBinding are cluster-scoped, not namespace-scoped -- this means uninstalling the Helm release may leave orphaned cluster resources; standard `helm uninstall` handles this but `kubectl delete namespace` would not (see `deploy/helm/mortgage-ai/templates/mlflow-rbac.yaml`)

## Related Patterns

- `helm-kagenti-agentruntime-a2a-spire-mlflow-toggle.md` -- the Kagenti autoManaged mode that replaces this manual RBAC
