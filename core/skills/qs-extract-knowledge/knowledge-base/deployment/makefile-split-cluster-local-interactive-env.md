---
name: makefile-split-cluster-local-interactive-env
description: Two Makefiles (cluster and local) with interactive env var collection script for Helm install
summary: "Splits quickstart deployment into deploy/cluster/Makefile (Helm-based OpenShift install via interactive env collection) and deploy/local/Makefile (podman compose lifecycle via start-dev.sh/stop-dev.sh plus test delegation), with two approaches: Approach A uses two standalone Makefiles with external shell scripts (install_with_env.sh, collect_env_vars.sh) assembling --set flags and a $(filter...) NAMESPACE guard that errors only on deployment targets; Approach B uses a three-tier root router (local/%, cluster/% pattern rules) with inline Makefile define-block credential prompting that writes to a temporary values YAML file, defaults NAMESPACE to current oc project, and runs hybrid local dev (infra in compose, apps native via uv run). Critical flow: prompt_for_value skips prompts when vars are pre-set (enabling CI), then install-namespace creates namespace with modelmesh-enabled=false label, then helm upgrade --install assembles conditional --set/--set-json flags for tolerations, MaaS API base, SerpAPI keys, ORACLE subchart toggle, EXTRA_HELM_ARGS injection, and defaults (postgres/rag_password, minio_rag_user/minio_rag_password); also provides build-mcp-images targets iterating MCP_SERVERS with CONTAINER_RUNTIME (default podman) and quay.io/rh-ai-quickstart registry. Gotchas: use --set-json not --set for JSON array values like tolerations, Approach B's temporary values file (/tmp/rhdp-values.yaml) contains plaintext secrets and persists if install fails before rm -f, install-namespace labels modelmesh-enabled=false to prevent ModelMesh interfering with vLLM serving, and .env loading differs between approaches (.EXPORT_ALL_VARIABLES vs include ../../.env)."
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
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Three-tier delegating Makefile with inline bash credential prompting and hybrid compose+native processes"
    approach: "B"
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

---

## Approach B: Delegating Root Makefile with Inline Credential Prompting (from ansible-log-analysis)

### When to Use

When the quickstart has a three-tier Makefile structure with a root router, and credentials are collected inline in the Makefile rather than via external shell scripts. Also suitable when the local development uses a hybrid of compose services and native Python processes.

### Differences from Approach A

- Root Makefile delegates via pattern rules (`local/%` and `cluster/%`) to subdirectory Makefiles, rather than having two standalone Makefiles
- Credential collection is done via inline bash in the Helm Makefile's `define` block, not via external scripts
- Credentials are written to a temporary values file passed to `helm install`, rather than assembled as `--set` flags
- Local dev runs backend, UI, and annotation natively via `uv run` (not in compose), while infrastructure stays in compose
- No external `install_with_env.sh` or `collect_env_vars.sh` scripts

### Root Makefile Router

```makefile
# Makefile (root)
local/%:
	@$(MAKE) -C deploy/local $*

cluster/%:
	@$(MAKE) -C deploy/helm $*
```

### Inline Credential Prompting

The Helm Makefile uses a `define` block with inline bash for credential collection, skipping prompts when variables are pre-set via `.env`:

```makefile
# deploy/helm/Makefile (excerpt)
define prompt_openai_credentials
	@bash -c '\
	if [ -z "$(OPENAI_API_TOKEN)" ]; then \
		echo -n "Enter LLM API TOKEN: "; read -s OPENAI_API_TOKEN; echo ""; \
	else \
		OPENAI_API_TOKEN="$(OPENAI_API_TOKEN)"; \
	fi; \
	echo "backend:" > $(MODEL_VALUES_FILE); \
	echo "  secret:" >> $(MODEL_VALUES_FILE); \
	echo "    OPENAI_API_TOKEN: \"$$OPENAI_API_TOKEN\"" >> $(MODEL_VALUES_FILE)'
endef

install: namespace
	$(call prompt_openai_credentials)
	helm install $(ANSIBLE_LOG_MONITOR_CHART) ./ansible-log-monitor -n $(NAMESPACE) $(env_args) -f $(MODEL_VALUES_FILE)
	@rm -f $(MODEL_VALUES_FILE)
```

### Gotchas (Approach B)

- The temporary values file (`/tmp/rhdp-values.yaml`) contains plaintext secrets and could be left on disk if the install fails before the `rm -f` runs
- The Helm Makefile loads `.env` from `../../.env` via `include`, while the root Makefile uses `.EXPORT_ALL_VARIABLES`
- NAMESPACE defaults to `$(shell oc project -q 2>/dev/null || echo "default")` rather than requiring it (no error on missing NAMESPACE for install targets)

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Makefile tiers | 2 (cluster + local) | 3 (root router + cluster + local) |
| Credential collection | External shell scripts | Inline bash in Makefile define |
| Credential passing to Helm | `--set` flags assembled in script | Temporary values YAML file |
| NAMESPACE handling | Error if not set (filter guard) | Defaults to current oc project |
| Local app processes | All in compose | Hybrid: infra in compose, apps native via uv |
