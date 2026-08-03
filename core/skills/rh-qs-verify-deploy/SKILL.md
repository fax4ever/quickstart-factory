---
name: rh-qs-verify-deploy
description: |
  Verify a quickstart deployment on OpenShift after rh-qs-deploy. Runs Makefile verify targets,
  confirms health endpoints and Helm release status, and produces a verification report before
  documentation. Use when Helm install succeeds or CI E2E passes.
---

# rh-qs-verify-deploy

**Category:** `deployment/`

## Trigger

- **`rh-qs-deploy`** complete: `make helm-lint`, `make helm-template` pass
- Live install attempted: `make deploy NAMESPACE=<ns>` succeeded (human, CI, or deployment sub-agent)
- Optional: **`rh-qs-test-suite`** Kind E2E or prod nightly green

## Where This Runs

This skill works inside the scaffolded quickstart's own repo. Pipeline files, design doc, and reports stay in the parent `quickstart-factory/.rhoai-qs/<slug>/` — reference them as `../.rhoai-qs/<slug>/...`. See [pipeline-convention.md](../../../docs/foundation/pipeline-convention.md#nested-quickstart-repos).

## Purpose

Closes the **biggest pipeline gap**: validating that the quickstart actually works on-cluster **before** writing README deploy steps. Documentation (`rh-qs-document`) must reflect verified behavior, not assumed behavior.

## Agent rules

- Agents prepare Makefile targets and interpret output — they do **not** run raw `oc` or `kubectl`
- All cluster verification goes through **`make verify-deploy`** and related Makefile targets
- If live cluster access is unavailable, produce a **partial report** from `helm template` + local `make dev` and flag gaps for human verification

## What it does

1. Confirms Helm release is installed and resources are healthy (via Makefile, not ad-hoc CLI)
2. Hits application **health endpoints** (in-cluster URL or port-forward target documented in Makefile)
3. Runs optional **`helm test`** hooks if the chart defines them
4. Validates **security smoke checks** from **`rh-qs-secure`** (no plaintext secrets in running config)
5. Exercises the **primary user journey** at minimum (API call or UI smoke — as defined in PRD)
6. Writes **`../.rhoai-qs/<slug>/reports/verify-deploy-<date>.md`** with pass/fail evidence
7. Only when verification passes → hand off to **`rh-qs-document`**

## Workflow

### Phase 0: Resolve Quickstart Context

Before doing anything, resolve which quickstart this session is for. Run `ls ../.rhoai-qs/ 2>/dev/null` (excluding `_shared`) and spawn the **validation-skill subagent**:

```python
Agent(
    description="Resolve which quickstart this verify-deploy session is for",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-verify-deploy/subagents/validation-skill-prompt.md

User message: {user_message}
Existing slugs: {existing_slugs}
Is entry point: false
Calling skill: rh-qs-verify-deploy
"""
)
```

Handle the result per [validation-skill-template.md](../../../docs/foundation/validation-skill-template.md#main-agent-handling).

### Remaining phases

```
- [ ] 1. Read design doc + deploy Makefile targets
- [ ] 2. Run make helm-lint && make helm-template (local, no cluster)
- [ ] 3. Confirm make deploy completed (or run via deployment sub-agent)
- [ ] 4. Run make verify-deploy NAMESPACE=<ns>
- [ ] 5. Run security smoke checks (rh-qs-secure application-security.md)
- [ ] 6. Exercise primary user flow (scripted curl or documented manual step)
- [ ] 7. Write verification report to ../.rhoai-qs/<slug>/reports/
- [ ] 8. Fix deploy/chart issues and re-verify if any check fails
```

## Recommended Makefile targets

Add to the quickstart repo during **`rh-qs-deploy`**:

```makefile
RELEASE ?= <slug>
CHART_DIR ?= deploy/helm/$(RELEASE)
NAMESPACE ?= <slug>-demo

deploy:          ## helm upgrade --install (only cluster entry point)
undeploy:        ## helm uninstall
verify-deploy:   ## Post-install smoke test — REQUIRED before rh-qs-document
helm-lint:
helm-template:
```

`verify-deploy` should:

- Wait for Deployment rollout (via `helm status` / chart hooks / scripted health URL)
- Curl or probe `/health` (and one domain endpoint from the PRD)
- Fail with a clear message if shared-service aliases (MLflow, etc.) are misconfigured
- Emit a short JSON or text summary agents can parse

## Verification report template

Save to **`../.rhoai-qs/<slug>/reports/verify-deploy-YYYY-MM-DD.md`**:

```markdown
# Verify deploy — <Title>

## Environment
- Namespace: <ns>
- Helm release: <name>
- OpenShift AI version (if known): <version>
- Verified by: human | CI | sub-agent

## Results
| Check | Status | Evidence |
|-------|--------|----------|
| helm lint | pass/fail | |
| helm template | pass/fail | |
| make deploy | pass/fail | |
| health endpoint | pass/fail | URL + status code |
| primary user flow | pass/fail | |
| security smoke | pass/fail | |

## Issues found
- ...

## Doc impact
- README deploy steps confirmed: yes/no
- Commands to document: <list exact make/helm invocations>
```

## Shared platform services

When using shared MLflow or other cluster-wide services:

- Confirm service alias resolves in the quickstart namespace
- Confirm `create=false` on foreign CRs — do not adopt other Helm releases
- Record exact `--set` flags that worked in the verification report for README authors

## Output

- Verification report in `../.rhoai-qs/<slug>/reports/`
- Chart/Makefile fixes if verification failed
- Green light for **`rh-qs-document`** only when critical checks pass

## Next skill

When verification report is green → **`rh-qs-document`** (docs must match verified commands and flags)

## References

- [Agent permissions](../rh-qs-secure/references/agent-permissions.md)
- [Application security](../rh-qs-secure/references/application-security.md)
- [Makefile CI contract](../rh-qs-test-suite/references/makefile-ci-contract.md)
- Design doc: `../.rhoai-qs/<slug>/designs/design.md`
- [subagents/validation-skill-prompt.md](./subagents/validation-skill-prompt.md) — pass by file path only, do NOT read directly
