---
name: helm-devworkspace-per-user-namespace-rbac
description: Helm range loop creating per-user namespaces, DevWorkspace CRs, and RBAC for multi-tenant IDE workspaces
summary: "Pre-provisions multi-tenant OpenShift DevSpaces IDE workspaces via Helm range loop over a users list, creating per-user wksp-<user> namespaces (with che.eclipse.org/username annotation and app.kubernetes.io/part-of: che.eclipse.org labels), DevWorkspace CRs (workspace.devfile.io/v1alpha2 with Git project cloning, UDI container, and che-code IDE contribution), and RBAC RoleBindings granting edit ClusterRole -- conditionally enabled via workspace.enabled across three templates (namespace.yaml, devworkspace.yaml, rbac.yaml). Use when deploying workshop or multi-user environments needing pre-configured DevSpaces code assistant workspaces; requires DevSpaces operator (CheCluster) in openshift-devspaces namespace and DevWorkspace API -- no alternatives within this pattern. Critical config: users list in values.yaml drives the range loop, workspace.namespacePrefix (default wksp) sets naming, workspace.devworkspace.image defaults to registry.redhat.io/devspaces/udi-rhel9:3.25.0, and the IDE contribution URI is hardcoded to devspaces-dashboard.openshift-devspaces.svc.cluster.local:8080. Gotchas: namespaces must carry labels app.kubernetes.io/part-of: che.eclipse.org and app.kubernetes.io/component: workspaces-namespace plus annotation che.eclipse.org/username for DevSpaces recognition, routingClass: che routes through DevSpaces gateway not individual Routes, users must pre-exist in cluster IdP (Keycloak) with matching names, and adding/removing users requires updating the list and running helm upgrade."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "Creates per-user namespaces (wksp-user1 through wksp-user5) with DevWorkspace CRs, RBAC RoleBindings, and DevSpaces annotations for multi-tenant code assistant workspaces"
    approach: "A"
---

# Per-User DevWorkspace Namespace and RBAC Provisioning

## Overview

This pattern uses a Helm range loop over a list of usernames to create per-user namespaces, DevWorkspace custom resources, and RBAC RoleBindings. It provisions multi-tenant IDE workspaces via OpenShift DevSpaces, where each user gets an isolated namespace with a pre-configured DevWorkspace that clones a Git repository and provides a VS Code-like IDE with AI coding extensions.

## Pattern Description

Instead of requiring users to manually create their own DevSpaces workspaces, this pattern pre-provisions everything during Helm install. A `users` list in values.yaml drives a range loop across three template files: namespace creation (with DevSpaces annotations), DevWorkspace CR creation (with Git project and IDE contribution), and RoleBinding creation (granting each user `edit` ClusterRole in their namespace). The pattern is conditionally enabled via `workspace.enabled`.

## Implementation

### User List in Values

```yaml
# charts/maas-code-assistant/values.yaml
users:
  - user1
  - user2
  - user3
  - user4
  - user5

workspace:
  enabled: true
  namespacePrefix: wksp
  devworkspace:
    name: exercises
    projects:
      repoUrl: https://github.com/rh-ai-quickstart/maas-code-assistant.git
      revision: main
    image: registry.redhat.io/devspaces/udi-rhel9:3.25.0
```

### Per-User Namespace with DevSpaces Annotations

```yaml
# charts/maas-code-assistant/templates/workspace/namespace.yaml
{{- if .Values.workspace.enabled }}
{{- range $user := .Values.users }}
---
apiVersion: v1
kind: Namespace
metadata:
  name: {{ $.Values.workspace.namespacePrefix }}-{{ $user }}
  labels:
    app.kubernetes.io/part-of: che.eclipse.org
    app.kubernetes.io/component: workspaces-namespace
  annotations:
    openshift.io/display-name: "Workspace {{ $user }}"
    openshift.io/description: "Workspace Namespace"
    che.eclipse.org/username: {{ $user }}
{{- end }}
{{- end }}
```

### DevWorkspace CR per User

```yaml
# charts/maas-code-assistant/templates/workspace/devworkspace.yaml
{{- if .Values.workspace.enabled }}
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
  template:
    projects:
    - name: {{ $.Values.workspace.devworkspace.name }}
      git:
        remotes:
          origin: {{ $.Values.workspace.devworkspace.projects.repoUrl }}
        checkoutFrom:
          revision: {{ $.Values.workspace.devworkspace.projects.revision }}
    components:
      - name: tooling-container
        container:
          image: {{ $.Values.workspace.devworkspace.image }}
          sourceMapping: /projects
          env:
            - name: CHE_DASHBOARD_URL
              value: https://devspaces.{{ $.Values.global.wildcardDomain }}/dashboard/
{{- end }}
{{- end }}
```

### RBAC RoleBinding per User

```yaml
# charts/maas-code-assistant/templates/workspace/rbac.yaml
{{- if .Values.workspace.enabled }}
{{- range $user := .Values.users }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: wksp-edit-{{ $user }}
  namespace: {{ $.Values.workspace.namespacePrefix }}-{{ $user }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: edit
subjects:
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: {{ $user }}
{{- end }}
{{- end }}
```

## Configuration

- **Key settings:** `users` list defines usernames (default: user1 through user5); `workspace.namespacePrefix` (default: `wksp`) sets the namespace naming convention; `workspace.devworkspace.image` sets the UDI container image; `workspace.devworkspace.projects.repoUrl` sets the Git repo cloned into each workspace
- **Defaults:** 5 users, `wksp` prefix, Red Hat DevSpaces UDI 3.25.0 image, main branch checkout
- **Dependencies:** Requires OpenShift DevSpaces operator (CheCluster) to be running; requires DevWorkspace API (`workspace.devfile.io/v1alpha2`); the IDE contribution URI references the DevSpaces dashboard internal service

## Gotchas

- The DevWorkspace IDE contribution URI is hardcoded to the internal cluster service DNS `devspaces-dashboard.openshift-devspaces.svc.cluster.local:8080` -- this depends on the DevSpaces operator being installed in the `openshift-devspaces` namespace
- The namespace labels `app.kubernetes.io/part-of: che.eclipse.org` and `app.kubernetes.io/component: workspaces-namespace` along with the `che.eclipse.org/username` annotation are required for DevSpaces to recognize the namespace as belonging to a user
- The `routingClass: che` setting routes workspace traffic through the DevSpaces gateway rather than creating individual Routes per workspace
- Users must exist in the cluster's identity provider (Keycloak in this quickstart) with matching usernames for the RBAC RoleBindings to be effective
- Adding or removing users requires updating the `users` list in values.yaml and re-running `helm upgrade`

## Related Patterns

- `helm-keycloak-openshift-oauth-patch-realmimport.md` -- creates the matching users in Keycloak that correspond to the workspace usernames
