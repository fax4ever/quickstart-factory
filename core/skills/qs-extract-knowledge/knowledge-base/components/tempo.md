---
name: tempo
description: "TempoStack distributed tracing backend with MinIO S3 storage, deployed via Tempo Operator on OpenShift"
summary: "Deploys Grafana Tempo as a distributed tracing backend on OpenShift via the Tempo Operator (OLM Subscription for tempo-product on stable channel from redhat-operators) and a TempoStack CR, storing traces in MinIO (quay.io/minio/minio) S3 storage with PVC-backed volumes (12Gi MinIO, 15Gi TempoStack) in observability-hub namespace using two-phase Helm deployment (operator Subscription chart + instance chart) with OpenShift multitenancy mode and gateway-based UI via COO UIPlugin (Observe -> Traces) replacing Jaeger Query. Approach A deploys a dedicated MinIO (Recreate strategy, entrypoint \"mkdir -p /storage/<bucket>\" for auto-bucket creation) with dual secrets (minio-tempo for S3 creds using in-cluster DNS endpoint http://<svc>.<ns>.svc.cluster.local:<port>, plus MinIO root creds via envFrom) and per-ServiceAccount ClusterRoleBindings for OTEL collector cross-namespace trace export -- use for standalone/isolated observability; Approach B references a pre-existing shared MinIO (minio-observability-storage) with a single secret (minio-tempo-credentials), credentials overridden via Makefile helm_tempo_args, all system:authenticated users granted trace read access via namespace-prefixed clusterResourceName, embedded UIPlugin CR, and helm list idempotent install checks -- use for multi-backend stacks sharing storage. Applications export traces to http://tempostack-gateway.observability-hub.svc.cluster.local:8080; S3 endpoints use in-cluster DNS; jaegerQuery.enabled is set to false in favor of the Gateway approach. Cross-namespace OTEL collector 401 errors require ClusterRoleBindings granting tempostack-traces-write to the collector ServiceAccount; Tempo Operator requires AllNamespaces scope (targetNamespaces: []) as OwnNamespace is unsupported; default credentials (admin/minio123) are test-only; MinIO sets HOME=/tmp for non-root compatibility; Approach B requires the shared MinIO to exist before deployment and PVC cleanup on uninstall needs explicit deletion with timeout."
metadata:
  type: component
tags:
  tech_stack: [tempo, minio, helm, openshift]
  ai_pattern: [observability, tracing]
  platform: [openshift, kubernetes]
  data_layer: [minio]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "TempoStack with dedicated MinIO deployment for S3 trace storage, multitenancy via OpenShift mode"
    approach: "A"
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "TempoStack with shared MinIO instance, embedded UIPlugin, broad RBAC for all authenticated users"
    approach: "B"
---

# Tempo

## Overview

Tempo is a distributed tracing backend deployed on OpenShift via the Tempo Operator and the TempoStack custom resource. In this quickstart it stores traces in a co-deployed MinIO instance that provides S3-compatible object storage. The deployment is split into two Helm charts: one for the operator (OLM Subscription) and one for the TempoStack instance plus its MinIO storage backend, deployed into an `observability-hub` namespace.

## Tech Stack & Dependencies

- **Runtime:** Grafana Tempo (operator-managed), MinIO (`quay.io/minio/minio`)
- **Container image:** MinIO uses `quay.io/minio/minio`; Tempo pods are managed by the Tempo Operator
- **Key dependencies:** Tempo Operator (installed via OLM from `redhat-operators` catalog), PersistentVolumeClaim for MinIO storage
- **Helm subchart:** Two separate charts -- `helm/01-operators/tempo-operator/` (operator only) and `helm/02-observability/tempo/` (TempoStack instance + MinIO)

## Key Patterns

### Two-Phase Operator + Instance Deployment

The operator and the TempoStack instance are deployed as separate Helm charts. The operator chart installs only the OLM Subscription; it explicitly does not create TempoStack instances. The instance chart creates the TempoStack CR along with its MinIO storage backend.

From `helm/01-operators/tempo-operator/templates/subscription.yaml`:

```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {{ include "tempo-operator.subscriptionName" . }}
  namespace: {{ include "tempo-operator.namespace" . }}
spec:
  channel: {{ .Values.operator.subscription.channel }}
  installPlanApproval: {{ .Values.operator.subscription.installPlanApproval }}
  name: {{ .Values.operator.subscription.name }}
  source: {{ .Values.operator.subscription.source }}
  sourceNamespace: {{ .Values.operator.subscription.sourceNamespace }}
```

The operator values specify `tempo-product` from the `redhat-operators` catalog on the `stable` channel.

### TempoStack CR with Multitenant OpenShift Mode

The TempoStack resource uses OpenShift-native multitenancy with a gateway for UI access. Jaeger Query UI is disabled in favor of the Gateway + COO UIPlugin approach for accessing traces through the OpenShift Console (Observe -> Traces).

From `helm/02-observability/tempo/templates/tempostack.yaml`:

```yaml
apiVersion: tempo.grafana.com/v1alpha1
kind: TempoStack
metadata:
  name: {{ .Values.tempoStack.name }}
spec:
  storage:
    secret:
      name: minio-tempo
      type: s3
  storageSize: {{ .Values.tempoStack.storageSize }}
  tenants:
    mode: {{ .Values.tempoStack.tenants.mode }}
    authentication:
      {{- range .Values.tempoStack.tenants.authentication }}
      - tenantName: {{ .tenantName }}
        tenantId: {{ .tenantId | quote }}
      {{- end }}
  template:
    gateway:
      enabled: {{ .Values.tempoStack.template.gateway.enabled }}
```

### MinIO with Auto Bucket Creation

MinIO is deployed as a single-replica Deployment with a Recreate strategy. The container entrypoint creates the required S3 bucket before starting the server, avoiding a separate init container or post-deploy job.

From `helm/02-observability/tempo/templates/minio-deployment.yaml`:

```yaml
command:
  - /bin/sh
  - '-c'
  - |
    mkdir -p /storage/{{ .Values.minio.s3.bucket }} && \
    /usr/bin/docker-entrypoint.sh minio server /storage --console-address ":{{ .Values.minio.service.ports.console }}"
```

### Dual Secret Pattern for MinIO-to-Tempo Wiring

Two separate secrets are created: one for Tempo to connect to MinIO (S3 credentials with endpoint URL), and one for the MinIO container itself (root user credentials). The S3 endpoint secret constructs the full in-cluster DNS name.

From `helm/02-observability/tempo/templates/minio-secrets.yaml`:

```yaml
# S3 credentials for Tempo
stringData:
  access_key_id: {{ .Values.minio.s3.accessKeyId }}
  access_key_secret: {{ .Values.minio.s3.accessKeySecret }}
  bucket: {{ .Values.minio.s3.bucket }}
  endpoint: http://{{ .Values.minio.service.name }}.{{ include "tempo-stack.namespace" . }}.svc.cluster.local:{{ .Values.minio.service.ports.api }}
---
# MinIO root user credentials
stringData:
  MINIO_ROOT_USER: {{ .Values.minio.credentials.rootUser }}
  MINIO_ROOT_PASSWORD: {{ .Values.minio.credentials.rootPassword }}
```

### Cross-Namespace RBAC for OTEL Collector Trace Export

A dedicated `rbac2.yaml` file addresses 401 authentication errors when the OTEL collector sends traces to Tempo from a different namespace. It creates ClusterRoleBindings for the `otel-collector` ServiceAccount in both the application namespace (`llama-serve`) and the observability namespace (`observability-hub`).

From `helm/02-observability/tempo/templates/rbac2.yaml`:

```yaml
# RBAC Fix for OTEL Collector Cross-Namespace Tempo Access
# This addresses the 401 authentication errors when OTEL collector
# tries to export traces to Tempo
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: otel-collector-tempo-traces-write
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: tempostack-traces-write
subjects:
- kind: ServiceAccount
  name: otel-collector
  namespace: llama-serve
```

## Configuration

- **Environment variables:** `HOME=/tmp` (set on MinIO container for non-root compatibility), `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` (from `minio-user-creds` Secret)
- **Config files:** No additional config files; all configuration is via Helm values and the TempoStack CR
- **Helm values:**
  - `global.namespace` -- target namespace (default: `observability-hub`)
  - `tempoStack.storageSize` -- trace storage size (default: `15Gi`)
  - `tempoStack.resources.total.limits.memory` -- memory limit (default: `10Gi`)
  - `tempoStack.resources.total.limits.cpu` -- CPU limit (default: `5000m`)
  - `tempoStack.tenants.mode` -- tenant mode (default: `openshift`)
  - `tempoStack.tenants.authentication` -- list of tenant name/ID pairs
  - `minio.storage.size` -- MinIO PVC size (default: `12Gi`)
  - `minio.s3.bucket` -- S3 bucket name for traces (default: `tempo`)
  - `minio.service.name` -- MinIO service name (default: `minio-tempo-svc`)

## Known Gotchas

- **Cross-namespace 401 errors:** When the OTEL collector runs in a different namespace than Tempo, it gets 401 authentication errors exporting traces. The fix requires explicit ClusterRoleBindings granting the `otel-collector` ServiceAccount write access to Tempo traces (see `rbac2.yaml`). The comment in the source code reads: "This addresses the 401 authentication errors when OTEL collector tries to export traces to Tempo."
- **Operator scope must be cluster-wide:** The Tempo Operator does not support OwnNamespace install mode. The OperatorGroup `targetNamespaces` must be set to `[]` (empty array) for AllNamespaces scope. The `helm/01-operators/tempo-operator/values.yaml` comment states: "Empty array [] enables cluster-wide scope (AllNamespaces install mode). This is required for Tempo operator as it doesn't support OwnNamespace mode."
- **Gateway vs Jaeger Query conflict:** The Jaeger Query UI and ingress are disabled (`jaegerQuery.enabled: false`) in favor of the Gateway approach. The README notes: "The legacy Jaeger Query UI route has been disabled in favor of the modern Gateway + COO UIPlugin approach."
- **Default MinIO credentials are test-only:** The values.yaml ships with `admin/minio123` credentials and an explicit comment: "TEST VALUES - CHANGE IN PRODUCTION."
- **MinIO HOME directory override:** The MinIO container sets `HOME=/tmp` to work under non-root security contexts where the default home directory is not writable.

## Testing Notes

- Check that the MinIO PVC is bound: `kubectl get pvc minio-tempo -n observability-hub`
- Verify TempoStack status: `kubectl get tempostack tempostack -n observability-hub -o yaml`
- Check operator logs if TempoStack is not ready: `kubectl logs -n openshift-tempo-operator deployment/tempo-operator-controller`
- Verify gateway services exist: `oc get services -n observability-hub -l app.kubernetes.io/component=gateway`
- Access traces via the OpenShift Console under Observe -> Traces (requires COO UIPlugin)
- Validate the OTLP endpoint for applications: `http://tempostack-gateway.observability-hub.svc.cluster.local:8080`

## Related Patterns

- Alloy (OTEL collector that sends traces to Tempo)
- MinIO (shared S3-compatible object storage pattern)
- Observability stack (overall observability architecture)

---

## Approach B: Shared MinIO with Embedded UIPlugin (from openshift-ai-observability-summarizer)

### When to Use

Use this approach when a shared MinIO instance already exists in the cluster (e.g., deployed by a separate `minio` Helm chart for multiple observability backends like Tempo and Loki). This avoids deploying a dedicated MinIO per component and centralizes object storage management. Also appropriate when the UIPlugin CR should be co-deployed with the TempoStack rather than as a separate chart.

### Differences from Approach A

- **No dedicated MinIO deployment:** The chart sets `minio.enabled: false` and references a pre-existing shared MinIO service (`minio-observability-storage`) instead of deploying its own MinIO Deployment, Service, and PVC.
- **Single S3 secret:** Only one secret (`minio-tempo-credentials`) is created containing S3 access credentials and endpoint. There is no separate MinIO root user secret since MinIO is managed externally.
- **Credential injection via Makefile:** S3 credentials are overridden at deploy time through Makefile `helm_tempo_args` rather than being baked into values.yaml defaults.
- **Broader RBAC model:** A ClusterRole/ClusterRoleBinding grants all `system:authenticated` users read access to traces, rather than binding specific OTEL collector ServiceAccounts.
- **Embedded UIPlugin:** The `UIPlugin` CR for distributed tracing is a template within the tempo chart itself, not a separate Helm chart.
- **Operator installation via Makefile scripts:** The Tempo Operator is installed via `make install-tempo-operator` using `OPERATOR_MANAGER_SCRIPT`, not via a separate operator-only Helm chart.

### Shared MinIO Reference Pattern

The chart disables its own MinIO deployment and points to a shared instance via values. The Makefile passes actual credentials at install time.

From `deploy/helm/observability/tempo/values.yaml`:

```yaml
minio:
  enabled: false  # Disable dedicated MinIO deployment
  shared:
    serviceName: minio-observability-storage
    namespace: observability-hub
    ports:
      api: 9000
      console: 9001
  s3:
    accessKeyId: "admin"
    accessKeySecret: "minio123"
    bucket: tempo
    endpoint: http://minio-observability-storage.observability-hub.svc.cluster.local:9000
```

From `Makefile`:

```makefile
helm_tempo_args = \
    --set minio.s3.accessKeyId=$(MINIO_USER) \
    --set minio.s3.accessKeySecret=$(MINIO_PASSWORD) \
    --set minio.s3.bucket=tempo
```

### Single S3 Credentials Secret

A single secret provides all four fields Tempo needs to connect to the shared MinIO. The secret name is `minio-tempo-credentials` (different from Approach A's `minio-tempo`).

From `deploy/helm/observability/tempo/templates/minio-secrets.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: minio-tempo-credentials
type: Opaque
stringData:
  access_key_id: {{ .Values.minio.s3.accessKeyId }}
  access_key_secret: {{ .Values.minio.s3.accessKeySecret }}
  bucket: {{ .Values.minio.s3.bucket }}
  endpoint: {{ .Values.minio.s3.endpoint }}
```

The TempoStack CR references this secret:

```yaml
spec:
  storage:
    secret:
      name: minio-tempo-credentials
      type: s3
```

### Broad Trace-Read RBAC for All Authenticated Users

Instead of binding specific ServiceAccounts, this approach grants all authenticated users read access to traces via the tenant-specific resource names defined in the TempoStack authentication config.

From `deploy/helm/observability/tempo/templates/rbac.yaml`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ include "tempo-stack.clusterResourceName" . }}-traces-reader
rules:
  - apiGroups:
      - 'tempo.grafana.com'
    resources:
      {{- range .Values.tempoStack.tenants.authentication }}
      - {{ .tenantName }}
      {{- end }}
    resourceNames:
      - traces
    verbs:
      - 'get'
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {{ include "tempo-stack.clusterResourceName" . }}-traces-reader
subjects:
  - kind: Group
    apiGroup: rbac.authorization.k8s.io
    name: system:authenticated
```

The `clusterResourceName` helper includes the namespace to avoid ClusterRole naming conflicts across releases:

```yaml
{{- define "tempo-stack.clusterResourceName" -}}
{{- printf "%s-%s" $namespace $fullname | trunc 63 | trimSuffix "-" }}
{{- end }}
```

### Embedded UIPlugin Template

The UIPlugin CR for distributed tracing is deployed as part of the tempo chart, not as a standalone chart.

From `deploy/helm/observability/tempo/templates/uiplugin.yaml`:

```yaml
apiVersion: observability.openshift.io/v1alpha1
kind: UIPlugin
metadata:
  name: distributed-tracing
spec:
  type: DistributedTracing
  distributedTracing:
    timeout: 30s
```

This differs from Approach A's separate `distributed-tracing-ui-plugin` chart by including a `distributedTracing.timeout` field and being co-located with the TempoStack resources.

### Querier Resource Allocation in TempoStack

The TempoStack template explicitly configures querier replicas and resource requests/limits, with defaults pulled from the top-level resource configuration.

From `deploy/helm/observability/tempo/templates/tempostack.yaml`:

```yaml
template:
  querier:
    replicas: 1
    resources:
      limits:
        memory: {{ .Values.tempoStack.resources.total.limits.memory }}
        cpu: {{ .Values.tempoStack.resources.total.limits.cpu }}
      requests:
        memory: {{ .Values.tempoStack.resources.total.requests.memory | default "2Gi" }}
        cpu: {{ .Values.tempoStack.resources.total.requests.cpu | default "1000m" }}
```

### Known Gotchas (Approach B)

- **Shared MinIO must exist first:** The chart assumes `minio-observability-storage` is already deployed. The `install-observability-stack` Makefile target enforces this by running `install-minio` before `install-observability`. Deploying tempo before the shared MinIO service exists will leave the TempoStack in a failed state.
- **Credentials in values.yaml are placeholders:** The values.yaml ships with `admin/minio123` as S3 credentials. The Makefile `helm_tempo_args` overrides these with `$(MINIO_USER)` and `$(MINIO_PASSWORD)` at deploy time. The comment in values.yaml states: "Credentials are passed via Makefile helm_tempo_args."
- **Idempotent install check:** The Makefile checks `helm list` for an existing `tempo` release before installing, printing "TempoStack already installed, skipping..." to avoid upgrade collisions during repeated runs.
- **PVC cleanup on uninstall:** The uninstall target explicitly deletes PVCs labeled `app.kubernetes.io/name=tempo` with a 30-second timeout, since Helm does not remove PVCs by default.

---

## Choosing Between Approaches

| Criteria | Approach A (Dedicated MinIO) | Approach B (Shared MinIO) |
|----------|------------------------------|---------------------------|
| MinIO lifecycle | Deployed and managed within the tempo chart | Pre-existing shared instance, managed separately |
| Storage isolation | Tempo has its own MinIO with dedicated PVC | Shares MinIO with other backends (Loki, etc.) |
| Secret pattern | Dual secrets (S3 creds + MinIO root creds) | Single S3 credentials secret |
| RBAC scope | Specific ServiceAccount bindings for OTEL collector | All `system:authenticated` users get trace read access |
| UIPlugin deployment | Separate Helm chart | Embedded in the tempo chart |
| Operator installation | Dedicated operator-only Helm chart | Makefile target with operator manager script |
| Credential management | Defaults in values.yaml | Overridden via Makefile args at deploy time |
| Best for | Standalone observability setup, isolated environments | Multi-backend observability stacks sharing storage |
