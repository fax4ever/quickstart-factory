---
name: tekton-camel-export-quarkus-buildah-pipeline
description: Tekton pipeline converting Camel YAML DSL routes to Quarkus via camel export, Maven build, and Buildah image push to internal registry
summary: "Builds container images from Apache Camel YAML DSL routes via a six-task Tekton pipeline: workspace init (root chmod -R 777), git-clone, permission fix, camel export converting YAML DSL to a Quarkus Maven project with parameterized GAV/deps, Maven package on ubi10/openjdk-21 with Red Hat GA repo (-Dcom.redhat.xpaas.repo.redhatga), Dockerfile injection from base-image-config-quarkus ConfigMap, and Buildah push to the internal registry (TLS_VERIFY=false, 1Gi PVC workspace). Use when Camel routes are defined as YAML DSL requiring compilation into runnable Quarkus JVM containers on OpenShift; requires a pre-built camel-launcher base image (default version 4.18.1.redhat-00016) and cluster-scoped buildah/git-clone tasks resolved via Tekton cluster resolver from the openshift-pipelines namespace. Critical config: camel export --runtime=quarkus --fresh --gav=<coords> --dep=<deps> with runtime-version defaulting to Quarkus 3.33.2.redhat-00002; each app parameterizes its own GAV and dependency list (e.g., camel-jms, camel-observability-services, mvn:org.apache.activemq:artemis-jakarta-client-all). Gotchas: JAVA_OPTS must set -Dcamel.jbang.quarkusVersion alongside the --quarkus-version CLI flag or export produces wrong version; workspace init runs as root (runAsUser: 0) with chmod 777 because tasks alternate UIDs (0, 185, 65532); the Dockerfile is stored in a ConfigMap not the source repo, decoupling base image config from application source."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [tekton, camel, quarkus, maven, buildah]
  ai_pattern: [data-pipeline]
  platform: [openshift]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Tekton 'build' pipeline with custom camel-launcher base image, camel export to Quarkus, Maven package, ConfigMap-sourced Dockerfile, and Buildah push to internal registry"
    approach: "A"
---

# Tekton Camel Export to Quarkus Build Pipeline

## Overview

A Tekton pipeline pattern that builds container images from Apache Camel YAML DSL routes by first converting them to a Quarkus Maven project using `camel export`, then compiling with Maven, injecting a Dockerfile from a Kubernetes ConfigMap, and finally building the container image with Buildah. This is a unique build flow because source code is not traditional Java/Python but Camel YAML route definitions that must be exported to a compilable project first.

## Pattern Description

The pipeline has six sequential tasks: workspace initialization, git clone, permission fix, Camel export (converting YAML DSL to a Quarkus Maven project with specified dependencies and GAV coordinates), Maven build (`./mvnw clean package`), Dockerfile injection from a ConfigMap, and Buildah image build/push to the OpenShift internal registry. A separate `camel-launcher` base image containing the Camel CLI JAR is built first as a prerequisite and used to run the `camel export` command.

## Implementation

### Pipeline Task Chain

The `build` pipeline defines a six-step task chain:

```
init-workspace -> git-clone -> fix-workspace -> camel-export
  -> maven-build -> prepare-dockerfile -> build-image
```

### Camel Export Task

The `camel-export` task uses a pre-built camel-launcher image to convert YAML DSL routes to a Quarkus project:

```yaml
# deploy/tasks/11-camel-export.yaml
- name: export
  image: $(params.camel-image)
  workingDir: $(workspaces.source.path)/$(params.app-path)
  script: |
    #!/usr/bin/env bash
    set -euo pipefail
    EXPORT_DIR="$(workspaces.source.path)/$(params.export-dir)"
    EXTRA_ARGS=""
    VERSION="$(params.runtime-version)"
    if [ -n "${VERSION}" ]; then
      EXTRA_ARGS="--quarkus-version=${VERSION}"
      export JAVA_OPTS="${JAVA_OPTS:-} -Dcamel.jbang.quarkusVersion=${VERSION}"
    fi
    DEP_ARGS=""
    DEPS="$(params.deps)"
    if [ -n "${DEPS}" ]; then
      DEP_ARGS="--dep=${DEPS}"
    fi
    CMD="camel export --runtime=quarkus ${EXTRA_ARGS} ${DEP_ARGS} --gav=$(params.gav) --fresh --dir=${EXPORT_DIR}"
    eval "${CMD}"
```

### Parameterized Dependency Injection

Each application specifies its Maven GAV and additional Camel/Quarkus dependencies as pipeline parameters:

```yaml
# deploy/pipeline/build-apps.yaml (correlator example)
APP_NAME="correlator"
GAV="com.example:correlator:1.0.0"
DEPS="camel-jms,camel-observability-services,mvn:org.apache.camel.quarkus:camel-quarkus-platform-http,mvn:org.apache.activemq:artemis-jakarta-client-all:2.44.0,mvn:io.quarkiverse.messaginghub:quarkus-pooled-jms:2.12.0"
```

### ConfigMap-Sourced Dockerfile

Instead of including a Dockerfile in the source repo, the pipeline reads it from a ConfigMap at build time:

```yaml
# deploy/tasks/12-prepare-dockerfile.yaml
- name: write-dockerfile
  image: image-registry.openshift-image-registry.svc:5000/openshift/cli:latest
  script: |
    #!/usr/bin/env bash
    set -euo pipefail
    CONFIG_MAP="base-image-config-quarkus"
    DEST="$(workspaces.source.path)/$(params.export-dir)/$(params.dockerfile-path)"
    mkdir -p "$(dirname "${DEST}")"
    oc get configmap "${CONFIG_MAP}" -o jsonpath='{.data.Dockerfile}' > "${DEST}"
```

### Maven Build with Red Hat GA Repository

The Maven build step uses a UBI-based OpenJDK image and activates the Red Hat GA repository:

```yaml
# deploy/pipeline/build.yaml (maven-build inline taskSpec)
- name: maven-goals
  image: registry.access.redhat.com/ubi10/openjdk-21:latest
  workingDir: $(workspaces.source.path)/export
  script: |
    #!/usr/bin/env bash
    set -euo pipefail
    ./mvnw clean package -Dcom.redhat.xpaas.repo.redhatga
```

### Cluster Task References via Resolver

The pipeline references cluster-scoped Tekton tasks (git-clone, buildah) using the resolver pattern:

```yaml
# deploy/pipeline/build.yaml
taskRef:
  resolver: cluster
  params:
    - name: kind
      value: task
    - name: name
      value: buildah
    - name: namespace
      value: openshift-pipelines
```

## Configuration

- **Key settings:** `camel-launcher-version` (default: `4.18.1.redhat-00016`), `runtime-version` (Quarkus version, default: `3.33.2.redhat-00002`), `gav` (Maven coordinates per app), `deps` (comma-separated Camel dependencies)
- **Defaults:** Images pushed to `image-registry.openshift-image-registry.svc:5000/<namespace>/<app-name>:latest`; TLS_VERIFY set to `false` for internal registry; workspace uses 1Gi PVC
- **Dependencies:** OpenShift Pipelines operator installed; `buildah` and `git-clone` cluster tasks available in `openshift-pipelines` namespace; `base-image-config-quarkus` ConfigMap must exist

## Gotchas

- The `camel export --fresh` flag forces a clean export without caching, ensuring reproducible builds at the cost of longer build times
- The `JAVA_OPTS` environment variable for Quarkus version must be set alongside the `--quarkus-version` flag -- the `camel export` task sets both via `-Dcamel.jbang.quarkusVersion` in JAVA_OPTS
- The workspace permission fix task (`init-workspace`) runs as root (`runAsUser: 0`) and `chmod -R 777` on the workspace -- this is needed because different task steps run as different users (root for init, 185 for OpenJDK, 65532 for fix-permissions)
- The Dockerfile is stored externally in the `base-image-config-quarkus` ConfigMap rather than in the source repo -- this decouples the base image configuration from application source

## Related Patterns

- `tekton-parallel-sub-pipelinerun-fan-out.md` -- the orchestrator pipeline that invokes this build pipeline for each component
- `configmap-stored-dockerfile-quarkus-jvm-runtime.md` -- the Dockerfile ConfigMap pattern used by the prepare-dockerfile task
- `tekton-camel-launcher-base-image-build.md` -- the prerequisite task that builds the camel-launcher image
