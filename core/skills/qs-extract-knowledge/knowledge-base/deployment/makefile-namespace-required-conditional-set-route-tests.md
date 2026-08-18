---
name: makefile-namespace-required-conditional-set-route-tests
description: Makefile with namespace guard, conditional helm --set-string from env vars, and oc route-based multi-tier test targets
summary: "Provides a Makefile that guards Helm cluster deployments with `ifndef NAMESPACE` error blocks, conditionally injects optional environment variables (OPENAI_API_ENDPOINT, OPENAI_API_TOKEN, OPENAI_MODEL) as `--set-string` flags using Make's `$(if $(VAR),...)` syntax, and wires multi-tier pytest test targets that resolve OpenShift Route URLs for cluster integration testing. Use when the quickstart needs a single Makefile managing Helm deploy with conditional env-var passthrough plus five pytest test tiers (test-unit, test-integration, test-integration-llm, test-cluster, test-cluster-llm) filtered by markers (unit, integration, llm, local_only, cluster_only) -- see makefile-split-cluster-local-interactive-env.md for interactive env setup or makefile-delegating-router-cluster-local.md for a delegating pattern. Critical patterns: deploy-cluster uses `$(if $(OPENAI_API_ENDPOINT),--set-string \"ui.llm.endpoint=$(OPENAI_API_ENDPOINT)\")` with a catch-all `$(HELM_ARGS)` and `--create-namespace`; test targets resolve routes via `oc get route <name> -n $(NAMESPACE) -o jsonpath='{.spec.host}'` to set UI_BASE, ORCH_BASE, and GUARDRAILS_BASE; local deploy uses Podman Compose with `--env-file .env`. The `$(if $(VAR),...)` conditional checks non-emptiness not definedness so `VAR=\"\"` will NOT trigger the --set-string flag; guardrails route uses `2>/dev/null` because the Route may not exist with CRD-based operators; `-include .env` silently ignores a missing .env file; and test-e2e bootstraps MicroShift via ci/setup-microshift.sh rather than running pytest directly."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [agents]
  platform: [openshift]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Makefile with ifndef NAMESPACE error guard, $(if ...) conditional --set-string for optional env vars, and route-based test-cluster/test-cluster-llm targets using pytest markers"
    approach: "A"
---

# Makefile with Namespace Guard, Conditional Helm Set, and Route-Based Test Tiers

## Overview

This pattern provides a Makefile that wraps Helm deployment with required-namespace validation and conditionally passes environment variables as Helm `--set-string` flags, plus multi-tier test targets that resolve OpenShift Route URLs via `oc get route` for cluster-based integration testing with pytest marker-based filtering.

## Pattern Description

The Makefile defines a `deploy-cluster` target that requires a `NAMESPACE` variable (failing with a descriptive error if missing), then runs `helm upgrade --install` with optional `--set-string` flags injected only when the corresponding environment variable is set. Test targets (`test-cluster`, `test-cluster-llm`) similarly require `NAMESPACE` and resolve Route URLs via `oc get route` to set environment variables for pytest, using marker-based filtering to separate LLM-dependent tests from pure integration tests.

## Implementation

### Deploy Target with Namespace Guard and Conditional Sets

```makefile
# Makefile
-include .env

deploy-cluster:
ifndef NAMESPACE
	$(error NAMESPACE is required. Usage: make deploy-cluster NAMESPACE=<oc-project>)
endif
	helm upgrade --install investment-advisor-agent deploy/helm \
		-n $(NAMESPACE) --create-namespace \
		--set namespace=$(NAMESPACE) \
		$(if $(OPENAI_API_ENDPOINT),--set-string "ui.llm.endpoint=$(OPENAI_API_ENDPOINT)") \
		$(if $(OPENAI_API_TOKEN),--set-string "ui.llm.apiToken=$(OPENAI_API_TOKEN)") \
		$(if $(OPENAI_MODEL),--set-string "ui.llm.model=$(OPENAI_MODEL)") \
		$(if $(VITE_ORCHESTRATOR_URL),--set-string "ui.orchestratorUrl=$(VITE_ORCHESTRATOR_URL)") \
		$(HELM_ARGS)
```

### Local Deploy Target

The local deploy target uses Podman Compose with an env file:

```makefile
# Makefile
deploy-local:
	podman compose --env-file .env -f deploy/local/compose.yml up --build
```

### Route-Based Cluster Test Targets

Test targets resolve OpenShift Route URLs and pass them as environment variables to pytest:

```makefile
# Makefile
test-cluster:
ifndef NAMESPACE
	$(error NAMESPACE is required. Usage: make test-cluster NAMESPACE=<oc-project>)
endif
	UI_BASE=http://$(shell oc get route ui -n $(NAMESPACE) -o jsonpath='{.spec.host}') \
	ORCH_BASE=http://$(shell oc get route orchestrator -n $(NAMESPACE) -o jsonpath='{.spec.host}') \
	GUARDRAILS_BASE=http://$(shell oc get route guardrails -n $(NAMESPACE) -o jsonpath='{.spec.host}' 2>/dev/null) \
	pytest tests/integration -m "integration and not llm and not local_only" -v

test-cluster-llm:
ifndef NAMESPACE
	$(error NAMESPACE is required. Usage: make test-cluster-llm NAMESPACE=<oc-project>)
endif
	UI_BASE=http://$(shell oc get route ui -n $(NAMESPACE) -o jsonpath='{.spec.host}') \
	ORCH_BASE=http://$(shell oc get route orchestrator -n $(NAMESPACE) -o jsonpath='{.spec.host}') \
	GUARDRAILS_BASE=http://$(shell oc get route guardrails -n $(NAMESPACE) -o jsonpath='{.spec.host}' 2>/dev/null) \
	pytest tests/integration -m "integration and not local_only" -v
```

### Local and Unit Test Targets

```makefile
# Makefile
test-unit:
	pytest tests/unit -m unit -v

test-integration:
	pytest tests/integration -m "integration and not llm and not cluster_only" -v

test-integration-llm:
	pytest tests/integration -m "integration and not cluster_only" -v

test-e2e:
	ci/setup-microshift.sh
```

## Configuration

- **Key settings:** `NAMESPACE` is required for all cluster targets; `OPENAI_API_ENDPOINT`, `OPENAI_API_TOKEN`, `OPENAI_MODEL` are optional env vars passed as `--set-string` only when set; `HELM_ARGS` allows appending arbitrary Helm flags
- **Defaults:** Helm release name is `investment-advisor-agent`; chart path is `deploy/helm`; `--create-namespace` ensures the namespace exists; local deploy uses `deploy/local/compose.yml`
- **Dependencies:** `-include .env` loads environment variables from a `.env` file (silently ignored if missing); `oc` CLI for route resolution; Podman Compose for local deploy

## Gotchas

- The `$(if $(VAR),...)` Make conditional only checks if the variable is non-empty -- an empty `OPENAI_API_ENDPOINT=""` would NOT trigger the `--set-string` flag, while `OPENAI_API_ENDPOINT=https://...` would (see `deploy-cluster` target)
- The guardrails route resolution uses `2>/dev/null` because the guardrails Route may not exist if guardrails is deployed via the NemoGuardrails CRD operator rather than a standard Route -- the `GUARDRAILS_BASE` variable will be empty in that case (see `test-cluster` target)
- The `-include .env` directive (with the leading dash) silently ignores a missing `.env` file, allowing the Makefile to work without it while still supporting local environment configuration (see top of `Makefile`)
- The five test tiers use pytest markers (`unit`, `integration`, `llm`, `local_only`, `cluster_only`) to select appropriate test subsets for each context -- `test-cluster` excludes `llm` and `local_only`, `test-cluster-llm` excludes only `local_only`, `test-integration` excludes `llm` and `cluster_only` (see all test targets)
- The `test-e2e` target simply runs `ci/setup-microshift.sh` which bootstraps a MicroShift cluster -- it does not run pytest directly, relying on the CI workflow to execute tests after setup (see `Makefile`)

## Related Patterns

- `makefile-split-cluster-local-interactive-env.md` -- alternative Makefile pattern with interactive environment setup
- `makefile-delegating-router-cluster-local.md` -- delegating Makefile pattern
