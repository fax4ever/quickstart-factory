---
name: helm-kagenti-agentruntime-a2a-spire-mlflow-toggle
description: Kagenti AgentRuntime CRD with SPIRE sidecar injection, multi-port A2A per-agent exposure, and MLflow autoManaged toggle
summary: "Deploys a Kagenti AgentRuntime CRD (mtlsMode: permissive, egressEnforcement: none) to register an API Deployment with the Kagenti A2A mesh, injecting SPIRE sidecars via pod annotations (kagenti.io/inject, kagenti.io/spire) and protocol.kagenti.io/a2a label with SVID certificates output to a readOnly emptyDir at /spiffe. Use when building multi-agent A2A on OpenShift needing per-persona port exposure -- Helm range over agent names (public, borrower, lo, uw, ceo) assigns sequential ports from kagenti.a2aBasePort (default 8080-8084); set kagenti.mlflow.autoManaged=true to delegate MLflow RBAC to the Kagenti controller, skipping manual ServiceAccount/ClusterRole/ClusterRoleBinding via the nil-safe `dig \"mlflow\" \"autoManaged\" false .Values.kagenti` pattern. When kagenti.enabled=true, uvicorn is explicitly overridden to port 8001 via command/args to accommodate the sidecar proxy, with inboundPortsExclude: \"8000\" leaving the API port outside mTLS and outboundPortsExclude: \"5432,9000,8081\" bypassing database and internal services. Gotchas: the conditional ServiceAccount switch (mlflow-client vs default SA) can trigger pod restarts if the autoManaged toggle changes mid-lifecycle, the SPIRE emptyDir is readOnly so only the operator-injected sidecar writes SVID certs, and the Kagenti operator plus SPIRE server must be pre-installed."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [agents]
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Kagenti AgentRuntime CRD for multi-agent A2A, SPIRE sidecar, dynamic port allocation, MLflow controller auto-management"
    approach: "A"
---

# Kagenti AgentRuntime with A2A Multi-Port and SPIRE Sidecar

## Overview

This pattern integrates the Kagenti operator for Agent-to-Agent (A2A) communication in a multi-agent deployment. It creates an `AgentRuntime` CRD, injects SPIRE sidecars for mTLS identity via pod annotations, dynamically exposes one A2A port per agent persona using Helm template range, and optionally delegates MLflow RBAC and environment variable injection to the Kagenti MLflow controller.

## Pattern Description

The Kagenti operator manages agent lifecycle and inter-agent communication. When `kagenti.enabled=true`, the API deployment gains several modifications: SPIRE sidecar injection annotations, A2A protocol labels, per-agent port exposure (one port per persona), an emptyDir volume for SPID output, and a shifted application port (8001 instead of 8000) to accommodate the sidecar. An `AgentRuntime` CR targets the Deployment to register it with the Kagenti mesh. When `kagenti.mlflow.autoManaged=true`, manual MLflow RBAC (ServiceAccount, ClusterRole, ClusterRoleBinding) is skipped in favor of the Kagenti MLflow controller auto-discovering and injecting configuration.

## Implementation

### AgentRuntime CRD

The AgentRuntime CR registers the API deployment as an agent in the Kagenti mesh:

```yaml
# deploy/helm/mortgage-ai/templates/kagenti-agentruntime.yaml
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: {{ .Values.api.name }}
  labels:
    kagenti.io/type: agent
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ .Values.api.name }}
  type: agent
  mtlsMode: permissive
  egressEnforcement: none
```

### SPIRE Sidecar Injection via Pod Annotations

SPIRE is injected by the Kagenti operator based on pod-level annotations:

```yaml
# deploy/helm/mortgage-ai/templates/api-deployment.yaml (excerpt)
template:
  metadata:
    labels:
      kagenti.io/type: agent
      protocol.kagenti.io/a2a: ""
    annotations:
      kagenti.io/inject: "enabled"
      kagenti.io/spire: "enabled"
      kagenti.io/inbound-ports-exclude: {{ .Values.kagenti.inboundPortsExclude }}
      kagenti.io/outbound-ports-exclude: {{ .Values.kagenti.outboundPortsExclude }}
```

### Dynamic A2A Port Allocation Per Agent Persona

Each agent persona gets its own A2A port, allocated sequentially from a configurable base:

```yaml
# deploy/helm/mortgage-ai/templates/api-deployment.yaml (excerpt)
ports:
  - name: http
    containerPort: 8000
    protocol: TCP
  {{- if .Values.kagenti.enabled }}
  {{- range $i, $name := list "public" "borrower" "lo" "uw" "ceo" }}
  - name: a2a-{{ $name }}
    containerPort: {{ add $.Values.kagenti.a2aBasePort $i }}
    protocol: TCP
  {{- end }}
  {{- end }}
```

### Application Port Shift with Kagenti

When Kagenti is enabled, uvicorn listens on port 8001 instead of 8000 (the default from the Containerfile CMD) to make room for the Kagenti sidecar proxy:

```yaml
# deploy/helm/mortgage-ai/templates/api-deployment.yaml (excerpt)
{{- if .Values.kagenti.enabled }}
command: ["uvicorn"]
args: ["src.main:app", "--host", "0.0.0.0", "--port", "8001"]
{{- end }}
```

### MLflow autoManaged Toggle

When the Kagenti MLflow controller is available, manual RBAC and env var injection are skipped:

```yaml
# deploy/helm/mortgage-ai/templates/secret.yaml (excerpt)
{{- if not (dig "mlflow" "autoManaged" false .Values.kagenti) }}
MLFLOW_TRACKING_URI: {{ .Values.secrets.MLFLOW_TRACKING_URI | toString | b64enc }}
MLFLOW_EXPERIMENT_NAME: {{ .Values.secrets.MLFLOW_EXPERIMENT_NAME | toString | b64enc }}
{{- end }}
```

The `dig` function safely navigates the nested values structure, defaulting to `false` if any key is missing.

### SPIRE Volume Mount

An emptyDir volume is mounted for SPIRE to output SVID certificates:

```yaml
# deploy/helm/mortgage-ai/templates/api-deployment.yaml (excerpt)
volumeMounts:
  - name: svid-output
    mountPath: /spiffe
    readOnly: true
volumes:
  - name: svid-output
    emptyDir: {}
```

## Configuration

- **Key settings:** `kagenti.enabled` toggles all Kagenti integration; `kagenti.a2aBasePort` (default: 8080) sets the first A2A port; `kagenti.inboundPortsExclude` (default: "8000") and `kagenti.outboundPortsExclude` (default: "5432,9000,8081") control sidecar interception; `kagenti.mlflow.autoManaged` (default: false) delegates MLflow to the Kagenti controller
- **Defaults:** `mtlsMode: permissive` allows both mTLS and plain traffic; `egressEnforcement: none` does not restrict outbound; five agent personas (public, borrower, lo, uw, ceo) mapped to ports 8080-8084
- **Dependencies:** Kagenti operator must be installed; SPIRE server must be running in the cluster; when `mlflow.autoManaged=true`, the Kagenti MLflow controller must be deployed

## Gotchas

- The application port shifts from 8000 to 8001 when Kagenti is enabled, overriding the Containerfile's default CMD -- the command/args are explicitly set in the Deployment template (see `deploy/helm/mortgage-ai/templates/api-deployment.yaml` lines 97-99)
- The `inboundPortsExclude: "8000"` value excludes the main API port from sidecar interception, meaning the HTTP API is not mTLS-protected while A2A ports are (see `deploy/helm/mortgage-ai/values.yaml` line 369)
- The `dig "mlflow" "autoManaged" false .Values.kagenti` pattern avoids nil pointer errors when the `kagenti.mlflow` key doesn't exist at all in values -- `dig` traverses nested maps safely (see `deploy/helm/mortgage-ai/templates/secret.yaml` line 68, `api-deployment.yaml` line 36)
- The ServiceAccount for the API pod switches between `mlflow-client` and the default SA based on whether manual MLflow RBAC is active -- this conditional SA selection could cause pod restart if the toggle changes (see `deploy/helm/mortgage-ai/templates/api-deployment.yaml` lines 36-40)
- The SPIRE emptyDir volume is mounted as `readOnly: true` in the application container, meaning the SPIRE sidecar (injected by the operator) writes to it and the app only reads (see `deploy/helm/mortgage-ai/templates/api-deployment.yaml` lines 349-353)

## Related Patterns

- `helm-mlflow-clusterrole-rhoai-pipeline-runner-rbac.md` -- the manual MLflow RBAC that Kagenti autoManaged replaces
- `helm-mcp-gateway-httproute-mcpserverregistration.md` -- MCP Gateway integration that complements Kagenti A2A
