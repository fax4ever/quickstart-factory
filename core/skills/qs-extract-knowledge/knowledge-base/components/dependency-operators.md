---
name: dependency-operators
description: Helm chart that installs OLM-managed operators and creates their operands via post-install Jobs on OpenShift
summary: "Solves declarative installation of multiple OLM-managed operators and their operands on OpenShift via a Helm umbrella chart with a condition-gated install-operators subchart that generates Namespace, OperatorGroup, and Subscription per values.yaml entry -- supports both Automatic and Manual install-plan approval with pinned startingCSV. Use when deploying a stack requiring coordinated operator installation (RHOAI, Kuadrant, CloudNativePG, LeaderWorkerSet) with operand creation as post-install Jobs; each Job gets a dedicated ServiceAccount with least-privilege RBAC, mounts Bash scripts from ConfigMaps (defaultMode 493), and uses the cluster-internal tools image. Critical patterns: CNPG Job polls readyInstances then propagates connection URI secret via dry-run/apply; Kuadrant Job deletes controller pod before CR apply then bootstraps Authorino TLS via serving-cert annotation and CA bundle env vars; Gateway toggles HTTPS wildcard cert vs Route edge termination via useRoute boolean; DSC components (kserve, dashboard, llamastackoperator) are individually toggled. Gotchas: Manual approval fails Helm render if startingCSV is missing (explicit fail template guard), hook-delete-policy before-hook-creation is required for idempotent helm upgrade, Kuadrant controller pod must be restarted before applying the CR, and Authorino TLS depends on the OpenShift service-ca operator for auto-generated serving certificates."
metadata:
  type: component
tags:
  tech_stack: [helm, bash]
  ai_pattern: [model-serving]
  platform: [openshift, rhoai, kserve, olm]
  data_layer: [cloudnative-pg]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "Umbrella Helm chart installing nine OLM operators with Manual install-plan approval and post-install Jobs for operand creation"
    approach: "A"
---

# Dependency Operators

## Overview

A Helm umbrella chart that declaratively installs OpenShift operators via OLM Subscriptions and then creates their operands through Kubernetes Jobs run as Helm post-install/post-upgrade hooks. It bundles a reusable `install-operators` subchart that handles Namespace, OperatorGroup, Subscription, and Manual install-plan approval for any number of operators, plus parent-chart templates that create operands such as DataScienceCluster, Kuadrant, LeaderWorkerSetOperator, Gateway, and CloudNativePG Cluster resources.

## Tech Stack & Dependencies

- **Runtime:** Helm v2 chart with Bash shell scripts executed inside Jobs
- **Container image:** `image-registry.openshift-image-registry.svc:5000/openshift/tools:latest` (cluster-internal tools image)
- **Key dependencies:** OLM (Operator Lifecycle Manager), OpenShift internal image registry
- **Helm subchart:** `install-operators` (local subchart, condition-gated via `install-operators.enabled`)

## Key Patterns

### Data-Driven Operator Installation via Subchart

The `install-operators` subchart iterates over a `values.yaml` map to create Namespace, OperatorGroup, and Subscription resources for each operator. No per-operator templates are needed; adding a new operator requires only a values entry.

```yaml
# values.yaml -- each key becomes a Subscription
install-operators:
  enabled: true
  operators:
    rhods-operator:
      enabled: true
      channel: stable-3.4
      namespace: redhat-ods-operator
      installPlanApproval: Manual
      startingCSV: rhods-operator.3.4.0
      operatorGroup:
        enabled: true
```

The Subscription template loops over `.Values.operators`:

```yaml
{{- range $operator, $config := .Values.operators }}
{{- if $config.enabled }}
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {{ $operator }}
  namespace: {{ $config.namespace | default "openshift-operators" }}
spec:
  channel: {{ $config.channel }}
  installPlanApproval: {{ $config.installPlanApproval | default "Automatic" }}
  name: {{ $operator }}
  source: {{ $config.catalog | default "redhat-operators" }}
  sourceNamespace: openshift-marketplace
{{- end }}
{{- end }}
```

### Manual Install-Plan Approval with Pinned CSV

When `installPlanApproval: Manual` is set, the subchart requires `startingCSV` and fails the Helm render if missing. It creates a ServiceAccount, ClusterRoleBinding, ConfigMap (with an approve script), and a Helm post-install Job that polls for the matching InstallPlan and approves it.

```yaml
# install-plan-approvals.yaml -- validation guard
{{- if eq ($config.installPlanApproval | default "Automatic") "Manual" }}
{{- if not $config.startingCSV }}
{{- fail "Manual approvals with this chart require pinning a specific CSV with startingCSV for the operator" }}
{{- end }}
```

The approve script polls in a loop until it finds an InstallPlan whose `clusterServiceVersionNames` matches the pinned CSV and whose status is `RequiresApproval` or `Complete`, then patches it approved.

### Operand Creation via Post-Install Jobs

Each operand (DataScienceCluster, Kuadrant, LeaderWorkerSet) has a dedicated Job template that:
1. Creates a ServiceAccount with least-privilege RBAC (scoped ClusterRoleBindings or RoleBindings)
2. Mounts operand YAML files from a ConfigMap (loaded via `$.Files.Glob`)
3. Runs a Bash script as a Helm `post-install,post-upgrade` hook with `before-hook-creation` delete policy
4. Applies the operand YAML with retry loops (`while ! oc apply -f ...; do sleep 5; done`)

```yaml
# job-create-datasciencecluster.yaml (pattern)
annotations:
  helm.sh/hook: post-install,post-upgrade
  helm.sh/hook-delete-policy: before-hook-creation
spec:
  backoffLimit: 4
  template:
    spec:
      serviceAccountName: create-datasciencecluster
      restartPolicy: Never
      containers:
      - name: create-datasciencecluster
        image: {{ $.Values.global.toolsImage }}
        command: ["/app/create-datasciencecluster.sh"]
        volumeMounts:
          - name: create-datasciencecluster-script
            mountPath: /app
      volumes:
        - name: create-datasciencecluster-script
          configMap:
            name: create-datasciencecluster
            defaultMode: 493
```

### CloudNativePG Cluster with Secret Propagation

The DataScienceCluster creation script also handles the PostgreSQL lifecycle: it waits for the CNPG controller, creates the Cluster CR, polls until `readyInstances` matches the desired count, extracts the connection URI from the auto-generated secret, and creates a derived secret in `redhat-ods-applications` for consumption by MaaS.

```bash
# create-datasciencecluster.sh (excerpt)
oc rollout status -n cloudnative-pg deployment/cnpg-controller-manager
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

### Kuadrant with Authorino TLS Bootstrap

The Kuadrant creation script waits for all four sub-operators (authorino, dns, limitador, rhcl) to have an installed CSV, restarts the controller pod, applies the Kuadrant CR, then configures Authorino with serving-cert TLS and custom CA bundle environment variables.

```bash
# create-kuadrant.sh (excerpt)
oc delete pod -l app=kuadrant,control-plane=controller-manager
oc rollout status deployment/kuadrant-operator-controller-manager
oc apply -f kuadrant.yaml
oc wait --for=condition=Ready kuadrant kuadrant --timeout 15m0s
oc annotate service authorino-authorino-authorization \
  service.beta.openshift.io/serving-cert-secret-name=authorino-server-cert --overwrite
oc patch authorino authorino --type=merge \
  --patch '{"spec": {"listener": {"tls": {"enabled": true, "certSecretRef": {"name": "authorino-server-cert"}}}}}'
oc set env deployment/authorino \
  SSL_CERT_FILE=/etc/ssl/certs/openshift-service-ca/service-ca-bundle.crt \
  REQUESTS_CA_BUNDLE=/etc/ssl/certs/openshift-service-ca/service-ca-bundle.crt
```

### Gateway API with Route Fallback

The chart supports two modes for the MaaS gateway: direct HTTPS with a wildcard certificate (`useRoute: false`, default) or OpenShift Route edge termination with ClusterIP service (`useRoute: true`). Both are controlled by a single boolean in values.

```yaml
# gateway.yaml -- listener toggle
{{- if .useRoute }}
- name: http
  port: 80
  protocol: HTTP
  hostname: {{ .hostname | default (printf "maas.%s" $.Values.global.wildcardDomain) }}
{{- else }}
- name: https
  port: 443
  protocol: HTTPS
  tls:
    certificateRefs:
    - kind: Secret
      name: {{ $.Values.global.wildcardCertName }}
    mode: Terminate
{{- end }}
```

## Configuration

- **Environment variables:** `PACKAGE`, `PACKAGE_NAMESPACE`, `CSV` (set on install-plan approval Jobs to identify the operator and target CSV)
- **Config files:** Shell scripts in `files/` directories (`openshift-ai/`, `rhcl/`, `lws/`) loaded into ConfigMaps via `$.Files.Glob`
- **Helm values:**
  - `global.toolsImage` -- container image for all Jobs (defaults to cluster-internal tools image)
  - `global.wildcardDomain` -- cluster apps domain for gateway hostname
  - `install-operators.operators.<name>` -- per-operator config (channel, namespace, installPlanApproval, startingCSV, operatorGroup, catalog)
  - `dataScienceCluster.create` / `dataScienceCluster.components` -- toggle and configure DSC components (kserve, dashboard, llamastackoperator)
  - `gateways.maasDefaultGateway.useRoute` -- switch between HTTPS Gateway and OpenShift Route
  - `postgresCluster.create` / `postgresCluster.namespace` -- toggle CloudNativePG cluster creation
  - `rhcl.create` / `lws.create` -- toggle Kuadrant and LeaderWorkerSet operand creation

## Known Gotchas

- Manual install-plan approval requires pinning `startingCSV` -- the Helm template fails explicitly with `{{- fail "..." }}` if this is missing, preventing silent misconfiguration.
- The Kuadrant creation script deletes the controller-manager pod (`oc delete pod -l app=kuadrant,control-plane=controller-manager`) and waits for rollout before applying the CR -- this restart is required for the operator to pick up sub-operator readiness.
- The CNPG secret propagation uses `--dry-run=client -oyaml | oc apply -f-` to make the secret creation idempotent across Helm upgrades.
- All post-install Jobs use `helm.sh/hook-delete-policy: before-hook-creation` so that re-running `helm upgrade` creates fresh Jobs rather than failing on existing ones.
- ConfigMaps holding scripts use `defaultMode: 493` (octal 0755) to ensure scripts are executable when mounted.
- The Authorino TLS setup relies on OpenShift's `service.beta.openshift.io/serving-cert-secret-name` annotation to auto-generate a serving certificate and the `service-ca-bundle.crt` for CA trust.

## Testing Notes

- After `helm install`, verify all operator Subscriptions show `AtLatestKnown` state: `oc get subscriptions.operators.coreos.com -A`
- Check that post-install Jobs completed: `oc get jobs -A -l app.kubernetes.io/managed-by=Helm`
- Verify the DataScienceCluster is ready: `oc get datascienceclusters`
- Verify Kuadrant readiness: `oc wait --for=condition=Ready kuadrant kuadrant -n kuadrant-system`
- Check CloudNativePG cluster readiness: `oc get cluster -n maas-db`
- Verify the gateway is created: `oc get gateway -n openshift-ingress`

## Related Patterns

- Deployment KB files covering Helm subchart wiring patterns
- `cloudnative-pg` component for database cluster details
- `kserve-vllm` or model-serving components that depend on DSC being configured
