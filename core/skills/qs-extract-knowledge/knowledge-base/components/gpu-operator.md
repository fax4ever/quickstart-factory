---
name: gpu-operator
description: "NVIDIA GPU Operator ClusterPolicy management via Helm with MIG support for OpenShift"
summary: "Manages NVIDIA GPU Operator's ClusterPolicy CR on OpenShift via a standalone Helm chart (charts/gpu-operator/, appVersion 25.10.1), configuring driver settings, MIG partitioning, device plugin, DCGM exporter (Prometheus serviceMonitor), and CDI — the operator must be pre-installed via OLM (gpu-operator-certified.v25.10.1+). Use when GPU workloads need right-sized MIG allocations with strategy: mixed for per-node configs via nvidia.com/mig.config labels (all-disabled default) rather than dedicating full GPUs — the custom-aml-workload profile partitions 8x H100 NVL GPUs into 3g.47gb (LLM tensor-parallel), 1g.24gb (VLM), and 1g.12gb (embedding/reranking) slices, freeing 5 full GPUs for FP8-quantized models. Critical config: model deployments must switch resource requests from nvidia.com/gpu to MIG-specific names (nvidia.com/mig-3g.47gb: \"2\"), chart requires operator.useOcpDriverToolkit: true and operator.defaultRuntime: crio, with MIG profiles stored in ConfigMap default-mig-parted-config. MIG reconfiguration takes 3-5 minutes disrupting existing GPU pods, unlabeled nodes default to all-disabled under mixed strategy, the chart does not install the GPU Operator (only manages ClusterPolicy CR), and the old nvidia.com/gpu resource name will not schedule on MIG-partitioned GPUs."
metadata:
  type: component
tags:
  tech_stack: [helm, openshift]
  ai_pattern: [model-serving]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Standalone Helm chart managing ClusterPolicy with mixed MIG strategy and custom FP8-optimized MIG profiles on H100 GPUs"
    approach: "A"
---

# GPU Operator

## Overview

This component is a standalone Helm chart that manages the NVIDIA GPU Operator's `ClusterPolicy` custom resource on OpenShift. The GPU Operator itself is installed separately via OLM (Operator Lifecycle Manager); this chart only configures its behavior, including driver settings, MIG (Multi-Instance GPU) partitioning, monitoring, and device plugin options. It enables right-sizing GPU allocations for FP8-quantized AI models on RHOAI clusters.

## Tech Stack & Dependencies
- **Runtime:** NVIDIA GPU Operator v25.10+ (installed via OLM, not by this chart)
- **Container image:** N/A (operator images managed by OLM subscription)
- **Key dependencies:** OpenShift 4.12+, GPU-enabled worker nodes, OLM
- **Helm subchart:** Standalone chart (`charts/gpu-operator/`, apiVersion v2, appVersion 25.10.1)

## Key Patterns

### OLM-Installed Operator with Helm-Managed Configuration

The GPU Operator is installed via OLM subscription. This chart only creates the `ClusterPolicy` CR that configures the operator's behavior. This separation means the chart can be deployed independently of the operator lifecycle.

From `charts/gpu-operator/values.yaml`:

```yaml
operator:
  # The GPU operator is installed via OLM subscription
  # This chart only manages the ClusterPolicy
  namespace: nvidia-gpu-operator
  defaultRuntime: crio
  useOcpDriverToolkit: true
```

The chart produces a single resource -- a `ClusterPolicy` CR at `templates/clusterpolicy.yaml`:

```yaml
apiVersion: nvidia.com/v1
kind: ClusterPolicy
metadata:
  name: gpu-cluster-policy
spec:
  operator:
    defaultRuntime: {{ .Values.operator.defaultRuntime }}
    use_ocp_driver_toolkit: {{ .Values.operator.useOcpDriverToolkit }}
```

### Mixed MIG Strategy with Per-Node Configuration

The chart uses `strategy: mixed` to enable per-node MIG configurations via node labels rather than applying a single MIG config cluster-wide. Nodes without a `nvidia.com/mig.config` label fall back to the default (`all-disabled`).

From `charts/gpu-operator/values.yaml`:

```yaml
mig:
  # single = all GPUs use same MIG config
  # mixed = per-node MIG configs (use node labels to select config)
  strategy: mixed

migManager:
  enabled: true
  config:
    name: default-mig-parted-config
    # With strategy: mixed, label nodes with nvidia.com/mig.config=<config-name>
    default: all-disabled
```

Nodes are labeled to activate specific MIG profiles:

```bash
# Label GPU node to use custom-aml-workload MIG config
oc label node <gpu-node-name> nvidia.com/mig.config=custom-aml-workload --overwrite
```

### Custom MIG Profile for FP8-Optimized Workloads

The repo defines a `custom-aml-workload` MIG profile that partitions 8x H100 NVL GPUs to right-size allocations for FP8-quantized models, freeing 5 full GPUs.

From `docs/advanced-docs/gpu-mig-migration-fp8.md`:

```yaml
custom-aml-workload:
  # GPU 0: LLM FP8 (tensor parallel across 2 MIG slices)
  - devices: [0]
    mig-enabled: true
    mig-devices:
      "3g.47gb": 2     # 2x 46.38GB = 92.76GB for LLM

  # GPU 1: VLM FP8 + 3 spare slices
  - devices: [1]
    mig-enabled: true
    mig-devices:
      "1g.24gb": 4     # 1 for VLM (21.62GB), 3 available

  # GPU 2: Embedding + Reranking + 5 spare slices
  - devices: [2]
    mig-enabled: true
    mig-devices:
      "1g.12gb": 7     # 2 for models, 5 available

  # GPU 3-7: Full GPUs available
  - devices: [3,4,5,6,7]
    mig-enabled: false
```

### MIG Resource Names in Model Deployments

When MIG is enabled, model-serving workloads switch from `nvidia.com/gpu` to MIG-specific resource names. This is configured in the model-serving chart's `values.yaml`.

From `charts/model-serving/values.yaml`:

```yaml
# FP8 model fits on 2x 3g.47gb MIG slices (2x 46GB = 92GB)
nvidia.com/mig-3g.47gb: "2"

# Embedding model fits on 1x 1g.12gb MIG slice (10.75GB)
nvidia.com/mig-1g.12gb: "1"

# FP8 VLM needs 1x 3g.47gb MIG slice (46.38GB) for encoder cache
nvidia.com/mig-3g.47gb: "1"
```

## Configuration
- **Environment variables:** None directly (operator manages its own pods)
- **Config files:** `values.yaml` covers driver, MIG manager, device plugin, toolkit, DCGM, GFD, CDI, vGPU, sandbox, and daemonset settings
- **Helm values:**
  - `operator.useOcpDriverToolkit: true` -- required for OpenShift
  - `mig.strategy` -- `single` (uniform) or `mixed` (per-node labels)
  - `migManager.config.name` -- ConfigMap name for MIG profiles
  - `migManager.config.default` -- fallback MIG profile for unlabeled nodes
  - `driver.licensingConfig.nlsEnabled` -- NLS licensing toggle
  - `driver.kernelModuleType` -- `auto`, `nv-open`, or `nvidia`
  - `dcgmExporter.serviceMonitor.enabled` -- Prometheus metrics collection
  - `cdi.enabled` -- Container Device Interface support

## Known Gotchas
- **Chart does not install the operator.** The GPU Operator must be installed via OLM first (`gpu-operator-certified.v25.10.1` or later). The chart only manages the `ClusterPolicy` CR. (Source: `charts/gpu-operator/README.md` and `values.yaml` comment)
- **MIG changes take 3-5 minutes.** After labeling a node, the MIG manager pod reconfigures GPUs -- existing GPU pods are disrupted during this window. (Source: `charts/gpu-operator/README.md`, step 3)
- **Model deployments must update resource names.** Switching from full GPUs to MIG requires changing resource requests from `nvidia.com/gpu` to `nvidia.com/mig-<profile>` in every workload manifest. The old resource name will not schedule on MIG-partitioned GPUs. (Source: `charts/gpu-operator/README.md`, "Updating Model Deployments for MIG" section; `charts/model-serving/values.yaml` comments)
- **`useOcpDriverToolkit` must be `true` on OpenShift.** This enables the OpenShift Driver Toolkit integration for building driver modules. (Source: `charts/gpu-operator/values.yaml` line 9)
- **Mixed strategy requires explicit node labels.** With `strategy: mixed`, MIG is only enabled on nodes with the `nvidia.com/mig.config=<config-name>` label. Unlabeled nodes use the `default` config (typically `all-disabled`). (Source: `values.yaml` comments on mig.strategy and migManager.config)

## Testing Notes
- Verify the GPU Operator is running before deploying this chart: `oc get csv -n nvidia-gpu-operator | grep gpu-operator`
- After applying MIG config, verify slices with: `oc exec -n nvidia-gpu-operator $DRIVER_POD -- nvidia-smi -L`
- Check available MIG resources on nodes: `oc describe node <gpu-node> | grep nvidia.com/mig`
- Monitor MIG manager logs: `oc logs -n nvidia-gpu-operator -l app=nvidia-mig-manager --tail=100`
- Verify ConfigMap loaded: `oc get configmap default-mig-parted-config -n nvidia-gpu-operator -o yaml`

## Related Patterns
- Model serving components that consume MIG resources (nvidia.com/mig-* resource requests)
- DCGM exporter for GPU monitoring and Prometheus metrics
- FP8 quantization strategy for reducing GPU memory footprint
