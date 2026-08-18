---
name: helm-inline-grafana-alerting-loki-webhook
description: Grafana alert rules watching Loki for Ansible log statuses, triggering webhook to backend inference
summary: "Configures Grafana unified alerting with Loki LogQL alert rules, webhook contact points, and notification policies entirely inline in a Helm umbrella chart's values.yaml to detect fatal/failed Ansible log entries and POST to a backend inference endpoint. Use when you need Helm-declarative observability alerting on Loki log patterns without an external alert manager -- alert rules use a three-step expression chain (LogQL count_over_time query, reduce sum, threshold gt 0) firing immediately with notification policies grouping by alertname/status/job. Critical config: Loki runs SingleBinary mode with 2MB max_line_size and 100MB ingestion rate for large Ansible logs, all non-SingleBinary replicas zeroed; Grafana requires unified_alerting: true with legacy alerting: false and feature toggles alertingSimplifiedRouting/alertingQueryAndExpressionsStepMode; webhook URL uses Go template urlquery with .CommonAnnotations/.CommonLabels to pass alert context as query parameters. Gotchas: Go template double-curly-brace escaping ({{ \"{{\" }}) is mandatory in Helm values to prevent chart rendering conflicts, Loki gateway resolver is hardcoded to OpenShift DNS IP 172.30.0.10, Loki datasource uid must match alert rule datasourceUid, and Grafana/Loki charts must be committed as tgz in charts/."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, grafana, loki]
  ai_pattern: [agents]
  platform: [openshift]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Grafana unified alerting with Loki LogQL, webhook contact points to backend with Go template params"
    approach: "A"
---

# Grafana Alerting with Loki LogQL and Backend Webhook

## Overview

This pattern configures Grafana's unified alerting system entirely through Helm values to monitor a Loki log store for specific Ansible log statuses (fatal, failed) and trigger webhook notifications to the backend's inference endpoint. The entire alerting pipeline -- contact points, notification policies, alert rules, datasources, and Grafana feature toggles -- is defined inline in the umbrella chart's `values.yaml`.

## Pattern Description

The Grafana subchart is configured via nested values in the parent chart's `values.yaml`. Alert rules use Loki LogQL `count_over_time` queries to detect fatal and failed log entries within 5-minute windows. When triggered, alerts are routed through notification policies to a webhook contact point that POSTs to the backend's `/grafana-alert/` endpoint with Go-templated query parameters extracting labels from the alert annotations. Loki is configured in SingleBinary deployment mode with high ingestion limits for bulk historical log loading.

## Implementation

### Grafana Datasource Provisioning

The Loki datasource is provisioned via the Grafana subchart's `datasources` values:

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (grafana section)
grafana:
  fullnameOverride: grafana
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
      - access: proxy
        editable: true
        isDefault: true
        name: Loki
        type: loki
        url: http://loki:3100
        uid: loki
```

### Alert Rules with Loki LogQL

Two alert rules monitor Loki for fatal and failed log statuses. Each uses a three-step expression chain (LogQL query, reduce to sum, threshold check):

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (grafana.alerting.rules section)
rules:
  - uid: fatal-logs-alert
    title: Fatal Ansible Logs
    condition: C
    data:
      - refId: A
        datasourceUid: loki
        model:
          expr: 'count_over_time({status="fatal"}[5m])'
          queryType: instant
      - refId: B
        datasourceUid: __expr__
        model:
          expression: A
          reducer: sum
          type: reduce
      - refId: C
        datasourceUid: __expr__
        model:
          expression: B
          type: threshold
          conditions:
            - evaluator:
                params: [0]
                type: gt
    annotations:
      summary: "Detected fatal Ansible log"
    labels:
      severity: critical
      alert_type: ansible_fatal
```

### Webhook Contact Point with Go Template Parameters

The webhook contact point POSTs to the backend inference endpoint, passing alert labels as URL query parameters using Go template syntax:

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (grafana.alerting.contactpoints section)
contactPoints:
  - orgId: 1
    name: backend-inference-webhook
    receivers:
      - uid: backend-webhook-receiver
        type: webhook
        settings:
          url: 'http://alm-backend:8000/grafana-alert/?log_message={{ "{{" }} urlquery (or .CommonAnnotations.description .CommonAnnotations.summary "Grafana alert triggered") {{ "}}" }}&detected_level={{ "{{" }} urlquery (or .CommonLabels.detected_level "error") {{ "}}" }}&filename={{ "{{" }} urlquery (or .CommonLabels.filename "unknown") {{ "}}" }}'
          httpMethod: POST
```

### Loki SingleBinary with High Ingestion Limits

Loki is configured in SingleBinary mode with tuned limits for large Ansible log entries:

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (loki section)
loki:
  fullnameOverride: loki
  deploymentMode: SingleBinary
  singleBinary:
    replicas: 3
  loki:
    limits_config:
      max_line_size: 2MB
      ingestion_rate_mb: 100
      ingestion_burst_size_mb: 200
      max_global_streams_per_user: 100000
    server:
      grpc_server_max_recv_msg_size: 104857600  # 100MB
      grpc_server_max_send_msg_size: 104857600  # 100MB
```

### Grafana Feature Toggles and Unified Alerting

Unified alerting is explicitly enabled and legacy alerting disabled via `grafana.ini`:

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (grafana.grafana.ini section)
grafana.ini:
  unified_alerting:
    enabled: true
  alerting:
    enabled: false
  feature_toggles:
    enable: alertingSimplifiedRouting,alertingQueryAndExpressionsStepMode
```

## Configuration

- **Key settings:** Alert rules evaluate every 1 minute with 0s `for` duration (fire immediately); notification policies group by `alertname`, `status`, `job` with 10s group_wait and 4h repeat_interval
- **Defaults:** Grafana admin user/password set to `admin`/`alm_password`; Loki `auth_enabled: false`; Loki uses its built-in MinIO for chunk storage
- **Dependencies:** Requires Loki to be running at `http://loki:3100`; backend must expose `/grafana-alert/` endpoint; Grafana and Loki charts committed as tgz in `charts/`

## Gotchas

- The Go template syntax for the webhook URL requires double-curly-brace escaping in Helm values: `{{ "{{" }}` and `{{ "}}" }}` to prevent Helm from interpreting the Go templates during chart rendering (see `values.yaml` line 94)
- Loki's `max_line_size: 2MB` is set because Ansible log entries range from 415-757 KB per the inline comment (see `values.yaml` line 346)
- Loki's `gateway.nginxConfig.resolver` is hardcoded to `172.30.0.10` which is the OpenShift DNS resolver IP (see `values.yaml` line 416)
- All non-SingleBinary Loki deployment modes have their replicas zeroed out explicitly (backend, read, write, ingester, querier, etc.) to prevent stale defaults from the Loki chart (see `values.yaml` lines 373-397)

## Related Patterns

- `helm-umbrella-mixed-remote-local-committed-deps.md` -- umbrella chart that includes the Grafana and Loki tgz files
- `helm-alloy-sidecar-pvc-log-collector.md` -- Alloy feeds logs into this Loki instance
