---
name: devspaces-workspace
description: "OpenShift DevSpaces CheCluster and DevWorkspace provisioning for cloud-native IDE workspaces in quickstarts"
summary: "Provisions containerized cloud-native IDE workspaces (che-code/VS Code) on OpenShift DevSpaces for AI quickstart workshops, split into CheCluster operator resource and per-user DevWorkspace instances managed via inline Helm templates in the parent chart. Use when quickstarts need browser-based IDE environments with pre-cloned repos; `devspaces.enabled` (default false) controls CheCluster creation (skip when operator pre-installed via `dependency-operators` chart), while `workspace.enabled` (default true) provisions per-user namespaces by ranging over the `users` list with Che labels, `che.eclipse.org/username` annotations, and edit RBAC bindings. UDI tooling container `registry.redhat.io/devspaces/udi-rhel9:3.25.0` runs in each workspace, `CHE_DASHBOARD_URL` connects to the dashboard, and the `all-dependencies.yaml` overlay sets `devspaces.enabled: true` for full automated deployments. Auto-idling is disabled (`secondsOfInactivityBeforeIdling: -1`) intentionally for workshops but unsuitable for production; `startTimeoutSeconds: 1200` accommodates large UDI image pulls; the IDE contribution URI hardcodes `http://devspaces-dashboard.openshift-devspaces.svc.cluster.local:8080` which breaks if the DevSpaces namespace changes."
metadata:
  type: component
tags:
  tech_stack: [openshift-devspaces, devworkspace, che-code, helm]
  ai_pattern: []
  platform: [openshift, rhoai]
  data_layer: []
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "DevSpaces CheCluster + per-user DevWorkspace provisioning for AI code assistant IDE"
    approach: "A"
---

# DevSpaces Workspace

## Overview

OpenShift DevSpaces provides containerized cloud-native IDE instances for developer teams working on an OpenShift cluster. In AI Quickstarts, it serves as the development environment where users interact with AI code assistant capabilities. The component is split into two logical pieces managed by a single Helm chart: the CheCluster operator resource (in the `devspaces/` template directory) and per-user DevWorkspace instances (in the `workspace/` template directory).

## Tech Stack & Dependencies

- **Runtime:** OpenShift DevSpaces 3.26 (operator), UDI container `registry.redhat.io/devspaces/udi-rhel9:3.25.0`
- **Container image:** `registry.redhat.io/devspaces/udi-rhel9:3.25.0` (tooling container for workspaces)
- **Key dependencies:** DevSpaces operator installed via OLM (stable channel), OpenShift OAuth for user authentication
- **Helm subchart:** None -- templates are inline in the `maas-code-assistant` parent chart under `templates/devspaces/` and `templates/workspace/`

## Key Patterns

### Conditional CheCluster Deployment

The CheCluster resource is gated behind `devspaces.enabled` (default `false`) to allow advanced users who already have DevSpaces installed to skip this step. When enabled, it creates both the namespace and a minimal CheCluster resource.

```yaml
# charts/maas-code-assistant/templates/devspaces/checluster.yaml
{{- if .Values.devspaces.enabled }}
apiVersion: org.eclipse.che/v2
kind: CheCluster
metadata:
  name: devspaces
  namespace: {{ .Values.devspaces.namespace }}
spec:
  components: {}
  networking: {}
  devEnvironments:
    startTimeoutSeconds: 1200
    secondsOfInactivityBeforeIdling: -1
{{- end }}
```

### Per-User DevWorkspace Provisioning

DevWorkspace instances are created by ranging over the `users` list in values.yaml. Each user gets a dedicated namespace (`wksp-<username>`) with a DevWorkspace that clones the quickstart repo and connects to the DevSpaces dashboard for the VS Code (che-code) editor.

```yaml
# charts/maas-code-assistant/templates/workspace/devworkspace.yaml
{{- range $user := .Values.users }}
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

### Workspace Namespace with Che Labels

Each user namespace is annotated with Che-specific labels and annotations so the DevSpaces operator recognizes it as a workspace namespace and maps it to the correct user.

```yaml
# charts/maas-code-assistant/templates/workspace/namespace.yaml
metadata:
  name: {{ $.Values.workspace.namespacePrefix }}-{{ $user }}
  labels:
    app.kubernetes.io/part-of: che.eclipse.org
    app.kubernetes.io/component: workspaces-namespace
  annotations:
    che.eclipse.org/username: {{ $user }}
```

### Per-User RBAC

Each workspace namespace gets a RoleBinding granting the user the `edit` ClusterRole, ensuring they can manage resources within their workspace namespace.

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

## Configuration

- **Environment variables:**
  - `CHE_DASHBOARD_URL` -- set on the tooling container to `https://devspaces.{{ .Values.global.wildcardDomain }}/dashboard/`, connecting the workspace to the DevSpaces dashboard
- **Config files:** None -- all configuration is via Helm values
- **Helm values:**
  - `devspaces.enabled` (default `false`) -- whether to deploy the CheCluster resource
  - `devspaces.namespace` (default `openshift-devspaces`) -- target namespace for the CheCluster
  - `workspace.enabled` (default `true`) -- whether to create DevWorkspace instances
  - `workspace.namespacePrefix` (default `wksp`) -- prefix for per-user workspace namespaces
  - `workspace.devworkspace.name` (default `exercises`) -- name of the DevWorkspace resource
  - `workspace.devworkspace.projects.repoUrl` -- git repo URL cloned into the workspace
  - `workspace.devworkspace.projects.revision` (default `main`) -- git branch to check out
  - `workspace.devworkspace.image` -- UDI container image for the tooling container
  - `users` -- list of usernames; each gets a workspace namespace and DevWorkspace instance

## Known Gotchas

- `secondsOfInactivityBeforeIdling` is set to `-1` in the CheCluster spec, which disables workspace auto-idling. This is intentional for quickstart/workshop scenarios where users should not have their workspaces shut down during exercises, but would be inappropriate for production multi-tenant deployments.
- `startTimeoutSeconds` is set to `1200` (20 minutes), significantly higher than the default, to accommodate the large UDI image pull on first workspace start.
- The `devspaces.enabled` flag defaults to `false` while `workspace.enabled` defaults to `true`. This means the all-in-one installation expects DevSpaces to be pre-installed (via the `dependency-operators` chart which installs the operator from OLM), and only the CheCluster resource creation is optional. The `all-dependencies.yaml` overlay sets `devspaces.enabled: true` for full automated deployments.
- The DevWorkspace IDE contribution URI hardcodes the internal service URL `http://devspaces-dashboard.openshift-devspaces.svc.cluster.local:8080` -- this will break if the DevSpaces namespace is changed without updating this template.
- Workspace namespaces require the `che.eclipse.org/username` annotation and `app.kubernetes.io/part-of: che.eclipse.org` label for the DevSpaces operator to properly associate them with users.

## Testing Notes

- After deployment, verify the CheCluster reaches `Active` status: `oc get checluster devspaces -n openshift-devspaces`
- Verify workspace namespaces are created: `oc get ns | grep wksp-`
- Verify DevWorkspace instances are running: `oc get devworkspace -A`
- Check that the DevSpaces dashboard is accessible at `https://devspaces.<wildcardDomain>/dashboard/`
- Confirm users can open their workspace and the quickstart repo is cloned in `/projects`

## Related Patterns

- Dependency operators chart installs the DevSpaces operator via OLM subscription (stable channel)
- User provisioning in `values.yaml` (`users` list) drives both workspace creation and other per-user resources like MaaS subscriptions
