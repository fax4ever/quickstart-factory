---
name: devworkspace
description: "Helm-managed DevWorkspace resources for provisioning per-user OpenShift DevSpaces IDE workspaces on RHOAI"
summary: "Provisions per-user containerized IDE workspaces on RHOAI via workspace.devfile.io/v1alpha2 and OpenShift DevSpaces, using Helm range loops to create namespaces (prefixed wksp-<user> with che.eclipse.org/username annotation and app.kubernetes.io/part-of: che.eclipse.org label), DevWorkspace CRs with routingClass: che, and edit ClusterRole RoleBindings -- single approach (A, maas-code-assistant) handles namespace creation, RBAC, and workspace provisioning together. Use when deploying browser-based VS Code environments (UDI image registry.redhat.io/devspaces/udi-rhel9) with auto-cloned git projects (sourceMapping: /projects), CHE_DASHBOARD_URL injection, and pre-configured Continue extension for MaaS-served LLM access -- requires CheCluster CR and DevSpaces operator pre-installed via OLM. Critical config: workspace.enabled and devspaces.enabled are separate feature flags with mismatched defaults (workspace.enabled: true but devspaces.enabled: false in values.yaml), so plain helm install creates DevWorkspace CRs without the backing CheCluster causing workspace start failures -- use the all-dependencies.yaml overlay to enable both. Gotchas: IDE editor contribution URI is hardcoded to the openshift-devspaces namespace and breaks if DevSpaces is deployed elsewhere, CheCluster sets secondsOfInactivityBeforeIdling: -1 disabling auto-idle so workspaces consume resources indefinitely, and startTimeoutSeconds: 1200 (20 min) is expected due to UDI image pull on first launch."
metadata:
  type: component
tags:
  tech_stack: [openshift-devspaces, devworkspace-api, helm]
  ai_pattern: []
  platform: [openshift, rhoai]
  data_layer: []
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "Helm templates provisioning per-user DevWorkspace CRs with namespaces and RBAC for a MaaS code assistant"
    approach: "A"
---

# DevWorkspace

## Overview

DevWorkspace is the Kubernetes-native API (`workspace.devfile.io/v1alpha2`) used by OpenShift DevSpaces to provision containerized IDE instances for developers. In the maas-code-assistant quickstart, Helm templates create one DevWorkspace custom resource per user, each in its own namespace, giving developers a browser-based VS Code environment that connects to a privately-hosted LLM via MaaS. The workspace provisioning is tightly coupled with a CheCluster instance running in OpenShift DevSpaces.

## Tech Stack & Dependencies

- **Runtime:** OpenShift DevSpaces 3.25+ (CheCluster `org.eclipse.che/v2`)
- **Container image:** `registry.redhat.io/devspaces/udi-rhel9:3.25.0` (Universal Developer Image)
- **Key dependencies:** DevSpaces operator installed via OLM (`stable` channel), CheCluster CR deployed, per-user namespaces with RBAC
- **Helm subchart:** None -- templates are part of the parent `maas-code-assistant` chart under `templates/workspace/`

## Key Patterns

### Per-User Namespace and DevWorkspace Provisioning via Helm Range

The quickstart iterates over a `users` list in values.yaml and creates a dedicated namespace, DevWorkspace CR, and RoleBinding for each user. This is a Helm-native multi-tenancy pattern that avoids relying on DevSpaces' built-in user provisioning.

```yaml
# charts/maas-code-assistant/templates/workspace/devworkspace.yaml
{{- range $user := .Values.users }}
---
kind: DevWorkspace
apiVersion: workspace.devfile.io/v1alpha2
metadata:
  name: {{ $.Values.workspace.devworkspace.name }}
  namespace: {{ $.Values.workspace.namespacePrefix }}-{{ $user }}
spec:
  routingClass: che
  contributions:
    - name: ide
      uri: http://devspaces-dashboard.openshift-devspaces.svc.cluster.local:8080/dashboard/api/editors/devfile?che-editor=che-incubator/che-code/latest
{{- end }}
```

The `routingClass: che` delegates route management to the DevSpaces operator. The IDE editor is fetched dynamically from the DevSpaces dashboard service via an internal cluster URL rather than being bundled into the DevWorkspace spec.

### Namespace Labels and Annotations for DevSpaces Integration

Each per-user namespace carries specific labels and annotations that DevSpaces requires to recognize it as a workspace namespace:

```yaml
# charts/maas-code-assistant/templates/workspace/namespace.yaml
metadata:
  name: {{ $.Values.workspace.namespacePrefix }}-{{ $user }}
  labels:
    app.kubernetes.io/part-of: che.eclipse.org
    app.kubernetes.io/component: workspaces-namespace
  annotations:
    openshift.io/display-name: "Workspace {{ $user }}"
    che.eclipse.org/username: {{ $user }}
```

The `che.eclipse.org/username` annotation and `app.kubernetes.io/part-of: che.eclipse.org` label are required for DevSpaces to associate the namespace with the correct user.

### RBAC: Edit ClusterRole Binding Per User

Each user gets the built-in `edit` ClusterRole bound in their workspace namespace, granting them full CRUD on standard Kubernetes resources within that namespace:

```yaml
# charts/maas-code-assistant/templates/workspace/rbac.yaml
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: edit
subjects:
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: {{ $user }}
```

### Git Project Cloning into Workspace

The DevWorkspace spec configures a git project that is automatically cloned into the workspace container on start, with a configurable branch revision:

```yaml
# charts/maas-code-assistant/templates/workspace/devworkspace.yaml
template:
  projects:
  - name: {{ $.Values.workspace.devworkspace.name }}
    git:
      remotes:
        origin: {{ $.Values.workspace.devworkspace.projects.repoUrl }}
      checkoutFrom:
        revision: {{ $.Values.workspace.devworkspace.projects.revision }}
```

### Tooling Container with CHE_DASHBOARD_URL

The workspace runs a single `tooling-container` component using the UDI image, with the `CHE_DASHBOARD_URL` environment variable injected so the IDE can link back to the DevSpaces dashboard:

```yaml
# charts/maas-code-assistant/templates/workspace/devworkspace.yaml
components:
  - name: tooling-container
    container:
      image: {{ $.Values.workspace.devworkspace.image }}
      sourceMapping: /projects
      env:
        - name: CHE_DASHBOARD_URL
          value: https://devspaces.{{ $.Values.global.wildcardDomain }}/dashboard/
```

### Feature Gate via workspace.enabled

All three workspace templates are guarded by `{{- if .Values.workspace.enabled }}`, allowing the workspace provisioning to be toggled independently of the rest of the chart. The `all-dependencies.yaml` file sets `devspaces.enabled: true` for the full deployment, while values.yaml defaults `devspaces.enabled: false` and `workspace.enabled: true`.

## Configuration

- **Environment variables:**
  - `CHE_DASHBOARD_URL` -- injected into the tooling container; points to the DevSpaces dashboard URL constructed from `global.wildcardDomain`
- **Config files:**
  - `.vscode/config.yaml` -- pre-configured Continue extension config pointing to the MaaS-served Nemotron model via OpenAI-compatible API
- **Helm values:**
  - `workspace.enabled` (bool) -- toggle workspace provisioning on/off
  - `workspace.namespacePrefix` (string, default: `wksp`) -- prefix for per-user namespace names (produces `wksp-user1`, `wksp-user2`, etc.)
  - `workspace.devworkspace.name` (string, default: `exercises`) -- name of the DevWorkspace CR and project
  - `workspace.devworkspace.projects.repoUrl` (string) -- git repo URL cloned into the workspace
  - `workspace.devworkspace.projects.revision` (string, default: `main`) -- git branch/tag to checkout
  - `workspace.devworkspace.image` (string) -- UDI container image for the tooling container
  - `users` (list of strings) -- usernames to create workspaces for
  - `devspaces.enabled` (bool) -- controls CheCluster and DevSpaces namespace creation (separate from workspace resources)
  - `devspaces.namespace` (string, default: `openshift-devspaces`) -- namespace for the CheCluster CR

## Known Gotchas

- The CheCluster and DevWorkspace resources are controlled by separate feature flags (`devspaces.enabled` vs `workspace.enabled`). The `all-dependencies.yaml` sets `devspaces.enabled: true` but values.yaml defaults it to `false`, meaning a basic `helm install` without the all-dependencies overlay will create DevWorkspace CRs but skip the CheCluster -- the workspaces will fail to start without the DevSpaces operator and CheCluster in place.
- The IDE editor contribution URI (`http://devspaces-dashboard.openshift-devspaces.svc.cluster.local:8080/...`) is hardcoded to the `openshift-devspaces` namespace. If DevSpaces is deployed in a different namespace, this internal service URL will not resolve.
- The CheCluster spec sets `secondsOfInactivityBeforeIdling: -1`, which disables automatic workspace idling. This means workspaces remain running indefinitely and consume cluster resources until manually stopped.
- The CheCluster sets `startTimeoutSeconds: 1200` (20 minutes), indicating workspace starts can be slow, likely due to pulling the UDI image on first launch.

## Testing Notes

- Verify the DevSpaces operator is installed and the CheCluster CR is in `Ready` state in the `openshift-devspaces` namespace before creating DevWorkspace resources
- After Helm install, check that per-user namespaces exist: `oc get ns | grep wksp-`
- Verify DevWorkspace CRs are created and reach `Running` phase: `oc get devworkspaces -A`
- Confirm users can access their workspace IDE via the DevSpaces dashboard URL at `https://devspaces.<wildcardDomain>/dashboard/`

## Related Patterns

- CheCluster deployment pattern (DevSpaces operator management)
- Per-user namespace isolation with Helm range loops
- MaaS API integration via VS Code Continue extension configuration
