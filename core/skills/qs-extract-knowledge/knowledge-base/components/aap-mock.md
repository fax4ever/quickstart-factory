---
name: aap-mock
description: "Helm subchart deploying a mock Ansible Automation Platform log generator for testing log-analysis pipelines"
summary: "Mock AAP log generator (sourced from RHEcosystemAppEng/aap-log-generator) deployed as a conditional Helm subchart (aap-mock.enabled) within ansible-log-monitor, providing realistic logs consumed by aap-log-collector sidecar and Alloy/Loki pipeline for agentic AI log analysis on port 8080. Use when testing log-analysis pipelines without a real AAP instance; triple PVC layout (data 2Gi/logs 1Gi/sampleLogs 2Gi, emptyDir fallback when disabled) separates concerns, Makefile targets (load-logs via oc cp, trigger-refresh, trigger-replay with configurable rate_lines_per_sec) orchestrate replay, route.enabled toggles OpenShift Route vs ingress for non-OpenShift clusters, and logs can alternatively be baked into the Alloy image bypassing load-logs. Critical config: probes.liveness.initialDelaySeconds must be 120+ because the app loads all log files into memory before starting the HTTP server (~60-90s for 500 files, ~1.5GB memory requiring 2Gi limit); enforce OpenShift-restricted SCC via runAsNonRoot, drop ALL capabilities, and seccompProfile RuntimeDefault; only the probes.* values block is used in the deployment template despite dual probe definitions in values.yaml. Gotchas: PVCs are not auto-deleted on helm uninstall (requires manual kubectl delete pvc -l app.kubernetes.io/name=aap-mock), init container readiness gate blocks downstream services until both /healthz passes and /api/v2/jobs/ count > 0, and setting probe initialDelaySeconds lower than defaults causes pod restart loops with large log sets."
metadata:
  type: component
tags:
  tech_stack: [python, helm]
  ai_pattern: [data-pipeline]
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Mock AAP log generator deployed as Helm subchart with triple PVC layout and Makefile-driven log loading"
    approach: "A"
---

# AAP Mock (Ansible Automation Platform Log Generator)

## Overview

The aap-mock component is a mock Ansible Automation Platform that generates realistic AAP logs for testing and demonstration purposes. It serves as the data source in a log-analysis pipeline, providing sample log data that flows through collectors (Alloy/Promtail) into Loki and is processed by an agentic AI workflow. It is deployed as a conditional local Helm subchart within the `ansible-log-monitor` parent chart.

## Tech Stack & Dependencies

- **Runtime:** Python (containerized)
- **Container image:** `quay.io/rh-ai-quickstart/alm-aap-mock:latest`
- **Key dependencies:** None internal; consumed by the `aap-log-collector` sidecar and Alloy log collector
- **Helm subchart:** Local subchart under `deploy/helm/ansible-log-monitor/charts/aap-mock/` (v0.1.0)
- **Upstream source:** https://github.com/RHEcosystemAppEng/aap-log-generator

## Key Patterns

### Conditional Local Subchart

The aap-mock chart is wired as a local dependency in the parent `ansible-log-monitor` chart with a condition flag, making it optional for environments where a real AAP is available.

```yaml
# deploy/helm/ansible-log-monitor/Chart.yaml
dependencies:
  - name: aap-mock
    version: 0.1.0
    condition: aap-mock.enabled
```

### Triple PVC Layout

The chart defines three separate PersistentVolumeClaims for different data concerns: internal data, application logs, and sample log files loaded for replay. This separation allows independent sizing and lifecycle management.

```yaml
# deploy/helm/ansible-log-monitor/charts/aap-mock/values.yaml
persistence:
  data:
    enabled: true
    size: 2Gi
  logs:
    enabled: true
    size: 1Gi
  sampleLogs:
    enabled: true
    size: 2Gi
```

Each PVC falls back to `emptyDir` when disabled, configured in `deployment.yaml`:

```yaml
# deploy/helm/ansible-log-monitor/charts/aap-mock/templates/deployment.yaml
volumes:
  - name: data
    {{- if .Values.persistence.data.enabled }}
    persistentVolumeClaim:
      claimName: {{ include "aap-mock.fullname" . }}-data
    {{- else }}
    emptyDir: {}
    {{- end }}
```

### Init Container Readiness Gate

Downstream services use an init container that polls the aap-mock `/healthz` endpoint and then waits for sample logs to be available via the `/api/v2/jobs/` endpoint before starting. This pattern ensures the log pipeline does not start until data is ready.

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (alloy section)
initContainers:
  - name: wait-for-aap-mock
    image: registry.access.redhat.com/ubi9/ubi-minimal:latest
    command:
      - sh
      - -c
      - |
        until curl -f -s http://alm-aap-mock:8080/healthz > /dev/null 2>&1; do
          echo "Waiting for AAP Mock service..."
          sleep 5
        done
        until [ $(curl -f -s http://alm-aap-mock:8080/api/v2/jobs/ | grep -o '"count":[0-9]*' | cut -d':' -f2) -gt 0 ] 2>/dev/null; do
          echo "Waiting for sample logs to load..."
          sleep 5
        done
```

### Makefile-Driven Log Loading

Log files are loaded into the running pod via `oc cp` and then the mock API is triggered to refresh and start replay. This two-step pattern (copy files, then API call) is orchestrated through Makefile targets.

```makefile
# deploy/helm/Makefile
load-logs: ## Load logs from data/logs/ to aap-mock and start replay
	@POD=$$(oc get pod -n $(NAMESPACE) -l app.kubernetes.io/name=aap-mock ...); \
	oc cp -n $(NAMESPACE) /tmp/aap-logs-staging/. "$$POD:/app/sample-logs/"; \

trigger-refresh:
	curl -sf -X POST "http://$$ROUTE/api/auto-loaded/refresh"

trigger-replay:
	curl -sf -X POST "http://$$ROUTE/api/logs/replay" \
		-d '{"source": "auto-loaded", "id_or_path": "all", "loop": true, "rate_lines_per_sec": 100}'
```

### OpenShift-Ready Security Context

The chart enforces restricted security settings compatible with OpenShift's default SCC, letting the platform assign UIDs automatically.

```yaml
# deploy/helm/ansible-log-monitor/charts/aap-mock/values.yaml
podSecurityContext:
  runAsNonRoot: true
securityContext:
  allowPrivilegeEscalation: false
  runAsNonRoot: true
  capabilities:
    drop:
    - ALL
  seccompProfile:
    type: RuntimeDefault
```

## Configuration

- **Environment variables:**
  - `PORT` (hardcoded `8080`): HTTP server listen port
  - `PYTHONUNBUFFERED` (`1`): Ensures log output is not buffered
  - Custom env via `app.env` map (e.g., `REPLAY_RATE`, `LOOP_ENABLED`, `OTLP_ENDPOINT`)
- **Config files:** None; all configuration is through env vars and Helm values
- **Helm values:**
  - `enabled` (bool): Toggle the entire deployment on/off from the parent chart
  - `persistence.sampleLogs.size`: Size the sample-logs PVC (comment in values.yaml notes "500 log files ~= 200-300MB")
  - `probes.liveness.initialDelaySeconds` (default `120`): Must allow time for file loading before server starts
  - `probes.readiness.initialDelaySeconds` (default `90`): Files must load before server is marked ready
  - `route.enabled` (default `true`): Creates an OpenShift Route; set `ingress.enabled` for non-OpenShift clusters

## Known Gotchas

- **Long startup time for large log sets:** The app loads all log files into memory before starting the HTTP server. The values.yaml comment states "App loads all log files BEFORE starting server (~60-90s for 500 files)." This is why `probes.liveness.initialDelaySeconds` defaults to 120 and readiness to 90 -- setting these lower will cause pod restarts.
- **Memory sizing tied to log count:** The values.yaml comment notes "Loading 500+ log files requires ~1.5GB memory," which is why the default memory limit is 2Gi with a 512Mi request.
- **PVCs not auto-deleted on uninstall:** The README explicitly warns that PVCs are not automatically deleted and provides the manual cleanup command: `kubectl delete pvc -l app.kubernetes.io/name=aap-mock -n alm-infra`.
- **Dual probe definitions in values.yaml:** The values.yaml contains two sets of probe configurations (`livenessProbe`/`readinessProbe` at top level, and `probes.liveness`/`probes.readiness` lower down). Only the `probes.*` block is actually referenced in the deployment template.
- **Log loading workaround via Alloy:** A Makefile comment notes "As a workaround the logs already included in alloy as part of its image, so this loading not called." The `load-logs` target exists as a fallback for when logs are not baked into the image.

## Testing Notes

- Verify the pod starts and passes both `/healthz` (liveness) and `/readyz` (readiness) probes
- After loading logs, confirm via the status API: `curl -s http://<route>/api/status`
- The init container in the Alloy deployment serves as an integration test gate -- if aap-mock is unhealthy or has no logs, downstream services will not start
- Use `make trigger-refresh` and `make trigger-replay` Makefile targets to exercise the replay API

## Related Patterns

- Observability stack (Alloy/Loki/Grafana) that consumes aap-mock output
- `aap-log-collector` sidecar that polls `http://alm-aap-mock:8080` and writes job logs to a shared PVC
