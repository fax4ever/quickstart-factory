---
name: tester-cronjob-skopeo-digest-poll-ephemeral-ns-e2e-slack
description: CronJob-based tester that polls image digests via skopeo, deploys to ephemeral namespace, runs Tavern tests, reports to Slack
summary: "Solves periodic end-to-end integration testing of OpenShift-deployed quickstarts by running a CronJob-based tester container that detects image changes via skopeo digest polling against a ConfigMap, deploys to ephemeral namespaces, executes Tavern HTTP tests, and reports results to Slack. Use when you need autonomous recurring E2E validation triggered by image updates rather than CI-event-driven testing -- the CronJob runs every 4 hours with concurrencyPolicy Forbid, backoffLimit 0, startingDeadlineSeconds 300, and 45-minute activeDeadlineSeconds timeout. Critical pattern: the tester Containerfile bundles oc, helm, skopeo, and pytest-tavern with pre-fetched Helm repos, patching the Makefile via sed to skip the depend target at build time; ephemeral namespaces use short pr-test-MMDD-HHMM format to avoid OpenShift Route hostname length limits. Common gotcha: cleanup always exits code 0 regardless of test outcome (failure detection relies solely on Slack webhook messages, not pod exit codes), pipeline completion uses a hardcoded sleep 600 rather than event-driven polling, and the tester ServiceAccount ClusterRole grants full [\"*\"] verbs across all API groups giving cluster-admin-equivalent access."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, helm]
  ai_pattern: [recommendation]
  platform: [openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Dedicated tester container as CronJob with skopeo digest polling, ephemeral namespace deploy/test/cleanup, Tavern integration tests, Slack webhook notification"
    approach: "A"
---

# CronJob Tester with Image Digest Polling and Ephemeral Namespace E2E

## Overview

A dedicated tester container image bundles Helm charts, `oc`/`helm` CLIs, and pytest-tavern test suites. Deployed as a Kubernetes CronJob, it polls container image digests via skopeo, deploys the full system to an ephemeral namespace, runs integration tests, reports results to Slack, and cleans up the namespace regardless of test outcome.

## Pattern Description

The tester operates as a fully autonomous integration test system. Every 4 hours, the CronJob starts and first checks whether the monitored container image has changed by comparing its digest (via skopeo) against a stored digest in a ConfigMap. If no change is detected, the job exits immediately. If the image has changed, it creates a timestamped namespace, runs the full Makefile install, waits for pipeline completion, executes Tavern-based HTTP integration tests, sends results to a Slack webhook, and unconditionally uninstalls and deletes the namespace.

## Implementation

### Tester Containerfile

The tester image bundles all deployment and test dependencies:

```dockerfile
# tester/Containerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && \
    apt-get install -y curl tar jq make bash skopeo && \
    curl -L https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/openshift-client-linux.tar.gz | tar -xz -C /usr/local/bin oc && \
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash && \
    apt-get clean
COPY helm helm
COPY tests tests
COPY ./tester/check_image_and_run_tests.sh check_image_and_run_tests.sh
RUN pip3 install pytest tavern
RUN helm repo add rh-ai-quickstart https://rh-ai-quickstart.github.io/ai-architecture-charts && \
    helm repo update
# Patch Makefile to skip dependency updates (already bundled)
RUN cp /app/helm/Makefile /app/helm/Makefile.original && \
    sed 's/install: check-oc-version check-minio-credentials namespace depend/install: check-oc-version check-minio-credentials namespace/' /app/helm/Makefile.original > /app/helm/Makefile
CMD ["/bin/bash", "./check_image_and_run_tests.sh"]
```

### CronJob Definition

```yaml
# tester/cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: product-recommender-tester
  namespace: product-recommender-testing
spec:
  schedule: "0 */4 * * 0,1-5"  # Every 4 hours, Sunday to Friday
  successfulJobsHistoryLimit: 12
  failedJobsHistoryLimit: 7
  startingDeadlineSeconds: 300
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      activeDeadlineSeconds: 2700  # 45 minute timeout
      backoffLimit: 0
      template:
        spec:
          serviceAccountName: product-recommender-tester
          containers:
          - name: product-recommender-tester
            image: quay.io/rh-ai-quickstart/product-recommender-testing:latest
            env:
            - name: SLACK_WEBHOOK
              valueFrom:
                secretKeyRef:
                  name: slack-webhook
                  key: url
```

### Image Digest Polling

```bash
# tester/check_image_and_run_tests.sh (excerpt)
get_image_digest() {
    local image=$1
    if command -v skopeo &> /dev/null; then
        skopeo inspect --format "{{.Digest}}" docker://$image 2>/dev/null
    else
        docker manifest inspect $image | jq -r '.config.digest' 2>/dev/null
    fi
}
CURRENT_DIGEST=$(get_image_digest $TARGET_IMAGE)
STORED_DIGEST=$(get_stored_digest)  # reads from ConfigMap via oc
if [ "$CURRENT_DIGEST" = "$STORED_DIGEST" ] && [ -n "$STORED_DIGEST" ]; then
    echo "No change detected. Skipping tests."
    exit 0
fi
```

### Ephemeral Namespace Lifecycle and Cleanup

```bash
# Short namespace name to avoid route hostname length issues
TESTING_NAMESPACE="pr-test-$(date +%m%d-%H%M)"
oc create namespace $TESTING_NAMESPACE
trap 'cleanup_and_exit 1' INT TERM EXIT
cd /app/helm
timeout 30m make SHELL=/bin/bash install NAMESPACE=$TESTING_NAMESPACE minio.userId=minio minio.password=minio123
sleep 600  # Wait for pipeline to finish
cd /app/tests/integration
TEST_OUTPUT=$(NAMESPACE=$TESTING_NAMESPACE bash run_integration_tests.sh 2>&1)
ESCAPED_OUTPUT=$(echo "$TEST_OUTPUT" | jq -Rs .)
curl -X POST -H 'Content-type: application/json' --data "{\"text\": $ESCAPED_OUTPUT}" $SLACK_WEBHOOK
```

### ClusterRole for Test ServiceAccount

```yaml
# tester/rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: product-recommender-tester-cluster-role
rules:
- apiGroups: ["*"]
  resources: ["*"]
  verbs: ["*"]
- apiGroups: ["feast.dev"]
  resources: ["*"]
  verbs: ["*"]
- apiGroups: ["datasciencepipelinesapplications.opendatahub.io"]
  resources: ["*"]
  verbs: ["*"]
```

## Configuration

- **Key settings:** `SLACK_WEBHOOK` from Secret, `NAMESPACE` for deployment target, `product-recommender-testing` as the CronJob's home namespace
- **Defaults:** `minio.userId=minio`, `minio.password=minio123` for test installs; 45-minute active deadline; 600-second wait for pipeline completion
- **Dependencies:** ClusterRole with broad permissions across OpenShift, OpenDataHub, and Feast API groups; `slack-webhook` Secret; `frontend-backend-image-digest` ConfigMap for digest storage

## Gotchas

- The `cleanup_and_exit` function always exits with code `0` regardless of test results (by design, as stated in the script: "Exiting gracefully with code: 0"), so CronJob failure detection relies on Slack messages rather than pod exit codes.
- The Makefile is patched at image build time via `sed` to remove the `depend` prerequisite from the `install` target, since Helm repo dependencies are pre-fetched during the image build.
- Namespace names use `pr-test-$(date +%m%d-%H%M)` format to keep them short, avoiding OpenShift Route hostname length limits.
- The `sleep 600` (10-minute hardcoded wait) for pipeline completion is a fixed delay rather than an event-driven check.
- The ClusterRole grants `["*"]` across all API groups and resources, giving the tester SA full cluster-admin-equivalent access.

## Related Patterns

- `github-actions-workflow-run-cascade-build-chain.md` — CI workflows that build the images monitored by this tester
- `makefile-runtime-secret-bridge-multi-chart-oc-discovery.md` — the same Makefile install process used by the tester for ephemeral deploys
