---
name: ansible-f5xc-mesh-hugepages-prometheus-hostport
description: Ansible playbook deploying F5 XC Customer Edge mesh with HugePages, preflight checks, and Prometheus hostPort fix
summary: "Automates F5 Distributed Cloud Customer Edge mesh deployment on OpenShift via four Ansible roles (ocp_preflight, hugepages, storage_validation, f5xc_mesh) using kubernetes.core, handling cluster validation, HugePages kernel tuning, storage checks, and mesh lifecycle including Prometheus hostPort conflict resolution. Use when deploying F5 XC CE infrastructure requiring HugePages and automated Prometheus patching on OpenShift; the Makefile wraps ansible-playbook with tagged stages (step1: preflight/hugepages/storage, step2: mesh) and ANSIBLE_TAGS for selective execution, complementing the Helm-based application deployment. Nodes are auto-discovered if ocp_node_name is unset and labeled worker-hp for a Tuned profile MachineConfigPool (1792x2M pages); mesh renders CE manifests via Jinja2 or static YAML (f5xc_manifest_source) in ves-system namespace, waits for PVC binding (120s) and pod readiness (2100s), polls for manual F5 XC Console site approval (600s), then patches Prometheus via oc get | python3 | oc replace to strip hostPort entries when fix_prometheus_hostport is true. Site approval requires manual action in the F5 XC Console and cannot be automated, HugePages requires a node reboot the playbook warns about but does not wait for, the Prometheus fix uses python3 piping rather than strategic merge patch because JSON patches cannot remove individual keys within lists, and cleanup preserves HugePages by default -- pass -e remove_hugepages=true or make f5-clean REMOVE_HUGEPAGES=1 to also remove Tuned/MCP/labels."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [ansible]
  ai_pattern: [guardrails]
  platform: [openshift]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "Four Ansible roles (ocp_preflight, hugepages, storage_validation, f5xc_mesh) deploying F5 XC CE on OpenShift with Prometheus hostPort patching"
    approach: "A"
---

# Ansible F5 XC Customer Edge Mesh with HugePages and Prometheus Fix

## Overview

This pattern uses Ansible playbooks with the `kubernetes.core` collection to deploy F5 Distributed Cloud (XC) Customer Edge (CE) mesh infrastructure on OpenShift. The deployment spans four roles -- cluster preflight validation, HugePages configuration via MachineConfigPool and Tuned profiles, storage class validation, and mesh deployment with an automated Prometheus hostPort fix -- orchestrated by a Makefile that wraps `ansible-playbook`.

## Pattern Description

The Ansible playbook at `deploy/ansible/site.yml` runs against `localhost` (using the local kubeconfig) and auto-discovers cluster nodes if `ocp_node_name` is unset. The four roles execute in tagged stages: preflight and hugepages/storage (step1), then mesh deployment (step2). The mesh role deploys the CE manifest (from Jinja2 template or static file), waits for PVCs to bind and pods to reach Running, polls for manual site approval in the F5 XC Console, and patches the Prometheus deployment to remove hostPort bindings that conflict with OpenShift networking.

## Implementation

### Playbook Entry Point with Auto-Discovery

```yaml
# deploy/ansible/site.yml
- name: F5 XC Customer Edge Deployment on OpenShift
  hosts: localhost
  gather_facts: false
  collections:
    - kubernetes.core

  pre_tasks:
    - name: Discover cluster nodes
      kubernetes.core.k8s_info:
        kind: Node
      register: discovered_nodes
      when: ocp_node_name | default('') == ''

    - name: Auto-set ocp_node_name from first node
      ansible.builtin.set_fact:
        ocp_node_name: "{{ discovered_nodes.resources[0].metadata.name }}"
      when: ocp_node_name | default('') == ''

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

### HugePages via Tuned Profile and MachineConfigPool

The hugepages role labels a node with `worker-hp`, applies a Tuned profile for boot-time HugePages, and creates a MachineConfigPool:

```yaml
# deploy/ansible/roles/hugepages/files/hugepages-tuned-boottime.yaml
apiVersion: tuned.openshift.io/v1
kind: Tuned
metadata:
  name: hugepages
  namespace: openshift-cluster-node-tuning-operator
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

### Prometheus hostPort Fix

After site approval, the mesh role patches the Prometheus deployment to remove hostPort bindings that OpenShift blocks:

```yaml
# deploy/ansible/roles/f5xc_mesh/tasks/main.yml (lines 142-153)
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

### Makefile Integration

```makefile
# deploy/helm/Makefile (f5-deploy target, lines 829-851)
f5-deploy:
	@ansible-galaxy collection install -r "$(ANSIBLE_DIR)/requirements.yml" \
	    --force-with-deps -p "$(ANSIBLE_DIR)/collections"
	@ANSIBLE_STDOUT_CALLBACK=default ANSIBLE_CALLBACK_RESULT_FORMAT=yaml \
	    ansible-playbook "$(ANSIBLE_DIR)/site.yml" \
	    -e "ansible_collections_path=$(ANSIBLE_DIR)/collections" \
	    $(if $(ANSIBLE_TAGS),--tags "$(ANSIBLE_TAGS)",)
```

## Configuration

- **Key settings:** `ocp_node_name` (auto-discovered if empty), `hugepages_role_label` (default `worker-hp`), `f5xc_namespace` (default `ves-system`), `f5xc_cluster_name` and `f5xc_token` (in secrets.yml), `fix_prometheus_hostport` (default true)
- **Defaults:** Pod ready timeout 2100s (35 min), PVC bound timeout 120s, site approval timeout 600s (10 min); HugePages set to 1792x2M pages
- **Dependencies:** Requires `kubernetes.core>=3.0.0` and `ansible.utils>=2.0.0` collections; `oc` CLI must be logged in; secrets.yml must be created from secrets.yml.example

## Gotchas

- The site approval step requires manual action in the F5 XC Console -- the playbook polls with user-visible prompts but cannot automate this step (see `f5xc_mesh/tasks/main.yml` lines 76-89)
- HugePages configuration requires a node reboot to take effect via MachineConfigPool -- the playbook warns but does not wait for the reboot (see `hugepages/tasks/main.yml` lines 52-57)
- The Prometheus hostPort patch uses `oc get | python3 | oc replace` piping rather than a strategic merge patch because the fix needs to remove individual keys within a list, which JSON patches handle poorly
- The cleanup playbook (`deploy/ansible/cleanup.yml`) preserves HugePages config by default; pass `-e remove_hugepages=true` or use `make f5-clean REMOVE_HUGEPAGES=1` to also remove Tuned/MCP/labels (see `f5xc_cleanup/tasks/main.yml` lines 66-111)
- The `f5xc_manifest_source` variable controls whether to render from a Jinja2 template or use a static YAML file (`deploy/ce_ocp_gpu-ai.yml`), defaulting to template mode

## Related Patterns

- `helm-dual-chart-rag-umbrella-vendor-operator.md` -- the Helm-based deployment this Ansible playbook complements for infrastructure setup
- `makefile-validate-infra-kserve-webhook-gpu.md` -- cluster preflight validation in the Makefile (different scope than Ansible preflight)
