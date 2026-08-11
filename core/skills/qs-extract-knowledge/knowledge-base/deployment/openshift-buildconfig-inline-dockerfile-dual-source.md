---
name: openshift-buildconfig-inline-dockerfile-dual-source
description: OpenShift BuildConfig with inline Dockerfile for cluster builds, toggled vs default Quay image pull
summary: "Provides dual image sourcing for OpenShift quickstart components — default Quay pull (quay.io/rh-ai-quickstart/<name>:latest via values.yaml) vs on-cluster BuildConfig with inline multi-stage Dockerfile in spec.source.dockerfile, toggled by Makefile BUILD_* boolean flags using ifeq conditionals. Set BUILD_<COMPONENT>=true to switch to cluster-build mode; each component ships buildconfig.yaml (inline Dockerfile or binary source.type for data-loaders), imagestream.yaml (output target), and values.yaml with Quay defaults. On cluster-build, Makefile runs oc apply for ImageStream/BuildConfig then oc start-build --from-dir --follow, and overrides Helm with --set image.repository=image-registry.openshift-image-registry.svc:5000/$(NAMESPACE)/<name> --set image.tag=latest --set image.pullPolicy=Always. Gotchas: --from-dir context varies per component (parent dir for backend/UI needing packages/ or apps/ paths, current dir for co-located data-loader), inline Dockerfiles skip .dockerignore uploading full build context, uv venv shebangs require sed fixup between builder and runtime stage paths, triggers must be empty ([]) to prevent auto-rebuilds, and builder service account must pre-exist in namespace."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, nodejs]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "4 BuildConfigs (backend, UI, pg-airman-mcp, data-loader) with inline Dockerfiles, toggled by BUILD_* flags"
    approach: "A"
---

# OpenShift BuildConfig with Inline Dockerfile and Dual-Source Toggle

## Overview

This pattern provides two image sourcing strategies for each component: a pre-built image pulled from Quay (the default) and an on-cluster build using OpenShift BuildConfig resources with inline Dockerfiles. Makefile boolean flags (`BUILD_*`) toggle between the two modes, with the cluster-build path creating ImageStream and BuildConfig resources, triggering a build, then pointing the Helm chart at the internal registry image.

## Pattern Description

Each buildable component ships three non-template resources alongside its Helm chart: a `buildconfig.yaml` (containing a full inline Dockerfile in the `spec.source.dockerfile` field), an `imagestream.yaml` (output target), and the values.yaml default pointing to `quay.io/rh-ai-quickstart/<name>:latest`. When `BUILD_<COMPONENT>=true`, the Makefile applies the ImageStream and BuildConfig via `oc apply`, starts a build via `oc start-build`, then overrides the Helm image repository to the internal registry address.

## Implementation

### BuildConfig with Inline Dockerfile

The entire Dockerfile is embedded in the BuildConfig YAML rather than referencing a file path:

```yaml
# helm/copilot-backend/buildconfig.yaml
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: copilot-backend
spec:
  output:
    to:
      kind: ImageStreamTag
      name: copilot-backend:latest
  source:
    type: Dockerfile
    dockerfile: |
      FROM python:3.12-slim AS builder
      RUN pip install --no-cache-dir uv
      WORKDIR /app
      COPY packages/copilot/pyproject.toml /app/
      COPY packages/copilot/README.md /app/
      COPY packages/copilot/src /app/src
      RUN uv venv /tmp/copilot/.venv && \
          . /tmp/copilot/.venv/bin/activate && \
          uv pip install .
      FROM python:3.12-slim
      COPY --from=builder /tmp/copilot/.venv /app/.venv
      COPY --from=builder /app/src /app/src
      RUN find /app/.venv/bin -type f -exec sed -i \
          's|#!/tmp/copilot/.venv/bin/python|#!/app/.venv/bin/python|g' {} \;
      RUN chmod -R g=u /app && chgrp -R 0 /app
      EXPOSE 8080
      CMD ["/app/.venv/bin/python", "-m", "copilot"]
  strategy:
    type: Docker
    dockerStrategy:
      from:
        kind: DockerImage
        name: python:3.12-slim
  triggers: []
```

### Binary Build for Data Loader

The pgvector data-loader uses a binary build strategy, uploading the local directory to OpenShift:

```yaml
# helm/pgvector/buildconfig.yaml
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: pgvector-data-loader
spec:
  output:
    to:
      kind: ImageStreamTag
      name: pgvector-data-loader:latest
  source:
    type: Binary
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: Dockerfile.data-loader
  triggers: []
```

### Makefile Toggle Pattern

```makefile
# helm/Makefile (build-copilot-backend-image and copilot-backend-install)
build-copilot-backend-image:
	@oc apply -f $(COPILOT_BACKEND_CHART)/imagestream.yaml -n $(NAMESPACE)
	@oc apply -f $(COPILOT_BACKEND_CHART)/buildconfig.yaml -n $(NAMESPACE)
	@oc start-build copilot-backend --from-dir=.. --follow -n $(NAMESPACE)

copilot-backend-install:
ifeq ($(BUILD_COPILOT_BACKEND),true)
	@$(MAKE) build-copilot-backend-image NAMESPACE=$(NAMESPACE)
	# Override image to internal registry
	helm ... --set image.repository=image-registry.openshift-image-registry.svc:5000/$(NAMESPACE)/copilot-backend \
	         --set image.tag=latest --set image.pullPolicy=Always
else
	# Use default Quay image from values.yaml
	helm ... --timeout 5m
endif
```

### Internal Registry Image Override

When cluster-built, the Helm install overrides three image values:

```makefile
--set image.repository=image-registry.openshift-image-registry.svc:5000/$(NAMESPACE)/copilot-backend \
--set image.tag=latest \
--set image.pullPolicy=Always
```

## Configuration

- **Key settings:** `BUILD_COPILOT_UI`, `BUILD_PG_AIRMAN_MCP`, `BUILD_COPILOT_BACKEND`, `BUILD_DATA_LOADER` -- all default to `false`
- **Defaults:** When flags are false, images pull from `quay.io/rh-ai-quickstart/<name>:latest`; when true, images build from source and push to the namespace-scoped internal registry
- **Dependencies:** Cluster builds require the builder service account in the namespace (the Makefile's `namespace` target waits for it) and the internal image registry at `image-registry.openshift-image-registry.svc:5000`

## Gotchas

- The copilot-backend BuildConfig uses `--from-dir=..` (parent directory) as the build context because the Dockerfile copies from `packages/copilot/` which is above the `helm/` directory (see `helm/Makefile` line 578)
- The copilot-ui BuildConfig similarly uses `--from-dir=../` because it copies from `apps/ui/` (see `helm/Makefile` line 783)
- The pgvector data-loader uses `--from-dir=.` (the pgvector chart directory itself) since the data CSV files and scripts are co-located with the chart (see `helm/Makefile` line 316)
- Inline Dockerfiles in BuildConfig YAML do not benefit from `.dockerignore` -- the entire `--from-dir` contents are uploaded as build context
- The venv shebang fix (`sed -i 's|#!/tmp/copilot/.venv/bin/python|#!/app/.venv/bin/python|g'`) is necessary because uv creates shebangs pointing to the builder stage path, not the runtime stage path (see `helm/copilot-backend/buildconfig.yaml`)
- Build triggers are explicitly empty (`triggers: []`) to prevent automatic rebuilds -- all builds are manually triggered via `oc start-build`

## Related Patterns

- `helm-independent-subcharts-no-umbrella.md` -- the chart structure these BuildConfigs deploy into
- `container-build-clone-patch-third-party-mcp.md` -- the pg-airman-mcp BuildConfig which clones and patches a third-party repo
