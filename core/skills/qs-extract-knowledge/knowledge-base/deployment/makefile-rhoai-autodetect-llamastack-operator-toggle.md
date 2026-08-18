---
name: makefile-rhoai-autodetect-llamastack-operator-toggle
description: Makefile auto-detects RHOAI version and LlamaStack operator state from cluster to toggle deployment mode
summary: "Auto-detects RHOAI version (2.x vs 3.x) from redhat-ods-operator CSV via $(findstring 3.,...) and LlamaStack operator managementState from DataScienceCluster at Makefile parse time using ifeq/ifneq conditionals around $(shell oc ...), toggling between Helm chart and operator-based LlamaStack deployment without user intervention (defaults to RHOAI 2 / Helm chart on detection failure). Use when deploying quickstarts across RHOAI 2.x and 3.x clusters with optional LlamaStack operator -- the toggle controls helm_llama_stack_args template arguments (--set llama-stack.managedByOperator=true, --set llama-stack.network.allowedFrom.namespaces[0]=$(NAMESPACE)) and sets LLAMA_STACK_SVC_NAME to llamastack-service (operator) or llamastack (Helm); also auto-detects LOGGING_CHANNEL/LOGGING_STARTING_CSV from oc get packagemanifest -l catalog=redhat-operators. Both RHOAI_VERSION and USE_LLAMA_STACK_OPERATOR are exported for recursive $(MAKE) with $(origin) checks distinguishing undefined/file/command-line to respect explicit overrides, skip re-detection, and prevent CI version-bump corruption. Critical gotchas: RHOAI_VERSION avoids ?= because CI version-bump workflows set environment variables that override conditional assignment; check managementState not CRD existence (CRDs persist after operator disable); operator mode validates RHOAI_VERSION=3 via $(error); Logging/Loki channel queries must use -l catalog=redhat-operators to exclude community-operators alpha channel."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python]
  ai_pattern: [rag, model-serving]
  platform: [openshift, rhoai, kserve, vllm]
  data_layer: [pgvector]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "Auto-detects RHOAI 2.x vs 3.x and LlamaStack operator managementState; toggles between Helm chart and operator deployment with exported vars for recursive make"
    approach: "A"
---

# Makefile RHOAI Version Autodetect with LlamaStack Operator Toggle

## Overview

This pattern auto-detects the RHOAI (Red Hat OpenShift AI) version and LlamaStack operator state from the live cluster at Makefile parse time, switching between Helm chart-based and operator-based LlamaStack deployment without user intervention. The detected values are exported for recursive `$(MAKE)` calls and respect explicit user overrides.

## Pattern Description

The Makefile queries the cluster using `oc` commands during variable assignment (not recipe execution). It detects the RHOAI version from the CSV in `redhat-ods-operator` namespace and the LlamaStack operator's `managementState` from the `DataScienceCluster` resource. Based on these, it toggles `USE_LLAMA_STACK_OPERATOR` between `true` and `false`, which changes the Helm chart values passed to `helm upgrade --install` (e.g., `--set llama-stack.managedByOperator=true`). The LlamaStack service name changes accordingly (`llamastack-service` for operator vs `llamastack` for Helm chart).

## Implementation

### RHOAI Version Auto-Detection

```makefile
# Makefile
# Auto-detect RHOAI version from the cluster when not already set.
# RHOAI_VERSION is NOT declared with ?= to avoid corruption by the version-bump workflow.
# Only auto-detect if undefined to avoid re-detection in recursive make calls.
ifeq ($(origin RHOAI_VERSION),undefined)
  _RHOAI_CSV := $(shell oc get csv -n redhat-ods-operator \
    -l operators.coreos.com/rhods-operator.redhat-ods-operator \
    -o jsonpath='{.items[0].spec.version}' 2>/dev/null)
  ifneq ($(findstring 3.,$(_RHOAI_CSV)),)
    $(info Auto-detected RHOAI 3.x ($(_RHOAI_CSV)) - setting RHOAI_VERSION=3)
    RHOAI_VERSION := 3
  else
    RHOAI_VERSION := 2
  endif
endif
```

### LlamaStack Operator Auto-Detection

```makefile
# Makefile
# Auto-detect LlamaStack operator on RHOAI 3.x: if the operator is set to Managed
# in the DataScienceCluster, automatically use operator-based deployment.
# Checks managementState (not just CRD existence) because CRDs can persist after
# the operator is disabled.
# Respects explicit user override: if USE_LLAMA_STACK_OPERATOR is set on the command
# line, skip auto-detection entirely.
ifeq ($(RHOAI_VERSION),3)
ifeq ($(origin USE_LLAMA_STACK_OPERATOR),file)
ifneq ($(USE_LLAMA_STACK_OPERATOR),true)
  _LLAMA_OP_STATE := $(shell oc get datasciencecluster \
    -o jsonpath='{.items[0].spec.components.llamastackoperator.managementState}' \
    2>/dev/null)
  ifeq ($(_LLAMA_OP_STATE),Managed)
    $(info Auto-detected LlamaStack operator (Managed) - switching to operator mode)
    USE_LLAMA_STACK_OPERATOR := true
  endif
endif
endif
endif

# Export so recursive $(MAKE) calls inherit and skip re-detection
export USE_LLAMA_STACK_OPERATOR
export RHOAI_VERSION
```

### Service Name Toggle and Validation

```makefile
# Makefile
# LlamaStack service name changes based on deployment mode
ifeq ($(USE_LLAMA_STACK_OPERATOR),true)
  LLAMA_STACK_SVC_NAME := llamastack-service
else
  LLAMA_STACK_SVC_NAME := llamastack
endif

# Validate: LlamaStack operator requires RHOAI 3.x
ifeq ($(USE_LLAMA_STACK_OPERATOR),true)
ifneq ($(RHOAI_VERSION),3)
  $(error USE_LLAMA_STACK_OPERATOR=true requires RHOAI_VERSION=3.)
endif
endif
```

### Helm Argument Templates Using Toggle

```makefile
# Makefile
helm_llama_stack_args = \
    $(if $(LLM),--set global.models.$(LLM).enabled=true,) \
    $(if $(LLM_URL),--set global.models.$(LLM).url='$(call process_llm_url)',) \
    $(if $(filter true,$(USE_LLAMA_STACK_OPERATOR)),\
      --set llama-stack.managedByOperator=true \
      --set 'llama-stack.network.allowedFrom.namespaces[0]=$(NAMESPACE)',)
```

### Operator Channel Auto-Detection from Catalog

```makefile
# Makefile
# Logging/Loki operator channels auto-detected from the cluster's redhat-operators catalog.
# Must query with -l catalog=redhat-operators because loki-operator also exists
# in community-operators (with only an 'alpha' channel).
LOGGING_CHANNEL := $(shell oc get packagemanifest -l catalog=redhat-operators \
    -o jsonpath='{range .items[?(@.metadata.name=="cluster-logging")]}{.status.defaultChannel}{end}' \
    2>/dev/null)
LOGGING_STARTING_CSV := $(shell oc get packagemanifest -l catalog=redhat-operators \
    -o jsonpath='{range .items[?(@.metadata.name=="cluster-logging")].status.channels[?(@.name=="$(LOGGING_CHANNEL)")]}{.currentCSV}{end}' \
    2>/dev/null)
```

## Configuration

- **Key settings:** `USE_LLAMA_STACK_OPERATOR` (default: false, auto-detected on RHOAI 3.x), `RHOAI_VERSION` (auto-detected, values: 2 or 3), `LLM` (model ID), `LLM_URL` (external model URL)
- **Defaults:** RHOAI_VERSION defaults to 2 if CSV detection fails; USE_LLAMA_STACK_OPERATOR defaults to false unless operator is Managed
- **Dependencies:** Requires `oc` CLI authenticated to the target cluster; `oc get csv`, `oc get datasciencecluster`, `oc get packagemanifest` must succeed for auto-detection

## Gotchas

- `RHOAI_VERSION` is intentionally NOT declared with `?=` (Make conditional assignment) to avoid corruption by the version-bump CI workflow which sets environment variables -- the `$(origin RHOAI_VERSION)` check distinguishes "undefined" from "set by file" from "set by command line"
- The LlamaStack auto-detection checks `managementState` not just CRD existence because CRDs can persist after the operator is disabled
- `$(origin USE_LLAMA_STACK_OPERATOR)` is checked for `file` (meaning set in the Makefile itself) -- if the user explicitly passes `USE_LLAMA_STACK_OPERATOR=false` on the command line, auto-detection is skipped entirely
- Operator channels for Logging and Loki are queried with `-l catalog=redhat-operators` because the loki-operator also exists in community-operators with only an 'alpha' channel

## Related Patterns

- `makefile-validate-infra-kserve-webhook-gpu.md` -- pre-flight validation patterns
- `deploy-script-conditional-env-helm-set-cluster-autodiscovery.md` -- cluster autodiscovery in deploy scripts
