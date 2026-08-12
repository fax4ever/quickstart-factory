---
name: makefile-multi-image-runtime-type-deploy-switch
description: Makefile building 6 container images with deploy targets switching between OpenVINO CPU and KServe/Triton GPU runtimes
summary: "Solves building and pushing 6 container images (backend, frontend, data, eval, runtime, jupyter-training) in a monorepo with deploy targets that switch between OpenVINO CPU and KServe/Triton GPU model serving runtimes via a RUNTIME_TYPE variable defaulting to openvino. Use deploy-cpu (openvino), deploy-gpu (kserve/triton), or deploy-openvino-labelstudio targets when a quickstart needs multi-image builds with runtime-based deploy switching; prefer makefile-split-cluster-local-interactive-env for separate cluster/local Makefiles or makefile-interactive-values-init-model-cli-override for alternative credential collection. Deploy target chains helm-deps and check-openai-env (interactive .env creation for OPENAI_API_TOKEN/ENDPOINT/MODEL), auto-discovers OpenShift ingress domain via `oc get ingresses.config/cluster`, and passes RUNTIME_TYPE, credentials, route hosts, and LABEL_STUDIO_ENABLED via 15+ Helm --set flags with conditional `${host:+--set ...}` expansion. Push targets verify `podman image exists` before pushing to prevent stale image pushes; data image build context must be `app/` (not `app/data-image/`) because its Dockerfile references `app/models/` and `app/data/`; LABEL_STUDIO_ENABLED uses `$(if $(strip ...))` to avoid accidental disabling when the variable is empty."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python, nodejs]
  ai_pattern: [model-serving, multimodal]
  platform: [openvino, kserve, triton, openshift]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "6 images (backend, frontend, data, eval, runtime, jupyter-training); deploy/deploy-cpu/deploy-gpu targets; .env-based OpenAI credential flow"
    approach: "A"
---

# Makefile: Multi-Image Build with Runtime Type Deploy Switching

## Overview

A Makefile that manages building and pushing 6 separate container images for a multi-component monorepo, with deploy targets that switch between OpenVINO (CPU) and KServe/Triton (GPU) model serving runtimes via a `RUNTIME_TYPE` variable. The deploy target integrates interactive OpenAI credential collection, OpenShift ingress domain auto-discovery, and Helm install with 15+ `--set` flags.

## Pattern Description

The Makefile defines granular build/push targets for each of 6 images (backend, frontend, data, eval, runtime, jupyter-training) plus `build-all` and `push-all` aggregators. Deploy targets delegate to the base `deploy` target with different `RUNTIME_TYPE` values, and Helm receives the runtime type to conditionally configure the model serving stack. The `.env` file pattern loads OpenAI credentials, with an interactive prompt that creates the file when missing.

## Implementation

### Six-Image Build Matrix

Each image has its own build and push targets with consistent naming:

```makefile
# Makefile (excerpt)
IMAGE_REPOSITORY := $(if $(IMAGE_REGISTRY),$(IMAGE_REGISTRY)/,)$(IMAGE_NAME)
BACKEND_IMAGE := $(IMAGE_REPOSITORY)-backend:$(IMAGE_TAG)
FRONTEND_IMAGE := $(IMAGE_REPOSITORY)-frontend:$(IMAGE_TAG)
DATA_IMAGE := $(IMAGE_REPOSITORY)-data:$(IMAGE_TAG)
EVAL_IMAGE := $(IMAGE_REPOSITORY)-eval:$(IMAGE_TAG)
RUNTIME_IMAGE := $(IMAGE_REPOSITORY)-runtime:$(IMAGE_TAG)
JUPYTER_TRAINING_IMAGE := $(IMAGE_REPOSITORY)-jupyter-training:$(IMAGE_TAG)

build-all: build build-data build-eval build-runtime build-jupyter-training

push-all:
	@if podman image exists $(BACKEND_IMAGE); then podman push $(BACKEND_IMAGE); \
	  else echo "Warning: $(BACKEND_IMAGE) not found"; fi
	# ... repeated for all 6 images
```

### Runtime Type Deploy Switching

Three deploy targets select the model serving runtime:

```makefile
# Makefile (excerpt)
RUNTIME_TYPE ?= openvino

deploy-gpu:
	$(MAKE) deploy RUNTIME_TYPE=kserve

deploy-cpu:
	$(MAKE) deploy RUNTIME_TYPE=openvino

deploy-openvino-labelstudio:
	$(MAKE) deploy RUNTIME_TYPE=openvino LABEL_STUDIO_ENABLED=true
```

### Interactive OpenAI Credential Collection

The `check-openai-env` target prompts for missing credentials and saves them to `.env`:

```makefile
# Makefile (excerpt)
check-openai-env:
	@token="$(OPENAI_API_TOKEN)"; \
	endpoint="$(OPENAI_API_ENDPOINT)"; \
	model="$(OPENAI_MODEL)"; \
	if [ -z "$$token" ] || [ -z "$$endpoint" ] || [ -z "$$model" ]; then \
		if [ -z "$$token" ]; then printf "  OPENAI_API_TOKEN: "; read token; fi; \
		if [ -z "$$endpoint" ]; then printf "  OPENAI_API_ENDPOINT: "; read endpoint; fi; \
		if [ -z "$$model" ]; then printf "  OPENAI_MODEL: "; read model; fi; \
		printf 'OPENAI_API_TOKEN=%s\n...' > .env; \
	fi
```

### Deploy Target with Ingress Auto-Discovery

The deploy target auto-discovers the OpenShift ingress domain and generates host names:

```makefile
# Makefile (excerpt)
deploy: helm-deps check-openai-env
	@. ./.env; \
	domain=$$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null || true); \
	if [ -n "$$domain" ]; then \
		host="$(HELM_RELEASE)-$(NAMESPACE).$$domain"; \
		ls_host="$(HELM_RELEASE)-ls-$(NAMESPACE).$$domain"; \
	fi; \
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) \
		--namespace $(NAMESPACE) --create-namespace \
		--set modelServing.runtimeType=$(RUNTIME_TYPE) \
		--set openai.apiToken=$$OPENAI_API_TOKEN \
		$${host:+--set openshift.sharedHost=$$host} \
		$${ls_host:+--set labelStudio.route.host=$$ls_host} \
		# ... 15+ --set flags
```

### Eval Targets (Local and Cluster)

Two eval targets: local via compose profile and cluster via `helm test`:

```makefile
# Makefile (excerpt)
eval: check-openai-env
	EVAL_FEATURE=$(EVAL_FEATURE) EVAL_DATASET=$(EVAL_DATASET) \
	podman-compose -f $(COMPOSE_FILE) --profile eval run --rm --no-deps --build \
	  -v $(CURDIR)/app/evals/preds:/evals/preds:z,U backend-eval

eval-k8s:
	helm test $(HELM_RELEASE) --namespace $(NAMESPACE) --logs
```

### Platform Detection for Local Builds

The Makefile detects the host platform for local container builds:

```makefile
# Makefile (excerpt)
PLATFORM_RELEASE ?= linux/amd64
PLATFORM_LOCAL ?= $(shell uname -m | sed -e 's/x86_64/linux\/amd64/' \
  -e 's/arm64/linux\/arm64/' -e 's/aarch64/linux\/arm64/')

local-build-up: kill-ports local-down
	PODMAN_DEFAULT_PLATFORM=$(PLATFORM_LOCAL) podman-compose -f $(COMPOSE_FILE) up --build
```

## Configuration

- **Key settings:** `RUNTIME_TYPE` (openvino or kserve); `NAMESPACE` (default `ppe-compliance-monitor-demo`); `IMAGE_REGISTRY` (default `quay.io/rh-ai-quickstart`); `LABEL_STUDIO_ENABLED`; `EVAL_FEATURE` (chat or alerts); `EVAL_DATASET` (ppe or bird)
- **Defaults:** `RUNTIME_TYPE=openvino` (CPU path); `IMAGE_TAG=latest`; `PLATFORM_RELEASE=linux/amd64`
- **Dependencies:** `.env` file with OpenAI credentials (created interactively by `check-openai-env`); Helm chart deps updated by `helm-deps` target

## Gotchas

- The `push` and `push-*` targets check `podman image exists` before pushing and error if the image has not been built, preventing accidental pushes of stale images
- The `data` image build context is `app` (not `app/data-image`) because the Dockerfile references files from `app/models/` and `app/data/`
- The `local-build` target uses conditional image-exists checks (`podman image exists`) to skip rebuilds when images are already up-to-date
- The `kill-ports` target uses platform-specific commands (`lsof` on macOS, `fuser` on Linux) to clean up 10 ports (3000, 8888, 8080, 8081, 9000, 9001, 5432, 8000, 8554, 8082, 6006) before starting the local stack
- The `LABEL_STUDIO_ENABLED` variable uses `$(if $(strip ...))` in the deploy target to only pass `--set labelStudio.enabled=...` when the variable is non-empty, avoiding accidental disabling

## Related Patterns

- `makefile-split-cluster-local-interactive-env.md` -- alternative pattern with separate cluster/local Makefiles
- `makefile-interactive-values-init-model-cli-override.md` -- alternative interactive credential collection approach
