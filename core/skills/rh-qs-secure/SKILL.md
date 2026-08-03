---
name: rh-qs-secure
description: |
  Security guidance for AI Quickstarts. Split into cluster access guardrails (what the agent may do)
  and application security (secrets, RBAC, prompt guards). Use during rh-qs-architect, rh-qs-deploy,
  rh-qs-implement, and rh-qs-verify-deploy.
---

# rh-qs-secure

**Category:** `security/`

## Trigger

- Design doc is being written or reviewed (`rh-qs-architect`)
- Implementation touches auth, secrets, RBAC, or agent tools (`rh-qs-implement`)
- Deployment wiring secrets or ServiceAccounts (`rh-qs-deploy`)
- Post-deploy verification includes security checks (`rh-qs-verify-deploy`)

## Two security layers

| Layer | Question | Owner skill |
|-------|----------|-------------|
| **Cluster access** | What may the agent (or CI) do on OpenShift? | This skill — [agent-permissions.md](./references/agent-permissions.md) |
| **Application security** | Is the quickstart itself secure in production? | This skill — [application-security.md](./references/application-security.md) |

Do not conflate them. Minimal cluster permissions do not replace proper secret handling in the app.

## What it does

1. Defines **least-privilege cluster access** for agents building quickstarts
2. Audits **application security**: secrets, RBAC, network policy, prompt/input guards
3. Documents **OpenShift AI / Llama Stack safety** settings when agents or LLMs are in scope
4. Records security decisions in the design doc **Security considerations** section
5. Adds Makefile/Helm patterns so humans and CI verify security without ad-hoc `oc` commands

## Workflow

```
- [ ] 1. Read PRD compliance/security notes
- [ ] 2. Choose cluster access profile (see agent-permissions.md)
- [ ] 3. Audit application security checklist (see application-security.md)
- [ ] 4. Wire secrets via OpenShift Secrets / External Secrets — never plain text in Git
- [ ] 5. Scope ServiceAccount RBAC to the release namespace
- [ ] 6. Add prompt/input guardrails when LLM or agent endpoints are user-facing
- [ ] 7. Update design doc Security considerations + .env.example (names only)
- [ ] 8. Confirm verify-deploy includes security smoke checks
```

## Agent and MCP guardrails

Agents **must not** run `oc`, `kubectl`, or direct cluster API calls during quickstart development.

| Allowed | Not allowed |
|---------|-------------|
| `helm lint`, `helm template`, `helm upgrade --install` via Makefile targets | Raw `oc apply`, `kubectl exec`, cluster-wide reads |
| Edit Helm charts, values, and Makefile in repo | Delete or mutate resources owned by other Helm releases |
| Document verification commands for humans/CI | Impersonate cluster-admin or bypass RBAC |

When an MCP server bridges an agent to OpenShift:

- Expose an **allowlist** of tools (e.g. `helm_upgrade`, `helm_template`, `make_verify_deploy` only)
- Do not expose generic kubectl — agents may work around restrictions
- Prefer a **dedicated OpenShift user or ServiceAccount** with namespace-scoped `edit` (or narrower)

See [references/agent-permissions.md](./references/agent-permissions.md) for profiles and MCP notes.

## Application security essentials

See [references/application-security.md](./references/application-security.md):

- Passwords and API keys in **Secrets**, referenced by Helm — not in `values.yaml` or README
- **RBAC**: dedicated ServiceAccounts per component; no cluster-admin for app workloads
- **Routes/TLS**: edge or passthrough documented; no `insecureSkipVerify: true` without justification
- **Prompt guards**: Llama Stack safety / input filters when user content reaches models
- **Supply chain**: pin image tags and chart versions; document bump process via **`rh-qs-bump-versions`**

## Output

- Design doc section: **Security considerations**
- Helm: `Secret` templates or `existingSecret` patterns; scoped `Role`/`RoleBinding`
- `.env.example` with variable names only
- Optional `docs/security.md` for non-obvious threat model notes

## Next skill

Security review is **embedded** in the pipeline — not a terminal stage. After deploy wiring → **`rh-qs-verify-deploy`** (includes security smoke checks), then **`rh-qs-document`**.

## References

- [Agent permissions and MCP guardrails](./references/agent-permissions.md)
- [Application security checklist](./references/application-security.md)
- [Llama Stack safety](https://llama-stack.readthedocs.io/) — when orchestration is enabled
- Design doc: `.rhoai-qs/<slug>/designs/design.md` (or `../.rhoai-qs/<slug>/designs/design.md` when invoked from inside the scaffolded quickstart repo, e.g. during `rh-qs-deploy`)
