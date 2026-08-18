---
name: helm-hook-data-loader-job-readonly-user
description: Helm post-install hook Job loading CSV data into pgvector with read-only database user provisioning
summary: "Loads CSV sample data into a pgvector PostgreSQL database and provisions an mcp_readonly read-only user via a Helm post-install/post-upgrade hook Job (weight 5) running a Python script with pandas/psycopg2-binary on UBI9. Use when Helm-managed pgvector needs automated data seeding and read-only user creation at install/upgrade time; the Job image defaults to Quay (quay.io/rh-ai-quickstart/pgvector-data-loader:latest) but set BUILD_DATA_LOADER=true for on-cluster OpenShift binary build via ImageStream and BuildConfig. Database credentials come from secretKeyRef on Secret vector-database, the postgres host targets StatefulSet pod DNS pgvector-0.pgvector-postgres-service.<namespace>.svc.cluster.local, and the Makefile waits up to 600s with oc wait --for=condition=complete job/pgvector-data-loader. POSTGRES_READONLY_PASSWORD is passed as a plain Helm value (not secretKeyRef) unlike other credentials, hook-delete-policy: before-hook-creation will hang helm upgrade if a previous Job is stuck in a non-terminal state, and the binary build uses source.type: Binary so dockerfilePath: Dockerfile.data-loader resolves from the uploaded directory rather than the repo."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, postgresql, python]
  ai_pattern: []
  platform: [openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Post-install Job loads e-commerce CSV data and creates mcp_readonly user; supports Quay pull or binary cluster build"
    approach: "A"
---

# Helm Hook Data Loader Job with Read-Only User Provisioning

## Overview

This pattern uses a Helm post-install/post-upgrade hook Job to load sample data (CSV files) into a pgvector PostgreSQL database and provision a read-only database user. The data loader image can be sourced from Quay (default) or built on-cluster via OpenShift binary build. The Makefile waits for the Job to complete before proceeding with downstream deployments that depend on the loaded data.

## Pattern Description

The pgvector chart deploys a StatefulSet for PostgreSQL and a post-install hook Job that runs a Python script (`load_data.py`) to load CSV data and create a `mcp_readonly` database user. The Job's image source is toggleable: by default it pulls from `quay.io/rh-ai-quickstart/pgvector-data-loader:latest`, but with `BUILD_DATA_LOADER=true` the Makefile builds the image on-cluster using an OpenShift binary build (uploading CSV files and scripts to the internal registry).

## Implementation

### Data Loader Job Template

```yaml
# helm/pgvector/templates/data-loader-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: pgvector-data-loader
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "5"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  ttlSecondsAfterFinished: 300
  backoffLimit: 3
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: data-loader
          image: {{ .Values.dataLoader.image | default (printf
            "image-registry.openshift-image-registry.svc:5000/%s/pgvector-data-loader:latest"
            .Release.Namespace) }}
          imagePullPolicy: Always
          env:
            - name: POSTGRES_HOST
              value: "pgvector-0.pgvector-postgres-service.{{ .Release.Namespace }}.svc.cluster.local"
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: vector-database
                  key: DATABASE_USER
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: vector-database
                  key: DATABASE_PASSWORD
            - name: POSTGRES_DB
              valueFrom:
                secretKeyRef:
                  name: vector-database
                  key: DATABASE_NAME
            - name: POSTGRES_READONLY_PASSWORD
              value: "{{ .Values.postgres.readonlyPassword }}"
```

### Data Loader Dockerfile

```dockerfile
# helm/pgvector/Dockerfile.data-loader
FROM registry.access.redhat.com/ubi9/python-311:latest
USER root
RUN pip install --no-cache-dir pandas psycopg2-binary
RUN mkdir -p /data /scripts && chown -R 1001:0 /data /scripts && chmod -R g=u /data /scripts
COPY data/*.csv /data/
COPY scripts/load_data.py /scripts/load_data.py
RUN chmod +x /scripts/load_data.py
USER 1001
CMD ["python3", "/scripts/load_data.py"]
```

### Binary Build for Data Loader

```makefile
# helm/Makefile (build-data-loader-image target)
build-data-loader-image:
	@oc create imagestream pgvector-data-loader -n $(NAMESPACE) 2>/dev/null || true
	@oc apply -f $(POSTGRES_CHART)/buildconfig.yaml -n $(NAMESPACE)
	@cd $(POSTGRES_CHART) && oc start-build pgvector-data-loader \
	    --from-dir=. --follow -n $(NAMESPACE)
```

### Makefile Wait for Job Completion

```makefile
# helm/Makefile (database-install target, post-install wait)
@oc wait --for=condition=complete --timeout=600s \
    job/pgvector-data-loader -n $(NAMESPACE) || \
    (echo "Data loading job failed or timed out." && exit 1)
```

## Configuration

- **Key settings:** `dataLoader.image` (default `quay.io/rh-ai-quickstart/pgvector-data-loader:latest`), `postgres.readonlyPassword` (required, provisioned by the load script), `BUILD_DATA_LOADER` flag (default false)
- **Defaults:** Job auto-deletes after 300s (`ttlSecondsAfterFinished`); 3 retry attempts (`backoffLimit`); hook-delete-policy `before-hook-creation` ensures old Jobs are cleaned up before re-running
- **Dependencies:** Requires the pgvector StatefulSet to be running and ready (the Job connects to `pgvector-0.pgvector-postgres-service`); the Makefile waits up to 600 seconds for completion

## Gotchas

- The `POSTGRES_READONLY_PASSWORD` is passed as a plain value in the Job spec (`value: "{{ .Values.postgres.readonlyPassword }}"`) rather than through a Secret reference, unlike the other database credentials which use secretKeyRef (see `helm/pgvector/templates/data-loader-job.yaml`)
- The postgres host uses the fully-qualified pod DNS name `pgvector-0.pgvector-postgres-service.{{ .Release.Namespace }}.svc.cluster.local` rather than the headless service name, targeting the specific StatefulSet pod (see `helm/pgvector/templates/data-loader-job.yaml`)
- The binary build's BuildConfig uses `source.type: Binary` meaning no Dockerfile path resolution -- the `dockerfilePath: Dockerfile.data-loader` is resolved from the uploaded directory contents (see `helm/pgvector/buildconfig.yaml`)
- The `hook-delete-policy: before-hook-creation` means the previous Job must be deleted before the new one starts -- if a previous Job is stuck in a non-terminal state, `helm upgrade` will hang waiting for deletion

## Related Patterns

- `helm-independent-subcharts-no-umbrella.md` -- the chart structure containing this pgvector chart
- `openshift-buildconfig-inline-dockerfile-dual-source.md` -- the dual-source pattern used by the data loader's BuildConfig
