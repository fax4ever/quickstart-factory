---
name: installer
description: Containerized Kubernetes Job-based installer for deploying quickstarts with prereq checks, Helm install, status, and uninstall
summary: "Packages all quickstart deployment lifecycle operations (prerequisite validation, Helm chart installation, OLM operator management, status checks, two-mode uninstall, and version migration with pg_dump backup) into a single UBI9-minimal OCI image running as a Kubernetes Job that emits structured JSON on stdout for orchestrator parsing. Use when deployment must be automated end-to-end via a Job-based workflow with RBAC isolation (installer runs in default namespace with ClusterRole/ClusterRoleBinding scoped to target namespace) and durable result retrieval via /dev/termination-log, Job annotations, and log ConfigMaps (50KB cap, 7-day expiry). Critical config: ACTION env var routes to CHECK_PRE_REQS|STATUS|INSTALL|UNINSTALL_DELETE_ALL|UNINSTALL_KEEP_DATA (UPGRADE declared but rejected); deploy.sh creates ServiceAccount plus scoped RBAC before submitting the Job; prereqs validate OpenShift >=4.12, OLM catalog operator availability, storage classes, and GPU count; bundled Helm umbrella chart at /installer/charts/ installed with params for GPU flags, passwords, and org customization. Key gotchas: duplicate OperatorGroups cause OLM deadlock (guarded via Python-based YAML stripping), delete-all orphans ClusterRole/ClusterRoleBinding due to circular dependency (namespace deletion kills Job before EXIT trap), Keycloak CRDs intentionally not deleted to avoid cluster-wide cascade, exit code 2 signals prereq failure and skips RBAC cleanup, and build context must be repo root since Dockerfile copies umbrella chart from parent directory."
metadata:
  type: component
tags:
  tech_stack: [bash, podman, helm, oc-cli, ubi9-minimal, python3, jq]
  ai_pattern: []
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Self-contained OCI installer image with bundled Helm chart, OLM operator install, RBAC setup, and structured JSON log output for Navigator integration"
    approach: "A"
---

# Installer

## Overview

A containerized installer pattern that packages all deployment logic (prerequisite validation, Helm chart installation, operator lifecycle, status checks, uninstall) into a single OCI image. The image runs as a Kubernetes Job and communicates progress via structured JSON on stdout/stderr. Designed so that an orchestrator (e.g., Project Navigator) can submit a Job, stream its logs, and parse machine-readable status updates.

## Tech Stack & Dependencies

- **Runtime:** Bash scripts on `registry.access.redhat.com/ubi9/ubi-minimal:latest`
- **Container image:** `quay.io/rh-ai-quickstart/peoplemesh-installer:1.0.0`
- **Key dependencies:** `oc` CLI (OpenShift client, downloaded at build), Helm 3.14.0, Python 3, `jq`, `envsubst` (gettext), `bc`, `openssl`
- **Build tool:** Podman (`podman build --platform linux/amd64`)
- **Helm subchart:** Bundles the umbrella chart (`peoplemesh-umbrella/`) inside the image at `/installer/charts/`

## Key Patterns

### Action-Based Entrypoint

The entrypoint routes to different functions based on the `ACTION` environment variable. A single image handles all lifecycle operations.

```bash
# Required env vars validated at startup
: "${ACTION:?ACTION must be set (CHECK_PRE_REQS|STATUS|INSTALL|UNINSTALL_DELETE_ALL|UNINSTALL_KEEP_DATA|UPGRADE)}"
: "${TARGET_NAMESPACE:?TARGET_NAMESPACE must be set}"
: "${INSTALL_MODE:=demo}"

case "$ACTION" in
  CHECK_PRE_REQS) check_prerequisites || exit 2 ;;
  STATUS)         verify_deployment ;;
  INSTALL)        check_prerequisites || exit 2; deploy_quickstart; check_deployment_status ;;
  UNINSTALL_DELETE_ALL) cleanup_quickstart "delete-all" ;;
  UNINSTALL_KEEP_DATA)  cleanup_quickstart "keep-data" ;;
esac
```

### Structured JSON Log Output

All output is JSON on stdout for machine parsing. Functions emit status, success, and error objects. An orchestrator streams these lines to report real-time progress.

```bash
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
```

### Termination Message and Log ConfigMap Persistence

The installer writes a structured termination message to `/dev/termination-log` and also annotates the Job itself, so the orchestrator can retrieve results even after the pod is garbage-collected. All stdout/stderr is tee'd to a log file and persisted as a ConfigMap (capped at 50KB) with a 7-day expiry label.

```bash
# Tee all output to log file
exec 3>&1 4>&2
exec > >(tee -a "$_LOG_FILE") 2> >(tee -a "$_LOG_FILE" >&2)

# EXIT trap writes termination message and log ConfigMap
trap cleanup_on_exit EXIT
```

```bash
# Annotate Job for durable retrieval after pod cleanup
oc annotate job "$job_name" \
  --namespace default --overwrite \
  "peoplemesh-installer/termination-message=$message" 2>/dev/null || true
```

### Prerequisite Validation

The `CHECK_PRE_REQS` action validates cluster readiness before installation. It checks OpenShift version (minimum 4.12), Keycloak Operator availability in the `redhat-operators` catalog with minimum version, storage class existence, GPU availability (when GPU is requested), and cluster CPU/memory capacity.

```bash
# Check Keycloak Operator availability in OLM catalog
RHBK_AVAILABLE=$(oc get packagemanifests -n openshift-marketplace rhbk-operator \
  -o json 2>/dev/null | jq -r '.status.catalogSource' 2>/dev/null)

if [[ "$RHBK_AVAILABLE" != "redhat-operators" ]]; then
  missing+=("Red Hat build of Keycloak Operator not found in catalog")
fi
```

```bash
# GPU check when requested
GPU_COUNT=$(oc get nodes -o json 2>/dev/null | jq '
  [.items[].status.capacity."nvidia.com/gpu" // "0"] |
  map(tonumber) | add // 0' 2>/dev/null)
```

### OLM Operator Installation with Duplicate OperatorGroup Guard

The installer installs the Keycloak Operator via OLM Subscription, but first checks whether an OperatorGroup already exists in the target namespace to avoid the OLM deadlock caused by duplicate OperatorGroups. It uses `envsubst` to template the operator YAML and Python to strip the OperatorGroup document when one already exists.

```bash
local existing_og=$(oc get "$OLM_OPERATORGROUP_RESOURCE" \
  -n "$TARGET_NAMESPACE" -o name 2>/dev/null | head -1)

if [[ -n "$existing_og" ]]; then
  # Strip OperatorGroup from YAML to avoid duplicate
  envsubst '${NAMESPACE} ${CHANNEL} ${STARTING_CSV}' < "$KEYCLOAK_OPERATOR_YAML" | \
    python3 -c "
import sys
docs = sys.stdin.read().split('---')
for doc in docs:
    if 'kind: OperatorGroup' not in doc and doc.strip():
        print('---')
        print(doc, end='')
" | oc create --save-config -f -
fi
```

### Deploy Script Creates RBAC and Submits Job

The `deploy.sh` wrapper (run from a developer workstation) creates a ServiceAccount, Role, RoleBinding in the `default` namespace, plus a ClusterRole/ClusterRoleBinding scoped to the target namespace. It then submits a Kubernetes Job with the installer image and streams its logs.

```bash
# Installer runs in 'default' namespace, manages resources in target namespace
local INSTALLER_NAMESPACE="default"

# Generate unique job name
local JOB_NAME="peoplemesh-installer-$(echo $ACTION | tr '[:upper:]' '[:lower:]' | \
  tr '_' '-')-$(date +%s)"
```

### Uninstall with Data Preservation Option

Two uninstall modes are supported: `delete-all` (removes Helm release, PVCs, Keycloak Operator, and namespace) and `keep-data` (removes Helm release but preserves PVCs, operator, and namespace for reinstallation).

```bash
if [[ "$cleanup_mode" == "delete-all" ]]; then
  oc delete pvc -n "$TARGET_NAMESPACE" --all --wait=false 2>/dev/null || true
  uninstall_keycloak_operator
  oc delete namespace "$TARGET_NAMESPACE" --ignore-not-found=true --wait=false
else
  log_status "running" "uninstalling" "Keeping persistent volumes for future reinstall"
fi
```

### Version Migration Scripts

Upgrade migrations follow a convention-based path: `/installer/migrations/${SOURCE_VERSION}-to-${TARGET_VERSION}.sh`. Before running migrations, the installer backs up the pgvector database via `pg_dump` and stores the backup in a ConfigMap (for databases under 1MB).

```bash
MIGRATION_SCRIPT="/installer/migrations/${SOURCE_VERSION}-to-${TARGET_VERSION}.sh"

# Backup before upgrade
oc exec -n "$TARGET_NAMESPACE" pgvector-0 -- \
  pg_dump -U postgres -d peoplemesh > "$BACKUP_FILE"

# Store small backups in ConfigMap
if [[ $BACKUP_SIZE -lt 1048576 ]]; then
  oc create configmap "$BACKUP_NAME" --from-file="$BACKUP_FILE" -n "$TARGET_NAMESPACE"
fi
```

## Configuration

- **Environment variables:**
  - `ACTION` (required): `CHECK_PRE_REQS`, `STATUS`, `INSTALL`, `UNINSTALL_DELETE_ALL`, `UNINSTALL_KEEP_DATA`, `UPGRADE`
  - `TARGET_NAMESPACE` (required): Kubernetes namespace for the quickstart
  - `INSTALL_MODE` (default: `demo`): Deployment mode
  - `PARAM_KEYCLOAK_REALM_TESTUSER_PASSWORD` (required for INSTALL): Test user password
  - `PARAM_OLLAMA_GPU_ENABLED` / `PARAM_DOCLING_GPU_ENABLED` (optional): GPU acceleration flags
  - `PARAM_PEOPLEMESH_ORGANIZATION_NAME` / `PARAM_PEOPLEMESH_ORGANIZATION_CONTACTEMAIL` (optional): Org customization
  - `SOURCE_VERSION` / `TARGET_VERSION` (required for UPGRADE): Migration version range
  - `JOB_NAME` (set by deploy.sh): Used for log ConfigMap naming and Job annotation
- **Config files:** `installer/operators/keycloak.yaml` (OLM Subscription template with `envsubst` placeholders)
- **Helm values:** Passed through to the umbrella chart's `install.sh` via CLI args (`--namespace`, `--test-password`, `--ollama-gpu`, `--docling-gpu`, `--set`)

## Known Gotchas

- **Duplicate OperatorGroup causes OLM deadlock:** The installer explicitly checks for an existing OperatorGroup before creating one. If two OperatorGroups exist in a namespace, OLM will not install any operators. The code uses a Python snippet to strip the OperatorGroup from the YAML when one already exists (source: `installer/lib/install.sh`, lines 23-43).
- **Cluster-scoped RBAC orphaned on delete-all:** When `UNINSTALL_DELETE_ALL` deletes the namespace, the Job is killed before the EXIT trap can clean up ClusterRole/ClusterRoleBinding resources. This is a circular dependency: deleting either first removes the permission to delete the other. The code documents this explicitly and notes these must be cleaned up externally (source: `installer/lib/uninstall.sh`, lines 193-208).
- **Keycloak CRDs intentionally not deleted on uninstall:** Following OLM best practices, CRD deletion is skipped because it cascades and would destroy all Keycloak instances cluster-wide (source: `installer/lib/uninstall.sh`, line 51 comment).
- **Build context must be the repo root:** The Dockerfile copies `peoplemesh-umbrella/` and `quickstart-manifest.yaml` from the repo root, not from the `installer/` directory. The `build.sh` script validates this (source: `installer/build.sh`, line 41).
- **ConfigMap log capped at 50KB:** The log ConfigMap stores only the most recent 50KB (`tail -c 51200`) since ConfigMaps have a 1MB limit (source: `installer/entrypoint.sh`, line 68).
- **Termination message capped at 4KB:** Kubernetes truncates `/dev/termination-log` to 4KB, so the installer uses `printf '%.4096s'` to pre-truncate (source: `installer/entrypoint.sh`, line 133).
- **UPGRADE action is declared but not supported:** The entrypoint explicitly rejects the UPGRADE action with a `log_error` call before the `case` routing can reach it (source: `installer/entrypoint.sh`, lines 167-170).
- **Exit code 2 means prerequisites failed:** The installer uses distinct exit codes: 0 for success, 1 for general failure, and 2 for failed prerequisites. The EXIT trap detects code 2 to skip RBAC cleanup (source: `installer/entrypoint.sh`, line 153).

## Testing Notes

- **Local testing via podman:** Mount `$HOME/.kube/config` as `/tmp/kubeconfig` and set `KUBECONFIG=/tmp/kubeconfig`. Example: `podman run --rm -e ACTION=CHECK_PRE_REQS -e TARGET_NAMESPACE=test -v $HOME/.kube/config:/tmp/kubeconfig:ro -e KUBECONFIG=/tmp/kubeconfig quay.io/rh-ai-quickstart/peoplemesh-installer:1.0.0`
- **Quick iteration without rebuild:** Mount the `lib/` directory read-only to test script changes: `-v $(pwd)/installer/lib:/installer/lib:ro`
- **Cluster testing:** Use `deploy.sh` to submit as a real Kubernetes Job, which tests RBAC and native execution
- **Platform note:** Image targets `linux/amd64` only; Apple Silicon dev machines use QEMU emulation via podman for local testing

## Related Patterns

- `components/keycloak.md` — Keycloak Operator managed by this installer
- `components/pgvector.md` — Database backed up during upgrade migrations
- `components/ollama.md` — GPU acceleration toggled via installer parameters
