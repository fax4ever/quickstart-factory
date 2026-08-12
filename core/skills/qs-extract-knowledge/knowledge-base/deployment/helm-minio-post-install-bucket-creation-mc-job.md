---
name: helm-minio-post-install-bucket-creation-mc-job
description: MinIO deployment with post-install hook Job using minio/mc CLI to create default bucket via mc alias
summary: "Automates MinIO bucket provisioning on OpenShift by pairing a Helm-deployed MinIO Deployment (Recreate strategy, 100Gi PVC, dual TLS-edge Routes for S3 API port 9000 and web console port 9090) with a post-install hook Job running minio/mc:latest to create the default bucket after the server starts. Use when a quickstart needs S3-compatible object storage with guaranteed bucket existence at deploy time — the bucket name lives in a ConfigMap (labeled opendatahub.io/dashboard: \"true\") rather than values.yaml so the Makefile can discover it via oc get configmap and pass it to downstream charts like DSPA. The hook Job runs mc alias set minio http://minio-service.{{.Release.Namespace}}.svc.cluster.local:9000 with --api S3v4, credentials from minio-secret SecretKeyRef (MINIO_ROOT_USER and SECRET_KEY), MC_CONFIG_DIR=/tmp, then mc mb --ignore-existing minio/${MINIO_DEFAULT_BUCKET} with backoffLimit 3 and helm.sh/hook-weight -5. Hook-delete-policy hook-succeeded means failed Jobs persist for debugging; credentials are plaintext in values.yaml (b64enc only at Secret template render); mc uses HTTP for in-cluster connections while Routes expose HTTPS externally; the Secret itself notes it should be replaced with ExternalSecret or Vault for production."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, minio]
  ai_pattern: [data-pipeline]
  platform: [openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Standalone MinIO chart with PVC, dual Routes (API + UI), and post-install hook Job using minio/mc:latest to create bucket from ConfigMap name"
    approach: "A"
---

# MinIO Deployment with Post-Install Bucket Creation Hook Job

## Overview

Deploys a standalone MinIO instance with a PVC-backed Deployment, dual OpenShift Routes (API and UI), and a Helm post-install hook Job that uses the official `minio/mc` CLI image to create the default bucket after the MinIO server is running.

## Pattern Description

The MinIO chart deploys the server as a Recreate-strategy Deployment with a 100Gi PVC, exposes both the S3 API (port 9000) and web console (port 9090) via separate OpenShift Routes with TLS edge termination, and uses a post-install hook Job to create the default bucket. The bucket name comes from a ConfigMap rather than `values.yaml`, allowing the Makefile to reference it at deploy time via `oc get configmap`.

## Implementation

### Post-Install Bucket Creation Job

```yaml
# helm/minio/templates/create-bucket.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: create-bucket
  annotations:
    "helm.sh/hook": post-install
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: create-bucket
        image: minio/mc:latest
        command: ["/bin/sh", "-c"]
        args:
          - |
            mc alias set minio http://minio-service.{{.Release.Namespace}}.svc.cluster.local:9000 \
              "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" --api S3v4;
            mc mb --ignore-existing minio/${MINIO_DEFAULT_BUCKET};
        env:
        - name: MC_CONFIG_DIR
          value: "/tmp"
        - name: MINIO_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: minio-secret
              key: MINIO_ROOT_USER
        - name: MINIO_DEFAULT_BUCKET
          valueFrom:
            configMapKeyRef:
              name: minio-config
              key: DEFAULT_BUCKET
  backoffLimit: 3
```

### Bucket Configuration in ConfigMap

```yaml
# helm/minio/templates/config-map.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: minio-config
  labels:
    opendatahub.io/dashboard: 'true'
data:
  DEFAULT_BUCKET: recommender
  DEFAULT_REGION: us-east-1
```

### Dual OpenShift Routes

```yaml
# helm/minio/templates/routes.yaml
kind: Route
apiVersion: route.openshift.io/v1
metadata:
  name: minio-api
spec:
  to:
    kind: Service
    name: minio-service
  port:
    targetPort: api
  tls:
    termination: edge
---
kind: Route
apiVersion: route.openshift.io/v1
metadata:
  name: minio-ui
spec:
  to:
    kind: Service
    name: minio-service
  port:
    targetPort: ui
  tls:
    termination: edge
```

## Configuration

- **Key settings:** `minio.userId` and `minio.password` (set via Makefile `--set` flags), bucket name from ConfigMap (`recommender`), region from ConfigMap (`us-east-1`)
- **Defaults:** PVC size is 100Gi with ReadWriteOnce access mode, MinIO image is `quay.io/minio/minio:latest`
- **Dependencies:** OpenShift Route capability, storage class for PVC provisioning

## Gotchas

- The `hook-delete-policy: hook-succeeded` means the bucket creation Job is only deleted on success; failed Jobs remain for debugging.
- The ConfigMap is labeled with `opendatahub.io/dashboard: 'true'`, making it discoverable by the OpenShift AI dashboard.
- The `mc alias set` command uses HTTP (not HTTPS) for the in-cluster connection to MinIO, while the Route exposes HTTPS externally.
- The Secret comment says `Should be replaced with ExternalSecret and use a cloud-based solution or something like Vault`.
- MinIO credentials are base64-encoded using `{{ .Values.minio.password | b64enc | quote }}` in the Secret template, meaning values.yaml contains plaintext credentials.

## Related Patterns

- `makefile-runtime-secret-bridge-multi-chart-oc-discovery.md` — the Makefile that discovers the MinIO API route and creates bridge secrets
- `helm-dspa-crd-makefile-injected-external-minio.md` — the DSPA CRD that references MinIO's Secret for pipeline object storage
