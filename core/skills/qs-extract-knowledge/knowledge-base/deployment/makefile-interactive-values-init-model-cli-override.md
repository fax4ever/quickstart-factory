---
name: makefile-interactive-values-init-model-cli-override
description: Makefile with interactive values file init from example, HF token prompting, and CLI model/device/toleration overrides
summary: "Provides a single Makefile entry point for Helm values file lifecycle management (copy-from-example, interactive credential prompting, in-place sed updates) and dynamic --set flag assembly from CLI variables, supporting both interactive developer and scripted CI installation flows for a RAG stack (pgvector, llamastack, Streamlit) with optional Ansible-delegated F5 XC infrastructure deployment on OpenShift. Use when you need inline Makefile define blocks to handle values initialization and HF token validation within the Makefile itself -- unlike makefile-split-cluster-local-interactive-env which delegates env collection to external shell scripts; both source examples (f5-api-security and RAG) follow Approach A, where RAG adds TAVILY_SEARCH_API_KEY prompting in validate_values_file, dev-start/dev-stop targets with port-forwarding for local Streamlit development, and an INTERACTIVE=true/false toggle. Two define blocks drive the flow -- check_values_file copies rag-values.yaml.example and pauses for editing (bypassed when LLM is set, enabling CI), while validate_values_file extracts the HF token via sed range pattern /^llm-service:/,/^[^ ]/ and prompts interactively if missing; CLI variables (LLM, SAFETY, DEVICE, LLM_TOLERATION, LLAMA_STACK_ENV, RAW_DEPLOYMENT, EXTRA_HELM_ARGS) are conditionally appended as --set flags to helm upgrade --install. TOLERATIONS_TEMPLATE macro is defined for --set-json but the install target uses individual --set flags instead; oc delete jobs --all must run pre-install to clear completed init jobs blocking Helm upgrade; the sed YAML range pattern assumes standard indentation in the values file; and the values file is gitignored to prevent credential commits."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, ansible, streamlit, llamastack]
  ai_pattern: [rag, model-serving]
  platform: [openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/F5-API-Security"
    notes: "Single Makefile with values file copy-from-example, interactive HF token prompting, dynamic model/device/toleration CLI overrides, and Ansible delegation for F5 XC"
    approach: "A"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Same values file lifecycle and CLI overrides (LLM, SAFETY, DEVICE, tolerations, remote URLs/tokens, RAW_DEPLOYMENT, LLAMA_STACK_ENV, EXTRA_HELM_ARGS), adds TAVILY_SEARCH_API_KEY prompting in validate_values_file, dev-start/dev-stop targets for local Streamlit development with port-forwarding, and INTERACTIVE=true/false toggle; no Ansible delegation"
    approach: "A"
---

# Makefile Interactive Values Init with Model CLI Overrides

## Overview

This pattern uses a single Makefile that manages Helm values file lifecycle (copy from example, validate, interactive prompting), assembles dynamic `--set` flags from CLI variables for model/device/toleration configuration, and delegates F5 XC infrastructure deployment to Ansible. It enables both interactive (developer) and scripted (CI) installation flows from one entry point.

## Pattern Description

The `deploy/helm/Makefile` defines two Makefile `define` blocks (`check_values_file` and `validate_values_file`) that handle values file initialization and validation inline. The `install` target chains dependency update, job cleanup, values validation, and a `helm upgrade --install` with dynamically assembled `HELM_ARGS` based on which CLI variables are set (LLM, SAFETY, DEVICE, tolerations, URLs, API tokens). The same Makefile also provides `f5-deploy` and `f5-clean` targets that wrap `ansible-playbook` for F5 XC Customer Edge deployment, creating a single control plane for both Helm-based application deployment and Ansible-based infrastructure setup.

## Implementation

### Values File Copy-from-Example with Interactive Prompt

The `check_values_file` function auto-copies the example values file, displays an instruction box, and pauses for the user to edit:

```makefile
# deploy/helm/Makefile (check_values_file, lines 36-79)
VALUES_FILE := rag-values.yaml
VALUES_EXAMPLE := rag-values.yaml.example

define check_values_file
    @if [ ! -f "$(VALUES_FILE)" ]; then \
        if [ -f "$(VALUES_EXAMPLE)" ]; then \
            cp "$(VALUES_EXAMPLE)" "$(VALUES_FILE)"; \
            if [ -z "$(LLM)" ]; then \
                echo -e "$(GREEN)... IMPORTANT: Configuration Required ...$(NC)"; \
                echo -e "$(YELLOW)[WAITING]$(NC) Configure rag-values.yaml in another terminal, then press Enter..."; \
                read -p "" continue; \
            fi; \
        else \
            echo -e "$(RED)[ERROR]$(NC) Neither $(VALUES_FILE) nor $(VALUES_EXAMPLE) found."; \
            exit 1; \
        fi; \
    fi; \
    $(call validate_values_file)
endef
```

### Interactive HF Token Validation with sed In-Place Update

The `validate_values_file` function checks the HF token from the values file and prompts interactively if missing, then uses `sed` to update the file in-place:

```makefile
# deploy/helm/Makefile (validate_values_file, lines 82-105)
define validate_values_file
    HF_TOKEN=$$(grep -A 2 "^llm-service:" "$(VALUES_FILE)" | \
        grep "hf_token:" | sed 's/.*hf_token: *//' | tr -d '"' | tr -d ' '); \
    if [ -z "$$HF_TOKEN" ] || [ "$$HF_TOKEN" = "" ]; then \
        read -p "Enter your Hugging Face token (or press Enter to skip): " hf_input; \
        if [ -n "$$hf_input" ]; then \
            sed -i.bak "/^llm-service:/,/^[^ ]/ s|hf_token:.*|hf_token: \"$$hf_input\"|" \
                "$(VALUES_FILE)"; \
        fi; \
    fi; \
    rm -f "$(VALUES_FILE).bak" 2>/dev/null || true
endef
```

### Dynamic HELM_ARGS Assembly from CLI Variables

The `install` target builds up `HELM_ARGS` conditionally based on which Make variables are set, supporting model selection, device type, tolerations, remote URLs, and API tokens:

```makefile
# deploy/helm/Makefile (install target, lines 374-437)
install:
    @HELM_ARGS="-f $(VALUES_FILE)"; \
    if [ -n "$(LLM)" ]; then \
        HELM_ARGS="$$HELM_ARGS --set global.models.$(LLM).enabled=true"; \
        if [ -n "$(LLM_TOLERATION)" ]; then \
            HELM_ARGS="$$HELM_ARGS --set global.models.$(LLM).tolerations[0].key=$(LLM_TOLERATION)"; \
            HELM_ARGS="$$HELM_ARGS --set global.models.$(LLM).tolerations[0].effect=NoSchedule"; \
            HELM_ARGS="$$HELM_ARGS --set global.models.$(LLM).tolerations[0].operator=Exists"; \
        fi; \
    fi; \
    if [ -n "$(DEVICE)" ]; then \
        HELM_ARGS="$$HELM_ARGS --set llm-service.device='$(DEVICE)'"; \
    fi; \
    HELM_ARGS="$$HELM_ARGS $(EXTRA_HELM_ARGS)"; \
    helm -n $(NAMESPACE) upgrade --install $(RAG_CHART) $(RAG_CHART) -n $(NAMESPACE) $$HELM_ARGS
```

### Ansible Delegation for F5 XC Deployment

The Makefile provides `f5-deploy` and `f5-clean` targets that validate secrets, install Ansible collections, and run playbooks:

```makefile
# deploy/helm/Makefile (f5-deploy, lines 489-513)
ANSIBLE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))../ansible

f5-deploy:
    @if [ ! -f "$(ANSIBLE_DIR)/group_vars/all/secrets.yml" ]; then \
        echo -e "$(RED)[ERROR]$(NC) secrets.yml not found"; \
        exit 1; \
    fi
    @ansible-galaxy collection install -r "$(ANSIBLE_DIR)/requirements.yml" \
        --force-with-deps -p "$(ANSIBLE_DIR)/collections"
    @ansible-playbook "$(ANSIBLE_DIR)/site.yml" \
        -e "ansible_collections_path=$(ANSIBLE_DIR)/collections" \
        $(if $(ANSIBLE_TAGS),--tags "$(ANSIBLE_TAGS)",)
```

### Pre-Install Job Cleanup

The install target deletes existing jobs before re-deploying to avoid conflicts with completed init jobs:

```makefile
# deploy/helm/Makefile (delete-jobs, lines 479-483)
delete-jobs:
    @oc delete jobs -n $(NAMESPACE) --all ||:
```

## Configuration

- **Key settings:** `NAMESPACE` (required), `VALUES_FILE` (default `rag-values.yaml`), `LLM` (model name key), `SAFETY` (safety model key), `DEVICE` (cpu/gpu/hpu), `LLM_TOLERATION` / `SAFETY_TOLERATION`, `LLM_URL` / `SAFETY_URL`, `LLM_API_TOKEN` / `SAFETY_API_TOKEN`, `HF_TOKEN`, `RAW_DEPLOYMENT`, `LLAMA_STACK_ENV`, `EXTRA_HELM_ARGS`
- **Defaults:** `VERSION=0.2.22`, `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=rag_password`, `POSTGRES_DBNAME=rag_blueprint`; values file is `.gitignore`d to prevent credential leaks
- **Dependencies:** Requires `helm` and `oc` CLI tools; Ansible playbook for `f5-deploy` requires `ansible-playbook` and `group_vars/all/secrets.yml`

## Gotchas

- The `check_values_file` prompt is bypassed when `LLM` is set on the CLI (line 40: `if [ -z "$(LLM)" ]`), allowing CI pipelines to skip the interactive pause by always providing model selection
- The `sed -i.bak` token update uses a YAML range pattern (`/^llm-service:/,/^[^ ]/`) to scope the replacement to the `llm-service` block -- this assumes standard YAML indentation in the values file
- The `rag-values.yaml` file is `.gitignore`d (`deploy/helm/rag/.gitignore`) to prevent committing secrets; only `rag-values.yaml.example` is tracked
- The `TOLERATIONS_TEMPLATE` macro (line 28: `[{"key":"$(1)","effect":"NoSchedule","operator":"Exists"}]`) is defined for `--set-json` usage but the install target uses individual `--set` flags instead (lines 388-391)
- The `ANSIBLE_DIR` path is derived from the Makefile's own location using `$(dir $(abspath $(lastword $(MAKEFILE_LIST))))../ansible`, making it portable regardless of the working directory
- The `delete-jobs` target runs before install (line 379) to clear completed init jobs from previous installations that would otherwise block Helm upgrade

## Related Patterns

- `ansible-f5xc-mesh-hugepages-prometheus-hostport.md` -- the Ansible playbook invoked by the `f5-deploy` target
- `helm-umbrella-all-remote-ai-arch-deps.md` -- the Helm chart this Makefile installs
- `makefile-split-cluster-local-interactive-env.md` -- alternative approach using external shell scripts for env collection instead of inline Makefile define blocks
