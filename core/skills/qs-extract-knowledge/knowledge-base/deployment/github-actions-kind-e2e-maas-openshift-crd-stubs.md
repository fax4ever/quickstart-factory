---
name: github-actions-kind-e2e-maas-openshift-crd-stubs
description: Kind-based E2E with MaaS remote inference, stub OpenShift CRDs, Playwright UI tests, and fork-aware PR gate
summary: "Solves E2E testing of Helm-deployed OpenShift AI quickstarts in CI without a real OpenShift cluster or local GPUs, by running a Kind cluster with five stub CRDs (Route, InferenceService, ServingRuntime, DataSciencePipelinesApplication, Notebook) and remote MaaS model inference injected via helm `--set` flags from repository secrets. Use when the quickstart Helm chart references OpenShift/RHOAI CRDs and needs a full deployment test pipeline -- the four-job split (unit, integration, LlamaStack at 60min timeout, Playwright UI via chromium) plus a fork-aware pr-required-checks gate handles both internal and external contributors, triggered on PRs, pushes, manual dispatch, and daily cron at 10:00 UTC. Critical pattern: install stub CRDs with `x-kubernetes-preserve-unknown-fields: true` before helm install, use a `values-e2e.yaml` to disable OpenShift-only components (llm-service, configure-pipeline, ingestion-pipeline, mcp-servers) with `skipModelWait: true`, map Kind NodePorts 30080/30081 to host ports 8501/8321, and build images via Docker Buildx then load into Kind with Chart.yaml version as tag. Common gotchas: must pass `--skip-crds` during helm install to prevent conflicts with separately installed stubs, clear init containers via `--set-json llama-stack.initContainers='[]'` for MaaS mode, monitor port-forward PIDs with check_port_forwarding/check_processes functions during long Playwright runs, and add fork-skip conditions (`github.event.pull_request.head.repo.full_name == github.repository`) on secret-dependent jobs since fork PRs cannot access repository secrets."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python, playwright]
  ai_pattern: [rag, model-serving]
  platform: [kubernetes, openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "4-job E2E workflow with Kind cluster, 5 stub CRDs, MaaS remote model inference, Playwright browser tests, and fork-aware PR gate"
    approach: "A"
---

# Kind E2E with MaaS Remote Inference and OpenShift CRD Stubs

## Overview

This pattern runs end-to-end tests against a full Helm deployment in a Kind cluster, using stub CRDs to simulate OpenShift-specific resources and a remote Model-as-a-Service (MaaS) endpoint for LLM inference. It splits tests across four jobs (unit, integration, LlamaStack integration, Playwright UI) with a final gate job that allows fork PRs to skip secret-dependent tests.

## Pattern Description

The `e2e-tests.yaml` workflow creates a Kind cluster with port mappings, installs minimal stub CRDs for five OpenShift/RHOAI resources (Route, InferenceService, ServingRuntime, DataSciencePipelinesApplication, Notebook), deploys the full Helm chart with MaaS configuration injected via `--set` flags, and runs integration tests against the deployed services via port forwarding. A separate values file (`tests/e2e/values-e2e.yaml`) disables components that require full OpenShift (llm-service, configure-pipeline, ingestion-pipeline, mcp-servers) while keeping core services (pgvector, llama-stack, UI). The workflow runs on PRs, pushes, manual dispatch, and daily cron.

## Implementation

### Stub CRD Installation

Five stub CRDs are created inline to satisfy Helm template rendering without requiring a full OpenShift cluster. Each uses `x-kubernetes-preserve-unknown-fields: true` to accept any spec:

```yaml
# .github/workflows/e2e-tests.yaml (Install Required CRDs step)
# OpenShift Route CRD
kubectl apply -f - <<EOF
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: routes.route.openshift.io
spec:
  group: route.openshift.io
  names:
    kind: Route
    plural: routes
  scope: Namespaced
  versions:
  - name: v1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        x-kubernetes-preserve-unknown-fields: true
EOF

# Also installs: inferenceservices.serving.kserve.io,
# servingruntimes.serving.kserve.io,
# datasciencepipelinesapplications.datasciencepipelinesapplications.opendatahub.io,
# notebooks.kubeflow.org
```

### MaaS Configuration via Helm --set

The model endpoint, ID, and API token are injected at install time from repository secrets, avoiding local GPU requirements:

```yaml
# .github/workflows/e2e-tests.yaml (Install RAG application step)
helm install rag deploy/helm/rag \
  --namespace rag-e2e \
  --values tests/e2e/values-e2e.yaml \
  --set global.models.${MAAS_MODEL_ID}.url="${MAAS_ENDPOINT}" \
  --set global.models.${MAAS_MODEL_ID}.id="${MAAS_MODEL_ID}" \
  --set global.models.${MAAS_MODEL_ID}.enabled=true \
  --set global.models.${MAAS_MODEL_ID}.apiToken="${MAAS_API_KEY}" \
  --set-json llama-stack.initContainers='[]' \
  --skip-crds \
  --timeout 20m \
  --debug
```

### E2E Values File (Disable OpenShift-Only Components)

A dedicated values file disables components that require full OpenShift while keeping the core RAG stack:

```yaml
# tests/e2e/values-e2e.yaml (excerpt)
# Disable components that require OpenShift/KServe CRDs
llm-service:
  enabled: false

configure-pipeline:
  enabled: false

mcp-servers:
  enabled: false

ingestion-pipeline:
  enabled: false

# Keep core services
pgvector:
  enabled: true

llama-stack:
  enabled: true
  initContainers: []
  skipModelWait: true
```

### Kind Cluster with Port Mappings

The Kind cluster config maps container ports to host ports for NodePort-based service access:

```yaml
# Kind cluster config (inline in workflow)
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 8501
    protocol: TCP
  - containerPort: 30081
    hostPort: 8321
    protocol: TCP
```

### Fork-Aware PR Gate Job

A final `pr-required-checks` job aggregates results and allows fork PRs to skip secret-dependent jobs:

```yaml
# .github/workflows/e2e-tests.yaml (pr-required-checks job)
pr-required-checks:
  name: PR tests gate
  if: always() && github.event_name == 'pull_request'
  needs: [unit-tests, integration-tests, llamastack-integration-tests, ui-e2e-tests]
  steps:
    - name: Enforce test job outcomes
      run: |
        is_fork=false
        if [ "${HEAD_REPO}" != "${THIS_REPO}" ]; then is_fork=true; fi

        # Unit and integration tests must always pass
        if [ "${UNIT_RESULT}" != "success" ]; then exit 1; fi
        if [ "${INTEG_RESULT}" != "success" ]; then exit 1; fi

        # Secret-dependent jobs may be skipped for fork PRs
        if [ "${LLAMA_RESULT}" != "success" ]; then
          if [ "${is_fork}" = true ] && [ "${LLAMA_RESULT}" = "skipped" ]; then
            echo "Skipped (fork PR)"
          else
            exit 1
          fi
        fi
```

### Playwright UI E2E Tests

A separate job runs Playwright browser tests against the deployed application with port forwarding and process monitoring:

```yaml
# .github/workflows/e2e-tests.yaml (UI E2E tests)
- name: Install Playwright browsers
  run: playwright install chromium

- name: Run UI E2E tests with Playwright
  env:
    RAG_UI_ENDPOINT: http://localhost:8501
    LLAMA_STACK_ENDPOINT: http://localhost:8321
  run: |
    kubectl port-forward -n rag-e2e-ui svc/rag 8501:8501 &
    kubectl port-forward -n rag-e2e-ui svc/llamastack 8321:8321 &
    # Wait loop with port connectivity check
    for i in {1..30}; do
      if check_port_forwarding && check_processes; then break; fi
      sleep 2
    done
    pytest tests/e2e_ui/ -v --tb=short --browser chromium
```

## Configuration

- **Key settings:** `MAAS_ENDPOINT`, `MAAS_MODEL_ID`, `MAAS_API_KEY` repository secrets for remote model inference; `tests/e2e/values-e2e.yaml` for component toggles
- **Defaults:** Daily cron at 10:00 UTC; 60-minute timeout for LlamaStack integration tests; 10-minute timeout for unit tests; services exposed via NodePort (30080, 30081)
- **Dependencies:** Kind cluster, Helm CLI, Docker Buildx (to build and load images into Kind), Playwright for UI tests, pytest for all test tiers

## Gotchas

- The `--skip-crds` flag is used during `helm install` because the stub CRDs are installed separately -- without this flag, Helm would try to install CRDs from subchart templates which may conflict with the stubs
- The `--set-json llama-stack.initContainers='[]'` override clears init containers that would otherwise wait for local model readiness (since MaaS provides models remotely)
- Port forwarding processes can die during long test runs; the UI E2E job includes a `check_port_forwarding` function that verifies TCP connectivity and a `check_processes` function that confirms PIDs are alive
- Fork PRs cannot access repository secrets (including `MAAS_API_KEY`), so the `llamastack-integration-tests` and `ui-e2e-tests` jobs include an `if` condition that skips them for forks: `github.event.pull_request.head.repo.full_name == github.repository`
- The RAG UI image is built locally and loaded into Kind (`kind load docker-image`) using the version from Chart.yaml as the image tag, matching the `values.yaml` image tag

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- the Helm chart deployed in these tests
- `github-actions-multi-image-release-pipeline.md` -- the separate release/build workflows for the same repo
