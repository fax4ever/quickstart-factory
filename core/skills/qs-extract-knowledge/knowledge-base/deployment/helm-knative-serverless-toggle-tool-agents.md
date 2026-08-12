---
name: helm-knative-serverless-toggle-tool-agents
description: Conditional Knative Serving templates for tool agents toggled by serverless.enabled with autoscaling annotations
summary: "Enables optional Knative Serving deployment for tool-agent microservices in multi-agent Helm charts, toggled by serverless.enabled (default false), allowing scale-to-zero and burst autoscaling alongside always-active standard Kubernetes Deployments. Use when specific tool agents (e.g., risk, portfolio) have variable load benefiting from serverless autoscaling -- orchestrator, UI, guidelines, and guardrails agents remain Deployment-only; Knative Serving must be pre-installed on the cluster. Each tool agent has a separate ksvc-*.yaml template gated by {{ if .Values.serverless.enabled }} with autoscaling.knative.dev/min-scale and max-scale annotations plus containerConcurrency and timeoutSeconds spec fields, sharing centralized values (minScale: \"0\", maxScale: \"5\", concurrency: 10, timeoutSeconds: 60) and per-agent image tags. Knative Service and Deployment share the same name causing potential Service shadowing; minScale/maxScale must be quoted strings not integers matching Knative annotation format; ksvc templates are minimal -- missing readiness probes (/tools on port 7002), env vars, and volume mounts present in Deployment counterparts; orchestrator's TOOL_SERVERS env var must resolve service names regardless of deployment mode."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [agents]
  platform: [openshift, kserve]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Knative Service templates for risk and portfolio tool agents conditionally deployed when serverless.enabled=true, with configurable min/max scale, concurrency, and timeout"
    approach: "A"
---

# Knative Serverless Toggle for Tool Agents

## Overview

This pattern provides optional Knative Serving deployment for tool-agent microservices, allowing the same Helm chart to deploy agents as either standard Kubernetes Deployments or autoscaling Knative Services. It is suited for multi-agent architectures where individual tool agents have variable load and benefit from scale-to-zero or burst scaling.

## Pattern Description

The Helm chart includes both standard Deployment templates (always active) and conditional Knative Service (`ksvc`) templates gated by `{{ if .Values.serverless.enabled }}`. When serverless is enabled, the Knative Services are created alongside the Deployments. The `serverless` values block controls autoscaling parameters (min/max scale, concurrency target, timeout) shared across all serverless tool agents.

## Implementation

### Conditional Knative Service Templates

Each tool agent that supports serverless has its own `ksvc-*.yaml` template:

```yaml
# deploy/helm/templates/ksvc-portfolio.yaml
{{- if .Values.serverless.enabled }}
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: investment-advisor-agent-portfolio
  namespace: {{ .Values.namespace }}
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/min-scale: {{ .Values.serverless.minScale | quote }}
        autoscaling.knative.dev/max-scale: {{ .Values.serverless.maxScale | quote }}
    spec:
      containerConcurrency: {{ .Values.serverless.concurrency }}
      timeoutSeconds: {{ .Values.serverless.timeoutSeconds }}
      containers:
        - name: container
          image: {{ .Values.image.repository }}:{{ .Values.image.tags.portfolio }}
          ports:
            - containerPort: 7002
              protocol: TCP
{{- end }}
```

### Values Configuration

```yaml
# deploy/helm/values.yaml
serverless:
  enabled: false
  minScale: "0"
  maxScale: "5"
  concurrency: 10
  timeoutSeconds: 60
```

### Standard Deployment (Always Active)

The standard Deployment template for the same agent is unconditional:

```yaml
# deploy/helm/templates/deployment-portfolio.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: investment-advisor-agent-portfolio
  namespace: {{ .Values.namespace }}
spec:
  replicas: {{ .Values.replicas }}
  selector:
    matchLabels:
      app: investment-advisor-agent-portfolio
  template:
    spec:
      containers:
        - name: container
          image: {{ .Values.image.repository }}:{{ .Values.image.tags.portfolio }}
          ports:
            - containerPort: 7002
              protocol: TCP
          readinessProbe:
            httpGet:
              path: /tools
              port: 7002
```

## Configuration

- **Key settings:** `serverless.enabled` (default: `false`) toggles Knative Services; `minScale: "0"` enables scale-to-zero; `maxScale: "5"` caps burst scaling; `concurrency: 10` sets concurrent requests per pod; `timeoutSeconds: 60` sets request timeout
- **Defaults:** Serverless is disabled by default; two tool agents (risk, portfolio) have Knative Service templates; other agents (guidelines, orchestrator, UI) remain as Deployments only
- **Dependencies:** Knative Serving must be installed on the cluster when `serverless.enabled=true`; the Knative Service names match the Deployment names, which may conflict if both are active

## Gotchas

- When `serverless.enabled=true`, both the standard Deployment and the Knative Service are created for risk and portfolio agents -- they share the same name, which means the Knative Service may shadow the Deployment's Service; the orchestrator's `TOOL_SERVERS` env var references service names that must resolve regardless of deployment mode (see `deploy/helm/templates/deployment-orchestrator.yaml`)
- The `minScale` and `maxScale` values are quoted strings (`"0"`, `"5"`) not integers, matching the Knative annotation format which expects strings (see `deploy/helm/values.yaml`)
- Not all agents have serverless templates -- the orchestrator, UI, guidelines, and guardrails agents remain as standard Deployments, while only the risk and portfolio tool agents have `ksvc-*.yaml` templates (see `deploy/helm/templates/` listing)
- The Knative Service templates do not include readiness probes, environment variables, or volume mounts that the corresponding Deployment templates have -- they are minimal compared to the Deployment versions (compare `ksvc-portfolio.yaml` with `deployment-portfolio.yaml`)

## Related Patterns

- `helm-flat-chart-direct-crd-templating.md` -- the flat chart pattern this quickstart uses
- `helm-knative-kafka-cloudevents-triggers.md` -- Knative eventing (different from Knative serving used here)
