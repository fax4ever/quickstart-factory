---
name: postgres-maas-db
description: "CloudNativePG PostgreSQL cluster provisioned as RHOAI MaaS backing database via Helm post-install Job"
summary: "Provisions a CloudNativePG (CNPG) operator-managed PostgreSQL Cluster CR as the RHOAI MaaS backing database, using the EDB certified-operators catalog with a dedicated OperatorGroup in cloudnative-pg namespace — distinct from the pgvector subchart StatefulSet pattern and reused by the keycloak component. Use when RHOAI MaaS requires operator-managed PostgreSQL with auto-generated credentials; set postgresCluster.create: false to skip when an external PostgreSQL is available; prefer the pgvector subchart when the quickstart needs vector search extensions rather than MaaS backing storage. A Helm post-install Job waits for cnpg-controller-manager, applies the templated Cluster CR (postgresql.cnpg.io/v1, initdb bootstrap with shared database/owner name, configurable via postgresCluster.name/namespace/instances/storage.size), extracts the URI from convention-named <cluster-name>-app secret, and creates maas-db-config with DB_CONNECTION_URL in redhat-ods-applications via dry-run+apply idempotency — cross-namespace access requires RoleBindings granting edit ClusterRole. Gotchas: hardcoded sleep 5 after operator rollout works around webhook registration timing, the combined Job script bundles CNPG creation with DSCInitialization/DataScienceCluster so a CNPG failure blocks all downstream setup (backoffLimit: 4), and the CNPG secret naming convention (<name>-app) is assumed — operator version changes will break URI extraction."
metadata:
  type: component
tags:
  tech_stack: [postgresql, cloudnative-pg, helm]
  ai_pattern: [model-serving]
  platform: [rhoai, openshift]
  data_layer: [postgresql]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "CNPG Cluster CR for MaaS backing database; post-install Job extracts URI secret and copies to redhat-ods-applications namespace"
    approach: "A"
---

# postgres-maas-db

## Overview

postgres-maas-db is a CloudNativePG (CNPG) operator-managed PostgreSQL cluster that serves as the backing database for RHOAI's Models-as-a-Service (MaaS) feature. Unlike the pgvector subchart pattern used by other quickstarts, this component uses the Certified CloudNativePG operator from EDB to provision a `Cluster` CRD, and a Helm post-install Job to extract the auto-generated credentials and wire them into the `redhat-ods-applications` namespace as the `maas-db-config` secret required by RHOAI.

## Tech Stack & Dependencies

- **Runtime:** PostgreSQL (version managed by CNPG operator)
- **Container image:** Managed by the CloudNativePG operator (no explicit image in chart)
- **Key dependencies:** CloudNativePG Operator (installed from `certified-operators` catalog, `stable-v1` channel), RHOAI Operator (for DataScienceCluster that consumes the DB)
- **Helm subchart:** None -- the CNPG `Cluster` CR is rendered as a templated file within the `dependency-operators` chart, not a standalone subchart

## Key Patterns

### CNPG Operator Subscription

The CloudNativePG operator is installed via OLM Subscription as part of the `install-operators` subchart. It uses the `certified-operators` catalog (not `redhat-operators`), and is deployed into its own `cloudnative-pg` namespace with a dedicated OperatorGroup.

```yaml
# charts/dependency-operators/values.yaml
cloudnative-pg:
  enabled: true
  channel: stable-v1
  catalog: certified-operators
  namespace: cloudnative-pg
  operatorGroup:
    enabled: true
```

### CNPG Cluster CR as Templated File

The PostgreSQL cluster is defined as a CNPG `Cluster` custom resource rendered via Helm templating. It uses the `postgresql.cnpg.io/v1` API and bootstraps with `initdb` to create both the database and owner user with the same name. Storage and resources are configurable through values.

```yaml
# charts/dependency-operators/files/openshift-ai/cluster.yaml
{{- with $cluster := .Values.postgresCluster }}
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: {{ $cluster.name }}
  namespace: {{ $cluster.namespace }}
spec:
  instances: {{ $cluster.instances | default 1 }}
  storage:
    {{- toYaml ($cluster.storage | default ("{\"size\": \"2Gi\"}" | fromJson)) | nindent 6 }}
  bootstrap:
    initdb:
      database: {{ $cluster.name }}
      owner: {{ $cluster.name }}
{{- end }}
```

### Post-Install Job for Secret Wiring

A Helm post-install Job creates the CNPG cluster, waits for readiness, extracts the auto-generated URI from the CNPG-managed secret, and creates the `maas-db-config` secret in the `redhat-ods-applications` namespace. This secret contains the `DB_CONNECTION_URL` key that RHOAI MaaS expects.

```bash
# charts/dependency-operators/files/openshift-ai/create-datasciencecluster.sh
oc rollout status -n cloudnative-pg deployment/cnpg-controller-manager
sleep 5
oc apply -f cluster.yaml
while ! [ "$(oc get cluster -n {{ $db.namespace }} {{ $db.name }} \
  -o jsonpath='{.status.readyInstances}')" -eq "{{ $db.instances | default 1 }}" ]; do
  sleep 5
done
uri=$(oc get secret -n {{ $db.namespace }} {{ $db.name }}-app \
  -ojsonpath='{.data.uri}' | base64 -d)
oc create secret generic maas-db-config -n redhat-ods-applications \
  --from-literal=DB_CONNECTION_URL="$uri" --dry-run=client -oyaml | oc apply -f-
```

### Namespace and RBAC Setup for Cross-Namespace Secret Copy

The Job requires cross-namespace access: it reads the CNPG-generated secret from `maas-db` namespace and creates the `maas-db-config` secret in `redhat-ods-applications`. This is enabled through RoleBindings granting `edit` ClusterRole to the Job's ServiceAccount in both namespaces.

```yaml
# charts/dependency-operators/templates/job-create-datasciencecluster.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: {{ $db.namespace }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: create-maas-db-config-edit
  namespace: {{ $db.namespace }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: edit
subjects:
  - kind: ServiceAccount
    name: create-datasciencecluster
    namespace: redhat-ods-operator
```

### Conditional Creation via Values Flag

The entire postgres cluster and associated RBAC are gated behind `postgresCluster.create`, allowing deployments to skip CNPG provisioning when an external PostgreSQL database is already available.

```yaml
# charts/dependency-operators/values.yaml
postgresCluster:
  create: true
  name: maas
  namespace: maas-db
  storage:
    size: 5Gi
  resources:
    limits:
      cpu: "1"
      memory: 2Gi
    requests:
      cpu: 200m
      memory: 256Mi
```

### CNPG Convention-Based Secret Naming

The CNPG operator auto-generates a secret named `<cluster-name>-app` containing connection credentials (including `uri`, `username`, `password`, `host`, `port`, `dbname`). The post-install Job reads the `uri` key from this secret. This is the same convention used by the keycloak subchart's CNPG cluster (`keycloak-postgres-app`).

## Configuration

- **Environment variables:** None directly on the database component -- the CNPG operator manages the PostgreSQL container environment. The `DB_CONNECTION_URL` key in the resulting `maas-db-config` secret is consumed by RHOAI MaaS internally.
- **Config files:**
  - `charts/dependency-operators/files/openshift-ai/cluster.yaml` -- The CNPG Cluster CR template
  - `charts/dependency-operators/files/openshift-ai/create-datasciencecluster.sh` -- Post-install Job script that creates the cluster, waits, and copies the secret
- **Helm values:**
  - `postgresCluster.create` -- Whether to provision the CNPG cluster (default: `true`); set to `false` when using an external PostgreSQL
  - `postgresCluster.name` -- Name of both the CNPG Cluster CR and the database/owner (default: `maas`)
  - `postgresCluster.namespace` -- Namespace for the CNPG cluster (default: `maas-db`)
  - `postgresCluster.instances` -- Number of PostgreSQL instances (default: `1`)
  - `postgresCluster.storage.size` -- PVC storage size (default: `5Gi`)
  - `postgresCluster.resources` -- CPU/memory limits and requests

## Known Gotchas

- **Post-install Job combines multiple concerns:** The `create-datasciencecluster.sh` script handles CNPG cluster creation, secret wiring, DSCInitialization, and DataScienceCluster creation in a single Job. If the CNPG cluster creation fails, the entire Job fails and none of the subsequent resources (including the DataScienceCluster) are created. The Job has `backoffLimit: 4` but a persistent CNPG failure blocks all downstream setup.
- **sleep 5 after operator rollout:** The script has a hardcoded `sleep 5` between verifying the CNPG controller-manager rollout and applying the Cluster CR (see `create-datasciencecluster.sh` lines 12-14). This is a workaround for webhook registration timing -- if the CNPG webhook is not yet ready, the `oc apply` of the Cluster CR will fail.
- **CNPG secret naming convention assumed:** The script extracts the URI from `{{ $db.name }}-app` (e.g., `maas-app`) which is the CNPG operator's convention for application-level credentials. If the CNPG operator changes this naming convention in a future version, the secret extraction will break.
- **dry-run + apply pattern for idempotent secret creation:** The script uses `oc create secret ... --dry-run=client -oyaml | oc apply -f-` to create or update the `maas-db-config` secret idempotently. This pattern generates the Secret manifest client-side and then applies it, which works but produces a warning on first creation.
- **Database and owner share the same name:** The `initdb.database` and `initdb.owner` are both set to `{{ $cluster.name }}` (default: `maas`). This is intentional for the CNPG convention but means the database user has the same name as the database, which can be confusing when debugging connection issues.

## Testing Notes

- Verify the CNPG operator is running: `oc get deployment -n cloudnative-pg cnpg-controller-manager`
- Verify the CNPG cluster is healthy: `oc get cluster -n maas-db maas -o jsonpath='{.status.readyInstances}'` should return `1`
- Verify the auto-generated secret exists: `oc get secret -n maas-db maas-app` and confirm it contains `uri`, `username`, `password` keys
- Verify the `maas-db-config` secret was copied: `oc get secret -n redhat-ods-applications maas-db-config` and confirm it contains `DB_CONNECTION_URL`
- Verify the `DB_CONNECTION_URL` value is a valid PostgreSQL URI: `oc get secret -n redhat-ods-applications maas-db-config -o jsonpath='{.data.DB_CONNECTION_URL}' | base64 -d`

## Related Patterns

- `components/keycloak.md` -- Uses the same CNPG operator pattern for Keycloak's PostgreSQL backend (`keycloak-postgres` cluster)
- `components/pgvector.md` -- Alternative PostgreSQL deployment pattern using a Helm subchart StatefulSet rather than CNPG operator
