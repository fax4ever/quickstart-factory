---
name: guardrails-workbench
description: "Helm-deployed RHOAI workbench using Kubeflow Notebook CRD with git-clone Job and guardrails demo notebook"
summary: "Solves automated Jupyter workbench deployment on RHOAI using Kubeflow Notebook CRD with ODH annotations (inject-oauth for OAuth proxy sidecar, opendatahub.io/dashboard PVC label with pvc-protection finalizer) and ArgoCD sync-waves (0: PVC+RBAC, 1: Notebook, 2: git-clone Job with BeforeHookCreation hook-delete-policy). Use when a quickstart needs an interactive notebook environment with auto-cloned repo content -- the clone Job's initContainer polls for pod Running then runs oc exec git clone, requiring a ServiceAccount with pods/pods/exec permissions (get, list, create); NOTEBOOK_ARGS sets base_url to /notebook/<namespace>/<name> and tornado_settings links to RHOAI dashboard via clusterdomainurl. Critical config: workbench.enabled and workbench.gitRepo.enabled toggles control deployment, workbench.image from internal registry (s2i-minimal-notebook:2025.1), and the included notebook calls TrustyAI orchestrator gateway at /all/v1/chat/completions for PII, HAP, prompt injection, and gibberish detection. Gotchas: orchestrator URL hardcodes guardrails-demo namespace requiring manual update if redeployed elsewhere, OAuth sidecar causes 2/2 Ready pod count that may confuse readiness checks, clone Job hangs until backoffLimit: 3 if workbench never starts, and BeforeHookCreation deletes the completed Job on ArgoCD re-sync hiding it from kubectl get jobs."
metadata:
  type: component
tags:
  tech_stack: [jupyter, python, kubeflow, helm]
  ai_pattern: [guardrails]
  platform: [rhoai, openshift, kserve, trustyai]
  data_layer: []
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Helm-deployed RHOAI workbench with git-clone Job and healthcare guardrails demo notebook"
    approach: "A"
---

# Guardrails Workbench

## Overview

A Helm-deployed RHOAI workbench using the Kubeflow Notebook CRD that provides an interactive Jupyter environment for testing LLM guardrails. The workbench is fully automated: Helm deploys the Notebook resource, PVC, RBAC, and a Kubernetes Job that clones the quickstart repo into the workbench after it starts. The included notebook demonstrates TrustyAI guardrails orchestration with PII detection, content moderation, prompt injection protection, and gibberish detection.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 (RHOAI minimal notebook image)
- **Container image:** `image-registry.openshift-image-registry.svc:5000/redhat-ods-applications/s2i-minimal-notebook:2025.1`
- **Key dependencies:**
  - `requests` -- HTTP calls to the guardrails orchestrator gateway
  - Kubeflow Notebook CRD (`kubeflow.org/v1`) -- workbench lifecycle management
  - OpenShift tools image -- used by the git-clone Job for `oc exec`
- **Helm subchart:** None (standalone templates within the quickstart Helm chart)

## Key Patterns

### Kubeflow Notebook CRD with ODH Annotations

The workbench is deployed as a `kubeflow.org/v1 Notebook` resource with Open Data Hub annotations that enable OAuth injection and image tracking in the RHOAI dashboard.

```yaml
apiVersion: kubeflow.org/v1
kind: Notebook
metadata:
  name: {{ .Values.workbench.name }}
  annotations:
    notebooks.opendatahub.io/inject-oauth: "true"
    notebooks.opendatahub.io/last-image-selection: 'jupyter-minimal-cpu-py312-ubi9:2025.1'
    opendatahub.io/image-display-name: Jupyter | Minimal | CPU | Python 3.12
    argocd.argoproj.io/sync-wave: "1"
```

The `inject-oauth: "true"` annotation causes ODH to inject an OAuth proxy sidecar, which is why the workbench pod shows `2/2` Ready containers.

### NOTEBOOK_ARGS ServerApp Configuration

The Notebook container receives JupyterLab configuration via the `NOTEBOOK_ARGS` environment variable, setting up the base URL path to match the RHOAI dashboard routing convention.

```yaml
env:
  - name: NOTEBOOK_ARGS
    value: |-
      --ServerApp.port=8888
      --ServerApp.token=''
      --ServerApp.password=''
      --ServerApp.base_url=/notebook/{{ .Release.Namespace }}/{{ .Values.workbench.name }}
      --ServerApp.quit_button=False
      --ServerApp.tornado_settings={"user":"admin","hub_host":"https://rhods-dashboard-redhat-ods-applications.apps.{{ .Values.clusterdomainurl }}","hub_prefix":"/projects/{{ .Release.Namespace }}"}
```

The `base_url` must follow the `/notebook/<namespace>/<workbench-name>` pattern for the RHOAI dashboard proxy to route correctly. The `tornado_settings` links back to the RHOAI dashboard host.

### Git-Clone Job with Pod Exec

A Kubernetes Job clones the quickstart repo into the running workbench using `oc exec`. It uses an initContainer to poll until the workbench pod is Running before executing the clone.

```yaml
initContainers:
  - name: wait-for-workbench
    image: image-registry.openshift-image-registry.svc:5000/openshift/tools:latest
    command: ["/bin/bash"]
    args:
      - -ec
      - |
        echo "Waiting for workbench pod..."
        while [ -z "$(oc get pods -n {{ .Release.Namespace }} -l notebook-name={{ .Values.workbench.name }} -o jsonpath='{.items[0].status.phase}' 2>/dev/null | grep Running)" ]; do
          sleep 2
        done
containers:
  - name: git-clone
    image: image-registry.openshift-image-registry.svc:5000/openshift/tools:latest
    command: ["/bin/bash"]
    args:
      - -ec
      - |
        POD_NAME=$(oc get pods -n {{ .Release.Namespace }} -l notebook-name={{ .Values.workbench.name }} -o jsonpath='{.items[0].metadata.name}')
        oc exec -n {{ .Release.Namespace }} $POD_NAME -- bash -c "cd /opt/app-root/src && git clone {{ .Values.workbench.gitRepo.url }}"
```

The Job requires a ServiceAccount with `pods` and `pods/exec` permissions (get, list, create) to find and exec into the workbench pod.

### ArgoCD Sync-Wave Ordering

The workbench resources use ArgoCD sync-waves to ensure correct deployment order:

- Wave `0`: PVC and RBAC (ServiceAccount, Role, RoleBinding)
- Wave `1`: Notebook CRD (needs PVC to exist)
- Wave `2`: Git-clone Job (needs workbench pod to be Running)

The clone Job also carries ArgoCD hook annotations to prevent duplicate runs on re-sync:

```yaml
annotations:
  argocd.argoproj.io/sync-wave: "2"
  argocd.argoproj.io/hook: Sync
  argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
```

### RBAC for Pod Exec

The workbench ServiceAccount gets a Role with `pods` and `pods/exec` permissions so the clone Job can discover and exec into the workbench pod.

```yaml
rules:
- apiGroups: [""]
  resources: ["pods", "pods/exec"]
  verbs: ["get", "list", "create"]
```

### Workbench PVC with ODH Dashboard Label

The PVC uses the `opendatahub.io/dashboard: "true"` label so it appears in the RHOAI dashboard, and a `kubernetes.io/pvc-protection` finalizer to prevent accidental deletion.

```yaml
labels:
  opendatahub.io/dashboard: "true"
finalizers:
  - kubernetes.io/pvc-protection
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: {{ .Values.workbench.storage.size }}
```

### Notebook Content: Healthcare Guardrails Demo

The workbench hosts a notebook (`docs/healthcare-guardrails.ipynb`) that calls the TrustyAI guardrails orchestrator gateway's `/all/` route, which applies all configured detectors (regex PII, hate-and-profanity, prompt injection, gibberish) in a single request.

```python
guardrails_orchestrator_route = 'http://gorch-sample-service.guardrails-demo.svc.cluster.local:8090'
guardrails_gateway_endpoint = f'{guardrails_orchestrator_route}/all/v1/chat/completions'

def send_query(query):
    payload = {
        'model': model_name,
        'messages': [{'content': query, 'role': 'user'}]
    }
    response = post(guardrails_gateway_endpoint, json=payload)
    pprint(response.json())
```

The notebook tests four scenarios: normal query (passes all guardrails), PII detection (SSN blocked by regex detector), inappropriate content (blocked by HAP detector), and prompt injection attack (blocked by prompt injection detector).

## Configuration

- **Environment variables:**
  - `NOTEBOOK_ARGS` -- JupyterLab ServerApp configuration (port, base_url, tornado_settings)
  - `JUPYTER_IMAGE` -- workbench container image reference
- **Config files:** None (notebook code uses inline configuration for orchestrator endpoint)
- **Helm values:**
  - `workbench.enabled` -- toggle workbench deployment (default: `true`)
  - `workbench.name` -- workbench name, used across all resources (default: `guardrails-workbench`)
  - `workbench.image` -- notebook container image from internal registry
  - `workbench.resources.requests/limits` -- CPU (1/2) and memory (8Gi/8Gi)
  - `workbench.storage.size` -- PVC size (default: `1Gi`)
  - `workbench.gitRepo.url` -- repo URL to clone into workbench
  - `workbench.gitRepo.enabled` -- toggle git-clone Job (default: `true`)
  - `clusterdomainurl` -- cluster domain for RHOAI dashboard URL in tornado_settings

## Known Gotchas

- **Pod exec RBAC is required for the git-clone Job:** The clone Job uses `oc exec` to run `git clone` inside the workbench pod. Without the ServiceAccount/Role/RoleBinding providing `pods` and `pods/exec` permissions, the Job fails silently. The RBAC resources are in `workbench-role.yaml`.
- **Clone Job polls with sleep loop for pod readiness:** The initContainer uses a `while` loop with `sleep 2` to poll for the workbench pod to reach Running state. If the workbench never starts (e.g., image pull failure, insufficient resources), the clone Job hangs until its `backoffLimit: 3` is exhausted.
- **Hardcoded orchestrator endpoint in notebook:** The notebook uses `http://gorch-sample-service.guardrails-demo.svc.cluster.local:8090` as the orchestrator URL, with `guardrails-demo` as the namespace. If deployed to a different namespace, this URL must be manually updated in the notebook cell.
- **OAuth sidecar doubles container count:** The `inject-oauth: "true"` annotation causes ODH to inject an OAuth proxy sidecar, so the workbench pod shows `2/2` Ready instead of `1/1`. This is expected but may confuse readiness checks that expect a single container.
- **ArgoCD hook annotations prevent clone Job persistence:** The `BeforeHookCreation` delete policy means the clone Job is deleted on the next sync. This is intentional (prevents duplicate clones) but means `kubectl get jobs` won't show the completed Job after a re-sync.
- **PVC is only 1Gi by default:** The default storage of 1Gi is sufficient for the cloned repo and notebook artifacts but may be too small if users add additional data or dependencies.

## Testing Notes

- After deployment, verify the workbench pod shows `2/2` Ready (one container for Jupyter, one for OAuth proxy)
- The clone Job should complete (status `Completed`) -- check with `oc get pods` for the `-clone-repo-` pod
- Access the workbench via the RHOAI dashboard: Data Science Projects -> project -> Workbenches -> Open
- Inside the workbench, navigate to `guardrailing-llms/docs/healthcare-guardrails.ipynb`
- All detector pods and the orchestrator pod must be Running before executing the notebook
- The notebook's `send_query` function returns empty `choices` and a `warning`/`detections` block when guardrails trigger

## Related Patterns

- See `notebooks.md` for notebook content patterns (data ingestion, model download, integration testing)
- See the architecture KB files for TrustyAI guardrails orchestrator and detector deployment patterns
- See deployment KB files for Helm chart structure and ArgoCD sync-wave patterns
