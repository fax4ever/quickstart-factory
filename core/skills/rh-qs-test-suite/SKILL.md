---
name: rh-qs-test-suite
description: |
  Build production-grade GitHub Actions workflows for AI Quickstarts: split PR checks, Kind-based E2E,
  LLM evaluations, image publish, nightly schedules, and dev→main promotion. Use after rh-qs-deploy
  when Helm and Makefile deploy targets exist, or when expanding CI beyond rh-qs-scaffold basics.
---

# rh-qs-test-suite

**Category:** `github/`  
**Reference implementation:** [it-self-service-agent](https://github.com/rh-ai-quickstart/it-self-service-agent) `.github/`

## Trigger

- Helm chart and Makefile deploy targets exist from **`rh-qs-deploy`** if not create it.
- Design doc **`designs/design.md`** defines testing strategy (unit / integration / E2E / evals) — this skill runs inside `.rhoai-qs/<slug>/` itself (the scaffolded quickstart repo), so the design doc sits right alongside the code, no `../` needed
- Optional: replace or extend minimal workflows from **`rh-qs-scaffold`**

## What it does

1. Splits CI into **focused workflows** (quality, unit tests, Kind E2E, evals, image build) instead of one monolithic job
2. Adds **composite actions** under `.github/actions/` (`prepare-runner`, `kind`, `inspect`)
3. Adds **`scripts/ci/`** helpers (Kind + local registry, optional integration hooks)
4. Defines a **Makefile CI contract** so workflows only call `make` targets
5. Documents required **secrets and repository variables**
6. Configures **branch protection** status checks to match workflow job names
7. Optionally adds **nightly** and **dev→main promotion** workflows for mature quickstarts

## Workflow

```
- [ ] 1. Read design testing strategy + PRD eval requirements
- [ ] 2. Add Makefile CI targets (see references/makefile-ci-contract.md)
- [ ] 3. Add scripts/ci/kind-with-registry.sh (Podman-compatible)
- [ ] 4. Add composite actions (prepare-runner, kind, inspect)
- [ ] 5. Add PR workflows (checks, e2e, branch policy — as needed)
- [ ] 6. Configure repo secrets/vars (see references/secrets-and-variables.md)
- [ ] 7. Add build-and-push on push to main/dev (if publishing images)
- [ ] 8. Add nightly / promotion workflows only when design requires them
- [ ] 9. Register required status checks in branch protection
- [ ] 10. Open test PR and confirm all workflows green
```

## Design principles (from it-self-service-agent)

| Principle | Practice |
|-----------|----------|
| Makefile as CI API | Workflows run `make <target>`; no duplicated install logic in YAML |
| Pin tool versions | `UV_VERSION` (and Helm) in workflow `env` must match `Makefile` |
| Concurrency | `group: ${{ github.workflow }}-${{ github.event.pull_request.number }}` + `cancel-in-progress: true` on PRs |
| Split by risk/cost | Fast lint/unit on `pull_request`; heavy Kind/evals on `pull_request_target` or schedule |
| Fail fast on secrets | First step validates required secrets before checkout/cluster work |
| Debug on failure | `if: failure()` → composite `inspect` (or upload cluster logs) |
| Artifacts | Tar and upload `evaluations/results` (or test reports) with `retention-days: 30` |
| Fork safety | `pull_request` for untrusted code; `pull_request_target` only when org secrets are required — checkout `github.event.pull_request.head.sha` |

## Workflow set (choose per design)

| Workflow file | Trigger | Purpose |
|---------------|---------|---------|
| `pr-checks.yml` | `pull_request` | Lockfiles, lint, mypy/ruff, helm export/kubeconform, unit tests |
| `pr-e2e-tests.yml` | `pull_request_target`, schedule, `workflow_dispatch` | Kind deploy + integration + short evals |
| `pr-pip-install-build.yml` | `pull_request` | Validate alternate install path (`use_pip_install`) |
| `pr-evaluation-check.yml` | `pull_request_target` | Known-bad conversation / regression eval gate |
| `pr-branch-check.yml` | `pull_request` → `main` | Enforce `dev` or `dev-<sha>` source branch |
| `build-and-push.yaml` | `push` to `main`/`dev` | Build and push images to Quay (org-owned repos only) |
| `nightly-e2e-*.yml` | `schedule`, `workflow_dispatch` | Longer eval suites on Kind or prod cluster |
| `create-dev-to-main-pr.yaml` | `workflow_dispatch` | Version-checked promotion PR with temp branch |

Full catalog and naming conventions: [references/workflow-catalog.md](./references/workflow-catalog.md)

## Repository layout to add

```
.github/
├── workflows/
│   ├── pr-checks.yml
│   ├── pr-e2e-tests.yml          # if integration/e2e in design
│   ├── pr-branch-check.yml         # if using dev/main promotion model
│   └── build-and-push.yaml         # if publishing to quay.io/rh-ai-quickstart
├── actions/
│   ├── prepare-runner/action.yaml
│   ├── kind/action.yaml
│   └── inspect/action.yml
scripts/ci/
└── kind-with-registry.sh
```

Skeleton YAML: [references/workflow-skeletons.md](./references/workflow-skeletons.md)

## Composite actions

| Action | Role |
|--------|------|
| `prepare-runner` | Free disk (`jlumbroso/free-disk-space`); log memory/swap before Kind |
| `kind` | Install Kind → registry cluster → `make build/push` → `make helm-install-test` |
| `inspect` | On failure, capture namespace/events/logs (stub OK until wired) |

Details and inputs: [references/composite-actions.md](./references/composite-actions.md)

## Makefile CI contract

Implement these targets (names can alias existing ones):

| Target | Used by |
|--------|---------|
| `check-uv-version` | PR quality |
| `check-lockfiles` / `update-lockfiles` | PR quality |
| `deps-all` | PR unit + quality |
| `test-all` or `test` | PR unit |
| `helm-export-validate-demo` | PR helm (kubeconform) |
| `helm-depend` | Kind action |
| `build-all-images` / `push-all-images` | Kind + build-and-push |
| `helm-install-test` | Kind E2E |
| `helm-install-prod` | Nightly prod (optional) |
| `verify-deploy` | Post-install smoke (required before rh-qs-document) |
| `sync-evaluations` | E2E with LLM evals |
| `test-*-integration` | Named integration tests from design |

Full list: [references/makefile-ci-contract.md](./references/makefile-ci-contract.md)

## Secrets and variables

Configure in GitHub **before** enabling `pull_request_target` E2E workflows:

- **Secrets:** `LLM_API_TOKEN_EVAL`, `LLM_API_TOKEN_INFERENCE`, `QUAY_USERNAME`, `QUAY_PASSWORD`, optional `PROD_TOKEN` / `PROD_SERVER` for prod nightlies
- **Variables:** `LLM_URL_EVAL`, `LLM_ID_INFERENCE`, `LLM_INFERENCE`, `LLM_URL_INFERENCE`

Never commit tokens. Use mock tokens only where workflows explicitly allow (e.g. `HF_TOKEN: mock_hf_token_for_ci` for helm template validation).

Catalog: [references/secrets-and-variables.md](./references/secrets-and-variables.md)

## Branch protection

Required status checks should match **job names** (or workflow names) users see in the PR UI, for example:

- `Code Quality Check`
- `Run unit-tests`
- `Helm export validation`
- `Run e2e tests (uv sync with evals)` — if E2E enabled

For repos using **dev → main**: require `Validate PR comes from dev branch` on PRs to `main`.

## Minimal vs full quickstart

| Profile | Include |
|---------|---------|
| **Minimal** | `pr-checks.yml` only (extends scaffold `ci.yaml` pattern) |
| **Standard** | `pr-checks.yml` + `pr-e2e-tests.yml` + `kind` action + `scripts/ci/` |
| **Agent + evals** | Standard + `pr-evaluation-check.yml` + eval artifact upload |
| **Release train** | Full + `pr-branch-check.yml` + `build-and-push.yaml` + `create-dev-to-main-pr.yaml` + nightlies |

Match profile to the **Testing strategy** section in `designs/design.md`.

## Verification

```bash
# Local parity with CI
make check-lockfiles
make lint
make test-all
make helm-export-validate-demo NAMESPACE=ci-demo HF_TOKEN=mock_hf_token_for_ci

# Kind path (requires podman/docker + kind)
bash scripts/ci/kind-with-registry.sh
make helm-install-test NAMESPACE=test REGISTRY=localhost:5001 ...
```

Open a PR and confirm workflows pass. For `pull_request_target`, validate from a branch in the same repo (fork PRs may not receive secrets).

## Output

- `.github/workflows/*` and `.github/actions/*` committed
- `scripts/ci/*` for Kind/registry
- Makefile targets documented in README (via `rh-qs-document`)
- Branch protection updated with correct required checks

## Next skill

When CI workflows are green on a test PR → **`rh-qs-verify-deploy`**, then **`rh-qs-document`**

## References

- [Workflow catalog](./references/workflow-catalog.md) — map each it-self-service-agent workflow to quickstart use
- [Composite actions](./references/composite-actions.md) — `prepare-runner`, `kind`, `inspect`
- [Secrets and variables](./references/secrets-and-variables.md)
- [Makefile CI contract](./references/makefile-ci-contract.md)
- [Workflow skeletons](./references/workflow-skeletons.md) — copy-paste YAML starters
