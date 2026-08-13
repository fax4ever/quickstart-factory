---
name: configmap-stored-dockerfile-quarkus-jvm-runtime
description: Quarkus JVM runtime Dockerfile stored in a ConfigMap and injected into Tekton build workspace at build time
summary: "Decouples the Quarkus JVM runtime Dockerfile from application source by storing it in ConfigMap `base-image-config-quarkus`, designed for Camel YAML DSL routes where `camel export` generates a Quarkus Maven project but no Dockerfile exists in the repo. Use when multiple components share identical Quarkus fast-jar build artifacts and operators need to update the base image independently — a Tekton `prepare-dockerfile` task extracts content via `oc get configmap -o jsonpath='{.data.Dockerfile}'` and writes it to `src/main/docker/Dockerfile.jvm` before Buildah builds the image. The Dockerfile uses `ubi10/openjdk-21-runtime:latest` with `COPY --chown=185` directives, `USER 185` for OpenShift restricted SCC, fast-jar layout in `/deployments/`, entrypoint via Red Hat's `run-java.sh`, and `JAVA_OPTS_APPEND` overridable by Helm deployment templates. The ConfigMap must be applied before the pipeline runs, the `oc` CLI must be available in the task step image, and `ubi10/openjdk-21-runtime` (runtime-only) must not be confused with `ubi10/openjdk-21` (full JDK) used in the Maven build task."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [tekton, quarkus, buildah]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "base-image-config-quarkus ConfigMap containing a UBI10 OpenJDK 21 runtime Dockerfile, extracted by a Tekton task via oc get configmap jsonpath and written to the build workspace"
    approach: "A"
---

# ConfigMap-Stored Dockerfile for Quarkus JVM Runtime

## Overview

A deployment pattern where the Dockerfile for building application container images is stored in a Kubernetes ConfigMap rather than in the source repository. A Tekton task reads the Dockerfile content from the ConfigMap via `oc get configmap` and writes it to the build workspace before the Buildah image build step. This decouples the base image and build recipe from the application source code.

## Pattern Description

The pattern addresses a scenario where the application source code is Camel YAML DSL routes (not a standard Java project with a Dockerfile). The `camel export` command generates a Quarkus Maven project, but the Dockerfile for the final runtime image is managed separately. Storing it in a ConfigMap allows operators to update the base image or build recipe without modifying the application repo, and multiple applications can share the same Dockerfile definition.

## Implementation

### ConfigMap Definition

The Dockerfile is stored as a data key in the ConfigMap, applied before the build pipeline runs:

```yaml
# deploy/resources/configmaps/base-image-config-quarkus.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: base-image-config-quarkus
data:
  Dockerfile: |
    FROM registry.access.redhat.com/ubi10/openjdk-21-runtime:latest
    ENV LANGUAGE='en_US:en'
    COPY --chown=185 target/quarkus-app/lib/ /deployments/lib/
    COPY --chown=185 target/quarkus-app/*.jar /deployments/
    COPY --chown=185 target/quarkus-app/app/ /deployments/app/
    COPY --chown=185 target/quarkus-app/quarkus/ /deployments/quarkus/
    EXPOSE 8080
    USER 185
    ENV JAVA_OPTS_APPEND="-Dquarkus.http.host=0.0.0.0 -Djava.util.logging.manager=org.jboss.logmanager.LogManager"
    ENV JAVA_APP_JAR="/deployments/quarkus-run.jar"
    ENTRYPOINT [ "/opt/jboss/container/java/run/run-java.sh" ]
```

### Tekton Task Extracting Dockerfile

The `prepare-dockerfile` task reads the ConfigMap content and writes it to the expected path:

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

### Buildah Reference

The subsequent Buildah task references the Dockerfile at the standard Quarkus path:

```yaml
# deploy/pipeline/build.yaml (build-image task)
params:
  - name: DOCKERFILE
    value: src/main/docker/Dockerfile.jvm
  - name: CONTEXT
    value: .
```

## Configuration

- **Key settings:** ConfigMap name `base-image-config-quarkus`; Dockerfile path defaults to `src/main/docker/Dockerfile.jvm`; base image is `registry.access.redhat.com/ubi10/openjdk-21-runtime:latest`
- **Defaults:** User ID 185 (standard Red Hat OpenJDK container user); Quarkus fast-jar layout in `/deployments/`; entrypoint via Red Hat's `run-java.sh` script
- **Dependencies:** The ConfigMap must be applied to the namespace before the Tekton pipeline runs; the `oc` CLI must be available in the task step image

## Gotchas

- The Dockerfile uses `ubi10/openjdk-21-runtime` (runtime-only image) not the full JDK -- the Maven build happens in a separate Tekton task using `ubi10/openjdk-21` (full JDK), and only the built artifacts are consumed by this Dockerfile
- The file ownership is set to UID 185 (`--chown=185`) which is the standard user in Red Hat OpenJDK containers -- this matches the `USER 185` directive and is required for OpenShift's restricted SCC
- The `JAVA_OPTS_APPEND` variable is set in the Dockerfile but can be overridden by the Helm chart's deployment template, which appends additional JVM flags (Netty workaround, truststore path)
- All three application components (correlator, analyzer, ui-console) share this same Dockerfile since they all produce Quarkus JVM fast-jar artifacts with the same directory structure

## Related Patterns

- `tekton-camel-export-quarkus-buildah-pipeline.md` -- the pipeline that consumes this Dockerfile
- `helm-range-loop-multi-component-files-get-properties.md` -- the Helm chart that overrides JAVA_OPTS_APPEND at deploy time
