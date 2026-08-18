---
name: gpu-operator-clusterpolicy-mig-mixed
description: NVIDIA GPU Operator ClusterPolicy with mixed MIG strategy for per-node GPU partitioning
summary: "Manages the NVIDIA GPU Operator ClusterPolicy via Helm on OpenShift to configure Multi-Instance GPU (MIG) partitioning in mixed mode, allowing each node to run a different MIG profile selected by nvidia.com/mig.config labels for heterogeneous GPU workloads (A100/H100) on a single cluster. Use mixed MIG strategy when different nodes need different GPU partitions for varied workloads such as model serving with kserve-multi-model-mig-gpu-slicing; use single strategy when all nodes should share the same MIG configuration. Key settings are mig.strategy: mixed, migManager.config.name: default-mig-parted-config with default all-disabled (no MIG until node is labeled), operator.useOcpDriverToolkit: true, driver NLS licensing with auto-upgrade (maxParallelUpgrades: 1, maxUnavailable: \"25%\"), and DCGM exporter ServiceMonitor, GFD, and CDI enabled. The default-mig-parted-config ConfigMap is created by the GPU Operator itself not this chart; unlabeled nodes get all-disabled (no MIG); sandboxDevicePlugin.enabled: true coexists with sandboxWorkloads.enabled: false; vgpuManager and GDS are disabled since this pattern targets physical MIG not virtual GPUs."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [model-serving]
  platform: [openshift]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "ClusterPolicy with mixed MIG strategy, MIG Manager enabled, OCP driver toolkit, and CDI support"
    approach: "A"
---

# GPU Operator ClusterPolicy with Mixed MIG Strategy

## Overview

This pattern manages the NVIDIA GPU Operator's ClusterPolicy via a dedicated Helm chart, configuring Multi-Instance GPU (MIG) partitioning in `mixed` mode. Mixed MIG allows different nodes to use different MIG configurations based on node labels, enabling heterogeneous GPU workloads on the same cluster.

## Pattern Description

The GPU Operator is installed via OLM (Operator Lifecycle Manager), but its ClusterPolicy custom resource is managed by this Helm chart. The chart configures MIG strategy as `mixed` (rather than `single`), meaning nodes are labeled with `nvidia.com/mig.config=<config-name>` to select their MIG partitioning. The MIG Manager watches these labels and reconfigures GPUs accordingly. The chart also enables related subsystems: DCGM exporter for monitoring, GFD for node feature discovery, CDI for container device interface, and the OCP driver toolkit integration.

## Implementation

### ClusterPolicy with MIG Configuration

```yaml
# charts/gpu-operator/templates/clusterpolicy.yaml (excerpt)
apiVersion: nvidia.com/v1
kind: ClusterPolicy
metadata:
  name: gpu-cluster-policy
spec:
  operator:
    defaultRuntime: {{ .Values.operator.defaultRuntime }}
    use_ocp_driver_toolkit: {{ .Values.operator.useOcpDriverToolkit }}

  mig:
    strategy: {{ .Values.mig.strategy }}

  migManager:
    enabled: {{ .Values.migManager.enabled }}
    config:
      name: {{ .Values.migManager.config.name }}
      default: {{ .Values.migManager.config.default }}
```

### MIG Manager Defaults

```yaml
# charts/gpu-operator/values.yaml (excerpt)
mig:
  # mixed = per-node MIG configs (use node labels to select config)
  strategy: mixed

migManager:
  enabled: true
  config:
    name: default-mig-parted-config
    default: all-disabled
```

### Driver with NLS Licensing and Auto-Upgrade

```yaml
# charts/gpu-operator/values.yaml (excerpt)
driver:
  enabled: true
  useNvidiaDriverCRD: false
  kernelModuleType: auto
  upgradePolicy:
    autoUpgrade: true
    maxParallelUpgrades: 1
    maxUnavailable: "25%"
  licensingConfig:
    nlsEnabled: true
```

### Monitoring and Device Management

```yaml
# charts/gpu-operator/values.yaml (excerpt)
dcgm:
  enabled: true
dcgmExporter:
  enabled: true
  serviceMonitor:
    enabled: true
gfd:
  enabled: true
cdi:
  enabled: true
  default: false
```

## Configuration

- **Key settings:** `mig.strategy: mixed` enables per-node MIG configuration via labels; `migManager.config.default: all-disabled` means GPUs start without MIG until a node is labeled; `operator.useOcpDriverToolkit: true` uses OpenShift's driver toolkit for driver compilation
- **Defaults:** MIG defaults to `all-disabled`; auto-upgrade enabled with 1 parallel upgrade; DCGM exporter ServiceMonitor enabled for Prometheus scraping
- **Dependencies:** NVIDIA GPU Operator installed via OLM subscription; nodes with MIG-capable GPUs (A100, H100, etc.); nodes must be labeled with `nvidia.com/mig.config=<config-name>` for MIG partitioning to activate

## Gotchas

- The `migManager.config.name: default-mig-parted-config` references a ConfigMap that defines available MIG profiles; this ConfigMap is created by the GPU Operator itself, not by this chart
- With `strategy: mixed`, unlabeled nodes get `all-disabled` (no MIG partitioning); to enable MIG on a node, label it with `nvidia.com/mig.config=custom-aml-workload` (or whatever config name matches a profile in the MIG parted config)
- The chart sets `vgpuManager.enabled: false` and `gds.enabled: false` since this workload does not use virtual GPUs or GPUDirect Storage
- `sandboxWorkloads.enabled: false` and `sandboxDevicePlugin.enabled: true` coexist -- the device plugin is enabled even when sandbox workloads are disabled

## Related Patterns

- `kserve-multi-model-mig-gpu-slicing.md` -- the InferenceServices that consume MIG slices provisioned by this ClusterPolicy
