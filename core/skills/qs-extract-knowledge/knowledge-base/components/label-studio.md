---
name: label-studio
description: "Label Studio annotation platform deployed as optional Helm subchart with PostgreSQL backend and PVC storage"
summary: "Provides an open-source annotation UI for labeling training data (e.g., YOLO bounding boxes in multimodal-compliance-monitor), deployed as a conditional Helm subchart (`file://../label-studio` aliased `labelStudio`, gated by `labelStudio.enabled`) that shares PostgreSQL with the main application via `POSTGRE_*` env vars. Enable via `make deploy-labelstudio` or `make deploy-openvino-labelstudio` when a quickstart needs a data-labeling workflow; leave `labelStudio.enabled` false to skip entirely with zero rendered resources. Critical config: chart auto-derives `LABEL_STUDIO_HOST` and `CSRF_TRUSTED_ORIGINS` from `route.host`, resolves `POSTGRE_HOST` to `<release>-<chartName>-postgresql`, manages Django `SECRET_KEY` via `auth.existingSecretName` or `auth.secretKey`, and mounts a 5Gi PVC at `/label-studio/data`. Gotchas: `_helpers.tpl` defaults fullname to `ppe-compliance-monitor` so `global.chartName` must be set when reusing in another quickstart; database host auto-resolution breaks if PostgreSQL naming diverges from `<release>-<chartName>-postgresql`; route name truncated to 30 chars risks collisions with long release names; Helm uses `heartexlabs/label-studio:latest` while podman-compose pins a digest, causing local-vs-cluster version drift."
metadata:
  type: component
tags:
  tech_stack: [label-studio, django, postgresql, helm]
  ai_pattern: [data-pipeline, multimodal]
  platform: [openshift, kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Optional Label Studio annotation UI for creating and refining YOLO training datasets, sharing PostgreSQL with the main app"
    approach: "A"
---

# Label Studio

## Overview

Label Studio is an open-source data annotation platform used in quickstart architectures to provide a UI for labeling training data (e.g., bounding boxes for object detection). In the multimodal-compliance-monitor quickstart it is deployed as an **optional** Helm subchart that shares the same PostgreSQL instance as the main application. It is gated behind `labelStudio.enabled` so users who do not need annotation can skip it entirely.

## Tech Stack & Dependencies

- **Runtime:** Django-based application (from upstream `heartexlabs/label-studio` image)
- **Container image:** `docker.io/heartexlabs/label-studio:latest`
- **Key dependencies:** PostgreSQL (shared with the main application stack)
- **Helm subchart:** Local file dependency (`file://../label-studio`) aliased as `labelStudio` with condition `labelStudio.enabled`
- **Storage:** PersistentVolumeClaim (5Gi default) mounted at `/label-studio/data`

## Key Patterns

### Optional Subchart Gated by Condition

Label Studio is wired as a conditional Helm subchart dependency. Every template is wrapped with `{{- if .Values.enabled }}` so nothing is rendered unless `labelStudio.enabled` is set to `true`.

```yaml
# deploy/helm/ppe-compliance-monitor/Chart.yaml
dependencies:
  - name: label-studio
    version: "0.1.x"
    repository: file://../label-studio
    alias: labelStudio
    condition: labelStudio.enabled
```

The Makefile exposes dedicated deploy targets that toggle the flag:

```makefile
# Makefile
LABEL_STUDIO_ENABLED ?=

deploy-labelstudio:
	$(MAKE) deploy LABEL_STUDIO_ENABLED=true

deploy-openvino-labelstudio:
	$(MAKE) deploy RUNTIME_TYPE=openvino LABEL_STUDIO_ENABLED=true
```

### Shared PostgreSQL Database

Label Studio connects to the same PostgreSQL instance used by the rest of the quickstart, using Label Studio's native `POSTGRE_*` environment variables. The host defaults to the release-scoped PostgreSQL service name via a Helm template expression:

```yaml
# deploy/helm/label-studio/templates/deployment.yaml
- name: POSTGRE_HOST
  value: {{ .Values.database.host | default (printf "%s-%s-postgresql"
    .Release.Name (default "ppe-compliance-monitor" .Values.global.chartName)) | quote }}
- name: POSTGRE_PORT
  value: {{ .Values.database.port | quote }}
- name: POSTGRE_NAME
  value: {{ .Values.database.name | quote }}
```

### OpenShift Route with Separate Hostname

The chart creates an OpenShift Route with a distinct hostname pattern (`<release>-ls-<namespace>.<domain>`) to avoid collision with the main application route. The route name is truncated to 30 characters:

```yaml
# deploy/helm/label-studio/templates/route.yaml
metadata:
  name: {{ printf "%s-ls" .Release.Name | trunc 30 | trimSuffix "-" }}
```

The Makefile constructs the Label Studio route host separately:

```makefile
# Makefile
ls_host="$(HELM_RELEASE)-ls-$(NAMESPACE).$$domain"
# ...
$${ls_host:+--set labelStudio.route.host=$$ls_host}
```

### CSRF and Host Configuration

The deployment template auto-derives `LABEL_STUDIO_HOST` and `CSRF_TRUSTED_ORIGINS` from the route host when explicit values are not set. This avoids CSRF errors when accessing Label Studio through the OpenShift route:

```yaml
# deploy/helm/label-studio/templates/deployment.yaml
{{- if .Values.app.host }}
- name: LABEL_STUDIO_HOST
  value: {{ .Values.app.host | quote }}
{{- else if .Values.route.host }}
- name: LABEL_STUDIO_HOST
  value: {{ printf "https://%s" .Values.route.host | quote }}
{{- end }}
{{- if .Values.app.csrfTrustedOrigins }}
- name: CSRF_TRUSTED_ORIGINS
  value: {{ .Values.app.csrfTrustedOrigins | quote }}
{{- else if .Values.route.host }}
- name: CSRF_TRUSTED_ORIGINS
  value: {{ printf "https://%s" .Values.route.host | quote }}
{{- end }}
```

### Django SECRET_KEY via Kubernetes Secret

The chart supports providing a Django `SECRET_KEY` either from an existing Kubernetes secret or by generating one from `auth.secretKey`. If `auth.existingSecretName` is not set but `auth.secretKey` is, the chart creates a Secret resource:

```yaml
# deploy/helm/label-studio/templates/secret.yaml
{{- if and .Values.enabled (not .Values.auth.existingSecretName) .Values.auth.secretKey }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "label-studio.fullname" . }}-auth
type: Opaque
stringData:
  SECRET_KEY: {{ .Values.auth.secretKey | quote }}
{{- end }}
```

## Configuration

- **Environment variables:**
  - `DJANGO_DB`: Set to `default` (hardcoded)
  - `USE_X_FORWARDED_HOST`: Set to `true` for reverse proxy support
  - `LABEL_STUDIO_HOST`: Auto-derived from `route.host` or set via `app.host`
  - `CSRF_TRUSTED_ORIGINS`: Auto-derived from `route.host` or set via `app.csrfTrustedOrigins`
  - `SECRET_KEY`: Optional Django secret key from Kubernetes Secret
  - `POSTGRE_HOST`, `POSTGRE_PORT`, `POSTGRE_NAME`, `POSTGRE_USER`, `POSTGRE_PASSWORD`: PostgreSQL connection parameters
- **Config files:** None (all configuration via environment variables)
- **Helm values:**
  - `labelStudio.enabled`: Toggle the entire subchart (default `false` in subchart, `true` in parent values)
  - `labelStudio.route.host`: OpenShift route hostname (auto-set by Makefile)
  - `labelStudio.storage.size`: PVC size (default `5Gi`)
  - `labelStudio.database.*`: PostgreSQL connection overrides
  - `labelStudio.auth.existingSecretName` / `labelStudio.auth.secretKey`: Django SECRET_KEY management

## Known Gotchas

- **Fullname defaults to `ppe-compliance-monitor`:** The `_helpers.tpl` uses `default "ppe-compliance-monitor"` as the fallback chart name in the fullname template. When reusing this subchart in another quickstart, `global.chartName` must be set or resource names will reference the wrong application (see `_helpers.tpl` line 16).
- **Database host auto-resolution assumes PostgreSQL naming convention:** The `POSTGRE_HOST` default is `<release>-<chartName>-postgresql`. If the PostgreSQL service uses a different naming pattern, `database.host` must be set explicitly.
- **Route name truncation to 30 chars:** The route name is `<release>-ls` truncated to 30 characters. Long release names could cause collisions or unreadable route names.
- **Podman-compose uses pinned digest while Helm uses `latest` tag:** The local dev setup (`deploy/local/podman-compose.yaml`) pins Label Studio to a specific image digest, while the Helm chart defaults to `latest`. This could cause version mismatches between local and cluster deployments.

## Testing Notes

- Deploy with `make deploy-labelstudio` or `make deploy-openvino-labelstudio` to enable the annotation UI
- Verify the Label Studio pod is running and the PVC is bound
- Access Label Studio via the OpenShift route (the Makefile auto-sets the hostname)
- For local development, Label Studio is available at `http://localhost:8082` via podman-compose
- Confirm PostgreSQL connectivity by checking that Label Studio loads without database errors

## Related Patterns

- PostgreSQL component (`pgvector.md`) -- shared database instance
- MinIO component (`minio.md`) -- used alongside Label Studio for object storage in the same quickstart
