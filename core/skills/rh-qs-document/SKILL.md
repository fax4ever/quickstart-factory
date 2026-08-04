---
name: rh-qs-document
description: Generate README and catalog documentation for AI Quickstarts from verified deployment. Creates or updates README.md with deploy steps, requirements, architecture diagram, and catalog metadata. Use only after rh-qs-verify-deploy produces a green report.
---

# rh-qs-document

**Category:** `documentation/'

## Trigger

**`rh-qs-verify-deploy`** report is green (`reports/verify-deploy-*.md`); CI workflows from `rh-qs-test-suite` are in place when the design requires them

Documentation runs **after** verification — not before. Every deploy command in the README must match what verify-deploy actually ran.

## Where This Runs

This skill works inside `.rhoai-qs/<slug>/` — the scaffolded quickstart's own repo, since `README.md` lives at that repo's root. Pipeline files, design doc, and reports sit right alongside the code in this same folder — reference them as plain relative paths, no `../` needed. See [pipeline-convention.md](../../../docs/foundation/pipeline-convention.md#where-skills-run-and-why-it-matters-for-paths).

## What it does

1. Generates **README.md** from the implementation using standard quickstart catalog structure
2. Includes: title, description, requirements (hardware/software), deploy steps, delete/cleanup steps
3. References the **Mermaid architecture diagram** from the architect phase (saved in `docs/images/`)
4. Adds **catalog metadata/tags** for Red Hat documentation discovery
5. Documents all **environment variables** and their purpose
6. Optionally generates a **demo script outline** for video/presentation

## Workflow

### Phase 0: Resolve Quickstart Context

Before doing anything, resolve which quickstart this session is for. Run `ls ../ 2>/dev/null` (excluding `reports` and `blog-drafts`) and spawn the **validation-skill subagent**:

```python
Agent(
    description="Resolve which quickstart this documentation session is for",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-document/subagents/validation-skill-prompt.md

User message: {user_message}
Existing slugs: {existing_slugs}
Is entry point: false
Calling skill: rh-qs-document
"""
)
```

Handle the result per [validation-skill-template.md](../../../docs/foundation/validation-skill-template.md#main-agent-handling).

### Remaining phases

```
- [ ] 1. Read verify-deploy report — use verified commands, flags, and namespace
- [ ] 2. Explore repository (code, Helm, Makefile, compose, docs/images/)
- [ ] 3. Read design doc for architecture diagram and component list
- [ ] 4. Gather user-facing facts (hardware, RHOAI version, permissions)
- [ ] 5. Draft or update README.md using ReadmeStructure
- [ ] 6. Validate every documented command exists in Makefile or Helm (no undocumented oc/kubectl)
- [ ] 7. Cross-check README deploy steps against verify-deploy evidence
- [ ] 8. Optional: write docs/demo-script.md
```

### README sections

Use [references/ReadmeStructure.md](./references/ReadmeStructure.md):

- Title and short description (catalog character limits)
- Workload-focused detailed description
- Requirements: specific GPU, tested OpenShift AI version, permissions
- Deploy and Delete steps (copy-pasteable; use `make deploy` / `make undeploy` and podman terminology — not raw `oc`)
- Architecture section with diagram from `docs/images/` or design doc
- Environment variables table
- Tags/metadata for catalog

### Demo script (optional)

Save to `docs/demo-script.md`:

- Setup (~2 min)
- Primary user journey demo (~5 min)
- Architecture callout (~2 min)
- Cleanup (~1 min)

## What not to include

- Line-by-line code walkthroughs
- Generic placeholders when repo pins specific versions
- Commands not present in Makefile or Helm

## Audience

Readers may have **limited OpenShift AI experience**. Use plain language, explicit prerequisites, ordered steps.

## Output

- `README.md` (create or replace)
- Optional `docs/demo-script.md`
- Updated `docs/images/` if diagram exported

## Next skill

When README is complete → **`rh-qs-ship`**

## References

- [README structure](./references/ReadmeStructure.md)
- Design doc: `designs/design.md`
- [subagents/validation-skill-prompt.md](./subagents/validation-skill-prompt.md) — pass by file path only, do NOT read directly
