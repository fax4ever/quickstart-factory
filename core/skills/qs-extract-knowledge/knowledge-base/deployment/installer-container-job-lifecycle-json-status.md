---
name: installer-container-job-lifecycle-json-status
description: Containerized installer image running as K8s Job with structured JSON status output, prerequisite checking, and full lifecycle management
summary: "Packages a quickstart's Helm umbrella chart with oc/helm CLIs into a UBI9-minimal installer image that runs as a Kubernetes Job, providing full lifecycle management (CHECK_PRE_REQS, STATUS, INSTALL, UNINSTALL_DELETE_ALL, UNINSTALL_KEEP_DATA, UPGRADE) with structured JSON output for machine parsing via log_status/log_success/log_error/log_prerequisites_failed functions. Use when you need a self-contained installer image that separates deployment logic from the end-user experience, enabling both CLI-driven (deploy.sh) and navigator-driven workflows from one image -- the Job runs in the default namespace while managing resources in a separate TARGET_NAMESPACE via ClusterRole/ClusterRoleBinding/ServiceAccount RBAC created and cleaned up by the client script. ACTION and TARGET_NAMESPACE are required env vars; prerequisite checking validates OpenShift 4.12+, RHBK operator catalog presence, storage class, GPU availability, and 4 CPU/16GB RAM minimum; INSTALL_MODE (default: demo) and GPU toggles (PARAM_OLLAMA_GPU_ENABLED, PARAM_DOCLING_GPU_ENABLED) control behavior; termination messages dual-write to /dev/termination-log (4KB truncated via `printf '%.4096s'`) and as Job annotations for post-pod-GC retrieval, with logs persisted in a 50KB-capped ConfigMap with 7-day expiry labels. The default-to-target namespace separation requires ClusterRoleBinding not namespace-scoped RoleBinding; UNINSTALL_DELETE_ALL deletes the target namespace killing the installer Job before its EXIT trap can clean cluster-scoped RBAC (must be cleaned externally); `helm dependency update` must run pre-build to resolve `file://` Chart.yaml references into bundled tarballs inside the image."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "UBI9-minimal installer image bundling oc CLI + Helm + umbrella chart, runs as Job in default namespace with ACTION-based lifecycle (CHECK_PRE_REQS, STATUS, INSTALL, UNINSTALL_DELETE_ALL, UNINSTALL_KEEP_DATA), structured JSON status output, termination messages, log ConfigMap persistence, and deploy.sh client script"
    approach: "A"
---

# Containerized Installer Job with Lifecycle Management and JSON Status

## Overview

This pattern packages a quickstart's Helm chart, CLI tools (oc, helm), and deployment automation scripts into a container image that runs as a Kubernetes Job. The Job accepts an `ACTION` environment variable to perform different lifecycle operations (install, uninstall, status check, prerequisite validation). All output is structured JSON for machine parsing, with termination messages and log ConfigMap persistence for post-run retrieval.

## Pattern Description

The installer separates the deployment logic from the end-user experience. A client script (`deploy.sh`) creates the required RBAC, submits a Job with the installer image, follows logs, and retrieves the termination message. The installer container (`entrypoint.sh`) sources modular library scripts and dispatches based on the `ACTION` environment variable. This enables both CLI-driven and navigator-driven deployment workflows from the same image.

## Implementation

### Installer Dockerfile

```dockerfile
# installer/Dockerfile
FROM registry.access.redhat.com/ubi9/ubi-minimal:latest

RUN microdnf install -y python3 python3-pip jq tar gzip bc openssl gettext \
    && microdnf clean all

# Install oc CLI
RUN curl -L https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz -o /tmp/oc.tar.gz && \
    tar -xzvf /tmp/oc.tar.gz -C /usr/local/bin/ oc && \
    chmod +x /usr/local/bin/oc && rm /tmp/oc.tar.gz

# Install Helm
RUN curl -L https://get.helm.sh/helm-v3.14.0-linux-amd64.tar.gz | \
    tar -xzv -C /tmp && mv /tmp/linux-amd64/helm /usr/local/bin/helm && \
    chmod +x /usr/local/bin/helm && rm -rf /tmp/linux-amd64

# Copy bundled Helm chart
COPY peoplemesh-umbrella/ /installer/charts/peoplemesh-umbrella/
COPY installer/entrypoint.sh /installer/entrypoint.sh
COPY installer/lib/ /installer/lib/
COPY installer/operators/ /installer/operators/
COPY installer/migrations/ /installer/migrations/

WORKDIR /installer
ENTRYPOINT ["/installer/entrypoint.sh"]
```

### Entrypoint with ACTION Dispatch

```bash
# installer/entrypoint.sh (excerpt)
: "${ACTION:?ACTION must be set (CHECK_PRE_REQS|STATUS|INSTALL|UNINSTALL_DELETE_ALL|UNINSTALL_KEEP_DATA|UPGRADE)}"
: "${TARGET_NAMESPACE:?TARGET_NAMESPACE must be set}"

case "$ACTION" in
  CHECK_PRE_REQS)
    check_prerequisites || exit 2
    log_success "[]"
    ;;
  INSTALL)
    check_prerequisites || exit 2
    deploy_quickstart
    check_deployment_status
    ENDPOINTS=$(get_endpoints)
    log_success "$ENDPOINTS"
    ;;
  UNINSTALL_DELETE_ALL)
    cleanup_quickstart "delete-all"
    verify_deployment
    log_success "[]"
    ;;
esac
```

### Structured JSON Status Output

```bash
# installer/entrypoint.sh (excerpt)
log_status() {
  local status=$1 phase=$2 message=$3
  echo "{\"status\":\"$status\",\"phase\":\"$phase\",\"message\":\"$message\"}"
}

log_success() {
  local endpoints=$1
  echo "{\"status\":\"success\",\"endpoints\":$endpoints}"
}

log_error() {
  local message=$1
  echo "{\"status\":\"error\",\"message\":\"$message\"}" >&2
  exit 1
}

log_prerequisites_failed() {
  local missing_json=$1
  echo "{\"status\":\"prerequisites_failed\",\"missing\":$missing_json}" >&2
  exit 2
}
```

### Termination Message and Log ConfigMap

```bash
# installer/entrypoint.sh (excerpt)
write_termination_message() {
  local exit_code=$1
  local message="{\"status\":\"${status}\",\"action\":\"${ACTION}\",\"namespace\":\"${TARGET_NAMESPACE}\",\"logConfigMap\":{\"name\":\"${cm_name}\",\"namespace\":\"default\"}}"
  printf '%.4096s' "$message" > /dev/termination-log 2>/dev/null || true
  # Annotate the Job for durable retrieval after pod cleanup
  oc annotate job "$JOB_NAME" --namespace default --overwrite \
    "peoplemesh-installer/termination-message=$message" 2>/dev/null || true
}

write_log_configmap() {
  local log_content
  log_content=$(tail -c 51200 "$_LOG_FILE" 2>/dev/null || echo "")
  oc create configmap "$cm_name" --namespace default \
    --from-file=log="$log_tmpfile" 2>/dev/null || true
  oc label configmap "$cm_name" --namespace default --overwrite \
    "app=peoplemesh-installer" \
    "target-namespace=${TARGET_NAMESPACE}" \
    "peoplemesh-installer/expires-at=${expires_at}" 2>/dev/null || true
}
```

### Deploy Script (Client Side)

```bash
# installer/deploy.sh (excerpt)
deploy_job() {
  local ACTION=$1 TARGET_NAMESPACE=$2 EXTRA_ENV=$3
  local INSTALLER_NAMESPACE="default"

  # Create ClusterRole with all permissions needed for installation
  cat <<RBAC | oc apply -f -
  apiVersion: rbac.authorization.k8s.io/v1
  kind: ClusterRole
  metadata:
    name: peoplemesh-installer-${TARGET_NAMESPACE}
  rules:
    - apiGroups: [""] resources: ["nodes"] verbs: ["get", "list"]
    - apiGroups: [""] resources: ["namespaces"] verbs: ["get", "list", "create", "delete"]
    # ... full set of permissions
RBAC

  cat <<EOF | oc apply -f -
  apiVersion: batch/v1
  kind: Job
  metadata:
    name: ${JOB_NAME}
    namespace: ${INSTALLER_NAMESPACE}
  spec:
    backoffLimit: 0
    template:
      spec:
        serviceAccountName: peoplemesh-installer
        containers:
        - name: installer
          image: ${FULL_IMAGE}
          env:
          - name: ACTION
            value: "${ACTION}"
          - name: TARGET_NAMESPACE
            value: "${TARGET_NAMESPACE}"
EOF

  # Follow logs and clean up RBAC after completion
}
```

### Prerequisite Checking

```bash
# installer/lib/check_pre_reqs.sh (excerpt)
check_prerequisites() {
  local missing=()

  # Check OpenShift version >= 4.12
  OCP_VERSION=$(oc version -o json | jq -r '.openshiftVersion' | cut -d. -f1,2)

  # Check RHBK operator availability in catalog
  RHBK_AVAILABLE=$(oc get packagemanifests -n openshift-marketplace rhbk-operator -o json | \
    jq -r '.status.catalogSource')

  # Check storage class with ReadWriteOnce
  # Check GPU availability if requested
  # Check cluster capacity (4 CPU, 16GB RAM minimum)

  if [[ ${#missing[@]} -gt 0 ]]; then
    MISSING_JSON=$(printf '%s\n' "${missing[@]}" | jq -R . | jq -s .)
    log_prerequisites_failed "$MISSING_JSON"
    return 1
  fi
}
```

## Configuration

- **Key settings:** `ACTION` (required env var: CHECK_PRE_REQS, STATUS, INSTALL, UNINSTALL_DELETE_ALL, UNINSTALL_KEEP_DATA); `TARGET_NAMESPACE` (required); `INSTALL_MODE` (default: demo); `PARAM_OLLAMA_GPU_ENABLED`, `PARAM_DOCLING_GPU_ENABLED` (GPU toggles)
- **Defaults:** Installer Job runs in `default` namespace; manages resources in the target namespace; image at `quay.io/rh-ai-quickstart/peoplemesh-installer:1.0.0`; prerequisites: OpenShift 4.12+, RHBK operator in catalog, 4 CPU / 16GB RAM minimum
- **Dependencies:** Installer needs ClusterRole/ClusterRoleBinding for cross-namespace access; `ose-cli:latest` is used for Job containers; the bundled Helm chart must have `helm dependency update` run before building the image

## Gotchas

- The installer Job runs in the `default` namespace but manages resources in the `TARGET_NAMESPACE` -- this separation requires a ClusterRoleBinding, not just a namespace-scoped RoleBinding (see `installer/deploy.sh` lines 92-154)
- When `UNINSTALL_DELETE_ALL` deletes the target namespace, it kills the installer Job before the EXIT trap can clean up cluster-scoped RBAC (ClusterRole, ClusterRoleBinding); these must be cleaned up externally (see `installer/lib/uninstall.sh` lines 195-208 comment)
- The termination message is written to both `/dev/termination-log` (standard K8s mechanism, 4KB limit via printf truncation) and as a Job annotation (for persistence after pod garbage collection) (see `installer/entrypoint.sh` lines 133-141)
- The build script runs `helm dependency update` inside the `peoplemesh-umbrella/` directory before building the image, packaging all local subcharts as tarballs inside the image; the `file://` references in Chart.yaml become resolved tarballs (see `installer/build.sh` lines 54-56)
- The log ConfigMap is capped at 50KB (`tail -c 51200`) and stored in the `default` namespace with a 7-day expiry label for cleanup (see `installer/entrypoint.sh` lines 68-88)
- The `deploy.sh` client cleans up all RBAC resources after Job completion, including the ServiceAccount, Roles, and ClusterRole/ClusterRoleBinding (see `installer/deploy.sh` lines 264-274)

## Related Patterns

- `helm-umbrella-all-local-file-ref-conditional-deps.md` -- the Helm chart bundled inside the installer image
- `container-build-ubi-multistage-fullstack.md` -- UBI-based container builds (different: app container, not deployment tooling)
