---
name: tempo
description: "TempoStack distributed tracing backend with MinIO S3 storage, deployed via Tempo Operator on OpenShift"
summary: "Deploys Grafana Tempo as a distributed tracing backend on OpenShift via the Tempo Operator (OLM Subscription for tempo-product on stable channel from redhat-operators) and a TempoStack CR, storing traces in a co-deployed MinIO (quay.io/minio/minio) S3 backend with PVC-backed storage (default 12Gi MinIO, 15Gi TempoStack). Uses a two-phase Helm deployment -- operator chart (Subscription only) and instance chart (TempoStack + MinIO) in observability-hub namespace -- with OpenShift multitenancy mode, gateway-based UI via COO UIPlugin (Observe -> Traces) replacing Jaeger Query; applications export traces to http://tempostack-gateway.observability-hub.svc.cluster.local:8080. MinIO Deployment uses Recreate strategy with entrypoint \"mkdir -p /storage/<bucket>\" for auto-bucket creation; dual secrets wire S3 credentials (referenced as minio-tempo in the TempoStack CR) with in-cluster DNS endpoint http://<svc>.<ns>.svc.cluster.local:<port> to Tempo, while a separate secret provides MinIO root user credentials via envFrom. Cross-namespace OTEL collector 401 errors require ClusterRoleBindings granting tempostack-traces-write to the collector ServiceAccount; Tempo Operator requires AllNamespaces scope (targetNamespaces: []) as OwnNamespace mode is unsupported; default credentials (admin/minio123) are test-only; MinIO sets HOME=/tmp for non-root security context compatibility."
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
