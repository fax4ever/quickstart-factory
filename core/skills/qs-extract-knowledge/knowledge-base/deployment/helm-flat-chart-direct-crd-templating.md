---
name: helm-flat-chart-direct-crd-templating
description: Single Helm chart with no dependencies or subcharts, directly templating operator CRDs as raw templates
summary: "Deploys an entire quickstart from a single flat Helm chart with no dependencies block or subchart directories, directly templating operator CRDs (KServe InferenceService, ServingRuntime, TrustyAI GuardrailsOrchestrator, Kubeflow Notebook) as 11 individual template files producing 14 Kubernetes resources for full field-level control. Use over umbrella charts (helm-umbrella-all-remote-ai-arch-deps) or independent subcharts (helm-independent-subcharts-no-umbrella) when full control over every CRD field is needed without shared chart abstraction; installation is a single `helm install` with no `helm dependency update` step, requiring KServe, TrustyAI operator, and Kubeflow Notebook controller pre-installed on the cluster. Configuration uses a flat values.yaml with top-level keys (mainLLM, detectors, orchestrator, workbench, clusterdomainurl) — detectors default to CPU (`useGpu: false`), workbench is enabled by default, and the LLM requires 1 GPU; Chart.yaml contains only name, version, and description with no dependencies block. Without subcharts, common pattern changes (e.g., InferenceService structure) cannot be inherited from a shared chart, all 14 resources upgrade atomically in a single release making partial upgrades impossible, and no Makefile is provided for pre-install validation checks, wait loops, or phased deployment."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [guardrails, model-serving]
  platform: [kserve, vllm, rhoai, openshift]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Flat chart directly templates InferenceService, ServingRuntime, GuardrailsOrchestrator, and Notebook CRDs with no subcharts or remote dependencies"
    approach: "A"
---

# Helm Flat Chart with Direct CRD Templating

## Overview

This pattern deploys an entire quickstart from a single flat Helm chart with no `dependencies:` in `Chart.yaml` and no subchart directories. Every Kubernetes and operator custom resource is defined directly as a template file in `helm/templates/`. This contrasts with the more common umbrella chart patterns that pull reusable subcharts from `ai-architecture-charts` or bundle local subcharts.

## Pattern Description

The chart directory contains only `Chart.yaml`, `values.yaml`, and a `templates/` directory with individual YAML files for each resource. There are no subchart dependencies, no `charts/` directory, and no `helm dependency update` step required. The `Chart.yaml` is minimal -- just name, version, and description. All operator CRDs (KServe InferenceService, ServingRuntime, TrustyAI GuardrailsOrchestrator, Kubeflow Notebook) are templated directly, giving full control over every field without subchart abstraction layers.

## Implementation

### Minimal Chart.yaml

The chart has no dependencies block at all:

```yaml
# helm/Chart.yaml
apiVersion: v2
description: A quickstart for LLM Guardrails with TrustyAI orchestrator
name: guardrailing-llms
version: 1.0.0
```

### Direct Template Files

Each operator CRD gets its own template file rather than being wrapped in a subchart:

```
helm/templates/
  _helpers.tpl                     # Helper functions
  configmaps.yaml                  # 3 ConfigMaps for orchestrator config
  guardrails-orchestrator.yaml     # GuardrailsOrchestrator CRD
  inferenceservice-detectors.yaml  # 3 InferenceService CRDs
  inferenceservice-llm.yaml        # 1 InferenceService CRD
  servingruntime-detectors.yaml    # 3 ServingRuntime CRDs
  servingruntime-llm.yaml          # 1 ServingRuntime CRD
  workbench.yaml                   # Kubeflow Notebook CRD
  workbench-job-clone.yaml         # Job for git clone
  workbench-pvc.yaml               # PVC for workbench
  workbench-role.yaml              # ServiceAccount + RBAC
```

### Install Command

Installation is a single `helm install` with no prior dependency build step:

```bash
# From README.md
PROJECT="guardrails-demo"
oc new-project ${PROJECT}
helm install ${PROJECT} helm/ --namespace ${PROJECT}
```

## Configuration

- **Key settings:** All configuration is in a single flat `values.yaml` with top-level keys (`mainLLM`, `detectors`, `orchestrator`, `workbench`, `clusterdomainurl`) -- no nested subchart keys required
- **Defaults:** Workbench is enabled by default (`workbench.enabled: true`); detectors run on CPU by default (`detectors.useGpu: false`); LLM requires 1 GPU
- **Dependencies:** Requires KServe, TrustyAI operator, and the Kubeflow Notebook controller to be installed on the cluster; no Helm repository add or `helm dependency update` needed

## Gotchas

- Without subcharts, all template files must be maintained individually -- changes to common patterns (e.g., InferenceService resource structure) cannot be inherited from a shared chart (visible across all template files in `helm/templates/`)
- The chart deploys 11 template files producing 14 Kubernetes resources in a single release, making partial upgrades impossible -- every resource is upgraded together (see `helm/templates/` listing)
- No Makefile is provided, so there are no pre-install validation checks, wait loops, or phased deployment -- the user must manually verify pod readiness via `oc get pod` (see README.md install instructions)

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- the opposite approach: all dependencies sourced from remote ai-architecture-charts
- `helm-independent-subcharts-no-umbrella.md` -- separate charts installed independently rather than a single flat chart
