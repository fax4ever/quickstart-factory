---
name: helm-flat-chart-direct-crd-templating
description: Single Helm chart with no dependencies or subcharts, directly templating operator CRDs as raw templates
summary: "Deploys quickstarts from a single flat Helm chart with no dependencies or subchart directories, directly templating operator CRDs (KServe InferenceService/ServingRuntime, TrustyAI GuardrailsOrchestrator/NemoGuardrails, Kubeflow Notebook, LlamaStackDistribution) as raw template files for full field-level control without subchart abstraction. Use over umbrella charts (helm-umbrella-all-remote-ai-arch-deps) or independent subcharts (helm-independent-subcharts-no-umbrella) when full CRD field control is needed; Approach A (guardrailing-llms, llm-cpu-serving, multi-agent-loan-origination) uses one CRD per file with `_helpers.tpl` per-component label/selector helpers, scaling from 11 files/14 resources to 27 files with 10+ `.enabled`-toggled conditional components (keycloak, llamastack, nemo-guardrails, kagenti, mcp servers, mlflow, minio, seed) and supporting SQLite sidecars and dual seed Jobs, while Approach B (lemonade-stand-assistant) adds `helm.sh/weight` ordering (MinIO at -5/-4, runtimes at 0, InferenceServices at 1), bundles multiple resources per file, and conditionally skips the entire LLM stack via `{{ if not .Values.model }}` -- choose A for simpler organization or complex multi-component toggles, B when resource ordering or conditional deployment is needed. Configuration uses flat values.yaml with top-level keys (mainLLM, detectors, orchestrator, workbench, clusterdomainurl); Chart.yaml has only name/version/description with no dependencies block; single `helm install` with no `helm dependency update`, requiring KServe, TrustyAI operator, and Kubeflow Notebook controller pre-installed; detectors default to CPU (`useGpu: false`), LLM requires 1 GPU. Without subcharts, common CRD pattern changes (e.g., InferenceService structure) cannot be inherited from a shared chart, all resources upgrade atomically in a single release making partial upgrades impossible, and neither approach provides a Makefile for pre-install validation checks, wait loops, or phased deployment."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [guardrails, model-serving, agents]
  platform: [kserve, vllm, rhoai, openshift]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Flat chart directly templates InferenceService, ServingRuntime, GuardrailsOrchestrator, and Notebook CRDs with no subcharts or remote dependencies"
    approach: "A"
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "Flat chart with helm.sh/weight ordering, conditional LLM bypass, MinIO init container, and multi-resource template files"
    approach: "B"
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "Flat chart directly templates KServe ServingRuntime/InferenceService, LlamaStackDistribution CR, Kubeflow Notebook with SQLite sidecar, and dual seed Jobs"
    approach: "A"
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Flat chart with 27 template files, 10+ conditional components (keycloak, llamastack, nemo-guardrails, kagenti, mcp servers, mlflow, minio, seed) toggled via .enabled flags, extensive _helpers.tpl with per-component label/selector helpers, and TrustyAI NemoGuardrails + KServe InferenceService CRDs"
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

---

## Approach B: Flat Chart with Helm Weight Ordering and Conditional Resources (from lemonade-stand-assistant)

### When to Use

When a flat chart needs ordered resource creation (storage before model servers) and conditional resource inclusion (skip GPU-bound LLM when external model endpoint is available).

### Differences from Approach A

- Uses `helm.sh/weight` annotations to enforce resource creation order (MinIO at `-5`/`-4`, ServingRuntimes at `0`, InferenceServices at `1`) whereas Approach A has no weight annotations
- Template files contain multiple resources per file (e.g., `minio-storage-models.yaml` has Service + PVC + Deployment + Secret) whereas Approach A uses one CRD per file
- Conditionally deploys the local LLM via `{{ if not .Values.model }}` -- entire ServingRuntime + InferenceService gated on a single values key
- Each detector InferenceService is in its own template file (one per detector) rather than combined into a single template
- No Makefile, no workbench, no `_helpers.tpl` -- even simpler than Approach A

### Implementation

```
chart/templates/
  chunker.yaml                    # Deployment + Service
  configmap_auxiliary_images.yaml  # ConfigMap (regex/gateway images)
  dashboard-configmap.yaml         # Conditional OpenShift Console dashboard
  fms-orchestr8-config-nlp.yaml   # Orchestrator NLP config
  guardrails-orchestrator.yaml    # GuardrailsOrchestrator CRD
  ibm-hap-detector.yaml           # ServingRuntime + InferenceService
  lemonade-stand-app.yaml         # ConfigMap + Deployment + Service + Route + Secret + ServiceMonitor
  lingua.yaml                     # Deployment + Service
  llm-llama32.yaml                # Conditional ServingRuntime + InferenceService
  minio-storage-models.yaml       # Service + PVC + Deployment + Secret (weighted)
  prompt-injection-detector.yaml  # ServingRuntime + InferenceService
  shiny-dashboard.yaml            # Deployment + Service + Route
```

### Helm Weight Ordering

```yaml
# chart/templates/minio-storage-models.yaml (weight -5 for service/PVC/secret, -4 for deployment)
annotations:
  helm.sh/weight: "-5"
---
# chart/templates/ibm-hap-detector.yaml (weight 0 for runtime, 1 for inference service)
annotations:
  helm.sh/weight: "0"   # ServingRuntime
  helm.sh/weight: "1"   # InferenceService
```

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Resource ordering | No ordering mechanism | `helm.sh/weight` annotations for phased deployment |
| Resources per file | One CRD per template file | Multiple related resources per file |
| Conditional resources | `workbench.enabled` toggle | `{{ if not .Values.model }}` for entire LLM stack |
| Helper templates | `_helpers.tpl` present | No helper templates |
| Total template files | 11 files producing 14 resources | 12 files producing 20+ resources |
| Makefile | Not provided | Not provided |

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- the opposite approach: all dependencies sourced from remote ai-architecture-charts
- `helm-independent-subcharts-no-umbrella.md` -- separate charts installed independently rather than a single flat chart
- `helm-minio-initcontainer-hf-model-download.md` -- the MinIO init container pattern used in Approach B
- `helm-conditional-llm-bypass-external-model.md` -- the conditional LLM bypass pattern used in Approach B
