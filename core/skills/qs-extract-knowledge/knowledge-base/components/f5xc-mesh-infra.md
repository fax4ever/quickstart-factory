---
name: f5xc-mesh-infra
description: "Ansible-driven F5 XC Customer Edge deployment on OpenShift with HugePages, storage validation, and Prometheus fix"
summary: "Deploys an F5 XC Customer Edge into `ves-system` on OpenShift via Ansible with four tagged roles (ocp_preflight, hugepages, storage_validation, f5xc_mesh) using `kubernetes.core`, auto-discovering the target node for SNO and reading secrets (`f5xc_token`, `f5xc_cluster_name`) from `group_vars/all/secrets.yml`. Use when provisioning F5 Distributed Cloud mesh on OpenShift needing HugePages (2Mi x 1792 via Tuned operator + `worker-hp` MachineConfigPool) and CE registration with `k8s-minikube-voltmesh` hardware profile; CE manifest supports Jinja2 template or static file via `f5xc_manifest_source`. Critical config: `pod_ready_timeout` defaults to 2100s (~35min) for CE readiness polling, `fix_prometheus_hostport` (default true) patches Prometheus hostPort conflicts after manual site approval (polled up to `site_approval_timeout` 600s), and cleanup deletes cluster-scoped resources (ClusterRoleBindings, ClusterRole) before namespace removal. HugePages require a node reboot to take effect (capacity reads 0 until MCP triggers reboot), CE init DaemonSet needs privileged/hostNetwork/hostPID with host root mount at `/`, vp-manager requires three 1Gi PVCs with a pre-validated default StorageClass, and cleanup preserves HugePages unless `-e remove_hugepages=true` is explicitly passed to avoid accidental reboots."
metadata:
  type: component
tags:
  tech_stack: [ansible, jinja2, python]
  ai_pattern: [guardrails]
  platform: [openshift, kubernetes]
  infra: [f5-distributed-cloud, hugepages, machineconfigpool, tuned-operator]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "Ansible playbook deploying F5 XC Customer Edge mesh on OpenShift with preflight checks, HugePages setup, and Prometheus hostPort workaround"
    approach: "A"
---

# F5 XC Mesh Infrastructure

## Overview

This component deploys an F5 Distributed Cloud (XC) Customer Edge (CE) node onto an OpenShift cluster using Ansible. It provisions the `ves-system` namespace with the Volterra CE stack (vp-manager StatefulSet, DaemonSet init containers, RBAC, ConfigMaps), configures HugePages via the OpenShift Tuned operator and MachineConfigPool, validates cluster storage, and applies a Prometheus hostPort fix required after site approval. The playbook is designed to run from localhost against a connected `oc`/`kubectl` session.

## Tech Stack & Dependencies

- **Runtime:** Ansible (localhost execution, no remote SSH)
- **Collections:** `kubernetes.core` (>=3.0.0), `ansible.utils` (>=2.0.0)
- **Container images:** `gcr.io/volterraio/volterra-ce-init`, `gcr.io/volterraio/vpm`, `gcr.io/volterraio/tinytools`
- **OpenShift APIs:** Tuned (tuned.openshift.io/v1), MachineConfigPool (machineconfiguration.openshift.io/v1)
- **External dependency:** F5 XC Console for site token generation and manual site approval

## Key Patterns

### Multi-Role Playbook with Tagging

The main playbook (`site.yml`) orchestrates four roles in sequence with Ansible tags, enabling selective execution of deployment stages.

```yaml
# deploy/ansible/site.yml
roles:
  - role: ocp_preflight
    tags: [preflight, step1]
  - role: hugepages
    tags: [hugepages, step1]
  - role: storage_validation
    tags: [storage, step1]
  - role: f5xc_mesh
    tags: [mesh, step2]
```

### Auto-Discovery of OCP Node

The playbook auto-discovers the target node name when `ocp_node_name` is left empty, picking the first node from the cluster. This avoids hardcoding node names for single-node or SNO environments.

```yaml
# deploy/ansible/site.yml (pre_tasks)
- name: Discover cluster nodes
  kubernetes.core.k8s_info:
    kind: Node
  register: discovered_nodes
  when: ocp_node_name | default('') == ''

- name: Auto-set ocp_node_name from first node
  ansible.builtin.set_fact:
    ocp_node_name: "{{ discovered_nodes.resources[0].metadata.name }}"
  when: ocp_node_name | default('') == ''
```

### HugePages via Tuned Operator and MachineConfigPool

HugePages (2Mi x 1792) are configured through the OpenShift Tuned operator with a boot-time kernel parameter, targeted at nodes labeled `worker-hp` via a dedicated MachineConfigPool.

```yaml
# deploy/ansible/roles/hugepages/files/hugepages-tuned-boottime.yaml
spec:
  profile:
  - data: |
      [main]
      summary=Boot time configuration for hugepages
      include=openshift-node
      [bootloader]
      cmdline_openshift_node_hugepages=hugepagesz=2M hugepages=1792
    name: openshift-node-hugepages
  recommend:
  - machineConfigLabels:
      machineconfiguration.openshift.io/role: "worker-hp"
    priority: 30
    profile: openshift-node-hugepages
```

### Jinja2-Templated CE Manifest with Dual Source Mode

The CE Kubernetes manifest is rendered from a Jinja2 template by default (`f5xc_manifest_source: "template"`), but the role also supports applying a pre-existing static YAML file (`f5xc_manifest_source: "file"`). The template creates the namespace, RBAC (ServiceAccounts, Roles, ClusterRoles, bindings), a DaemonSet for CE init, and a StatefulSet for vp-manager with three PVCs.

```yaml
# deploy/ansible/roles/f5xc_mesh/tasks/main.yml
- name: Deploy CE manifest from template
  kubernetes.core.k8s:
    state: present
    template: "{{ role_path }}/templates/ce_k8s.yml.j2"
  when: f5xc_manifest_source == "template"

- name: Deploy CE manifest from static file
  kubernetes.core.k8s:
    state: present
    src: "{{ playbook_dir }}/../../ce_ocp_gpu-ai.yml"
  when: f5xc_manifest_source == "file"
```

### Prometheus hostPort Patch

After site approval, the F5 XC control plane deploys a Prometheus instance with `hostPort` bindings that conflict on OpenShift. The playbook polls for the Prometheus deployment, then patches it by piping the deployment JSON through a Python one-liner to strip `hostPort` entries.

```yaml
# deploy/ansible/roles/f5xc_mesh/tasks/main.yml
- name: Patch Prometheus to remove hostPort bindings
  ansible.builtin.shell: |
    oc -n {{ f5xc_namespace }} get deployment prometheus -o json | \
    python3 -c "
    import json, sys
    dep = json.load(sys.stdin)
    for c in dep['spec']['template']['spec']['containers']:
        if 'ports' in c:
            for p in c['ports']:
                p.pop('hostPort', None)
    json.dump(dep, sys.stdout)
    " | oc -n {{ f5xc_namespace }} replace -f -
  when: prom_has_hostport | default(false)
```

### Cleanup with Ordered Resource Deletion

The cleanup playbook (`cleanup.yml`) removes cluster-scoped resources (ClusterRoleBindings, ClusterRole) before deleting the namespace. HugePages cleanup is opt-in via `-e remove_hugepages=true` to avoid unexpected node reboots.

```yaml
# deploy/ansible/roles/f5xc_cleanup/tasks/main.yml
- name: HugePages resources kept
  ansible.builtin.debug:
    msg: "HugePages config (Tuned, MCP, node label) preserved. Pass -e remove_hugepages=true to also remove these."
  when: not (remove_hugepages | default(false) | bool)
```

## Configuration

- **Environment variables:** None (all configuration is via Ansible vars)
- **Config files:**
  - `group_vars/all/vars.yml` -- main configuration (namespace, coordinates, timeouts, hardware profile, manifest source)
  - `group_vars/all/secrets.yml` -- sensitive values (`f5xc_token`, `f5xc_cluster_name`), created from `secrets.yml.example`
  - `ansible.cfg` -- output formatting (YAML callback, skip display of skipped hosts)
- **Key variables:**
  - `f5xc_namespace` (default: `ves-system`) -- namespace for all CE resources
  - `f5xc_certified_hardware` (default: `k8s-minikube-voltmesh`) -- hardware profile for CE registration
  - `f5xc_manifest_source` (default: `template`) -- `template` for Jinja2 rendering, `file` for static manifest
  - `pod_ready_timeout` (default: `2100`, ~35 min) -- timeout for pod readiness polling
  - `fix_prometheus_hostport` (default: `true`) -- enables the Prometheus hostPort patch
  - `hugepages_role_label` (default: `worker-hp`) -- node role label for HugePages targeting

## Known Gotchas

- **HugePages require node reboot:** The Tuned profile sets boot-time kernel parameters. After initial application, HugePages capacity reads as `0` until the MachineConfigPool triggers a node reboot. The role warns about this explicitly: "HugePages may require a node reboot to take effect" (from `roles/hugepages/tasks/main.yml`).
- **Manual site approval required mid-playbook:** After vp-manager reaches Running state, a human must approve the site in the F5 XC Console. The playbook polls for a Prometheus deployment as a signal that approval happened, with a configurable timeout (`site_approval_timeout`, default 600s / 10 min).
- **Prometheus hostPort conflict on OpenShift:** The F5 XC-managed Prometheus deployment uses `hostPort` bindings that fail on OpenShift due to port conflicts. The `fix_prometheus_hostport` variable (default: `true`) enables automatic patching via `oc` + Python JSON manipulation.
- **Cleanup preserves HugePages by default:** Running `cleanup.yml` does not remove the Tuned profile, MachineConfigPool, or node label unless `-e remove_hugepages=true` is explicitly passed. This prevents accidental node reboots triggered by MachineConfigPool removal.
- **Three PVCs required:** The vp-manager StatefulSet creates three 1Gi PVCs (`etcvpm`, `varvpm`, `data`). The `storage_validation` role pre-checks that a default StorageClass with dynamic provisioning exists, failing early if not.
- **CE init DaemonSet requires privileged access:** The `volterra-ce-init` DaemonSet runs with `hostNetwork: true`, `hostPID: true`, and `privileged: true` security context, mounting the host root filesystem at `/`.

## Testing Notes

- Run preflight checks only: `ansible-playbook site.yml --tags preflight`
- Verify HugePages allocation after reboot: `oc get nodes <node> -o jsonpath='{.status.capacity.hugepages-2Mi}'`
- The playbook validates all pods in `ves-system` are Running with all containers ready as a final assertion
- Cleanup can be verified with: `ansible-playbook cleanup.yml` followed by checking that `ves-system` namespace no longer exists

## Related Patterns

- GPU operator or node feature discovery components that also use MachineConfigPool and Tuned profiles
- Ansible-based OpenShift infrastructure provisioning patterns
