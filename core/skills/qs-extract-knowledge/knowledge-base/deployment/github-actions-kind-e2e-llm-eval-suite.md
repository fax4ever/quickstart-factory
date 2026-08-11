---
name: github-actions-kind-e2e-llm-eval-suite
description: Kind-based E2E CI with LLM evaluation suite across PR, nightly, and pip-install-build workflows
summary: "Implements 19 GitHub Actions workflows in three tiers — PR checks (flake8/black/isort/mypy linting, kubeconform Helm validation, unit tests), Kind-based E2E integration tests (session serialization/reclaim, short-response via pull_request_target with SHA-pinned checkout), and nightly long-conversation evaluation suites against dev/main branches using 8B models for PRs and 70B for nightlies via separate LLM secrets (LLM_API_TOKEN_EVAL vs LLM_API_TOKEN_EVAL_70B) and endpoints (LLM_URL_INFERENCE vs LLM_URL_EVAL). Use when building an AI agent quickstart requiring comprehensive CI that spans quality gates, live LLM E2E testing in ephemeral Kind clusters, and scheduled evaluation regression suites with tarball artifact collection (30-day retention). The reusable Kind composite action (.github/actions/kind/action.yaml) orchestrates Kind v0.30.0 cluster setup with local registry (kind-with-registry.sh at localhost:5001), image build/push, and Helm deployment, supporting both uv-default and pip-fallback builds (use_pip_install input) with configurable replica counts (1 for nightlies, 2 for PR E2E). Critical gotcha: PR E2E must use pull_request_target (not pull_request) with SHA-pinned checkout to access repository secrets for LLM API tokens, pip-install builds are tested separately via pr-pip-install-build.yml to prevent QEMU/M1 regression, and all E2E workflows share a daily cron backstop (0 2 * * *) ensuring tests run even without open PRs."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python]
  ai_pattern: [agents, evaluation]
  platform: [kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "19 GitHub Actions workflows: PR checks, Kind-based E2E, nightly evals (short/long/prod), pip-install build verification"
    approach: "A"
---

# GitHub Actions Kind E2E with LLM Evaluation Suite

## Overview

This pattern implements a comprehensive CI/CD system with 19 GitHub Actions workflows spanning PR quality checks, Kind-based end-to-end testing with LLM evaluations, nightly evaluation suites with varying conversation depths, and build verification using both uv and pip install methods. The E2E tests deploy the full application to a Kind cluster, run integration tests against live (remote) LLM inference, and collect evaluation results as artifacts.

## Pattern Description

The workflow system is organized into three tiers: PR-triggered workflows (quality checks, E2E tests, evaluation checks, pip-install build), nightly scheduled workflows (long conversation tests against dev and main branches with different model sizes), and push-triggered builds (container image builds on main/dev). A reusable Kind composite action handles cluster setup, image building, and Helm deployment, used across all E2E workflows.

## Implementation

### Kind Composite Action

The `.github/actions/kind/action.yaml` composite action encapsulates cluster setup and app deployment:

```yaml
# .github/actions/kind/action.yaml (excerpt)
inputs:
  namespace:
    default: test
  llm:
    required: true
  llm_url:
    required: true
  replica_count:
    default: "1"
  helm_target:
    default: "helm-install-test"
  use_pip_install:
    default: "false"
runs:
  using: composite
  steps:
    - run: go install sigs.k8s.io/kind@v0.30.0
    - run: bash ./scripts/ci/kind-with-registry.sh
    - run: make helm-depend
    - run: make build-all-images REGISTRY=localhost:5001
    - run: make push-all-images REGISTRY=localhost:5001
    - run: make ${{inputs.helm_target}} NAMESPACE=${{inputs.namespace}} \
        REGISTRY=localhost:5001 LLM=${{inputs.llm}} \
        LLM_URL=${{inputs.llm_url}} LLM_API_TOKEN=$LLM_API_TOKEN
```

### PR Quality Checks (3 Parallel Jobs)

```yaml
# .github/workflows/pr-checks.yml (excerpt)
jobs:
  code-quality-check:  # flake8, black, isort, mypy, logging patterns
    steps:
      - run: make check-lockfiles
      - run: make check-requirements
      - run: make check-release-manifest
      - run: make lint-mypy-per-directory
      - run: make check-logging

  helm-export-validate:  # kubeconform validation, no cluster needed
    steps:
      - run: make helm-export-validate-demo
        env:
          NAMESPACE: ci-demo
          HF_TOKEN: mock_hf_token_for_ci

  pull-request-tests:  # unit tests
    steps:
      - run: make test-all
```

### PR E2E with Integration Tests

Uses `pull_request_target` for secret access with SHA-pinned checkout:

```yaml
# .github/workflows/pr-e2e-tests.yml (excerpt)
on:
  pull_request_target:
    types: [opened, synchronize, reopened]
  schedule:
    - cron: '0 2 * * *'
jobs:
  e2e-tests:
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event.pull_request.head.sha }}
      - uses: ./.github/actions/kind
        with:
          replica_count: "2"
      - run: make test-session-serialization-integration
      - run: make test-session-reclaim-integration
      - run: make test-short-resp-integration-request-mgr
```

### Nightly Evaluation Matrix

Multiple nightly workflows run longer conversation suites against different branches and model sizes:

```yaml
# .github/workflows/nightly-e2e-long-dev.yml (excerpt)
on:
  schedule:
    - cron: '0 3 * * *'
jobs:
  e2e-tests:
    steps:
      - uses: actions/checkout@v5
        with:
          ref: dev
      - uses: ./.github/actions/kind
      - run: make test-long-resp-integration-request-mgr
        env:
          LLM_URL: ${{ vars.LLM_URL_EVAL_70B }}
          LLM_API_TOKEN: ${{ secrets.LLM_API_TOKEN_EVAL_70B }}
```

### Evaluation Artifact Collection

All E2E workflows collect evaluation results as tarball artifacts:

```yaml
# Common pattern across E2E workflows
- name: Create evaluations tarball
  if: always()
  run: |
    tar -czf evaluations-results-${{ github.run_id }}.tar.gz \
      -C evaluations results/
- uses: actions/upload-artifact@v4
  with:
    name: evaluations-results-${{ github.run_id }}
    retention-days: 30
```

## Configuration

- **Key settings:** `LLM_API_TOKEN_EVAL` and `LLM_API_TOKEN_EVAL_70B` secrets for different model sizes; `LLM_URL_INFERENCE` and `LLM_URL_EVAL` repository variables separate inference from evaluation endpoints; `LLM_INFERENCE` and `LLM_ID_INFERENCE` identify the model
- **Defaults:** Kind cluster with 1 replica for nightlies, 2 replicas for PR E2E; `test` namespace; uv sync for default builds
- **Dependencies:** Requires Kind v0.30.0, a local container registry (via `kind-with-registry.sh`), Helm CLI, and remote LLM API endpoints with valid tokens

## Gotchas

- PR E2E uses `pull_request_target` (not `pull_request`) to access repository secrets for LLM API tokens, with `ref: ${{ github.event.pull_request.head.sha }}` to pin to the PR commit (see `.github/workflows/pr-e2e-tests.yml`)
- The `pr-pip-install-build.yml` workflow tests the pip fallback build path (`USE_PIP_INSTALL=true`) separately from the default uv build, ensuring QEMU/M1 compatibility does not regress (see `.github/workflows/pr-pip-install-build.yml`)
- Nightly workflows use different LLM secrets (`LLM_API_TOKEN_EVAL` vs `LLM_API_TOKEN_EVAL_70B`) allowing evaluation against different model sizes (8B for PRs, 70B for nightlies) (see nightly workflow files)
- All E2E workflows share the `pr-e2e-tests.yml` schedule (`cron: '0 2 * * *'`) as a daily backstop, in addition to their own PR triggers, ensuring tests run even without PRs (see `.github/workflows/pr-e2e-tests.yml`)

## Related Patterns

- `makefile-multi-profile-helm-install.md` -- Makefile targets used by the Kind composite action
- `container-build-parameterized-containerfile-template.md` -- Containerfile templates built during E2E setup
