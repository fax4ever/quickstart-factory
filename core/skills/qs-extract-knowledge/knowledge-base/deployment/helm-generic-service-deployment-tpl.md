---
name: helm-generic-service-deployment-tpl
description: Helm named template generating Deployment+Service+HPA from a dict of service config parameters
summary: "Eliminates Deployment+Service+HPA boilerplate across multiple microservices by using a single Helm named template (_service-deployment.tpl) that accepts a dict of serviceName, serviceConfig, imageKey, and context to generate all three resources with enforced security context (runAsNonRoot, seccompProfile RuntimeDefault, drop ALL capabilities). Use when multiple microservices share the same Deployment/Service/HPA structure but need per-service tuning of startup probes, termination grace periods, autoscaling behavior, and environment variables -- the template handles differentiation via \"if eq $serviceName\" conditionals and env var dispatch to per-service named templates in _env-helpers.tpl. Key settings: $serviceConfig.replicas defaults to 2, $serviceConfig.healthChecks allows full override of liveness/readiness/startup probes, $serviceConfig.autoscaling enables autoscaling/v2 HPA with per-service scale-up policies (agent-service: 30s stabilization/100% vs 60s/50% for others), and images resolve via $context.Values.image.<imageKey>. MLflow CA bundle volume mount is conditionally included only for agent-service when $context.Values.mlflow.enabled is true, agent-service uses longer startup (15s initial/60 failures) and termination (60s) than other services (10s/30 failures/30s), and the shorter HPA stabilization window for agent-service is deliberate to handle sudden load spikes from agent sessions."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, fastapi]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "One _service-deployment.tpl generates Deployment+Service+HPA for 3 microservices with per-service health check defaults"
    approach: "A"
---

# Helm Generic Service Deployment Template

## Overview

This pattern uses a Helm named template (`define "self-service-agent.serviceDeployment"`) that generates a complete Deployment, Service, and optional HorizontalPodAutoscaler from a dict of parameters. Three microservices (request-manager, agent-service, integration-dispatcher) reuse the same template by passing their own configuration, eliminating boilerplate while still supporting per-service health check tuning, environment variables, and autoscaling behavior.

## Pattern Description

The template accepts a dict with `serviceName`, `serviceConfig`, `imageKey`, and `context` keys. It produces a Deployment with security context (runAsNonRoot, seccompProfile, drop ALL capabilities), a ClusterIP Service, and a conditionally-rendered HPA. Per-service differentiation is handled via `{{- if eq $serviceName "..." }}` blocks for env var templates, health check defaults, startup probe timing, termination grace period, and autoscaling scale-up aggressiveness.

## Implementation

### Template Invocation

Each service's deployment YAML calls the named template with a dict:

```yaml
# helm/templates/agent-service-deployment.yaml
{{ include "self-service-agent.serviceDeployment" (dict
  "serviceName" "agent-service"
  "serviceConfig" .Values.requestManagement.agentService
  "imageKey" "agentService"
  "context" .) }}
```

### Template Structure with Per-Service Defaults

```yaml
# helm/templates/_service-deployment.tpl (excerpt)
{{- define "self-service-agent.serviceDeployment" -}}
spec:
  replicas: {{ $serviceConfig.replicas | default 2 }}
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: {{ $serviceName }}
        image: "{{ $context.Values.image.registry }}/{{ index $context.Values.image $imageKey }}:{{ $context.Values.image.tag }}"
        env:
        {{- if eq $serviceName "request-manager" }}
        {{- include "self-service-agent.requestManagerAllEnvVars" $context | nindent 8 }}
        {{- else if eq $serviceName "agent-service" }}
        {{- include "self-service-agent.agentServiceAllEnvVars" $context | nindent 8 }}
        {{- end }}
        # Per-service startup probe tuning
        startupProbe:
          initialDelaySeconds: {{- if eq $serviceName "agent-service" }} 15
            {{- else if eq $serviceName "integration-dispatcher" }} 20
            {{- else }} 10{{- end }}
          failureThreshold: {{- if eq $serviceName "agent-service" }} 60
            {{- else }} 30{{- end }}
      terminationGracePeriodSeconds: {{- if eq $serviceName "agent-service" }} 60
        {{- else }} 30{{- end }}
{{- end }}
```

### HPA with Per-Service Scale-Up Behavior

```yaml
# helm/templates/_service-deployment.tpl (HPA excerpt)
{{- if $serviceConfig.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  behavior:
    scaleUp:
      stabilizationWindowSeconds: {{- if eq $serviceName "agent-service" }} 30
        {{- else }} 60{{- end }}
      policies:
      - type: Percent
        value: {{- if eq $serviceName "agent-service" }} 100
          {{- else }} 50{{- end }}
{{- end }}
```

## Configuration

- **Key settings:** `$serviceConfig.replicas` defaults to 2; `$serviceConfig.healthChecks` allows full override of liveness/readiness/startup probes; `$serviceConfig.autoscaling` enables HPA with configurable CPU/memory thresholds; `$serviceConfig.uvicornWorkers` sets the UVICORN_WORKERS env var
- **Defaults:** Agent-service gets longer startup (15s initial, 60 failures), longer termination (60s), and more aggressive scale-up (100% / 30s window); other services use 10s initial, 30 failures, 30s termination, 50% / 60s window
- **Dependencies:** Environment variable templates (`_env-helpers.tpl`) define per-service env var blocks; image names reference `$context.Values.image.<imageKey>`

## Gotchas

- The template includes the MLflow CA bundle volume mount conditionally for `agent-service` only, using `{{- if and (eq $serviceName "agent-service") $context.Values.mlflow.enabled }}` -- other services do not need this volume (see `helm/templates/_service-deployment.tpl`)
- The env var dispatch uses named templates per service (`requestManagerAllEnvVars`, `agentServiceAllEnvVars`, `integrationDispatcherAllEnvVars`) defined in `_env-helpers.tpl`, keeping the deployment template clean while allowing extensive per-service env config
- The HPA stabilization window for agent-service (30s) is shorter than for other services (60s) because agent sessions can create sudden load spikes that need rapid response (see `helm/templates/_service-deployment.tpl`)

## Related Patterns

- `makefile-multi-profile-helm-install.md` -- Makefile targets that set values consumed by this template
