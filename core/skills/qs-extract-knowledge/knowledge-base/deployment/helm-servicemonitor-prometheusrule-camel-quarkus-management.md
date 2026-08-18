---
name: helm-servicemonitor-prometheusrule-camel-quarkus-management
description: ServiceMonitor targeting Camel Quarkus management port with PrometheusRule custom alerts for domain-specific pipeline events
summary: "Deploys Helm-managed ServiceMonitor and PrometheusRule for Camel Quarkus pipeline components that expose metrics on a dedicated management port (9876) via dual-port Services (http:8080 + management:9876). Use when Camel Quarkus components need per-component metric scraping at the non-standard /observe/metrics path with domain-specific alerts on application-defined counters (not framework metrics) -- requires OpenShift User Workload Monitoring or Prometheus Operator for CRD consumption. Helm range loop creates one ServiceMonitor per enabled component (30s scrape interval); a single PrometheusRule uses increase(...[1m]) > 0 expressions with severity labels (warning for error detection, info for pipeline completion); health probes target /observe/health/{started,live,ready} on management port 9876. Metrics path is /observe/metrics (set by camel-observability-services dependency, not default /metrics), alert expressions reference application-defined Camel route counters like correlator_errors_detected_total, and PrometheusRule annotations require double-brace escaping ({{ \"{{ $value }}\" }}) to prevent Helm Go templating from evaluating Prometheus template expressions."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, quarkus, camel, prometheus]
  ai_pattern: [data-pipeline]
  platform: [openshift]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "ServiceMonitor per component scraping /observe/metrics on management port 9876, plus PrometheusRule with domain alerts for error detection and analysis completion rates"
    approach: "A"
---

# ServiceMonitor and PrometheusRule for Camel Quarkus Management Port

## Overview

A Helm chart pattern deploying ServiceMonitor and PrometheusRule resources alongside Camel Quarkus application components. The ServiceMonitors scrape metrics from the Camel Quarkus management port (9876) at a non-standard path (`/observe/metrics`), while the PrometheusRule defines domain-specific alerts based on custom application metrics exposed by the Camel routes.

## Pattern Description

Each Camel Quarkus component exposes metrics on a dedicated management port (9876) separate from the application port (8080). The Helm chart creates one ServiceMonitor per component using the same range loop pattern as all other resources. A single PrometheusRule defines alerts that monitor custom Camel metrics -- in this case, counters for error detection events and LLM analysis completions. The Service resource exposes both the application port and the management port.

## Implementation

### Dual-Port Service

Each component's Service exposes both the application and management ports:

```yaml
# chart/templates/service.yaml
spec:
  ports:
    - name: http
      port: 8080
      targetPort: 8080
      protocol: TCP
    - name: management
      port: 9876
      targetPort: 9876
      protocol: TCP
```

### ServiceMonitor per Component

```yaml
# chart/templates/servicemonitor.yaml
{{- range $name, $component := .Values.components }}
{{- if $component.enabled }}
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: {{ $name }}
  labels:
    app: {{ $name }}
    app.kubernetes.io/part-of: smart-log-analyzer
spec:
  selector:
    matchLabels:
      app: {{ $name }}
  endpoints:
    - port: management
      path: /observe/metrics
      interval: 30s
{{- end }}
{{- end }}
```

### PrometheusRule with Domain-Specific Alerts

```yaml
# chart/templates/prometheusrule.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: smart-log-analyzer
spec:
  groups:
    - name: smart-log-analyzer.rules
      rules:
        - alert: ErrorDetected
          expr: increase(correlator_errors_detected_total[1m]) > 0
          labels:
            severity: warning
          annotations:
            summary: "Microservice error detected"
            description: 'The correlator has detected {{ "{{ $value | printf \"%.0f\" }}" }} new ERROR-severity events in the last minute.'
        - alert: AnalysisCompleted
          expr: increase(analyzer_analyses_completed_total[1m]) > 0
          labels:
            severity: info
          annotations:
            summary: "Error analysis completed"
            description: 'The analyzer has completed {{ "{{ $value | printf \"%.0f\" }}" }} LLM root cause analyses in the last minute.'
```

### Quarkus Health and Metrics Endpoints

The deployments use the management port for health probes as well:

```yaml
# chart/templates/deployment.yaml (probes)
startupProbe:
  httpGet:
    path: /observe/health/started
    port: 9876
livenessProbe:
  httpGet:
    path: /observe/health/live
    port: 9876
readinessProbe:
  httpGet:
    path: /observe/health/ready
    port: 9876
```

## Configuration

- **Key settings:** Management port 9876; metrics path `/observe/metrics`; health paths `/observe/health/{started,live,ready}`; scrape interval 30 seconds
- **Defaults:** All enabled components get a ServiceMonitor; one shared PrometheusRule covers all alerts; alerts use `increase(...[1m]) > 0` to detect any activity in the last minute
- **Dependencies:** OpenShift User Workload Monitoring or a Prometheus Operator instance must be deployed to consume the ServiceMonitor and PrometheusRule CRDs

## Gotchas

- The metrics path is `/observe/metrics` (not the Prometheus default `/metrics`) -- this is the Camel Quarkus observability services default path set by the `camel-observability-services` dependency
- The PrometheusRule alert expressions reference custom metric names (`correlator_errors_detected_total`, `analyzer_analyses_completed_total`) that are exposed by the Camel routes -- these are application-defined counters, not framework metrics
- The double-brace escaping in the PrometheusRule annotations (`{{ "{{ $value | printf \"%.0f\" }}" }}`) is required because Helm's Go templating would otherwise try to evaluate the Prometheus template expressions
- The `severity: info` label on the AnalysisCompleted alert makes it informational rather than actionable -- it confirms the pipeline is working, not that something is wrong

## Related Patterns

- `helm-range-loop-multi-component-files-get-properties.md` -- the parent chart pattern that hosts these observability resources
