---
name: f5xc-mesh-infra
description: "Ansible-driven F5 XC Customer Edge deployment on OpenShift with HugePages, storage validation, and Prometheus fix"
summary: "Deploys an F5 XC Customer Edge into `ves-system` on OpenShift via Ansible with four tagged roles (ocp_preflight, hugepages, storage_validation, f5xc_mesh) using `kubernetes.core`, auto-discovering the target node for SNO and reading secrets (`f5xc_token`, `f5xc_cluster_name`) from `group_vars/all/secrets.yml`. Use when provisioning F5 Distributed Cloud mesh on OpenShift needing HugePages (2Mi x 1792 via Tuned operator + `worker-hp` MachineConfigPool) and CE registration with `k8s-minikube-voltmesh` hardware profile; CE manifest supports Jinja2 template or static file via `f5xc_manifest_source`; when `f5xc_auto_approve` is true, automated site approval calls the F5 XC registration API with multi-strategy tenant discovery (explicit var, env var, redirect probing, JWT payload decoding) and polls PENDING/NEW registration lists every `f5xc_registration_poll_interval` (30s) matching by `cluster_name` since registration names are generated UUIDs. Critical config: `pod_ready_timeout` defaults to 2100s (~35min) for CE readiness polling, `fix_prometheus_hostport` (default true) patches Prometheus hostPort conflicts after site approval (polled up to `site_approval_timeout` 600s), and cleanup deletes cluster-scoped resources (ClusterRoleBindings, ClusterRole) before namespace removal. HugePages require a node reboot to take effect (capacity reads 0 until MCP triggers reboot), CE init DaemonSet needs privileged/hostNetwork/hostPID with host root mount at `/`, vp-manager requires three 1Gi PVCs with a pre-validated default StorageClass, cleanup preserves HugePages unless `-e remove_hugepages=true` is explicitly passed to avoid accidental reboots, and tenant subdomain must use the console login hostname not the internal apigw-tenant suffix shown in vp-manager logs."
metadata:
  type: component
tags:
  tech_stack: [ansible, jinja2, python]
  ai_pattern: [guardrails, api-security]
  platform: [openshift, kubernetes]
  infra: [f5-distributed-cloud, hugepages, machineconfigpool, tuned-operator]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "Ansible playbook deploying F5 XC Customer Edge mesh on OpenShift with preflight checks, HugePages setup, and Prometheus hostPort workaround"
    approach: "A"
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/f5-api-security"
    notes: "Same Ansible CE deployment with automated site registration approval via F5 XC API and multi-strategy tenant discovery"
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

### Automated Site Registration Approval via F5 XC API (from f5-api-security)

When `f5xc_auto_approve: true` (the default in `f5-api-security`), the role bypasses manual console approval by calling the F5 XC registration API directly. It looks up the registration by site name, polls for NEW/PENDING state, then POSTs an approval with cluster passport details.

```yaml
# deploy/ansible/roles/f5xc_mesh/tasks/approve_registration.yml
- name: Approve site registration via F5 XC API
  ansible.builtin.uri:
    url: "{{ f5xc_console_base }}/api/register/namespaces/system/registration/{{ f5xc_reg_name }}/approve"
    method: POST
    headers: "{{ f5xc_api_headers }}"
    body_format: json
    body:
      name: "{{ f5xc_reg_name }}"
      state: APPROVED
      passport:
        cluster_name: "{{ f5xc_cluster_name }}"
        cluster_size: "{{ f5xc_cluster_size | int }}"
        cluster_type: "{{ f5xc_cluster_type }}"
        latitude: "{{ f5xc_latitude | float }}"
        longitude: "{{ f5xc_longitude | float }}"
      tunnel_type: "{{ f5xc_tunnel_type }}"
    status_code: 200
  when: f5xc_reg_current_state | default('') in ['NEW', 'PENDING']
```

### Multi-Strategy Tenant Discovery (from f5-api-security)

The `discover_tenant.yml` task resolves the F5 XC console subdomain through a priority chain: (1) explicit `f5xc_tenant` variable, (2) `F5XC_TENANT` environment variable, (3) probing the global F5 XC console endpoint to extract the tenant from the redirect hostname, (4) decoding the JWT payload of the API token to extract `cname`/`tenant`/`org` fields and probing each candidate subdomain. This avoids hardcoding tenant names.

```yaml
# deploy/ansible/roles/f5xc_mesh/tasks/discover_tenant.yml
- name: Decode JWT payload from API token
  ansible.builtin.command:
    argv:
      - python3
      - -c
      - |
        import base64, json, sys
        parts = sys.argv[1].split(".")
        if len(parts) != 3:
          sys.exit(0)
        pad = "=" * (-len(parts[1]) % 4)
        payload = base64.urlsafe_b64decode(parts[1] + pad)
        sys.stdout.write(payload.decode("utf-8", errors="replace"))
      - "{{ f5xc_api_token }}"
  register: f5xc_jwt_decode
  when:
    - f5xc_tenant_effective is not defined
    - (f5xc_api_token.split('.')) | length == 3
```

### Registration Polling with State-Based Lookup (from f5-api-security)

When no registration is immediately found by site name, the role polls both PENDING and NEW registration lists via the F5 XC API, matching by `cluster_name` in the passport spec. This handles the delay between CE manifest deployment and registration appearing in the console.

```yaml
# deploy/ansible/roles/f5xc_mesh/tasks/poll_new_registration.yml
- name: Resolve registration name from NEW list
  ansible.builtin.set_fact:
    f5xc_reg_name: "{{ item.name }}"
  vars:
    _registration_cluster_name: >-
      {{ item.object.spec.gc_spec.passport.cluster_name | default(
        (((item.get_spec | default({})).gc_spec | default({})).passport | default({})).cluster_name | default('')
      ) }}
  loop: "{{ f5xc_new_regs.json['items'] | default([]) }}"
  when:
    - f5xc_reg_name | default('') | length == 0
    - _registration_cluster_name == f5xc_cluster_name
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
  - `f5xc_auto_approve` (default: `true` in f5-api-security) -- enables automated site registration approval via F5 XC API; requires `f5xc_api_token` in `secrets.yml`
  - `f5xc_registration_poll_interval` (default: `30`) -- seconds between registration polling attempts during auto-approval
  - `f5xc_cluster_size` (default: `1`) -- cluster size passed to the approval passport
  - `f5xc_tunnel_type` (default: `SITE_TO_SITE_TUNNEL_IPSEC_OR_SSL`) -- tunnel type for the approved site

## Known Gotchas

- **HugePages require node reboot:** The Tuned profile sets boot-time kernel parameters. After initial application, HugePages capacity reads as `0` until the MachineConfigPool triggers a node reboot. The role warns about this explicitly: "HugePages may require a node reboot to take effect" (from `roles/hugepages/tasks/main.yml`).
- **Manual site approval required mid-playbook (unless auto-approve is enabled):** After vp-manager reaches Running state, a human must approve the site in the F5 XC Console unless `f5xc_auto_approve: true` is set with a valid `f5xc_api_token`. The playbook polls for a Prometheus deployment as a signal that approval happened, with a configurable timeout (`site_approval_timeout`, default 600s / 10 min).
- **Prometheus hostPort conflict on OpenShift:** The F5 XC-managed Prometheus deployment uses `hostPort` bindings that fail on OpenShift due to port conflicts. The `fix_prometheus_hostport` variable (default: `true`) enables automatic patching via `oc` + Python JSON manipulation.
- **Cleanup preserves HugePages by default:** Running `cleanup.yml` does not remove the Tuned profile, MachineConfigPool, or node label unless `-e remove_hugepages=true` is explicitly passed. This prevents accidental node reboots triggered by MachineConfigPool removal.
- **Three PVCs required:** The vp-manager StatefulSet creates three 1Gi PVCs (`etcvpm`, `varvpm`, `data`). The `storage_validation` role pre-checks that a default StorageClass with dynamic provisioning exists, failing early if not.
- **CE init DaemonSet requires privileged access:** The `volterra-ce-init` DaemonSet runs with `hostNetwork: true`, `hostPID: true`, and `privileged: true` security context, mounting the host root filesystem at `/`.
- **Tenant subdomain differs from API gateway suffix:** The `secrets.yml.example` in `f5-api-security` warns: "Use the host you log in with, e.g. https://nfrredhat.console.ves.volterra.io -- NOT the internal apigw-tenant suffix shown in vp-manager logs (e.g. nfrredhat-ymwyotjx)." The tenant discovery fallback decodes the JWT token and filters out `ves-io` and `ves-` prefixed values to avoid false matches.
- **Registration lookup requires two-level fallback:** The `poll_new_registration.yml` task first tries `registrations_by_site/{site_name}`, then falls back to listing PENDING registrations, then NEW registrations, matching by `cluster_name` in the passport spec at `item.object.spec.gc_spec.passport.cluster_name`. This is needed because registration names are generated UUIDs that do not match the site name.

## Testing Notes

- Run preflight checks only: `ansible-playbook site.yml --tags preflight`
- Verify HugePages allocation after reboot: `oc get nodes <node> -o jsonpath='{.status.capacity.hugepages-2Mi}'`
- The playbook validates all pods in `ves-system` are Running with all containers ready as a final assertion
- Cleanup can be verified with: `ansible-playbook cleanup.yml` followed by checking that `ves-system` namespace no longer exists

## Related Patterns

- GPU operator or node feature discovery components that also use MachineConfigPool and Tuned profiles
- Ansible-based OpenShift infrastructure provisioning patterns
