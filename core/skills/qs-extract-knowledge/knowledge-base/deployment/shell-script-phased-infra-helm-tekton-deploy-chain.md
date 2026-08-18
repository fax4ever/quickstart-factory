---
name: shell-script-phased-infra-helm-tekton-deploy-chain
description: Shell script orchestrating 14-step deploy chain - raw manifests, Helm third-party, oc exec cache init, Tekton build, then Helm app install
summary: "Orchestrates a 14-step deploy chain via a single create.sh (no Makefile) that mixes raw oc apply manifests (Kafka, Infinispan, AMQ Broker/Artemis), third-party Helm charts (OpenTelemetry Collector via helm repo add open-telemetry, release camel-otel-collector), imperative oc exec REST cache provisioning for Infinispan, dynamic ConfigMap/Secret generation with namespace-scoped DNS, KServe Granite model auto-discovery, Tekton pipeline builds via tkn, and Helm app install (release smart-log-analyzer). Use when the quickstart requires strict sequential infrastructure-then-application ordering with heterogeneous deploy methods (raw manifests, Helm, Tekton, imperative commands) that cannot be expressed in a single Helm chart -- NS derives from oc project -q (defaults to slog-analyzer), requires oc/helm/tkn CLIs plus OpenShift Pipelines operator. Critical dependency chain: Secrets -> Kafka -> OTel Collector (Helm) -> Infinispan -> cache creation (oc exec) -> AMQ Broker -> infra-endpoints ConfigMap (--dry-run=client -o yaml | oc apply -f - for idempotency) -> OpenAI secret (dynamic from KServe) -> Tekton build (1Gi PVC workspace, images pushed to image-registry.openshift-image-registry.svc:5000) -> Helm app install -> post-deploy cleanup of PipelineRuns/TaskRuns/empty ReplicaSets. Script exits with error if no Granite model InferenceService exists in sandbox-shared-models namespace; oc wait timeouts (180s infra, 300s apps) cause hard failure if services start slowly; tkn pipeline start --showlog blocks for minutes during multi-image builds; delete.sh reverses order starting with Helm uninstalls."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, tekton, opentelemetry, kafka, infinispan, artemis]
  ai_pattern: [data-pipeline]
  platform: [openshift]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "create.sh orchestrating 14 sequential steps: secrets/configmaps, Kafka, OTel Collector (Helm), Infinispan, cache creation via oc exec REST, AMQ Broker, dynamic ConfigMap/Secret generation, Tekton pipeline build, Helm app install, post-deploy cleanup"
    approach: "A"
---

# Shell Script Phased Infrastructure-Helm-Tekton Deploy Chain

## Overview

A deployment pattern where a single shell script orchestrates the entire quickstart lifecycle through 14 sequential steps, mixing raw `oc apply` manifests, third-party Helm chart installs, imperative `oc exec` cache provisioning, dynamic secret generation from cluster state, Tekton pipeline builds, and finally Helm-based application deployment. Each step waits for the previous one to be fully ready before proceeding.

## Pattern Description

The `create.sh` script is the sole entry point for deploying the entire stack. It does not use a Makefile. The script deploys infrastructure services first (Kafka, OTel Collector, Infinispan, AMQ Broker), creates caches via REST API calls exec'd into the Infinispan pod, dynamically discovers a KServe InferenceService model and generates OpenAI-compatible credentials, triggers a Tekton pipeline to build application container images, then installs the application components via Helm. A paired `delete.sh` tears everything down in reverse. The ordering is critical because application components depend on infrastructure services and the Tekton-built images.

## Implementation

### Step Sequencing Overview

The 14 steps in `create.sh` follow this dependency chain:

```
Secrets/ConfigMaps -> Kafka -> OTel Collector (Helm) -> Infinispan
  -> Cache creation (oc exec) -> AMQ Broker -> infra-endpoints ConfigMap
  -> OpenAI secret (dynamic) -> Service CA bundle -> Tekton tasks/pipeline
  -> Pipeline build (tkn) -> Helm app install -> Wait for deployments
  -> Cleanup build resources
```

### Mixed Deployment Methods in One Script

The script uses three distinct deployment mechanisms within a single flow:

```bash
# create.sh - Raw manifests
oc apply -f deploy/resources/secrets/
oc apply -f deploy/resources/otel-infra/kafka/kafka-sandbox.yaml
oc wait deployment/kafka --for=condition=Available --timeout=180s

# Third-party Helm chart
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts 2>/dev/null || true
helm repo update
helm install camel-otel-collector open-telemetry/opentelemetry-collector \
  -f deploy/resources/otel-infra/otel-collector/values-sandbox.yaml \
  -n "${NS}" --wait --timeout 300s

# Tekton pipeline trigger via tkn CLI
tkn pipeline start build-apps \
  -p namespace="${NS}" \
  --use-param-defaults \
  -w name=shared-workspace,volumeClaimTemplateFile="${WORKSPACE_TEMPLATE}" \
  --showlog

# Application Helm chart
helm install smart-log-analyzer chart/ \
  --set namespace="${NS}" \
  -n "${NS}"
```

### Dynamic ConfigMap Generation with Namespace Interpolation

Infrastructure endpoints are generated dynamically with namespace-scoped service DNS:

```bash
# create.sh - Step 7: Dynamic ConfigMap with namespace-aware service addresses
oc create configmap infra-endpoints \
  --from-literal=ARTEMIS_BROKER_URL="tcp://artemis.${NS}.svc:61616" \
  --from-literal=INFINISPAN_HOSTS="infinispan.${NS}.svc:11222" \
  --dry-run=client -o yaml | oc apply -f -
```

### Post-Deploy Cleanup of Build Resources

After successful deployment, the script removes transient Tekton runs and empty ReplicaSets:

```bash
# create.sh - Step 14: Clean up build resources
oc delete pipelinerun --all 2>/dev/null || true
oc delete taskrun --all 2>/dev/null || true
oc get rs --no-headers | awk '$2==0 && $3==0 && $4==0 {print $1}' | xargs -r oc delete rs 2>/dev/null || true
```

### Corresponding delete.sh Teardown

The `delete.sh` reverses the installation: Helm uninstalls first, then raw manifest deletes, then Tekton cleanup, then ConfigMap/Secret cleanup.

```bash
# delete.sh - Ordered teardown
helm uninstall smart-log-analyzer 2>/dev/null || true
helm uninstall camel-otel-collector --ignore-not-found 2>/dev/null || true
oc delete -f deploy/resources/otel-infra/kafka/kafka-sandbox.yaml --ignore-not-found 2>/dev/null || true
oc delete -f deploy/resources/infinispan/infinispan-sandbox.yaml --ignore-not-found 2>/dev/null || true
oc delete -f deploy/resources/amq-broker/artemis-sandbox.yaml --ignore-not-found 2>/dev/null || true
```

## Configuration

- **Key settings:** `NS` is derived from `oc project -q` (current namespace); Tekton workspace uses 1Gi PVC; Helm release name is `smart-log-analyzer` for apps, `camel-otel-collector` for the OTel Collector
- **Defaults:** Namespace defaults to `slog-analyzer` in values.yaml; images are pushed to the internal OpenShift registry at `image-registry.openshift-image-registry.svc:5000`
- **Dependencies:** Requires `oc`, `helm`, and `tkn` CLI tools; a KServe InferenceService with a Granite model must exist in the `sandbox-shared-models` namespace; OpenShift Pipelines operator must be installed

## Gotchas

- The script expects a Granite model InferenceService to already exist in the `sandbox-shared-models` namespace -- if not found, the script exits with an error at Step 8 (`ERROR: No Granite model found in sandbox-shared-models namespace`)
- The `--dry-run=client -o yaml | oc apply -f -` pattern is used for ConfigMaps and Secrets to make them idempotent -- creating if absent or updating if present
- The `tkn pipeline start ... --showlog` call blocks until the Tekton pipeline completes, which builds all three application images -- this can take several minutes
- All `oc wait` commands use explicit timeouts (180s for infra, 300s for apps) -- if infrastructure takes longer to start, the script will fail

## Related Patterns

- `tekton-camel-export-quarkus-buildah-pipeline.md` -- the Tekton build pipeline invoked by Step 11
- `kserve-inferenceservice-autodiscovery-sa-token-secret.md` -- the dynamic model discovery in Step 8
- `infinispan-cache-oc-exec-rest-api-provisioning.md` -- the cache creation in Step 5
