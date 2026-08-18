---
name: shell-script-two-phase-helm-cluster-autodetect
description: Shell script orchestrating two-phase Helm deploy with cluster state auto-detection and operator skip logic
summary: "Uses a standalone shell script (all-in-one.sh) replacing Makefile orchestration to run two-phase Helm deployment on OpenShift, auto-detecting six cluster values (ingress domain, TLS cert with router-certs-default fallback, image registry, monitoring config, gateway type with Route fallback for non-LoadBalancer) and rendering environment.yaml from a .tpl template via eval/heredoc expansion passed as -f values to both Helm installs. Use when deployment needs cluster-state-dependent config, operator idempotency (queries OLM Subscriptions and sed-disables already-installed operators across 9 toggleable entries), and ordered phasing -- Phase 1 installs dependency-operators chart, oc wait for DataScienceCluster readiness, Phase 2 installs application with all-dependencies.yaml overlay enabling keycloak/devspaces/clusterMonitoring/kuadrant. Critical config: passwords interactively prompted and persisted to .env, KEYCLOAK_CLIENT_SECRET randomly generated, noisy helper censors secrets in logs, StorageClass validated at startup, and environment.yaml.tpl uses shell variable expansion into Helm values. Gotchas: processed flag prevents operator re-detection on reruns, script validates INGRESS_DOMAIN against logged-in cluster preventing cross-cluster mistakes, eval-based template rendering breaks on shell-special characters, and all-dependencies.yaml overlay enables components disabled by default in values.yaml."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [model-serving]
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "all-in-one.sh orchestrates dependency-operators and main chart with cluster auto-detection, interactive prompts, and operator pre-existence skip"
    approach: "A"
---

# Shell Script Two-Phase Helm Deployment with Cluster Auto-Detection

## Overview

This pattern uses a standalone shell script (instead of a Makefile) to orchestrate a two-phase Helm deployment. The script auto-detects cluster state (ingress domain, TLS certificates, image registry availability, monitoring config, gateway type), interactively prompts for sensitive values, persists them to a `.env` file, generates an environment values file from a template, auto-disables operators already installed on the cluster, and runs two sequential `helm upgrade --install` commands with an `oc wait` between them.

## Pattern Description

The `all-in-one.sh` script replaces the Makefile-based orchestration patterns used by other quickstarts. It solves three problems: (1) cluster-specific configuration that cannot be known at chart authoring time, (2) operator installation idempotency where some operators may already exist, and (3) ordered two-phase deployment where operands require their operators to be ready first.

The script generates `environment.yaml` from `environment.yaml.tpl` using shell `eval` and `cat << EOF` heredoc expansion, then passes it as a `-f` values file to both Helm installs. Before the first install, it queries the cluster for already-installed operator Subscriptions and uses `sed` to flip their `enabled: true` to `enabled: false` in the generated file.

## Implementation

### Cluster State Auto-Detection

The script probes the live cluster for six distinct configuration values before any Helm install:

```bash
# all-in-one.sh - Ingress domain and certificate detection
INGRESS_DOMAIN=$(oc get ingresscontroller -n openshift-ingress-operator default \
  -ojsonpath='{.status.domain}' 2>/dev/null)

INGRESS_CERTIFICATE=$(oc get ingresscontroller -n openshift-ingress-operator default \
  -ojsonpath='{.spec.defaultCertificate.name}' 2>/dev/null)
if [ -z "$INGRESS_CERTIFICATE" ]; then
  INGRESS_CERTIFICATE=router-certs-default
  INGRESS_CA="$(oc get secret -n openshift-ingress-operator router-ca \
    -ogo-template='{{ index .data "tls.crt" | base64decode }}')"
else
  INGRESS_CA=""
fi
```

```bash
# all-in-one.sh - Image registry and monitoring detection
if [ "$(oc get config.imageregistry cluster -ogo-template='...')" = "True" ]; then
  TOOLS_IMAGE=image-registry.openshift-image-registry.svc:5000/openshift/tools:latest
else
  TOOLS_IMAGE=quay.io/openshift-release-dev/ocp-v4.0-art-dev@sha256:e850f920...
fi

MONITORING_CONFIG=true
if oc get configmap -n openshift-monitoring cluster-monitoring-config >/dev/null 2>&1; then
  echo "WARNING: Detected an existing cluster monitoring config..." >&2
  MONITORING_CONFIG=false
fi
```

### Gateway Type Detection with Route Fallback

```bash
# all-in-one.sh - Detects non-LoadBalancer ingress and falls back to Route
function gateway_use_route {
  ret=1
  if ! oc get svc -n openshift-ingress router-default >/dev/null 2>&1; then
    ret=0
  fi
  if [ "$(oc get svc -n openshift-ingress router-default \
    -ojsonpath='{.spec.type}')" != "LoadBalancer" ]; then
    ret=0
  fi
  return $ret
}
```

### Interactive Prompts with .env Persistence

```bash
# all-in-one.sh - Passwords prompted once, persisted to .env for reruns
if [ -r .env ]; then
  . .env
fi
if [ -z "$ADMIN_PASSWORD" ]; then
  read -rsp 'Enter a password to set for the admin user: ' ADMIN_PASSWORD
  echo "ADMIN_PASSWORD=\"$ADMIN_PASSWORD\"" >> .env
fi
```

### Operator Pre-Existence Detection

The script queries all existing OLM Subscriptions on the cluster and disables matching operators in the generated environment file using `sed`:

```bash
# all-in-one.sh - Auto-disable already-installed operators
if ! $processed; then
  for operator in $(oc get subscriptions -A \
    -ojsonpath='{range .items[*]}{.spec.name}{"\n"}{end}' 2>/dev/null); do
    sed '/^[[:space:]]*'"$operator"':$/{n; s/enabled: true/enabled: false/;}' \
      environment.yaml > environment.yaml.tmp && mv environment.yaml.tmp environment.yaml
  done
  sed 's/^\([[:space:]]*processed:\) false/\1 true/' \
    environment.yaml > environment.yaml.tmp && mv environment.yaml.tmp environment.yaml
fi
```

### Environment Template with Shell Variable Expansion

```yaml
# environment.yaml.tpl - Rendered via eval "cat << EOF"
global:
  wildcardDomain: ${INGRESS_DOMAIN}
  wildcardCertName: ${INGRESS_CERTIFICATE}
  toolsImage: ${TOOLS_IMAGE}

keycloak:
  removeKubeAdmin: ${REMOVE_KUBE_ADMIN}
  realm:
    openshiftClientSecret: "${KEYCLOAK_CLIENT_SECRET}"
  ingressCA: |-
$(echo "${INGRESS_CA}" | sed 's/^/    /')

install-operators:
  processed: false
  operators:
    devspaces:
      enabled: true
    rhods-operator:
      enabled: true
    # ... 9 operators total
```

### Two-Phase Helm Install with Wait

```bash
# all-in-one.sh - Phase 1: operators, Phase 2: application
noisy helm upgrade --install --timeout 15m0s \
  dependency-operators charts/dependency-operators \
  -f environment.yaml
noisy oc wait --for=condition=Ready datasciencecluster default-dsc --timeout 15m0s

noisy -c "$ADMIN_PASSWORD" -c "$USER_PASSWORD" \
  helm upgrade --install -n default --timeout 20m0s \
  maas-code-assistant charts/maas-code-assistant \
  -f charts/maas-code-assistant/all-dependencies.yaml \
  -f environment.yaml \
  --set keycloak.realm.admin.password="$ADMIN_PASSWORD" \
  --set keycloak.realm.user.password="$USER_PASSWORD"
```

### Censored Command Logging

The `noisy` helper function logs commands while censoring sensitive values:

```bash
# all-in-one.sh - Censored command echo
function noisy {
  local censored=()
  while [ "$1" = "-c" ]; do
    shift; censored+=("$1"); shift;
  done
  local clean="${*}"
  for var in "${censored[@]}"; do
    clean="${clean/$var/<CENSORED>}"
  done
  echo "+ ${clean}"
  "${@}"
}
```

## Configuration

- **Key settings:** `ADMIN_PASSWORD` and `USER_PASSWORD` are interactively prompted and persisted to `.env`; `KEYCLOAK_CLIENT_SECRET` is randomly generated per run; 9 operators can be individually enabled/disabled
- **Defaults:** All 9 operators default to `enabled: true` in `environment.yaml.tpl`; the script auto-disables any that already have OLM Subscriptions
- **Dependencies:** Requires `oc` CLI authenticated to the target cluster; requires a default StorageClass (validated at script start); the `-f all-dependencies.yaml` overlay enables keycloak, devspaces, clusterMonitoring, and kuadrant restart for the main chart

## Gotchas

- The `environment.yaml` includes a `processed: false` flag that gets flipped to `true` after operator pre-existence detection runs, preventing re-detection on script reruns
- The script validates that if `environment.yaml` already exists, its `INGRESS_DOMAIN` matches the currently logged-in cluster, preventing cross-cluster deployment mistakes
- The `all-dependencies.yaml` overlay file enables optional components (keycloak, devspaces, clusterMonitoring, kuadrant.restart) that are disabled by default in `values.yaml`
- The `eval "cat << EOF"` heredoc approach for template rendering means shell-special characters in variable values could break rendering

## Related Patterns

- `helm-olm-generic-operator-subchart-manual-approval.md` -- the install-operators subchart deployed in Phase 1
- `helm-hook-configmap-mounted-script-jobs.md` -- the post-install Jobs triggered by both Helm installs
