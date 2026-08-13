---
name: helm-initcontainer-openshift-service-ca-jks-truststore
description: Init container building JKS truststore from OpenShift service-ca.crt annotation-injected ConfigMap for internal TLS
summary: "Enables Java/Quarkus pods to make HTTPS calls to cluster-internal KServe InferenceService endpoints whose TLS is signed by the OpenShift service CA, by building a JKS truststore in a conditional Helm init container. Use for JVM workloads calling service-CA-signed internal endpoints — enable per-component via `serviceCa.enabled: true` and `serviceCa.configMap` in Helm values.yaml; requires the OpenShift service CA operator and a deploy-script-created ConfigMap annotated `service.beta.openshift.io/inject-cabundle=true` before Helm install. The init container copies `$JAVA_HOME/lib/security/cacerts` from the application image, runs `keytool -import -trustcacerts -alias openshift-service-ca`, writes to an emptyDir truststore volume, and the main container consumes it via `JAVA_OPTS_APPEND` with `-Djavax.net.ssl.trustStore=/tmp/truststore/truststore.jks -Djavax.net.ssl.trustStorePassword=changeit`. The init container reuses the app image so images must be built before Helm install, the `changeit` truststore password is hardcoded and not configurable, and the `[ -f /service-ca/service-ca.crt ]` guard silently passes when the cert is missing — the pod starts but TLS calls to internal services fail at runtime."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, quarkus]
  ai_pattern: [model-serving]
  platform: [openshift, kserve]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Conditional initContainer in Helm Deployment template that copies the JDK cacerts, imports the OpenShift service CA cert via keytool, and mounts the truststore for HTTPS calls to internal KServe endpoints"
    approach: "A"
---

# Init Container for OpenShift Service CA JKS Truststore

## Overview

A Helm deployment pattern that uses an init container to build a JKS truststore containing the OpenShift service CA certificate. This enables Java/Quarkus applications to make HTTPS calls to cluster-internal services (like KServe InferenceService endpoints) that use certificates signed by the OpenShift service CA. The init container copies the JDK's default cacerts, imports the service CA certificate via `keytool`, and shares the result via an emptyDir volume.

## Pattern Description

OpenShift's service CA signs TLS certificates for internal services. Java applications need these certificates in a JKS truststore to make HTTPS calls to internal endpoints. The pattern uses an annotation-injected ConfigMap (`service.beta.openshift.io/inject-cabundle=true`) to get the CA certificate, then an init container imports it into a copy of the JDK's cacerts file. The main container references this truststore via JVM system properties. The entire pattern is conditional -- only components that declare `serviceCa.enabled: true` get the init container.

## Implementation

### Service CA ConfigMap Creation

The deploy script creates an empty ConfigMap and annotates it to trigger service CA injection:

```bash
# create.sh - Step 9: Create service CA bundle
oc create configmap service-ca-bundle --dry-run=client -o yaml | oc apply -f -
oc annotate configmap service-ca-bundle service.beta.openshift.io/inject-cabundle=true --overwrite
```

### Conditional Init Container in Helm Template

The init container is only rendered for components with `serviceCa.enabled: true`:

```yaml
# chart/templates/deployment.yaml
{{- if and $component.serviceCa $component.serviceCa.enabled }}
initContainers:
  - name: build-truststore
    image: {{ $.Values.imageRegistry }}/{{ $.Values.namespace }}/{{ $name }}:latest
    command: ['sh', '-c']
    args:
      - |
        cat "$JAVA_HOME/lib/security/cacerts" > /tmp/truststore/truststore.jks
        chmod 664 /tmp/truststore/truststore.jks
        if [ -f /service-ca/service-ca.crt ]; then
          keytool -import -trustcacerts -alias openshift-service-ca \
            -file /service-ca/service-ca.crt \
            -keystore /tmp/truststore/truststore.jks \
            -storepass changeit -noprompt
        fi
    volumeMounts:
      - name: truststore
        mountPath: /tmp/truststore
      - name: service-ca
        mountPath: /service-ca
{{- end }}
```

### JVM System Properties for Truststore

The main container's `JAVA_OPTS_APPEND` environment variable is conditionally extended with truststore properties:

```yaml
# chart/templates/deployment.yaml
- name: JAVA_OPTS_APPEND
  value: "{{ if $.Values.nettyWorkaround }}{{ $.Values.javaOptsAppend }}{{ end }}{{ if and $component.serviceCa $component.serviceCa.enabled }} -Djavax.net.ssl.trustStore=/tmp/truststore/truststore.jks -Djavax.net.ssl.trustStorePassword=changeit{{ end }}"
```

### Volume Definitions

Two volumes support the pattern -- an emptyDir for the truststore and a ConfigMap for the CA cert:

```yaml
# chart/templates/deployment.yaml
{{- if and $component.serviceCa $component.serviceCa.enabled }}
- name: truststore
  emptyDir: {}
- name: service-ca
  configMap:
    name: {{ $component.serviceCa.configMap }}
{{- end }}
```

### Values Configuration

The service CA feature is enabled per-component in values.yaml:

```yaml
# chart/values.yaml (analyzer component)
analyzer:
  serviceCa:
    enabled: true
    configMap: service-ca-bundle
```

## Configuration

- **Key settings:** `serviceCa.enabled` (boolean, per-component); `serviceCa.configMap` (name of the CA bundle ConfigMap); truststore password is hardcoded as `changeit` (JDK default)
- **Defaults:** Only the `analyzer` component enables service CA in this quickstart -- it needs TLS for calls to KServe model endpoints in the `sandbox-shared-models` namespace
- **Dependencies:** The `service-ca-bundle` ConfigMap must exist and be annotated before the Helm install; the OpenShift service CA operator must be running to inject the certificate

## Gotchas

- The init container reuses the same application image (`{{ $name }}:latest`) as the main container to get access to `$JAVA_HOME/lib/security/cacerts` -- this means the application images must be built before the Helm install
- The `changeit` password is the default JDK cacerts password and is hardcoded in both the init container script and the JVM system properties -- it is not configurable
- The init container copies the entire JDK cacerts file first (preserving all default CA certificates), then appends the OpenShift service CA -- this ensures the application can still make HTTPS calls to external services
- The `if [ -f /service-ca/service-ca.crt ]` guard makes the init container succeed even if the CA cert is not yet injected into the ConfigMap -- the application will fail at runtime if the cert is missing and it attempts an internal TLS call

## Related Patterns

- `kserve-inferenceservice-autodiscovery-sa-token-secret.md` -- the KServe endpoint whose TLS certificate this truststore enables
- `helm-range-loop-multi-component-files-get-properties.md` -- the Helm chart pattern that hosts this init container
