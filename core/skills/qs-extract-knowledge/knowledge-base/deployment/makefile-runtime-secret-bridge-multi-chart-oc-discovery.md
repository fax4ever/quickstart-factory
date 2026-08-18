---
name: makefile-runtime-secret-bridge-multi-chart-oc-discovery
description: Makefile deploys 3 independent Helm charts with runtime oc discovery to create bridge secrets between charts
summary: "Solves cross-chart value injection when deploying multiple independent Helm charts (MinIO, pipeline-server, product-recommender-system) that need runtime-discovered routes, ClusterIPs, ConfigMap data, and secret credentials from previously installed charts on OpenShift. Use when independent charts require post-install runtime values from each other but an umbrella chart is undesirable — if no runtime secret bridging is needed, prefer the simpler helm-independent-subcharts-no-umbrella pattern; the created bridge secret ds-pipeline-s3-dspa feeds into the DSPA CRD pattern in helm-dspa-crd-makefile-injected-external-minio. The Makefile uses $(eval VAR = $(shell oc get ...)) to discover values across four sequential phases (validation, MinIO, pipeline-server, app), passes them via --set flags, and creates the bridge secret with host/port/accesskey/secretkey/secure fields using --dry-run=client -o yaml | oc apply -f - for idempotent create/update; requires oc, helm, and jq CLIs. Credentials passed as make dot-notation arguments (minio.userId, minio.password) appear in the process table; pipeline-server target needs a manual retry loop before oc wait because the pod may not yet exist; MinIO enforces minimum credential lengths so validate early; uninstall runs oc delete project which removes the entire namespace, not just Helm releases."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, minio, postgresql]
  ai_pattern: [data-pipeline]
  platform: [rhoai, openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Makefile orchestrates minio, pipeline-server, product-recommender-system charts with runtime route/secret discovery and dynamic bridge secret creation"
    approach: "A"
---

# Makefile Runtime Secret Bridge for Multi-Chart Deployment

## Overview

Deploys multiple independent Helm charts in a defined order using a Makefile that discovers runtime values (routes, service IPs, secret data) via `oc` commands between installs and creates bridge secrets to connect independently-deployed charts that cannot reference each other's resources directly.

## Pattern Description

When independent Helm charts need values that only exist after a prior chart is installed (such as a MinIO route hostname or service ClusterIP), the Makefile acts as an orchestration layer: it installs chart A, uses `oc get` to discover the runtime endpoint, then passes discovered values to chart B via `--set` flags and/or creates a new Secret that bridges the two charts. This avoids the need for an umbrella chart while still allowing cross-chart references.

## Implementation

### Install Target Ordering

The top-level `install` target sequences four phases: validation, then minio, then pipeline-server, then the main app chart. Each phase depends on the previous chart being fully ready.

```makefile
# helm/Makefile
.PHONY: install
install: check-oc-version check-minio-credentials check-model-config namespace depend minio-install pipeline-server-install create-dynamic-secret product-recommender-install
```

### Runtime Route and ConfigMap Discovery

After installing MinIO, the pipeline-server install discovers the MinIO API route hostname and ConfigMap values at deploy time, then passes them as `--set` flags:

```makefile
.PHONY: pipeline-server-install
pipeline-server-install:
	$(eval MINIO_API_HOST = $(shell oc get route minio-api -n $(NAMESPACE) -o jsonpath='{.spec.host}'))
	$(eval DEFAULT_BUCKET= $(shell oc get configmap minio-config -n $(NAMESPACE) -o json | jq -r '.data["DEFAULT_BUCKET"]'))
	$(eval DEFAULT_REGION= $(shell oc get configmap minio-config -n $(NAMESPACE) -o json | jq -r '.data["DEFAULT_REGION"]'))
	@helm -n $(NAMESPACE) upgrade --install pipeline-server $(PIPELINE_SERVER_CHART) \
		--set minio.apiEndpoint=$(MINIO_API_HOST) \
		--set minio.defaultBucket=$(DEFAULT_BUCKET) \
		--set minio.defaultRegion=$(DEFAULT_REGION) \
		--timeout 300m
```

### Dynamic Bridge Secret Creation

The `create-dynamic-secret` target reads from the MinIO Secret and Service, then creates a new `ds-pipeline-s3-dspa` Secret that downstream charts consume. This bridges MinIO credentials into a format the product-recommender-system chart expects:

```makefile
.PHONY: create-dynamic-secret
create-dynamic-secret:
	$(eval MINIO_SERVICE_HOST = $(shell oc get svc minio-service -n $(NAMESPACE) -o=jsonpath='{.spec.clusterIP}'))
	$(eval MINIO_SERVICE_PORT = $(shell oc get svc minio-service -n $(NAMESPACE) -o=jsonpath='{.spec.ports[?(@.name=="api")].port}'))
	$(eval MINIO_ACCESS_KEY_VALUE = $(shell oc get secret minio-secret -n $(NAMESPACE) -o jsonpath='{.data.MINIO_ROOT_USER}' | base64 --decode))
	$(eval MINIO_SECRET_KEY_VALUE = $(shell oc get secret minio-secret -n $(NAMESPACE) -o jsonpath='{.data.MINIO_ROOT_PASSWORD}' | base64 --decode))
	@oc create secret generic ds-pipeline-s3-dspa -n $(NAMESPACE) \
		--from-literal=host=$(MINIO_SERVICE_HOST) \
		--from-literal=port=$(MINIO_SERVICE_PORT) \
		--from-literal=accesskey=$(MINIO_ACCESS_KEY_VALUE) \
		--from-literal=secretkey=$(MINIO_SECRET_KEY_VALUE) \
		--from-literal=secure=false \
		--dry-run=client -o yaml | oc apply -f -
```

### Credential Validation Before Install

MinIO enforces minimum credential lengths internally, so the Makefile validates early to prevent cryptic failures:

```makefile
MINIMUM_USERID_LENGTH = 3
MINIMUM_PASSWORD_LENGTH = 8

.PHONY: check-minio-credentials
check-minio-credentials:
	@if [ $$(wc -m <<< $(minio.userId)) -lt $$(expr $(MINIMUM_USERID_LENGTH) + 1) ]; then \
		echo "Set minio.userId to a value that is at least $(MINIMUM_USERID_LENGTH) characters in length."; \
		exit 1; \
	fi
```

## Configuration

- **Key settings:** `NAMESPACE` (required, enforced at top of Makefile), `minio.userId`, `minio.password`, `MODEL_NAME`, `MODEL_ENDPOINT`
- **Defaults:** `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=recsys_password`, `POSTGRES_DBNAME=recsys`
- **Dependencies:** `oc` CLI logged into an OpenShift cluster, `helm` CLI, `jq`

## Gotchas

- The bridge secret `ds-pipeline-s3-dspa` uses `--dry-run=client -o yaml | oc apply -f -` for idempotent create/update, sourced from the Makefile's `create-dynamic-secret` target.
- Credentials are passed via `make` arguments (`minio.userId`, `minio.password`) using dot notation rather than environment variables, so they appear in the process table during execution.
- The `pipeline-server-install` target polls for pod readiness with a manual retry loop (`for i in {1..25}; do ... sleep 5; done`) before `oc wait`, because the pod may not exist yet when `oc wait` is first called.
- Uninstall target calls `oc delete project $(NAMESPACE)` which removes the entire namespace, not just the Helm releases.

## Related Patterns

- `helm-independent-subcharts-no-umbrella.md` — same independent chart pattern but without runtime secret bridging
- `helm-dspa-crd-makefile-injected-external-minio.md` — the DSPA CRD that consumes the Makefile-injected values
