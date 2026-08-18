---
name: github-actions-microshift-e2e-crd-stubs-containerized-tests
description: MicroShift-based E2E with KServe/NemoGuardrails CRD stubs, containerized pytest runner, and parallel setup
summary: "Enables GitHub Actions E2E testing by deploying a Helm-based application onto a single-node MicroShift (OKD) cluster running in a Podman container, with KServe CRDs installed via Helm OCI chart (oci://ghcr.io/kserve/charts/kserve-crd) and NemoGuardrails CRD via kubectl -- both as stubs without controllers or reconciliation. Use when you need reproducible CI E2E tests against OpenShift-like APIs (Routes, CRDs, PVCs) without a full cluster; tests execute inside a pre-built python:3.12-slim container image via sudo podman run --network=host with route resolution via /etc/hosts mapped to the MicroShift container IP. Critical config: parallel setup runs MicroShift bootstrap and test image loading concurrently via background process, actions/cache@v4 caches all images, kubeconfig is extracted and rewritten to the container IP with --insecure-skip-tls-verify=true, marker-based pytest split separates LLM tests (conditional on OPENAI_API_TOKEN) from non-LLM tests, and a guidelines-docs Secret must be created from the actual PDF before Helm install. CRD stubs without controllers means CRs (InferenceService, NemoGuardrails) are stored but never reconciled -- no status updates or pods spawned so oc wait --for=condition=Ready uses || true; manual hostPath PersistentVolume with claimRef pre-binding is required for MinIO since MicroShift lacks a dynamic provisioner; MicroShift tag is resolved from GitHub API with a hardcoded fallback for rate-limit resilience."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python, pytest]
  ai_pattern: [agents, model-serving, guardrails]
  platform: [openshift, kserve]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "MicroShift E2E with KServe CRDs via Helm OCI, NemoGuardrails CRD via kubectl, pre-built test container image, parallel MicroShift+tests-image setup, marker-based LLM/non-LLM test split"
    approach: "A"
---

# MicroShift E2E with CRD Stubs and Containerized Test Runner

## Overview

This pattern runs end-to-end tests against a Helm-deployed application on a single-node MicroShift (OKD) cluster running inside a Podman container, with KServe and NemoGuardrails CRDs installed as stubs (no controllers). Tests execute inside a pre-built container image pulled from the registry, enabling reproducible test environments without installing Python dependencies in CI.

## Pattern Description

The `e2e-microshift.yml` workflow provisions a MicroShift cluster via a dedicated `ci/setup-microshift.sh` script, which clones the upstream MicroShift repo, starts MicroShift in a Podman container, installs KServe CRDs via Helm OCI chart, and installs the NemoGuardrails CRD via kubectl. The application is then deployed via `make deploy-cluster`, and tests run from a pre-built test container image using `sudo podman run --network=host`. The setup parallelizes MicroShift bootstrap and test image loading to reduce CI time.

## Implementation

### MicroShift Setup Script

The `ci/setup-microshift.sh` script handles the full cluster lifecycle: clone, image pull/cache, start, kubeconfig extraction, and CRD installation:

```bash
# ci/setup-microshift.sh (excerpt)
# Start MicroShift
make -C "$MICROSHIFT_DIR" run
make -C "$MICROSHIFT_DIR" run-ready
make -C "$MICROSHIFT_DIR" run-healthy

# Extract kubeconfig and fix server address
sudo podman cp microshift-okd-1:/var/lib/microshift/resources/kubeadmin/kubeconfig "$KUBECONFIG"
MICROSHIFT_IP=$(sudo podman inspect microshift-okd-1 | \
  jq -r '.[0].NetworkSettings.Networks | to_entries[0].value.IPAddress')
sed -i "s|server: https://.*:6443|server: https://${MICROSHIFT_IP}:6443|" "$KUBECONFIG"
oc config set-cluster "$CLUSTER_NAME" --insecure-skip-tls-verify=true

# Install KServe CRDs via Helm OCI (no controller)
helm install kserve-crd oci://ghcr.io/kserve/charts/kserve-crd \
  --version "$KSERVE_VERSION" \
  --namespace kserve --create-namespace \
  --wait --timeout 120s

# Install NemoGuardrails CRD (no controller)
oc apply -f "${NEMO_CONTROLLER_REPO}/config/crd/bases/trustyai.opendatahub.io_nemoguardrails.yaml"
```

### Parallel Setup in Workflow

MicroShift bootstrap and test image loading run in parallel via background process:

```yaml
# .github/workflows/e2e-microshift.yml (Setup step)
- name: Setup MicroShift and prepare tests image (parallel)
  run: |
    export MICROSHIFT_IMAGE_CACHE=/tmp/cache/microshift.tar
    export MICROSHIFT_TAG="${{ steps.microshift-tag.outputs.tag }}"
    ci/setup-microshift.sh &
    MICROSHIFT_PID=$!

    mkdir -p /tmp/cache
    if [ -f /tmp/cache/tests.tar ]; then
      echo ">>> Loading tests image from cache..."
      sudo podman load -i /tmp/cache/tests.tar
    else
      echo ">>> Pulling tests image (cache miss)..."
      sudo podman pull "${APP_REPO}:tests"
      sudo podman save -o /tmp/cache/tests.tar "${APP_REPO}:tests"
    fi

    echo ">>> Waiting for MicroShift setup to finish..."
    wait $MICROSHIFT_PID
```

### Containerized Test Runner

Tests run inside a pre-built container image with `--network=host` for access to cluster routes:

```yaml
# .github/workflows/e2e-microshift.yml (Run tests step)
- name: Run integration tests (no LLM)
  run: |
    sudo podman run --rm --network=host \
      -v "${{ github.workspace }}:/workspace:ro,Z" \
      -v /usr/local/bin/oc:/usr/local/bin/oc:ro \
      -v "${KUBECONFIG}:${KUBECONFIG}:ro" \
      -e KUBECONFIG="${KUBECONFIG}" \
      -e NAMESPACE="${NAMESPACE}" \
      -e UI_BASE="${{ steps.routes.outputs.UI_BASE }}" \
      -e ORCH_BASE="${{ steps.routes.outputs.ORCH_BASE }}" \
      -e GUARDRAILS_BASE="${{ steps.routes.outputs.GUARDRAILS_BASE }}" \
      "${APP_REPO}:tests" \
      tests/integration \
      -m "integration and not llm and not local_only and not requires_controllers" -v
```

### Test Container Dockerfile

The test image bundles pytest and all required dependencies:

```dockerfile
# tests/Dockerfile
FROM python:3.12-slim

COPY tests/requirements.txt /tmp/test-requirements.txt
COPY orchestrator/src/requirements.txt /tmp/orchestrator-requirements.txt

RUN pip install --no-cache-dir \
        -r /tmp/test-requirements.txt \
        -r /tmp/orchestrator-requirements.txt && \
    rm /tmp/test-requirements.txt /tmp/orchestrator-requirements.txt

WORKDIR /workspace
ENTRYPOINT ["pytest"]
```

### Route Resolution and Networking

Routes are mapped to the MicroShift container IP via /etc/hosts:

```yaml
# .github/workflows/e2e-microshift.yml
- name: Setup route networking
  run: |
    MICROSHIFT_IP=$(sudo podman inspect microshift-okd-1 \
      | jq -r '.[0].NetworkSettings.Networks | to_entries[0].value.IPAddress')
    for route in $(oc get routes -n "$NAMESPACE" -o jsonpath='{.items[*].spec.host}'); do
      echo "$MICROSHIFT_IP $route" | sudo tee -a /etc/hosts
    done
```

### Marker-Based LLM/Non-LLM Test Split

Non-LLM tests always run; LLM tests require the `OPENAI_API_TOKEN` secret:

```yaml
# .github/workflows/e2e-microshift.yml
- name: Run E2E tests (LLM)
  if: env.OPENAI_API_TOKEN != ''
  run: |
    sudo podman run --rm --network=host \
      ...
      "${APP_REPO}:tests" \
      tests/integration \
      -m "integration and llm and not local_only and not requires_controllers" -v
```

## Configuration

- **Key settings:** `KUBECONFIG=/tmp/microshift-kubeconfig`; `KSERVE_VERSION=v0.16.0` for CRD Helm chart; `NAMESPACE=ci-e2e`; MicroShift tag resolved from GitHub API with hardcoded fallback
- **Defaults:** 30-minute job timeout; MicroShift bootc image, oc CLI, and test image are all cached via `actions/cache@v4`; KServe CRDs installed with `--wait --timeout 120s`
- **Dependencies:** MicroShift requires `sudo podman` and privileged container access; test image requires pytest, httpx, and orchestrator dependencies; Helm CLI installed via `azure/setup-helm@v4`; oc CLI downloaded from Red Hat mirror

## Gotchas

- CRDs are installed without controllers, so CRs (InferenceService, NemoGuardrails) are created and stored but never reconciled -- there are no status updates and no pods spawned by KServe; the workflow explicitly notes `oc wait --for=condition=Ready isvc/guidelines-mlp --timeout=10s || true` as best-effort (see `ci/setup-microshift.sh` header comment and `e2e-microshift.yml` rollout step)
- The `--insecure-skip-tls-verify=true` flag is set on the kubeconfig because the MicroShift server cert is issued for localhost/internal names, not the container IP used from the host (see `ci/setup-microshift.sh`)
- The workflow manually creates a PersistentVolume with `hostPath` for MinIO storage because MicroShift does not have a dynamic provisioner for HostPath PVCs by default; the `claimRef` is set to pre-bind to the PVC created by the Helm chart (see `e2e-microshift.yml` "Create namespace and prerequisites" step)
- A `guidelines-docs` Secret is created from the actual PDF file before Helm install because the Helm chart's guidelines deployment mounts this Secret as a volume (see `e2e-microshift.yml` prerequisites step)
- The `skip_image_cache` workflow dispatch input allows skipping image build/cache for faster iteration when images are already in the registry (see `e2e-microshift.yml` inputs)
- The MicroShift tag is resolved from the GitHub API at runtime with a hardcoded fallback (`4.21.0_g29f429c21_4.21.0_okd_scos.ec.15`) in case of API rate limiting (see `e2e-microshift.yml` "Resolve MicroShift release tag" step)

## Related Patterns

- `github-actions-kind-e2e-maas-openshift-crd-stubs.md` -- alternative Kind-based approach with inline stub CRDs and MaaS remote inference
- `helm-kserve-mlserver-sklearn-minio-rawdeployment.md` -- the KServe InferenceService deployed in these tests
