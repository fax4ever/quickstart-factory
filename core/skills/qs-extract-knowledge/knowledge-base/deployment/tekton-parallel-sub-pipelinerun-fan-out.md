---
name: tekton-parallel-sub-pipelinerun-fan-out
description: Tekton orchestrator pipeline spawning parallel child PipelineRuns via inline oc create and polling for completion
summary: "Solves parallel fan-out of a shared Tekton `build` pipeline for multiple independent components (correlator, analyzer, ui-console) when Tekton lacks native fan-out, using an orchestrator `build-apps` pipeline where a shared camel-launcher base image build gates three parallel inline taskSpec tasks via `runAfter`. Use when multiple components must run the same pipeline concurrently with per-component parameters (app-name, app-path, GAV) and a shared prerequisite -- each parallel task runs the OpenShift internal CLI image to `oc create -f -` a child PipelineRun with `generateName` and `pipelineRef: name: build`, then polls `status.conditions[0].status` via jsonpath every 10s until True (exit 0) or False (exit 1). Critical config: each child PipelineRun requires its own 1Gi VolumeClaimTemplate workspace (three PVCs plus parent's allocated simultaneously), the referenced `build` pipeline and OpenShift Pipelines operator must be pre-applied, and parent params (repo-url, namespace, camel-launcher-version) are inherited while the CLI step uses `set -euo pipefail`. The polling loop has no built-in timeout (relies on parent PipelineRun or `tkn pipeline start` timeout for stuck children), old PipelineRuns/TaskRuns accumulate unless explicitly cleaned up via `create.sh` post-success, and all three parallel tasks share identical DEPS strings with differentiation only in APP_NAME, GAV, and source path."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [tekton]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "build-apps pipeline with shared camel-launcher build then three parallel inline-taskSpec tasks each spawning a child PipelineRun for correlator/analyzer/ui-console, polling status in a loop"
    approach: "A"
---

# Tekton Parallel Sub-PipelineRun Fan-Out

## Overview

A Tekton pipeline pattern where an orchestrator pipeline fans out multiple application builds by having parallel tasks that each create a child PipelineRun via `oc create`, then poll for completion. This achieves parallel builds of independent components that all share a common prerequisite (a base image build), without Tekton's native fan-out support.

## Pattern Description

The `build-apps` orchestrator pipeline first builds a shared `camel-launcher` base image, then launches three parallel inline tasks. Each task creates a new PipelineRun resource via `oc create -f -` using a heredoc, then enters a polling loop checking the PipelineRun's status condition until it succeeds or fails. The child PipelineRuns reference the `build` pipeline and each gets its own VolumeClaimTemplate workspace. This pattern solves the problem of running multiple instances of the same pipeline with different parameters in parallel while sharing a prerequisite step.

## Implementation

### Orchestrator Pipeline Structure

```
build-camel-launcher -> build-camel-launcher-image
  -> build-correlator  (parallel)
  -> build-analyzer    (parallel)
  -> build-ui-console  (parallel)
```

### Inline TaskSpec Spawning a Child PipelineRun

Each parallel task uses an inline taskSpec that creates a PipelineRun via `oc create`:

```yaml
# deploy/pipeline/build-apps.yaml (correlator task)
- name: build-correlator
  runAfter:
    - build-camel-launcher-image
  taskSpec:
    steps:
      - name: start-and-wait
        image: image-registry.openshift-image-registry.svc:5000/openshift/cli:latest
        script: |
          #!/usr/bin/env bash
          set -euo pipefail
          APP_NAME="correlator"
          GAV="com.example:correlator:1.0.0"
          DEPS="camel-jms,camel-observability-services,..."
          RUN=$(cat <<EOF | oc create -f - -o jsonpath='{.metadata.name}'
          apiVersion: tekton.dev/v1
          kind: PipelineRun
          metadata:
            generateName: build-${APP_NAME}-
          spec:
            pipelineRef:
              name: build
            params:
              - name: app-path
                value: "src/${APP_NAME}"
              - name: app-name
                value: "${APP_NAME}"
              ...
            workspaces:
              - name: shared-workspace
                volumeClaimTemplate:
                  spec:
                    accessModes:
                      - ReadWriteOnce
                    resources:
                      requests:
                        storage: 1Gi
          EOF
          )
```

### Polling Loop for Completion

After creating the child PipelineRun, the task polls its status:

```bash
# deploy/pipeline/build-apps.yaml (polling loop)
echo "Started ${RUN}"
while true; do
  STATUS=$(oc get pipelinerun "${RUN}" -o jsonpath='{.status.conditions[0].status}' 2>/dev/null || echo "Unknown")
  REASON=$(oc get pipelinerun "${RUN}" -o jsonpath='{.status.conditions[0].reason}' 2>/dev/null || echo "")
  if [ "${STATUS}" = "True" ]; then
    echo "${RUN}: Succeeded"
    exit 0
  elif [ "${STATUS}" = "False" ]; then
    echo "${RUN}: Failed (${REASON})"
    exit 1
  fi
  sleep 10
done
```

### Per-Component Parameters

Each parallel task passes component-specific values while sharing common parameters from the orchestrator:

```yaml
# deploy/pipeline/build-apps.yaml (parameters)
params:
  - name: repo-url
    value: $(params.repo-url)
  - name: repo-revision
    value: $(params.repo-revision)
  - name: namespace
    value: $(params.namespace)
  - name: camel-launcher-version
    value: $(params.camel-launcher-version)
  - name: runtime-version
    value: $(params.runtime-version)
```

## Configuration

- **Key settings:** Each child PipelineRun uses `generateName` for unique naming; each gets its own 1Gi VolumeClaimTemplate workspace; the polling interval is 10 seconds
- **Defaults:** `repo-url` defaults to the GitHub repo URL; `repo-revision` defaults to `main`; `namespace` defaults to `slog-analyzer`
- **Dependencies:** The `build` pipeline must be applied first; `oc` CLI must be available in the task step image; OpenShift Pipelines operator must be installed

## Gotchas

- Each child PipelineRun creates its own workspace PVC -- with three parallel builds, this means three 1Gi PVCs are allocated simultaneously plus the parent's workspace PVC
- The `generateName` prefix pattern (`build-correlator-`, `build-analyzer-`, `build-ui-console-`) creates unique PipelineRun names, but old runs accumulate unless cleaned up -- the parent `create.sh` script handles this by deleting all pipelineruns/taskruns after successful completion
- The polling loop has no timeout -- if a child PipelineRun gets stuck in a pending state, the parent task will poll indefinitely; the timeout comes from the parent PipelineRun's overall timeout or the `tkn pipeline start` timeout
- The three parallel tasks (correlator, analyzer, ui-console) all use the same `DEPS` string with identical dependencies -- the differentiation is in `APP_NAME`, `GAV`, and the source path (`src/${APP_NAME}`)

## Related Patterns

- `tekton-camel-export-quarkus-buildah-pipeline.md` -- the child `build` pipeline that each fan-out task references
