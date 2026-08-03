---
name: rh-qs-deploy
description: Deploy configuration for AI Quickstarts. Wires ai-architecture-charts Helm subcharts, compose.yml for local dev, Containerfiles, and Makefile deploy targets. Use when rh-qs-verify-build passes. Live cluster install uses a deployment sub-agent with Helm-only access.
---

# rh-qs-deploy

**Category:** `deployment/`

## Trigger

Local verification passed from **`rh-qs-verify-build`** (`make dev`, `make test`, `make lint` pass)

## Where This Runs

This skill works inside the scaffolded quickstart's own repo, since that's where Helm charts and Containerfiles live. Pipeline files and the design doc stay in the parent `quickstart-factory/.rhoai-qs/<slug>/` — reference them as `../.rhoai-qs/<slug>/...`. See [pipeline-convention.md](../../../docs/foundation/pipeline-convention.md#nested-quickstart-repos).

## Agent guardrails

- **Helm-only on cluster.** All install/upgrade/uninstall is expressed as Makefile targets (`make deploy`, `make undeploy`). Agents do **not** run `oc` or `kubectl`.
- **Use a deployment sub-agent** for live cluster work: narrow scope, allowlisted `make` targets only. See **`rh-qs-secure`** → [agent-permissions.md](../rh-qs-secure/references/agent-permissions.md).
- Apply **`rh-qs-secure`** when wiring secrets, ServiceAccounts, and shared platform services (MLflow aliases, `create=false` patterns).

## What it does

1. Wires **ai-architecture-charts** as Helm subchart dependencies based on the design document
2. Configures `Chart.yaml` with selected subcharts (llama-stack, llm-service, pgvector, minio, mcp-servers, etc.)
3. Sets up `values.yaml` with enablement flags and model configuration
4. Configures `compose.yml` for local development with **podman-compose**
5. Creates **Containerfiles** for each deployable package (multi-stage builds)
6. Adds Makefile targets: `make dev`, `make deploy`, `make undeploy`, `make verify-deploy`
7. Wires application environment variables to in-cluster services
8. Verifies locally: `helm lint`, `helm template` renders cleanly, local health checks pass
9. Hands off live cluster validation to **`rh-qs-verify-deploy`** (after `make deploy`)

## Workflow

### Phase 0: Resolve Quickstart Context

Before doing anything, resolve which quickstart this session is for. Run `ls ../.rhoai-qs/ 2>/dev/null` (excluding `_shared`) and spawn the **validation-skill subagent**:

```python
Agent(
    description="Resolve which quickstart this deploy session is for",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-deploy/subagents/validation-skill-prompt.md

User message: {user_message}
Existing slugs: {existing_slugs}
Is entry point: false
Calling skill: rh-qs-deploy
"""
)
```

Handle the result per [validation-skill-template.md](../../../docs/foundation/validation-skill-template.md#main-agent-handling).

### Remaining phases

```
- [ ] 1. Wire Helm app chart (api, ui, db, routes, migration job)
- [ ] 2. Add ai-architecture-charts subchart dependencies
- [ ] 3. Configure values.yaml (models, secrets, resources, GPU)
- [ ] 4. Set up compose.yml for local dev
- [ ] 5. Build/update Containerfiles
- [ ] 6. Wire env vars to in-cluster services
- [ ] 7. Add Makefile deploy targets (including verify-deploy)
- [ ] 8. Apply rh-qs-secure checklist for secrets and RBAC
- [ ] 9. Verify helm lint + template + local health
- [ ] 10. Spawn deployment sub-agent or ask human to run make deploy + make verify-deploy
```

### Helm subcharts

Add dependencies from https://rh-ai-quickstart.github.io/ai-architecture-charts. Pin versions from design doc.

Detailed guides:

- [Llama Stack + llm-service + pgvector](./references/helm-llamastack.md)
- [MinIO object storage](./references/helm-minio.md)

### Environment wiring

| Variable | Source |
|----------|--------|
| `LLAMA_STACK_URL` | llama-stack subchart service |
| `DATABASE_URL` | app db or pgvector subchart |
| `S3_ENDPOINT` | minio subchart (if enabled) |

Document all variables in `.env.example`. **Never** commit real tokens or API keys.

### Makefile targets

```bash
make dev            # podman-compose local stack
make deploy         # helm upgrade --install (sole cluster install entry point)
make verify-deploy  # post-install smoke test — required before rh-qs-document
make undeploy       # helm uninstall
make helm-lint
make helm-template
```

Do **not** document or use raw `oc`/`kubectl` for install. Verification and docs reference these Makefile targets only.

## Verification

```bash
make helm-lint
helm template deploy/helm/<slug>/ -f deploy/helm/<slug>/values.yaml
make dev && curl -f http://localhost:<port>/health
```

## Output

Complete deployment configuration: Helm chart, compose.yml, Containerfiles, and working Makefile targets.

## Next skill

When deploy configs render locally → **`rh-qs-test-suite`** (if design includes Kind/E2E/evals), then **`rh-qs-verify-deploy`**, then **`rh-qs-document`**

## References

- [Helm: Llama Stack guide](./references/helm-llamastack.md)
- [Helm: MinIO guide](./references/helm-minio.md)
- [ai-architecture-charts](https://github.com/rh-ai-quickstart/ai-architecture-charts)
- Design doc: `../.rhoai-qs/<slug>/designs/design.md`
- [subagents/validation-skill-prompt.md](./subagents/validation-skill-prompt.md) — pass by file path only, do NOT read directly
