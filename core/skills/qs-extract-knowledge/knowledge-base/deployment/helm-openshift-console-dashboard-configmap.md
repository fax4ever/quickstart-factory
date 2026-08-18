---
name: helm-openshift-console-dashboard-configmap
description: Grafana JSON dashboard embedded as ConfigMap in openshift-config-managed with console.openshift.io labels
summary: "Embeds a Grafana-format JSON dashboard into the OpenShift Console natively (no standalone Grafana) by creating a ConfigMap in openshift-config-managed namespace labeled console.openshift.io/dashboard: \"true\" for automatic Console discovery. Use when dashboards should appear in OpenShift Console monitoring without deploying Grafana -- prefer helm-inline-grafana-alerting-loki-webhook for standalone Grafana deployments or helm-uwm-podmonitor-vllm for PodMonitor-based metrics collection. Helm template gates creation on metrics.dashboard.enabled (default false) and uses .Files.Get \"dashboards/<name>.json\" with nindent 4 to embed dashboard JSON from chart/dashboards/; metrics.dashboard.odc separately adds console.openshift.io/odc-dashboard: \"true\" for Developer perspective visibility. ConfigMap namespace is hardcoded to openshift-config-managed (outside Helm release namespace) requiring cluster-admin privileges, the application must expose Prometheus metrics referenced in dashboard queries, and removing the console.openshift.io/dashboard label silently hides the dashboard."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [guardrails]
  platform: [openshift]
source_examples:
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "Conditional OpenShift Console dashboard via ConfigMap in openshift-config-managed namespace with .Files.Get for dashboard JSON"
    approach: "A"
---

# OpenShift Console Dashboard via ConfigMap

## Overview

This pattern deploys a Grafana-format JSON dashboard into the OpenShift Console by creating a ConfigMap in the `openshift-config-managed` namespace with the `console.openshift.io/dashboard: "true"` label. This makes the dashboard appear natively in the OpenShift web console under the monitoring section without requiring a standalone Grafana deployment.

## Pattern Description

The Helm chart includes a dashboard JSON file under `chart/dashboards/` and a template that conditionally creates a ConfigMap in the `openshift-config-managed` namespace. The template uses Helm's `.Files.Get` to embed the JSON content. The dashboard is gated behind a values toggle (`metrics.dashboard.enabled`) since it requires cluster-admin privileges to create resources in the `openshift-config-managed` namespace. An additional toggle (`metrics.dashboard.odc`) controls whether the dashboard also appears in the OpenShift Developer Console.

## Implementation

### Dashboard ConfigMap Template

```yaml
# chart/templates/dashboard-configmap.yaml
{{- if .Values.metrics.dashboard.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: lemonade-stand-dashboard
  namespace: openshift-config-managed
  labels:
    app: lemonade-stand
    app.kubernetes.io/name: lemonade-stand
    app.kubernetes.io/component: config
    console.openshift.io/dashboard: "true"
    {{- if .Values.metrics.dashboard.odc }}
    console.openshift.io/odc-dashboard: "true"
    {{- end }}
data:
  lemonade-dashboard.json: |-
    {{- .Files.Get "dashboards/lemonade-dashboard.json" | nindent 4 }}
{{- end }}
```

### Values Configuration

```yaml
# chart/values.yaml
metrics:
  dashboard:
    enabled: false # requires cluster-admin privileges to install the dashboard
    odc: false
```

### Dashboard JSON Structure

The dashboard JSON uses Prometheus queries for guardrail-specific metrics with a `$datasource` template variable:

```json
{
  "rows": [
    {
      "panels": [
        {
          "datasource": "$datasource",
          "targets": [
            {
              "expr": "sum(guardrail_requests_total)",
              "legendFormat": ""
            }
          ],
          "title": "Total Requests",
          "type": "singlestat"
        }
      ]
    }
  ]
}
```

## Configuration

- **Key settings:** `metrics.dashboard.enabled` (default `false`) -- must be explicitly enabled; `metrics.dashboard.odc` (default `false`) -- adds `console.openshift.io/odc-dashboard: "true"` label for Developer Console visibility
- **Defaults:** Both dashboard toggles default to `false` since the ConfigMap targets `openshift-config-managed` namespace which requires cluster-admin privileges
- **Dependencies:** Requires cluster-admin privileges to create ConfigMaps in `openshift-config-managed`; requires OpenShift monitoring stack (Prometheus/Thanos) to be active; the application must expose the Prometheus metrics referenced in the dashboard queries

## Gotchas

- The ConfigMap targets `namespace: openshift-config-managed` (hardcoded in the template), which is outside the Helm release namespace -- this requires cluster-admin privileges and the comment in values.yaml explicitly notes this (see `chart/values.yaml` line 37 and `chart/templates/dashboard-configmap.yaml`)
- The `console.openshift.io/dashboard: "true"` label is what makes OpenShift Console discover and display the dashboard -- removing this label hides the dashboard (see `chart/templates/dashboard-configmap.yaml`)
- The `console.openshift.io/odc-dashboard: "true"` label is separate and only added when `metrics.dashboard.odc` is true -- without it, the dashboard appears only in the Administrator perspective, not the Developer perspective (see `chart/templates/dashboard-configmap.yaml`)
- Uses `.Files.Get "dashboards/lemonade-dashboard.json"` to load the dashboard from a separate file rather than inlining the JSON in the template -- this keeps the 503-line JSON dashboard maintainable (see `chart/templates/dashboard-configmap.yaml`)

## Related Patterns

- `helm-uwm-podmonitor-vllm.md` -- alternative monitoring pattern using PodMonitor for vLLM metrics
- `helm-inline-grafana-alerting-loki-webhook.md` -- Grafana dashboards configured through Helm values for standalone Grafana deployments
