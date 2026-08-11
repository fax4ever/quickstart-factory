---
name: helm-workbench-notebook-job-exec-git-clone
description: Kubeflow Notebook workbench with Job that waits for pod readiness then execs git clone into it
summary: "Deploys a Kubeflow Notebook workbench on OpenShift AI with a separate Kubernetes Job that uses an init container polling `oc get pods -l notebook-name=<name>` for Running phase, then runs `oc exec git clone` into the notebook container at `/opt/app-root/src`. Conditionally deployed via `workbench.enabled` and `workbench.gitRepo.enabled` with four ArgoCD sync-wave-ordered resources (wave 0: PVC+RBAC for pods/exec, wave 1: Notebook CR with OAuth proxy injection, wave 2: clone Job with `backoffLimit: 3`) using the internal `openshift/tools:latest` image. Notebook image defaults to `s2i-minimal-notebook:2025.1` with 1 CPU/8Gi requests and 1Gi PVC; `clusterdomainurl` must be overridden from `cluster.example.com` for RHOAI dashboard tornado settings. Init container checks Running phase but not Jupyter server readiness so clone can fail on unmounted filesystem; `hook-delete-policy: BeforeHookCreation` with `argocd.argoproj.io/hook: Sync` causes the Job to re-run every ArgoCD sync rather than only on initial install; empty `ServerApp.token`/`ServerApp.password` rely entirely on OAuth proxy."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, jupyter]
  ai_pattern: [guardrails]
  platform: [rhoai, openshift]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Kubeflow Notebook CR + PVC + RBAC + Job with init-container wait loop and oc exec git clone, ArgoCD sync-wave ordered"
    approach: "A"
---

# Workbench Notebook with Job-Exec Git Clone

## Overview

This pattern deploys a Kubeflow Notebook workbench (Jupyter) on OpenShift AI and uses a separate Kubernetes Job to clone a git repository into the running workbench pod. The Job uses an init container to poll for the workbench pod's readiness before executing `oc exec` to run `git clone` inside the notebook container. ArgoCD sync-waves ensure correct ordering.

## Pattern Description

Four resources work together: a PVC for persistent storage, a Kubeflow Notebook CR that mounts the PVC, RBAC resources (ServiceAccount, Role, RoleBinding) granting pod exec permissions, and a Job that waits for the notebook pod to be running before cloning a git repo into it. The pattern is conditionally deployed via `workbench.enabled` and the git clone is additionally gated by `workbench.gitRepo.enabled`. ArgoCD sync-wave annotations order the deployment: PVC and RBAC at wave 0, Notebook at wave 1, clone Job at wave 2.

## Implementation

### Kubeflow Notebook CR

The notebook uses the OpenShift internal image registry for the base image and configures the Jupyter server with RHOAI dashboard integration:

```yaml
# helm/templates/workbench.yaml
{{- if .Values.workbench.enabled }}
apiVersion: kubeflow.org/v1
kind: Notebook
metadata:
  name: {{ .Values.workbench.name }}
  annotations:
    notebooks.opendatahub.io/inject-oauth: "true"
    argocd.argoproj.io/sync-wave: "1"
spec:
  template:
    spec:
      containers:
        - name: {{ .Values.workbench.name }}
          image: {{ .Values.workbench.image }}
          resources:
            requests:
              cpu: {{ .Values.workbench.resources.requests.cpu | quote }}
              memory: {{ .Values.workbench.resources.requests.memory }}
            limits:
              cpu: {{ .Values.workbench.resources.limits.cpu | quote }}
              memory: {{ .Values.workbench.resources.limits.memory }}
          volumeMounts:
            - name: workbench-pvc
              mountPath: /opt/app-root/src
          env:
            - name: NOTEBOOK_ARGS
              value: |-
                --ServerApp.port=8888
                --ServerApp.token=''
                --ServerApp.password=''
                --ServerApp.base_url=/notebook/{{ .Release.Namespace }}/{{ .Values.workbench.name }}
{{- end }}
```

### Git Clone Job with Init Container Wait

The Job uses an init container to poll for the workbench pod, then the main container execs into it:

```yaml
# helm/templates/workbench-job-clone.yaml
{{- if and .Values.workbench.enabled .Values.workbench.gitRepo.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Values.workbench.name }}-clone-repo
  annotations:
    argocd.argoproj.io/sync-wave: "2"
    argocd.argoproj.io/hook: Sync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 3
  template:
    spec:
      serviceAccountName: {{ .Values.workbench.name }}
      initContainers:
        - name: wait-for-workbench
          image: image-registry.openshift-image-registry.svc:5000/openshift/tools:latest
          command: ["/bin/bash"]
          args:
            - -ec
            - |
              echo "Waiting for workbench pod..."
              while [ -z "$(oc get pods -n {{ .Release.Namespace }} \
                -l notebook-name={{ .Values.workbench.name }} \
                -o jsonpath='{.items[0].status.phase}' 2>/dev/null \
                | grep Running)" ]; do
                sleep 2
              done
              echo "Workbench pod is running."
      containers:
        - name: git-clone
          image: image-registry.openshift-image-registry.svc:5000/openshift/tools:latest
          command: ["/bin/bash"]
          args:
            - -ec
            - |
              POD_NAME=$(oc get pods -n {{ .Release.Namespace }} \
                -l notebook-name={{ .Values.workbench.name }} \
                -o jsonpath='{.items[0].metadata.name}')
              oc exec -n {{ .Release.Namespace }} $POD_NAME -- \
                bash -c "cd /opt/app-root/src && git clone {{ .Values.workbench.gitRepo.url }}"
      restartPolicy: Never
{{- end }}
```

### RBAC for Pod Exec

The Job's ServiceAccount needs explicit permissions to get, list, and exec into pods:

```yaml
# helm/templates/workbench-role.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ .Values.workbench.name }}-pod-exec
  annotations:
    argocd.argoproj.io/sync-wave: "0"
rules:
- apiGroups: [""]
  resources: ["pods", "pods/exec"]
  verbs: ["get", "list", "create"]
```

## Configuration

- **Key settings:** `workbench.enabled` (default `true`) toggles the entire workbench stack; `workbench.gitRepo.enabled` (default `true`) toggles the git clone Job; `workbench.gitRepo.url` specifies the repo to clone; `workbench.image` defaults to the RHOAI internal registry minimal notebook image
- **Defaults:** Workbench requests 1 CPU / 8Gi memory with limits of 2 CPU / 8Gi; PVC size is 1Gi; the notebook image is `image-registry.openshift-image-registry.svc:5000/redhat-ods-applications/s2i-minimal-notebook:2025.1`
- **Dependencies:** Kubeflow Notebook controller (part of RHOAI); OpenShift tools image available in internal registry at `openshift/tools:latest`; the `clusterdomainurl` value for RHOAI dashboard integration in the tornado settings

## Gotchas

- The git clone Job uses `oc exec` to run commands inside the workbench pod rather than using a shared PVC or init container on the Notebook itself -- this means the Job needs RBAC for `pods/exec` and depends on the pod being in `Running` phase (see `helm/templates/workbench-job-clone.yaml`)
- The init container polls with `oc get pods -l notebook-name=<name>` and checks for `Running` phase, but does not verify that the Jupyter server inside is ready -- the clone could potentially fail if the container is running but the filesystem is not yet mounted (see `helm/templates/workbench-job-clone.yaml`)
- The ArgoCD annotations (`argocd.argoproj.io/hook: Sync` and `hook-delete-policy: BeforeHookCreation`) mean the Job is treated as an ArgoCD sync hook -- previous Job resources are deleted before each sync, and the Job runs during every ArgoCD sync, not just initial install (see `helm/templates/workbench-job-clone.yaml`)
- The Notebook `ServerApp.token` and `ServerApp.password` are set to empty strings, relying entirely on the OpenShift OAuth proxy (`notebooks.opendatahub.io/inject-oauth: "true"`) for authentication (see `helm/templates/workbench.yaml`)
- The `clusterdomainurl` value in values.yaml defaults to `cluster.example.com` and must be overridden for RHOAI dashboard hub integration in the notebook's tornado settings (see `helm/values.yaml`)

## Related Patterns

- `helm-flat-chart-direct-crd-templating.md` -- the chart structure containing this workbench deployment
- `helm-init-job-multi-service-wait-chain.md` -- alternative init Job pattern using chained init containers for multi-service readiness
