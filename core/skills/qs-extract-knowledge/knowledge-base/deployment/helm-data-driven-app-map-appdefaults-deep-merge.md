---
name: helm-data-driven-app-map-appdefaults-deep-merge
description: Helm chart iterating a values.apps map with appDefaults inheritance, auto-generated names, and deep merge
summary: "Deploys multiple heterogeneous services (backend, frontend, postgres) from a single Helm chart by defining all workloads in a values.apps map that every template (Deployment, Service, Ingress, CronJob, Job, ConfigMap) iterates via range, with per-app enabled flags controlling inclusion. Use when building a generic reusable chart for multi-service deployments where apps share common defaults (ClusterIP, 1 replica, IfNotPresent, no HPA) but need per-app overrides -- each app requires only image.repository, tag, and port while inheriting everything else from appDefaults via mustMerge/deepCopy deep merge. Helper templates auto-generate resource names as project.name-appName (63-char truncated); namespace is ns-{appname} unless project.deploymentTarget is kind; replicaCount uses a fallback chain (appConfig.replicaCount | replicas | defaults.replicaCount | 1); container-level security (allowPrivilegeEscalation: false, drop ALL capabilities) is applied unconditionally. Setting podSecurityContext: null suppresses default pod-level runAsNonRoot/seccompProfile; secretEnv renders as secretKeyRef in production but plain env vars when secretEnvAsEnv: true (Kind/local dev toggle); auto-generated ingress hostnames use {project.name}-{appName}.local and add NVIDIA DNS updater annotations unless project.orientation is external."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [kubernetes]
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "AI-Q Blueprint chart with data-driven app definitions, appDefaults deep merge, auto-generated ingress/labels"
    approach: "A"
---

# Helm Data-Driven App Map with appDefaults Deep Merge

## Overview

A Helm chart design pattern where all application workloads are defined as entries in a `values.apps` map rather than having separate templates per service. Every template iterates over this map with `range $appName, $appConfig := .Values.apps`, and each app inherits configuration from a shared `appDefaults` block. This creates a generic, reusable chart that deploys any number of services (backend, frontend, postgres, etc.) from a single template set.

## Pattern Description

The chart defines one `deployment.yaml`, one `service.yaml`, one `ingress.yaml`, etc. -- each template iterates the `apps` map and renders one Kubernetes resource per enabled app. Apps inherit defaults from `appDefaults` (replica count, service type, security context, HPA settings, image pull policy) but can override any value. Helper templates generate consistent naming, labels, and image references from the project and app names.

## Implementation

### App Definitions in Values

Apps are defined as a map under `apps:`. Each entry specifies only what differs from defaults.

```yaml
apps:
  backend:
    enabled: true
    image:
      repository: nvcr.io/nvidia/blueprint/aiq-agent
      tag: "2.0.0"
    port: 8000
    env:
      CONFIG_FILE: configs/config_web_default_llamaindex.yml
    resources:
      requests:
        cpu: 500m
        memory: 1Gi
  frontend:
    enabled: true
    image:
      repository: nvcr.io/nvidia/blueprint/aiq-frontend
      tag: "2.0.0"
    port: 3000
  postgres:
    enabled: true
    image:
      repository: bitnami/postgresql
      tag: latest
    ports:
    - name: postgres
      containerPort: 5432
```

### appDefaults Inheritance

The `appDefaults` block provides shared configuration that every app inherits unless overridden.

```yaml
appDefaults:
  replicaCount: 1
  service:
    type: ClusterIP
  serviceAccount:
    create: true
    annotations: {}
  autoscaling:
    enabled: false
    minReplicas: 1
    maxReplicas: 3
    targetCPUUtilizationPercentage: 80
  podSecurityContext: {}
  securityContext: {}
  image:
    pullPolicy: IfNotPresent
```

### Template Iteration with Deep Merge

Templates use `range` to iterate apps and `mustMerge` with `deepCopy` for safe merging of nested objects.

```yaml
{{- range $appName, $appConfig := .Values.apps }}
{{- if $appConfig.enabled }}
{{- $defaults := $.Values.appDefaults | default dict }}
{{- $replicaCount := $appConfig.replicaCount | default $appConfig.replicas | default $defaults.replicaCount | default 1 }}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "aiq.appFullname" (list $ $appName) }}
  namespace: {{ include "aiq.namespace" $ }}
```

### Auto-Generated Names and Labels

Helper templates generate consistent resource names from the project name and app name, with 63-character truncation.

```go
{{- define "aiq.appFullname" -}}
{{- $global := index . 0 -}}
{{- $appName := index . 1 -}}
{{- printf "%s-%s" $global.Values.project.name ($appName | trunc 15 | trimSuffix "-") | trunc 63 | trimSuffix "-" }}
{{- end }}
```

### Hardened Container Security Context

Every container gets a hardened security context applied unconditionally at the container level, regardless of pod-level settings.

```yaml
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop:
            - ALL
          readOnlyRootFilesystem: false
```

### Namespace Auto-Generation

The namespace template auto-generates a prefixed namespace based on the deployment target.

```go
{{- define "aiq.namespace" -}}
{{- if eq (.Values.project.deploymentTarget | default "") "kind" -}}
{{- .Values.appname -}}
{{- else -}}
{{- printf "ns-%s" .Values.appname -}}
{{- end -}}
{{- end }}
```

## Configuration

- **Key settings:** `project.name` drives all naming; `project.deploymentTarget` affects namespace; each app's `enabled` flag controls inclusion
- **Defaults:** ClusterIP services, 1 replica, no HPA, no ingress, IfNotPresent pull policy
- **Dependencies:** Each app must have an `image.repository` and `tag` specified either directly or via `imageRepository` global

## Gotchas

- The `podSecurityContext: null` in app values is used to explicitly suppress the default `runAsNonRoot: true` / `seccompProfile: RuntimeDefault` that the template applies when `podSecurityContext` is not present -- setting it to `null` tells the template to skip pod-level security context entirely
- Per-app `secretEnv` renders as `valueFrom.secretKeyRef` when `secretEnvAsEnv` is false (production), but renders as plain env vars when `secretEnvAsEnv` is true (Kind/local dev) -- this dual behavior is controlled by a single global toggle
- Auto-generated ingress hostnames use the pattern `{project.name}-{appName}.local` and auto-add NVIDIA DNS updater annotations unless `project.orientation` is set to `external`
- The CronJob, Job, and ConfigMap templates also iterate the apps map, looking for `cronJobs`, `jobs`, and `configMaps` sub-keys respectively

## Related Patterns

- `helm-vault-externalsecrets-sharedsecrets-secretenvasenv-toggle.md` -- the secrets management layer consumed by this app map pattern
- `helm-initcontainer-pgisready-configmap-sql-dual-db-langgraph.md` -- backend app's initContainer configuration within this pattern
