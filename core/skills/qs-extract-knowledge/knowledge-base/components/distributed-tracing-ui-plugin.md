---
name: distributed-tracing-ui-plugin
description: "Helm chart deploying an OpenShift UIPlugin CR that adds distributed tracing views to the console"
summary: "Adds distributed tracing views to the OpenShift web console by deploying a single UIPlugin CR (observability.openshift.io/v1alpha1, spec.type: DistributedTracing) -- a standalone Helm chart with no running workload, no container image, and no subchart dependency on ai-architecture-charts. Use when the Distributed Tracing Platform Operator is already installed on OpenShift 4.10+ with cluster-admin privileges; in lls-observability this deploys as Phase 2 alongside Tempo, OTel Collector, Grafana, and User Workload Monitoring. Key values are uiPlugin.name (default \"distributed-tracing\" via a dedicated helper separate from fullname), uiPlugin.type (default \"DistributedTracing\"), monitoring.enabled adding app.kubernetes.io/component and app.kubernetes.io/part-of labels, and advanced.enabled/advanced.spec for injecting arbitrary spec fields as the UIPlugin API evolves. The UIPlugin name must remain \"distributed-tracing\" per OpenShift documentation requirements, the v1alpha1 API version may break on cluster upgrades, and this chart only creates the CR -- tracing infrastructure (Tempo, OTel Collector) must be deployed separately before the console plugin becomes functional."
metadata:
  type: component
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
  data_layer: []
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "OpenShift UIPlugin CR for distributed tracing console integration in the observability stack"
    approach: "A"
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "UIPlugin CR embedded within the tempo-stack chart rather than standalone, includes distributedTracing.timeout config"
    approach: "A"
---

# Distributed Tracing UI Plugin

## Overview

The Distributed Tracing UI Plugin is a lightweight Helm chart that creates an OpenShift `UIPlugin` custom resource, integrating distributed tracing views directly into the OpenShift web console. It does not deploy any tracing infrastructure itself; it relies on the OpenShift Distributed Tracing Platform Operator already being installed on the cluster. In the lls-observability quickstart it is deployed as part of Phase 2 (observability) alongside Tempo, the OTel Collector, Grafana, and User Workload Monitoring.

## Tech Stack & Dependencies

- **Runtime:** None (no running workload; this chart only creates a CR)
- **Container image:** None
- **Key dependencies:** OpenShift Distributed Tracing Platform Operator, OpenShift 4.10+, cluster-admin privileges
- **Helm subchart:** Standalone chart (not a subchart of ai-architecture-charts)

## Key Patterns

### UIPlugin Custom Resource

The chart creates a single `UIPlugin` resource using the `observability.openshift.io/v1alpha1` API. The CR's `spec.type` field tells OpenShift which console plugin to enable.

```yaml
apiVersion: observability.openshift.io/v1alpha1
kind: UIPlugin
metadata:
  name: {{ include "distributed-tracing-ui-plugin.uiPluginName" . }}
  labels:
    {{- include "distributed-tracing-ui-plugin.uiPluginLabels" . | nindent 4 }}
spec:
  type: {{ .Values.uiPlugin.type }}
```

The resource name defaults to `distributed-tracing` (via `values.yaml`), and the type defaults to `DistributedTracing`.

### Fixed Resource Name Convention

The chart provides a dedicated helper for the UIPlugin name that falls back to `distributed-tracing`:

```yaml
{{- define "distributed-tracing-ui-plugin.uiPluginName" -}}
{{- .Values.uiPlugin.name | default "distributed-tracing" }}
{{- end }}
```

This is separate from the standard `fullname` helper, reflecting the fact that the UIPlugin name is a well-known identifier expected by the OpenShift console rather than a release-scoped resource name.

### Advanced Spec Extension

The chart supports injecting arbitrary additional spec fields through `advanced.spec`, gated behind `advanced.enabled`:

```yaml
{{- if .Values.advanced.enabled }}
{{- if .Values.advanced.spec }}
{{- toYaml .Values.advanced.spec | nindent 2 }}
{{- end }}
{{- end }}
```

This pattern allows forward-compatibility as the UIPlugin API evolves without modifying templates.

## Configuration

- **Environment variables:** None (no running container)
- **Config files:** None
- **Helm values:**
  - `uiPlugin.name` -- Name of the UIPlugin CR (default: `distributed-tracing`); should match OpenShift documentation requirements
  - `uiPlugin.type` -- Plugin type enum (default: `DistributedTracing`)
  - `uiPlugin.labels` / `uiPlugin.annotations` -- Additional metadata on the CR
  - `monitoring.enabled` -- Adds `app.kubernetes.io/component: ui-plugin` and `app.kubernetes.io/part-of: observability` labels (default: `true`)
  - `advanced.enabled` / `advanced.spec` -- Inject extra spec fields (default: disabled)

## Known Gotchas

- The UIPlugin name should remain `distributed-tracing` per OpenShift documentation requirements. The values.yaml comment explicitly warns: "For distributed tracing, this should typically be 'distributed-tracing' as per OpenShift documentation requirements."
- This chart only creates the UIPlugin resource; the actual distributed tracing infrastructure (Tempo, OTel Collector) must be deployed separately before the console plugin becomes functional.
- The chart uses `observability.openshift.io/v1alpha1`, an alpha API version. Upgrading OpenShift may require updating the API version.

## Testing Notes

- After `helm install`, verify the UIPlugin CR exists: `oc get uiplugin distributed-tracing`
- Check the OpenShift web console for the tracing UI tab under the observability section
- Ensure the Distributed Tracing Platform Operator is installed first; without it the CR will be rejected

## Related Patterns

- `tracing-config.md` -- OTel tracing configuration patterns
- `observability-stack.md` -- Overall observability architecture
