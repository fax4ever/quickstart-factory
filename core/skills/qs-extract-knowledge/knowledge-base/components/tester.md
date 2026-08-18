---
name: tester
description: "CronJob-based on-cluster integration tester that monitors image changes, deploys to ephemeral namespaces, runs Tavern tests, and reports to Slack"
summary: "On-cluster CronJob-based integration tester that monitors container image registries for digest changes via skopeo/ConfigMap comparison, deploys the full quickstart into ephemeral namespaces, runs Tavern YAML-based HTTP integration tests with variable chaining and custom Python validators, reports JSON-escaped results to Slack, and tears down -- enabling automated regression testing on real OpenShift infrastructure without external CI runner cluster access. Use when continuous on-cluster integration testing is needed triggered by image changes rather than git pushes, particularly when tests require live OpenShift resources (routes, model serving, Data Science Pipelines) that cannot be mocked in external CI. Critical config: CronJob schedule \"0 */4 * * 0,1-5\" with concurrencyPolicy: Forbid, activeDeadlineSeconds: 2700; tester ServiceAccount requires wildcard ClusterRole (apiGroups/resources/verbs: \"*\") for namespace creation and Helm installs; namespace labeled modelmesh-enabled=false to prevent ModelMesh sidecar injection; container image bundles oc CLI, skopeo, Helm with pre-registered repos and patched Makefile to skip helm dependency update at runtime. Common gotchas: cleanup always exits code 0 (Slack is the only failure channel -- CronJob status won't reflect test failures); namespace names intentionally short (pr-test-MMDD-HHMM) to avoid 63-char DNS label limit on OpenShift route hostnames; SLACK_WEBHOOK Secret is required for pod startup not just notifications; uses fixed 600s sleep post-install instead of readiness polling, risking premature test runs or wasted wait time."
metadata:
  type: component
tags:
  tech_stack: [python, pytest, tavern, bash, skopeo, oc-cli, helm, jq, curl]
  ai_pattern: [evaluation]
  platform: [openshift, rhoai]
  data_layer: []
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "CronJob that detects frontend-backend image changes via digest comparison, deploys the full system into an ephemeral namespace, runs Tavern integration tests, sends results to Slack, and tears down"
    approach: "A"
---

# Tester

## Overview

An on-cluster continuous integration tester deployed as a Kubernetes CronJob. It monitors a container image registry for digest changes, and when a new image is detected, deploys the entire quickstart into an ephemeral namespace, runs integration tests against the live deployment, reports results to Slack, and tears down the environment. This pattern enables automated regression testing on real OpenShift infrastructure without requiring external CI runners to have cluster access.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 (python:3.12-slim base image)
- **Container image:** `quay.io/rh-ai-quickstart/product-recommender-testing:latest`
- **Key dependencies:** pytest, tavern (YAML-based HTTP integration tests), skopeo (image digest inspection), oc CLI (OpenShift client), helm, jq, make, curl, bash
- **Helm subchart:** N/A (the tester deploys the quickstart's own Helm chart via `make install`)

## Key Patterns

### Image Change Detection via Digest Comparison

The tester avoids unnecessary test runs by comparing the current registry image digest against a stored value in a ConfigMap. Only when the digest changes does it proceed with deployment and testing.

```bash
# tester/check_image_and_run_tests.sh
get_image_digest() {
    local image=$1
    # Try skopeo first (more efficient)
    if command -v skopeo &> /dev/null; then
        skopeo inspect --format "{{.Digest}}" docker://$image 2>/dev/null
    else
        docker manifest inspect $image | jq -r '.config.digest' 2>/dev/null
    fi
}

store_digest() {
    local digest=$1
    local configmap_name="frontend-backend-image-digest"
    local namespace=${NAMESPACE:-"product-recommender-testing"}
    oc patch configmap $configmap_name -n $namespace \
      --type='merge' -p="{\"data\":{\"digest\":\"$digest\"}}"
}
```

### CronJob with Ephemeral Namespace Lifecycle

The CronJob creates a timestamped testing namespace, installs the full system via Helm, waits for readiness, runs tests, and tears down. A trap-based cleanup ensures uninstall happens even on failure.

```yaml
# tester/cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: product-recommender-tester
  namespace: product-recommender-testing
spec:
  schedule: "0 */4 * * 0,1-5"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      activeDeadlineSeconds: 2700
      backoffLimit: 0
      template:
        spec:
          restartPolicy: Never
          serviceAccountName: product-recommender-tester
          containers:
          - name: product-recommender-tester
            image: quay.io/rh-ai-quickstart/product-recommender-testing:latest
```

### Trap-Based Cleanup Guarantee

The script sets a shell trap to ensure the Helm uninstall always runs, even if the script is interrupted or tests fail. The cleanup exits with code 0 to prevent CronJob backoff on test failures.

```bash
# tester/check_image_and_run_tests.sh
cleanup_and_exit() {
    local original_exit_code=${1:-0}
    echo "=== CLEANUP: Ensuring system uninstall ==="
    if [ ! -z "$TESTING_NAMESPACE" ]; then
        cd /app/helm
        make SHELL=/bin/bash uninstall NAMESPACE=$TESTING_NAMESPACE || \
          echo "Uninstall had some issues"
    fi
    echo "Original exit code would have been: $original_exit_code"
    echo "Exiting gracefully with code: 0"
    exit 0
}

trap 'cleanup_and_exit 1' INT TERM EXIT
```

### Short Namespace Names to Avoid Route Length Issues

The testing namespace uses a short timestamp format to prevent OpenShift route hostname length limits from being exceeded.

```bash
# tester/check_image_and_run_tests.sh
TESTING_NAMESPACE="pr-test-$(date +%m%d-%H%M)"
oc create namespace $TESTING_NAMESPACE || echo "Namespace already exists"
oc label namespace $TESTING_NAMESPACE modelmesh-enabled=false || true
```

### Tavern YAML-Based Integration Tests

Integration tests are written as Tavern YAML files, enabling declarative HTTP test flows with variable chaining between stages. A Python helpers module provides custom response validators.

```yaml
# tests/integration/test_user_signup_and_signin.tavern.yaml
test_name: Signup a user and login
stages:
  - name: Test Signup a user
    request:
      url: "{tavern.env_vars.TEST_FRONTEND_URL}/auth/signup"
      method: POST
      json:
        email: "test{tavern.env_vars.TEST_TIMESTAMP}@test.com"
        password: "mypass"
        display_name: "Test User {tavern.env_vars.TEST_TIMESTAMP}"
        age: 25
        gender: "Male"
    response:
      status_code: 201
      save:
        json:
          user_id: "user.user_id"
```

### Slack Notification of Test Results

Test output is captured, JSON-escaped, and sent to a Slack webhook configured via a Kubernetes Secret.

```bash
# tester/check_image_and_run_tests.sh
TEST_OUTPUT=$(NAMESPACE=$TESTING_NAMESPACE bash run_integration_tests.sh 2>&1)
ESCAPED_OUTPUT=$(echo "$TEST_OUTPUT" | jq -Rs .)
curl -X POST -H 'Content-type: application/json' \
  --data "{\"text\": $ESCAPED_OUTPUT}" $SLACK_WEBHOOK
```

### Broad RBAC for Test ServiceAccount

The tester ServiceAccount is granted cluster-wide admin via a ClusterRole to enable namespace creation, Helm installs, and route inspection across OpenShift, OpenDataHub, and Feast API groups.

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
- apiGroups: ["datasciencepipelinesapplications.opendatahub.io"]
  resources: ["*"]
  verbs: ["*"]
- apiGroups: ["feast.dev"]
  resources: ["*"]
  verbs: ["*"]
```

### Containerized Tester Image Build

The tester image bundles the full Helm chart, tests, and CLI tools into a single container. It pre-registers Helm repos and patches the Makefile to skip dependency updates at runtime.

```dockerfile
# tester/Containerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && \
    apt-get install -y curl tar jq make bash skopeo && \
    curl -L https://mirror.openshift.com/.../openshift-client-linux.tar.gz \
      | tar -xz -C /usr/local/bin oc && \
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
COPY helm helm
COPY tests tests
COPY ./tester/check_image_and_run_tests.sh check_image_and_run_tests.sh
RUN pip3 install pytest tavern
RUN helm repo add rh-ai-quickstart \
      https://rh-ai-quickstart.github.io/ai-architecture-charts && \
    helm repo update
```

### Dynamic Route URL Resolution for Tests

The integration test runner resolves OpenShift route URLs dynamically via `oc get routes`, avoiding hardcoded hostnames.

```bash
# tests/integration/run_integration_tests.sh
export TEST_FRONTEND_URL=$(oc get routes product-recommender-system-frontend \
  -n "$NAMESPACE" -o json | jq -r '"https://" + .spec.host')
export TEST_FEAST_URL=$(oc get routes feast-feast-recommendation-ui \
  -n "$NAMESPACE" -o json | jq -r '"https://" + .spec.host')
```

## Configuration

- **Environment variables:**
  - `NAMESPACE` — Target testing namespace (default: `product-recommender-testing`)
  - `SLACK_WEBHOOK` — Slack incoming webhook URL (from Secret `slack-webhook`)
  - `TEST_FRONTEND_URL` — Resolved dynamically from OpenShift route
  - `TEST_FEAST_URL` — Resolved dynamically from OpenShift route
  - `TEST_TIMESTAMP` — Generated at runtime for unique test data isolation
- **Config files:** `tester/cronjob.yaml` (schedule, resource limits, image), `tester/rbac.yaml` (ClusterRole, ClusterRoleBinding, ServiceAccount)
- **Helm values:** N/A (the tester invokes the quickstart's own `make install`/`make uninstall`)

## Known Gotchas

- The cleanup function always exits with code 0 regardless of test outcome (`exit 0` in `cleanup_and_exit`). This prevents CronJob backoff retry logic from kicking in, but means CronJob status does not reflect test failures -- Slack is the only notification channel for failures.
- The namespace name `pr-test-$(date +%m%d-%H%M)` is kept short intentionally. OpenShift route hostnames include the namespace, and long namespace names can exceed the 63-character DNS label limit, causing route creation to fail silently.
- The `modelmesh-enabled=false` label on the testing namespace is required to prevent OpenDataHub ModelMesh from injecting sidecars into pods, which would interfere with the quickstart's own model serving setup.
- The Containerfile patches the Makefile at build time (`sed 's/install: ... depend/install: ... /'`) to remove the `depend` target from the install prerequisite chain. This avoids re-running `helm dependency update` at runtime since repos are pre-registered during image build.
- The script sleeps for 600 seconds (10 minutes) after `make install` to wait for the Data Science Pipeline to complete. This is a fixed delay rather than a readiness poll, which may cause test failures if the pipeline takes longer or waste time if it finishes quickly.
- The tester ClusterRole grants `*` on all API groups and resources. This is intentional because the tester needs to create namespaces, deploy Helm charts, and inspect routes across the cluster, but it represents a broad privilege scope.
- The `SLACK_WEBHOOK` env var is injected from a Kubernetes Secret (`slack-webhook`). If this Secret is missing, the CronJob pod will fail to start (not just fail to send notifications).
- The GitHub Actions workflow (`build-tester-image.yml`) triggers on changes to `tests/`, `tester/`, or `helm/` directories, ensuring the tester image stays in sync with the quickstart's deployment and test code.

## Testing Notes

- To run integration tests manually against a deployed instance: `cd tests/integration && NAMESPACE=<ns> ./run_integration_tests.sh`
- To run a single test file: `./run_integration_tests.sh test_endpoints.tavern.yaml`
- Tavern test files use `{tavern.env_vars.TEST_TIMESTAMP}` to generate unique test user emails, preventing conflicts between concurrent test runs.
- Custom response validation is done via Python helper functions referenced in Tavern YAML as `verify_response_with: function: tests_helpers:validate_product_list`.
- The test runner validates route URLs before starting tests, failing fast if routes return null (indicating the deployment is not ready or routes are misconfigured).

## Related Patterns

- The Tavern test framework complements the pytest marker-based approach in `test-suite.md` -- Tavern is declarative YAML for HTTP flows while pytest markers enable tier-based test selection
- Image digest monitoring relates to CI/CD pipeline patterns for continuous deployment verification
- Ephemeral namespace lifecycle relates to Helm deployment patterns for isolated testing environments
