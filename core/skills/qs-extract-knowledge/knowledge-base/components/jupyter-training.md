---
name: jupyter-training
description: JupyterLab notebook pod for YOLO model training on OpenShift with bundled notebook seeding and PVC workspace
summary: "Deploys a JupyterLab pod as an optional Helm subchart for interactive YOLOv8 fine-tuning on OpenShift, bundling a training notebook into a custom scipy-notebook image with ultralytics pre-installed and seeding it into the notebook root on startup via trainingExample.seedOnStartup. Use when quickstarts need an interactive notebook-based training environment -- gated by jupyter-training.enabled (defaults false) and wired as a conditional file-reference subchart from the parent chart. The arbitrary-UID workaround sets notebookRootDir to /tmp/jupyter-home/notebooks and HOME to /tmp/jupyter-home instead of PVC-mounted paths, symlinking the PVC as pvc-workspace, with auth via Kubernetes Secret (auth.existingSecretName or auto-created with default token \"changeme\"), ConfigMap-injected server config with checksum-triggered rolling restart, and Route haproxy.router.openshift.io/timeout: 3600s for long training sessions. jupyterlab-git must be pip-uninstalled in the Dockerfile (config-only disable is unreliable), /home/jovyan needs explicit chmod 755 or arbitrary-UID pods get PermissionError, YOLO training requires resources.limits.memory: 8Gi to avoid OOMKilled, and PVC stays Pending if no default StorageClass exists -- set workspace.storage.storageClassName explicitly."
metadata:
  type: component
tags:
  tech_stack: [jupyter, python, ultralytics, yolov8, helm]
  ai_pattern: [fine-tuning, multimodal]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "JupyterLab pod with bundled YOLO training notebook, Helm subchart, PVC workspace, and OpenShift arbitrary-UID workarounds"
    approach: "A"
---

# Jupyter Training

## Overview

A JupyterLab pod deployed as an optional Helm subchart for interactive YOLO model fine-tuning. The component bundles a training notebook into a custom container image, seeds it into the notebook root on startup, and provides a PVC-backed workspace for persistence. Designed for OpenShift with arbitrary-UID support and token-based authentication.

## Tech Stack & Dependencies

- **Runtime:** Python 3.11 on `quay.io/jupyter/scipy-notebook:python-3.11`
- **Container image:** Custom Dockerfile based on `quay.io/jupyter/scipy-notebook`, with `ultralytics` pre-installed and `jupyterlab-git` removed
- **Key dependencies:** `ultralytics` (YOLOv8), `scipy-notebook` base stack (numpy, pandas, matplotlib)
- **Helm subchart:** `jupyter-training` v0.1.0 (local file reference from parent chart, gated by `jupyter-training.enabled`)

## Key Patterns

### Notebook Bundling and Startup Seeding

The Dockerfile copies the notebook to a fixed path in the image. On pod startup, an init script seeds it into the notebook root directory if not already present, and also copies to the PVC workspace if writable.

```dockerfile
# training/jupyter-training/Dockerfile
FROM quay.io/jupyter/scipy-notebook:python-3.11
USER root
RUN mkdir -p /opt/bundled-training /home/jovyan/work
COPY yolo_training.ipynb /opt/bundled-training/yolo_training.ipynb
COPY yolo_training.ipynb /home/jovyan/work/yolo_training.ipynb
RUN chmod -R a+rX /opt/bundled-training
RUN chown -R "${NB_UID}:${NB_GID}" /home/jovyan/work
RUN /opt/conda/bin/pip uninstall -y jupyterlab-git || true
RUN /opt/conda/bin/pip install --no-cache-dir ultralytics
RUN chmod 755 /home/jovyan
USER ${NB_UID}
```

The deployment template seeds on startup (controlled by `trainingExample.seedOnStartup`):

```yaml
# deploy/helm/jupyter-training/templates/deployment.yaml (command excerpt)
BUNDLE=/opt/bundled-training;
rm -rf {{ .Values.notebookRootDir | quote }}/training;
if [ ! -e {{ .Values.notebookRootDir | quote }}/yolo_training.ipynb ] && [ -f "$BUNDLE/yolo_training.ipynb" ]; then
  cp -a "$BUNDLE"/yolo_training.ipynb {{ .Values.notebookRootDir | quote }}/;
fi;
```

### OpenShift Arbitrary-UID Workaround

The default notebook root is set to `/tmp/jupyter-home/notebooks` instead of the PVC path because OpenShift arbitrary-UID pods often cannot write to PVC-mounted directories without matching `fsGroup`. A symlink bridges the PVC into the temp-based notebook root.

```yaml
# values.yaml
jupyterHome: /tmp/jupyter-home
notebookRootDir: /tmp/jupyter-home/notebooks
```

```yaml
# deployment.yaml (command excerpt)
ln -snf /home/jovyan/work {{ printf "%s/pvc-workspace" .Values.notebookRootDir | quote }};
```

The `HOME` env var is also set to `/tmp/jupyter-home` so Jupyter/IPython dotfiles are writable by arbitrary UIDs.

### Conditional Subchart Enablement

The entire subchart is gated on `jupyter-training.enabled` (defaults to `false`). Every template wraps its content with this check:

```yaml
# Parent Chart.yaml dependency
- name: jupyter-training
  version: 0.1.0
  repository: file://../jupyter-training
  condition: jupyter-training.enabled
```

```yaml
# Every template file begins with:
{{- if .Values.enabled }}
```

### Token-Based Authentication

Auth uses a Kubernetes Secret containing the `JUPYTER_TOKEN` value. The chart creates the Secret automatically unless an existing one is referenced.

```yaml
# values.yaml
auth:
  existingSecretName: ""
  token: changeme
```

```yaml
# secret.yaml
{{- if and .Values.enabled (not .Values.auth.existingSecretName) }}
stringData:
  token: {{ .Values.auth.token | quote }}
{{- end }}
```

### Jupyter Server Config via ConfigMap

Server and Lab configuration is injected through a ConfigMap mounted at `/etc/jupyter/`. A checksum annotation on the deployment triggers a rolling restart when config changes.

```yaml
# _helpers.tpl
{{- define "jupyter-training.jupyterServerConfigJSON" -}}
{"ServerApp":{"ip":"0.0.0.0","allow_origin":"*","allow_remote_access":true,
  "trust_xheaders":true,"root_dir":{{ .Values.notebookRootDir | toJson }},
  "default_url":"/lab/tree/yolo_training.ipynb"
  {{ if $gitOff }},"jpserver_extensions":{"jupyterlab_git":false}{{ end }} }}
{{- end }}
```

```yaml
# deployment.yaml (pod annotation)
checksum/jupyter-config: {{ include "jupyter-training.jupyterConfigChecksum" . }}
```

## Configuration

- **Environment variables:**
  - `HOME` -- set to `jupyterHome` (`/tmp/jupyter-home`) for arbitrary-UID writability
  - `JUPYTER_TOKEN` -- from Secret, controls Lab login
  - `JUPYTER_PORT` -- defaults to `8888`
  - `NOTEBOOK_ARGS` -- computed from `notebookRootDir` + `notebookArgsExtra`, passed as CLI args to `start-notebook.py`
  - `CLASSES` -- (notebook-level) comma-separated class names for YOLO training (default: `Badge`)
  - `OUTPUT_ROOT` -- (notebook-level) YOLO dataset output directory (default: `./yolo_dataset`)

- **Config files:**
  - `jupyter_server_config.json` -- ServerApp settings (ip, root_dir, default_url, git extension toggle)
  - `jupyter_lab_config.json` -- Lab UI settings (disabled extensions, default URL)

- **Helm values:**
  - `enabled` -- gates entire subchart (default: `false`)
  - `jupyterHome` -- writable HOME for arbitrary UID (default: `/tmp/jupyter-home`)
  - `notebookRootDir` -- Jupyter server root directory (default: `/tmp/jupyter-home/notebooks`)
  - `notebookArgsExtra` -- additional CLI args (default: opens `yolo_training.ipynb`)
  - `jupyterGit.enabled` -- toggle JupyterLab Git extension (default: `false`)
  - `trainingExample.seedOnStartup` -- copy bundled notebook into root on startup (default: `true`)
  - `imageRegistry` -- container registry prefix (default: `quay.io/rh-ai-quickstart`)
  - `resources.limits.memory` -- set to `8Gi` for YOLO training memory requirements
  - `workspace.storage.size` -- PVC size (default: `1Gi`)
  - `workspace.storage.storageClassName` -- optional, needed when no default StorageClass exists
  - `auth.existingSecretName` -- reference an existing Secret instead of chart-generated one
  - `auth.token` -- demo token value (default: `changeme`)
  - `route.enabled` -- create OpenShift Route (default: `true`)
  - `route.tls.termination` -- TLS mode (default: `edge`)

## Known Gotchas

- **PVC permission denied under arbitrary UID:** OpenShift's restricted-v2 SCC rejects `fsGroup: 100` (the default in docker-stacks images). The chart works around this by using `/tmp/jupyter-home/notebooks` as `notebookRootDir` and symlinking the PVC as `pvc-workspace`. To use PVC directly as root, set `podSecurityContext.fsGroup` to a group allowed by your namespace SCC supplemental range. (Source: `values.yaml` comments and `NOTES.txt`)

- **`/home/jovyan` mode 700 blocks arbitrary UID:** The docker-stacks base image often leaves `/home/jovyan` with mode 700, so `pathlib.resolve()` on terminal cwd raises `PermissionError`. The Dockerfile explicitly sets `chmod 755 /home/jovyan`. (Source: `training/jupyter-training/Dockerfile` comment)

- **jupyterlab-git removal required:** Disabling the Git extension via Helm config (`/etc/jupyter`) does not reliably override the merged conda config, so Lab still shows Git errors. The Dockerfile uninstalls the package entirely with `pip uninstall -y jupyterlab-git`. Re-enabling requires rebuilding the image and setting `jupyterGit.enabled=true`. (Source: `Dockerfile` comment)

- **Default auth token is `changeme`:** Both the subchart `values.yaml` and the parent chart ship `token: changeme`. Production deployments must override via `auth.existingSecretName` or set a strong value in `auth.token`. (Source: `training/README.md` release note)

- **PVC stays Pending with WaitForFirstConsumer:** If no default StorageClass exists, set `workspace.storage.storageClassName` to match an available class (e.g., `gp3`, `managed-csi`). Also check that pod scheduling is not blocked by SCC rejection of `fsGroup`. (Source: `NOTES.txt`)

- **YOLO training memory:** Training needs significantly more memory than basic Jupyter usage. The chart sets `resources.limits.memory: 8Gi` to avoid OOMKilled during `model.train()`. (Source: `values.yaml` comment)

- **Notebook workspace root must match cwd:** The notebook uses `WORKSPACE_ROOT = Path.cwd()` and expects `upload/` as a sibling. On OpenShift, open the notebook from `training/yolo_training.ipynb` so the kernel cwd is the `training` folder. (Source: `training/README.md`)

- **Route timeout annotation:** The Route includes `haproxy.router.openshift.io/timeout: 3600s` to prevent long-running training sessions from being terminated by the router. (Source: `route.yaml`)

## Testing Notes

- Verify the notebook is seeded on first start: check that `yolo_training.ipynb` exists at `notebookRootDir`
- Verify PVC workspace symlink: `pvc-workspace` should appear in the file browser pointing to `/home/jovyan/work`
- Retrieve the auth token from the Secret and confirm Lab login works
- Check `oc get route` for the Jupyter URL (edge TLS by default)
- Run a small training pass (few epochs) to verify memory limits are sufficient and `ultralytics` works

## Related Patterns

- Parent chart wiring: `ppe-compliance-monitor` includes this as a conditional subchart via `file://../jupyter-training`
- Build targets: `make build-jupyter-training` and `make push-jupyter-training` in repo Makefile
