---
name: odf-obc-init-container-wait
description: ObjectBucketClaim for ODF S3 storage with init container that waits for OBC secret/configmap readiness
summary: "Provisions S3-compatible object storage on OpenShift via ODF ObjectBucketClaim (storageClassName: openshift-storage.noobaa.io, toggled by objectStorage.odf.objectBucketClaim.enabled), where NooBaa asynchronously creates a same-named Secret (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) and ConfigMap (BUCKET_HOST/BUCKET_PORT/BUCKET_NAME), requiring a bitnami/kubectl init container with runAsNonRoot security context and scoped RBAC to poll until both exist. Use when multiple Helm-deployed workloads need shared dynamic S3 credentials from ODF -- three consumers demonstrated (ingestor-server via envFrom, NV-Ingest via extraEnvFrom, Milvus via externalS3.enabled with minio.enabled: false), with YAML anchors (&odf-bucket-name) ensuring consistent OBC name references and entrypoint scripts bridging OBC vars to app-specific names (MINIO_ACCESSKEY, MINIO_ENDPOINT). Critical implementation: $skipOBCKeys template logic conditionally suppresses static envVars when OBC is enabled, $${VAR} double-dollar syntax prevents Helm from interpreting shell variables as template expressions, and bucket name defaults to \"default-bucket\". Key gotchas: Milvus forces MINIO_PORT: \"80\" instead of OBC-provided BUCKET_PORT to avoid ODF TLS cert issues, bitnami/kubectl:latest may break on older clusters due to API version mismatch, and the pattern requires ODF operator with NooBaa plus the openshift-storage.noobaa.io StorageClass pre-installed."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [rag]
  platform: [openshift]
  data_layer: [milvus]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "OBC provides S3 credentials to ingestor-server, NV-Ingest, and Milvus via envFrom with init container synchronization"
    approach: "A"
---

# ODF ObjectBucketClaim with Init Container Wait

## Overview

This pattern uses an OpenShift Data Foundation (ODF) ObjectBucketClaim to dynamically provision S3-compatible object storage. Since OBC resources (Secret and ConfigMap) are created asynchronously by the ODF operator, an init container polls for their existence before the main application starts. The OBC-generated credentials are then injected into multiple workloads via `envFrom`.

## Pattern Description

When an ObjectBucketClaim is created, ODF's NooBaa operator provisions a bucket and generates two resources: a Secret containing `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, and a ConfigMap containing `BUCKET_HOST`, `BUCKET_PORT`, and `BUCKET_NAME`. These resources share the same name as the OBC. Since creation is asynchronous, the application Deployment uses an init container that loops until both the Secret and ConfigMap exist, with dedicated RBAC to read them. The main containers then consume the credentials via `envFrom` and an entrypoint script that maps OBC variable names to application-specific env vars.

## Implementation

### ObjectBucketClaim Resource

```yaml
# charts/ingest/templates/object-bucket-claim.yaml
{{- if $obc.enabled }}
apiVersion: objectbucket.io/v1alpha1
kind: ObjectBucketClaim
metadata:
  name: {{ $obc.name }}
  namespace: {{ .Release.Namespace }}
spec:
  bucketName: {{ $obc.bucketName }}
  storageClassName: {{ $obc.storageClassName }}
{{- end }}
```

### Init Container Wait Loop

The init container uses `bitnami/kubectl` to poll for both the Secret and ConfigMap:

```yaml
# charts/ingest/templates/ingestor-server-deployment.yaml (excerpt)
initContainers:
  - name: wait-for-obc-secret
    image: {{ $cfg.waitForOBCSecret.image }}
    command:
      - /bin/sh
      - -c
      - |
        until kubectl get secret {{ $obc.name }} -n {{ .Release.Namespace }} 2>/dev/null \
          && kubectl get configmap {{ $obc.name }} -n {{ .Release.Namespace }} 2>/dev/null; do
          echo "Waiting for OBC secret and configmap {{ $obc.name }}..."
          sleep 2
        done
        echo "OBC secret and configmap ready"
    securityContext:
      runAsNonRoot: true
      runAsUser: 1001
```

### RBAC for Init Container

A dedicated ServiceAccount, Role, and RoleBinding grant the init container permission to read only the OBC-named Secret and ConfigMap:

```yaml
# charts/ingest/templates/ingestor-server-rbac.yaml (excerpt)
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ $cfg.appName }}-wait-obc-secret
rules:
  - apiGroups: [""]
    resources: ["secrets", "configmaps"]
    resourceNames: [{{ $obc.name | quote }}]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ $cfg.appName }}-wait-obc-secret
roleRef:
  kind: Role
  name: {{ $cfg.appName }}-wait-obc-secret
subjects:
  - kind: ServiceAccount
    name: {{ $cfg.appName }}
```

### Entrypoint Script Env Var Bridging

The main container maps OBC environment variable names to application-specific names via an entrypoint script:

```yaml
# charts/ingest/templates/ingestor-server-deployment.yaml (excerpt)
envFrom:
  - secretRef:
      name: {{ $obc.name }}
  - configMapRef:
      name: {{ $obc.name }}
command:
  - /bin/sh
  - -c
  - |
    export MINIO_ACCESSKEY="$${AWS_ACCESS_KEY_ID}"
    export MINIO_SECRETKEY="$${AWS_SECRET_ACCESS_KEY}"
    export MINIO_ENDPOINT="$${BUCKET_HOST}:80"
    export MINIO_BUCKET="$${BUCKET_NAME}"
    export NVINGEST_MINIO_BUCKET="$${BUCKET_NAME}"
    exec uvicorn nvidia_rag.ingestor_server.server:app --port 8082 --host 0.0.0.0
```

### Multi-Workload OBC Credential Sharing

The same OBC Secret and ConfigMap are consumed by three different workloads:

```yaml
# charts/ingest/values.yaml -- NV-Ingest subchart consumes OBC via extraEnvFrom
nv-ingest:
  extraEnvFrom:
    - secretRef:
        name: *odf-bucket-name
    - configMapRef:
        name: *odf-bucket-name

# Milvus standalone maps OBC vars to its own MINIO_* env vars
milvus:
  standalone:
    extraEnv:
      - name: MINIO_ADDRESS
        valueFrom:
          configMapKeyRef:
            name: *odf-bucket-name
            key: BUCKET_HOST
      - name: MINIO_PORT
        value: "80"  # Force HTTP port 80; avoids TLS cert issues with ODF
```

## Configuration

- **Key settings:** `objectStorage.odf.objectBucketClaim.enabled` toggles the entire OBC pattern; `storageClassName: openshift-storage.noobaa.io` targets ODF/NooBaa
- **Defaults:** OBC is enabled by default; bucket name defaults to `default-bucket`; YAML anchors (`&odf-bucket-name`) ensure the OBC name is consistent across all references
- **Dependencies:** ODF operator with NooBaa installed; the `openshift-storage.noobaa.io` StorageClass must exist

## Gotchas

- The init container image (`bitnami/kubectl:latest`) needs to match the cluster's Kubernetes version; using `latest` may cause issues on older clusters
- The entrypoint script uses `$${VAR}` (double dollar) to prevent Helm from interpreting shell variable references as template expressions
- Milvus forces `MINIO_PORT: "80"` instead of using the OBC-provided `BUCKET_PORT`; a comment in values.yaml notes this avoids TLS certificate verification issues with ODF
- When OBC is enabled, the template skips setting `MINIO_ACCESSKEY`, `MINIO_SECRETKEY`, `MINIO_ENDPOINT`, `MINIO_BUCKET`, and `NVINGEST_MINIO_BUCKET` from static envVars since they come from the entrypoint script instead (enforced by `$skipOBCKeys` logic in the template)
- Milvus also disables its built-in MinIO (`minio.enabled: false`) and uses `externalS3.enabled: true` when consuming OBC storage

## Related Patterns

- `helm-nv-ingest-ngc-remote-subchart.md` -- the NV-Ingest subchart that consumes OBC credentials via extraEnvFrom
- `openshift-scc-anyuid-rolebinding.md` -- the SCC grants needed by NV-Ingest alongside OBC integration
