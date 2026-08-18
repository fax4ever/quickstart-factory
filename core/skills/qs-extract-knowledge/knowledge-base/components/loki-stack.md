---
name: loki-stack
description: LokiStack Helm chart for centralized log aggregation with MinIO S3 backend on OpenShift
summary: "LokiStack deploys centralized log aggregation in the openshift-logging namespace via the Loki Operator, routing application, infrastructure (filtered to node/container sources), and audit (disabled by default) tenant logs through ClusterLogForwarder to a shared MinIO S3 backend at a cross-namespace cluster-local DNS endpoint. Use when building OpenShift observability stacks needing multi-tenant log retention (audit 1d, application 3d, infrastructure 7d) with per-tenant ingestion rate limits; LokiStack sizing ranges from 1x.demo to 1x.medium, tenants mode must be openshift-logging for RBAC integration, and a UIPlugin adds \"Observe > Logs\" to the OpenShift Console. Critical patterns: Helm lookup for automatic StorageClass detection (fallback gp3), idempotent collector SA detection via Makefile setting rbac.collector.create dynamically, Helm ownership-aware RBAC cleanup checking meta.helm.sh/release-name annotations, and helm.sh/resource-policy: keep on collector-rbac.yaml to survive uninstall. Gotchas: ClusterRole conflicts with OLM (chart creates only ClusterRoleBindings, not ClusterRoles), collector SA ownership race if Cluster Logging Operator creates SA first, ingester OOMKilled from default 256KB maxLineSize fixed by ingestionMaxLineSize: 2097152 (2MB), MinIO storage pressure requiring retention reduction, insecureSkipVerify: true for internal TLS needing CA validation for production, and stale Helm release recovery via force-removing failed Helm secrets."
metadata:
  type: component
tags:
  tech_stack: [loki, helm, openshift-logging, minio, s3]
  ai_pattern: [observability]
  platform: [openshift, rhoai]
  data_layer: [minio]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "LokiStack with shared MinIO storage, ClusterLogForwarder, multi-tenant retention, and OpenShift Console UIPlugin"
    approach: "A"
---

# Loki Stack

## Overview

LokiStack is the centralized log aggregation component in OpenShift AI observability quickstarts. It deploys a `LokiStack` custom resource (managed by the Loki Operator), a `ClusterLogForwarder` for routing logs from application, infrastructure, and audit tenants, and a `UIPlugin` to surface logs in the OpenShift Console under "Observe > Logs". The chart reuses a shared MinIO instance for S3-compatible object storage rather than deploying its own.

## Tech Stack & Dependencies

- **Runtime:** Loki 2.9.0 (via Loki Operator)
- **Container image:** Managed by the Loki Operator (not user-specified)
- **Key dependencies:** Loki Operator (`openshift-operators-redhat`), Cluster Logging Operator (`openshift-logging`), shared MinIO instance (`observability-hub` namespace)
- **Helm subchart:** Standalone chart at `deploy/helm/observability/loki/` (no subchart dependencies)
- **Namespace:** `openshift-logging` (hardcoded as `LOKI_NAMESPACE` in Makefile)

## Key Patterns

### Shared MinIO S3 Backend

The chart does not deploy its own object storage. Instead it creates a Secret pointing at an existing shared MinIO service in another namespace. This keeps storage centralized for both Loki and Tempo.

```yaml
# templates/minio-secrets.yaml
stringData:
  access_key_id: {{ .Values.minio.s3.accessKeyId }}
  access_key_secret: {{ .Values.minio.s3.accessKeySecret }}
  bucketnames: {{ .Values.minio.s3.bucket }}
  endpoint: {{ .Values.minio.s3.endpoint }}
```

The endpoint crosses namespaces via the cluster-local DNS:

```yaml
# values.yaml
endpoint: http://minio-observability-storage.observability-hub.svc.cluster.local:9000
```

### Multi-Tenant Retention Policies

Per-tenant retention and ingestion limits are defined in `values.yaml` and projected into the LokiStack spec. This allows audit logs (high volume) to have a shorter retention than infrastructure logs.

```yaml
# values.yaml
tenants:
  audit:
    retention:
      days: 1
    ingestionRateLimit: 5242880   # 5MB/s
  application:
    retention:
      days: 3
    ingestionRateLimit: 3145728   # 3MB/s
  infrastructure:
    retention:
      days: 7
    ingestionRateLimit: 5242880   # 5MB/s
```

### ClusterLogForwarder with Filtered Inputs

The `ClusterLogForwarder` uses custom named inputs to control which logs reach Loki. Infrastructure logs are filtered to `node` and `container` sources only, and audit logs are disabled by default due to high volume.

```yaml
# templates/clusterlogforwarder.yaml (excerpt)
inputs:
- name: {{ .Values.clusterLogging.logForwarder.inputs.infrastructure.customName }}
  type: infrastructure
  infrastructure:
    sources:
    {{- range .Values.clusterLogging.logForwarder.inputs.infrastructure.sources }}
    - {{ . }}
    {{- end }}
```

### OpenShift Console UIPlugin

A `UIPlugin` resource of type `Logging` is created to add the "Observe > Logs" menu item in the OpenShift Console, pointing at the LokiStack gateway.

```yaml
# templates/uiplugin.yaml
apiVersion: observability.openshift.io/v1alpha1
kind: UIPlugin
metadata:
  name: {{ .Values.uiPlugin.name }}
spec:
  type: Logging
  logging:
    timeout: {{ .Values.uiPlugin.logging.timeout }}
    lokiStack:
      name: {{ .Values.uiPlugin.logging.lokiStack.name }}
      namespace: {{ .Values.uiPlugin.logging.lokiStack.namespace }}
```

### Automatic StorageClass Detection

The `_helpers.tpl` uses Helm `lookup` to detect the cluster's default StorageClass at install time, falling back to `gp3` if none is found. The Makefile also performs its own detection and passes the value via `--set`.

```go
# templates/_helpers.tpl (excerpt)
{{- $storageClasses := lookup "storage.k8s.io/v1" "StorageClass" "" "" -}}
{{- range $storageClasses.items -}}
  {{- if and .metadata.annotations
    (or (eq (index .metadata.annotations
      "storageclass.kubernetes.io/is-default-class") "true")
      (eq (index .metadata.annotations
      "storageclass.beta.kubernetes.io/is-default-class") "true")) -}}
    {{- $defaultSC = .metadata.name -}}
  {{- end -}}
{{- end -}}
```

### Idempotent Collector SA Management

The Makefile detects whether the `collector` ServiceAccount already exists (e.g., created by the Cluster Logging Operator) and sets `rbac.collector.create` accordingly to avoid conflicts.

```makefile
# Makefile
check_collector_sa_and_get_flag = \
  if oc get serviceaccount collector -n $(LOKI_NAMESPACE) >/dev/null 2>&1; then \
    echo "false"; \
  else \
    echo "true"; \
  fi
```

### Helm Ownership-Aware RBAC Cleanup

Before each install/upgrade, a `cleanup-loki-clusterroles` target checks Helm release ownership annotations on each ClusterRoleBinding and ServiceAccount. Only resources owned by the `loki-stack` Helm release are deleted; resources owned by the operator are left alone.

```makefile
# Makefile (excerpt from cleanup-loki-clusterroles)
OWNER=$$(oc get clusterrolebinding $$crb \
  -o jsonpath='{.metadata.annotations.meta\.helm\.sh/release-name}');
if [ "$$OWNER" = "loki-stack" ]; then
  oc delete clusterrolebinding $$crb --ignore-not-found;
fi
```

## Configuration

- **Environment variables:** None directly; configuration is via Helm values
- **Config files:** `values.yaml` is the single configuration surface
- **Key Helm values:**
  - `lokiStack.size` -- LokiStack sizing (`1x.demo`, `1x.extra-small`, `1x.small`, `1x.medium`)
  - `lokiStack.storageClassName` -- set to `auto` for detection or an explicit class name
  - `lokiStack.limits.global.retention.days` -- global retention (default 3)
  - `lokiStack.limits.global.ingestionMaxLineSize` -- max line size in bytes (default 2MB; see gotchas)
  - `lokiStack.tenants.mode` -- must be `openshift-logging` for RBAC integration
  - `minio.s3.endpoint` -- full cluster-local URL to the shared MinIO service
  - `rbac.collector.create` -- set dynamically by Makefile based on existing SA
  - `clusterLogging.logForwarder.tls.insecureSkipVerify` -- `true` for internal cluster comm (see gotchas)
  - `clusterLogging.logForwarder.inputs.audit.enabled` -- disabled by default due to volume
  - `uiPlugin.enabled` -- enables "Observe > Logs" in OpenShift Console

## Known Gotchas

- **ClusterRole conflict between OLM and Helm:** The collector ClusterRoles (`collect-application-logs`, `collect-infrastructure-logs`, `collect-audit-logs`, `logging-collector-logs-writer`) are provided by the Cluster Logging Operator bundle via OLM. The chart only creates ClusterRoleBindings and the ServiceAccount, not the ClusterRoles themselves. An earlier version tried to create these ClusterRoles and failed on clean installs. Fixed in commit `90140f9`.

- **Collector SA ownership race:** If the Cluster Logging Operator creates the `collector` ServiceAccount before the Helm install runs, the install will fail with a conflict. The Makefile's `check_collector_sa_and_get_flag` function detects this and sets `rbac.collector.create=false`. The `collector-rbac.yaml` template also uses `helm.sh/resource-policy: keep` to avoid deletion on uninstall.

- **Max line size causing OOMKilled:** The default Loki `maxLineSize` of 256KB was causing ingester pods to be OOMKilled on large log lines. The chart sets `ingestionMaxLineSize: 2097152` (2MB) in `values.yaml` with a comment documenting this as a production fix.

- **MinIO storage pressure:** The values.yaml header documents a production incident where MinIO storage reached 99% usage. The fix involved reducing retention (7 -> 3 days global, 3 -> 1 day for audit) and filtering infrastructure log sources.

- **TLS for internal communication:** The `ClusterLogForwarder` uses `insecureSkipVerify: true` for internal cluster communication. The values.yaml documents this as the "CURRENT WORKING CONFIG" with a note to configure CA validation for production security.

- **Stale Helm release recovery:** The `install-loki` Makefile target includes logic to detect and force-remove stale Helm releases stuck in a failed state by deleting the Helm secret after a timeout.

## Testing Notes

- After install, verify the LokiStack pods are running: `oc get pods -n openshift-logging -l app.kubernetes.io/name=loki`
- Check that the UIPlugin is active: look for "Observe > Logs" in the OpenShift Console
- Verify log forwarding by checking `ClusterLogForwarder` status: `oc get clusterlogforwarder -n openshift-logging`
- Check drift with `make check-observability-drift` which runs `scripts/check-observability-drift.sh`

## Related Patterns

- `components/minio.md` -- shared MinIO storage backend
- `components/otel-collector.md` -- OpenTelemetry collector that feeds traces to Tempo alongside log collection
- `components/tempo.md` -- distributed tracing (sibling observability component using same shared MinIO)
- `components/cluster-observability-operator.md` -- parent operator for the observability stack
- `deployment/helm-subchart-wiring.md` -- general Helm deployment patterns
