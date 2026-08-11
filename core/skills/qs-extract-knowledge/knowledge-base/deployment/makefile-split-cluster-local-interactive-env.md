---
name: makefile-split-cluster-local-interactive-env
description: Two Makefiles (cluster and local) with interactive env var collection script for Helm install
summary: "Splits quickstart deployment into deploy/cluster/Makefile (Helm-based OpenShift install via interactive env collection) and deploy/local/Makefile (podman compose lifecycle via start-dev.sh/stop-dev.sh plus test delegation to tests/run_tests.sh). Use this split-Makefile pattern when the quickstart needs interactive credential collection (API keys, model config, DB passwords) for cluster installs with conditional Helm flags -- the prompt_for_value function skips prompts when vars are pre-set, enabling both interactive and CI flows; also provides build-mcp-images targets iterating MCP_SERVERS with CONTAINER_RUNTIME (default podman) and quay.io/rh-ai-quickstart registry. Critical flow: install-namespace (oc create namespace with modelmesh-enabled=false label) then install_with_env.sh builds helm upgrade --install with conditional --set/--set-json flags for tolerations, MaaS API base, SerpAPI keys, ORACLE subchart toggle, EXTRA_HELM_ARGS injection, and defaults (postgres/rag_password, minio_rag_user/minio_rag_password), followed by oc rollout status verification. Gotchas: use --set-json not --set for JSON array values like tolerations, the NAMESPACE guard uses $(filter...) to enforce only for deployment targets (allowing deps/help without NAMESPACE), and install-namespace labels modelmesh-enabled=false to prevent ModelMesh from interfering with vLLM-based model serving."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, fastapi]
  ai_pattern: [agents, model-serving]
  platform: [openshift]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Cluster Makefile with interactive install_with_env.sh; local Makefile wrapping podman compose"
    approach: "A"
---

# Split Makefiles with Interactive Env Collection

## Overview

This pattern uses two separate Makefiles for cluster deployment and local development. The cluster Makefile drives Helm-based OpenShift deployment through a shell script that interactively collects environment variables (API keys, model config, credentials) and assembles a `helm upgrade --install` command with dozens of `--set` flags. The local Makefile wraps podman compose operations and test commands.

## Pattern Description

Rather than a single top-level Makefile, the two Makefiles live in `deploy/cluster/Makefile` and `deploy/local/Makefile`. The cluster Makefile's `install` target calls `scripts/install_with_env.sh`, which sources `scripts/collect_env_vars.sh` to interactively prompt for values (unless already set via environment variables). This enables both interactive and scripted/CI installation flows. The local Makefile provides compose lifecycle targets and delegates testing to `tests/run_tests.sh`.

## Implementation

### Cluster Makefile Install Flow

The install target chains three steps: namespace creation, dependency update, and scripted installation:

```makefile
# deploy/cluster/Makefile (excerpt)
NAMESPACE ?=
AI_VIRTUAL_AGENT_CHART := helm
AI_VIRTUAL_AGENT_RELEASE := ai-virtual-agent

ifneq (,$(filter install install-status uninstall install-namespace,$(MAKECMDGOALS)))
ifeq ($(NAMESPACE),)
$(error NAMESPACE is not set. Use: make <target> NAMESPACE=<your-namespace>)
endif
endif

install-namespace:
	@oc create namespace $(NAMESPACE) &> /dev/null && oc label namespace $(NAMESPACE) modelmesh-enabled=false ||:
	@oc project $(NAMESPACE) &> /dev/null ||:

install: install-namespace deps
	@./scripts/install_with_env.sh $(NAMESPACE) $(AI_VIRTUAL_AGENT_RELEASE) $(AI_VIRTUAL_AGENT_CHART)
	@oc rollout status deploy/ai-virtual-agent -n $(NAMESPACE)
```

### Interactive Environment Variable Collection

The `collect_env_vars.sh` script prompts for values but skips the prompt if the variable is already set, allowing pre-configuration via environment:

```bash
# deploy/cluster/scripts/collect_env_vars.sh (excerpt)
prompt_for_value() {
    local var_name="$1"
    local prompt_text="$2"
    local default_value="$3"
    local current_value="${!var_name}"
    if [ -n "$current_value" ]; then
        echo "$current_value"
        return
    fi
    if [ -n "$default_value" ]; then
        read -r -p "$prompt_text [$default_value]: " input_value
        echo "${input_value:-$default_value}"
    else
        read -r -p "$prompt_text: " input_value
        echo "$input_value"
    fi
}

HF_TOKEN=$(prompt_for_value "HF_TOKEN" "Enter Hugging Face Token")
ADMIN_USERNAME=$(prompt_for_value "ADMIN_USERNAME" "Enter admin user name")
```

### Helm Command Builder

The install script assembles a helm command with conditional `--set` and `--set-json` flags based on which variables are present:

```bash
# deploy/cluster/scripts/install_with_env.sh (excerpt)
build_helm_cmd() {
    local cmd_args=()
    cmd_args+=("helm" "upgrade" "--install" "$AI_VIRTUAL_AGENT_RELEASE" "$AI_VIRTUAL_AGENT_CHART" "-n" "$NAMESPACE")
    cmd_args+=("--set" "pgvector.secret.user=$POSTGRES_USER")
    if [ -n "$LLM_TOLERATION" ]; then
        cmd_args+=("--set-json" "global.models.$LLM.tolerations=[{\"key\":\"$LLM_TOLERATION\",\"effect\":\"NoSchedule\",\"operator\":\"Exists\"}]")
    fi
    if [ -n "$MAAS_API_BASE" ]; then
        cmd_args+=("--set" "runners.langgraph.llm_api_base=$MAAS_API_BASE")
        cmd_args+=("--set" "runners.crewai.llm_api_base=$MAAS_API_BASE")
    fi
    if [ -n "$SERPAPI_API_KEY" ]; then
        cmd_args+=("--set" "apiKeys.serpapi=$SERPAPI_API_KEY")
        cmd_args+=("--set" "mcp-servers.mcp-servers.hotel.env.SERPAPI_API_KEY=$SERPAPI_API_KEY")
    fi
    "${cmd_args[@]}"
}
```

### MCP Image Build Targets

The cluster Makefile also provides targets for building and pushing MCP server container images:

```makefile
# deploy/cluster/Makefile (excerpt)
CONTAINER_RUNTIME ?= podman
MCP_IMAGE_REGISTRY ?= quay.io/rh-ai-quickstart
MCP_SERVERS := travel_research_mcp hotel_mcp flight_mcp

build-mcp-images:
	@for server in $(MCP_SERVERS); do \
		img_name=$$(echo "mcp-$$server" | sed 's/_mcp$$//; s/_/-/g'); \
		$(CONTAINER_RUNTIME) build -t $(MCP_IMAGE_REGISTRY)/$$img_name:$(MCP_IMAGE_TAG) \
			-f ../../mcp_servers/$$server/Containerfile ../../mcp_servers/$$server; \
	done
```

### Local Makefile

The local Makefile wraps podman compose with `start-dev.sh`/`stop-dev.sh` scripts and delegates testing:

```makefile
# deploy/local/Makefile (excerpt)
compose-up:
	./scripts/start-dev.sh

compose-down:
	./scripts/stop-dev.sh

test-unit:
	cd ../../ && ./tests/run_tests.sh --unit

test: lint test-all
```

## Configuration

- **Key settings:** `NAMESPACE` (required for cluster targets); `CONTAINER_RUNTIME` defaults to `podman`; `ORACLE` flag enables optional Oracle DB subchart
- **Defaults:** Database credentials default to `postgres/rag_password/rag_blueprint`; MinIO defaults to `minio_rag_user/minio_rag_password`
- **Dependencies:** Cluster Makefile requires `oc` CLI, `helm`, and `podman`; local Makefile requires `podman` and `podman compose`

## Gotchas

- The NAMESPACE guard uses `$(filter ...)` to only enforce the check for deployment targets, allowing non-deployment targets like `deps` and `help` to run without NAMESPACE set (see `deploy/cluster/Makefile` lines 50-54)
- The install script uses `--set-json` (not `--set`) for tolerations because the value is a JSON array, which `--set` cannot handle correctly (see `install_with_env.sh` line 51)
- The `install-namespace` target labels the namespace with `modelmesh-enabled=false` to prevent ModelMesh from interfering with vLLM-based model serving (see `deploy/cluster/Makefile` line 107)
- The `EXTRA_HELM_ARGS` variable in the install script allows injecting additional helm flags without modifying the script (see `install_with_env.sh` lines 152-157)

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- the Helm chart installed by this Makefile
- `compose-local-dev-ollama-llamastack-mcp.md` -- the compose stack managed by the local Makefile
