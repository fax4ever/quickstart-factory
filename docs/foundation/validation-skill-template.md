# Validation-Skill Subagent Template

Every factory skill now runs inside the shared `quickstart-factory` repo, where the `.rhoai-qs/` directory holds pipeline state for **every** quickstart ever worked on, namespaced by slug (see [pipeline-convention.md](pipeline-convention.md)). Because multiple quickstarts coexist in one place, no skill can safely assume "the quickstart" without first checking — that's the job of **`validation-skill`**, a required subagent every factory skill delegates to before doing any real work.

## Why This Exists

Before this convention, each quickstart lived in its own repo. A skill's current working directory was, by construction, scoped to exactly one quickstart — there was nothing to disambiguate. Now that `.rhoai-qs/mortgage-processor/` and `.rhoai-qs/spending-transaction-monitor/` can both exist side by side in the same repo, every skill has a new question to answer at the very start: **which quickstart is this session about?**

Getting this wrong silently means writing pipeline files, specs, or code into the wrong quickstart's namespace. `validation-skill` exists to make sure that never happens — it either resolves the slug with confidence, or it stops and asks.

## When It Runs

**Phase 0, before any other phase**, in every skill except the pipeline's entry point (`rh-qs-discovery`) when it is starting a genuinely new idea. Even `rh-qs-discovery` runs `validation-skill` when the user is *continuing or refining* an existing PRD rather than starting fresh — the only case it's skipped entirely is a brand-new idea with no prior slug.

## Required File

Every skill's `subagents/` directory includes:

```
subagents/validation-skill-prompt.md
```

Self-contained, following the standard subagent structure from [skill-directory-structure.md](skill-directory-structure.md).

## Inputs (provided by the main agent)

| Input | Description |
|-------|-------------|
| `user_message` | The user's raw request for this session (e.g., "deploy mortgage-processor", "continue the fraud idea", "run rh-qs-deploy") |
| `existing_slugs` | List of quickstart slug folders, **excluding** the two cross-cutting folders `reports/` and `blog-drafts/` (see [pipeline-convention.md](pipeline-convention.md#cross-cutting-locations)) |
| `is_entry_point` | `true` only for `rh-qs-discovery`; changes how a zero-match result is handled |
| `calling_skill` | Name of the skill invoking this subagent (for logging/messaging only) |

The main agent runs the listing command itself — the subagent never has filesystem access, it only reasons over the list it's given. The exact command depends on where the calling skill runs (see [pipeline-convention.md](pipeline-convention.md#where-skills-run-and-why-it-matters-for-paths)):
- Skills running at the `quickstart-factory` root (discovery, architect, scaffold): `ls .rhoai-qs/ 2>/dev/null`, then filter out `reports` and `blog-drafts`.
- Skills running inside `.rhoai-qs/<slug>/` itself (implement, deploy, verify-deploy, document, test-suite, ship): `ls ../ 2>/dev/null`, then filter out `reports` and `blog-drafts`.

## Resolution Logic

```
1. Does user_message name a quickstart explicitly (slug or human name)?
   - Match against existing_slugs (fuzzy: "mortgage processor" → "mortgage-processor")
   - High-confidence match → resolved, no confirmation needed
   - Ambiguous partial match → needs_user_input

2. No explicit name in user_message:
   - Zero existing_slugs:
     - is_entry_point = true  → new_quickstart (discovery will create the slug)
     - is_entry_point = false → error (a slug must already exist by this stage)
   - Exactly one existing slug → resolved, but confirm_with_user = true
   - Multiple existing slugs → needs_user_input, list all options
```

**Rule: never guess silently when more than one slug exists.** A wrong guess means writing into the wrong quickstart's files. Ambiguity always produces a question, not an assumption.

## Output

```json
{
  "resolution": "resolved | needs_user_input | new_quickstart | error",
  "slug": "mortgage-processor",
  "confidence": "high | medium | low",
  "confirm_with_user": false,
  "question_for_user": null,
  "error_message": null
}
```

**Example — ambiguous case** (two slugs exist, user didn't name one):

```json
{
  "resolution": "needs_user_input",
  "slug": null,
  "confidence": "low",
  "confirm_with_user": false,
  "question_for_user": "Which quickstart is this for — mortgage-processor or spending-transaction-monitor?",
  "error_message": null
}
```

**Example — error case** (non-entry-point skill, no slugs exist yet):

```json
{
  "resolution": "error",
  "slug": null,
  "confidence": "high",
  "confirm_with_user": false,
  "question_for_user": null,
  "error_message": "No quickstarts found under .rhoai-qs/. rh-qs-deploy requires an existing PRD and design — run rh-qs-discovery first."
}
```

## Main Agent Handling

| `resolution` | Main agent action |
|---|---|
| `resolved`, `confirm_with_user: false` | Proceed directly with `slug` |
| `resolved`, `confirm_with_user: true` | Show the assumed slug, ask for a quick confirmation, then proceed |
| `needs_user_input` | Present `question_for_user`, wait for the answer, re-resolve |
| `new_quickstart` | Proceed into discovery's normal PRD-creation flow; the slug is created later once the idea has a name |
| `error` | Show `error_message` to the user and stop — do not fabricate a slug |

## Once Resolved

Every subsequent phase constructs paths using the resolved `slug`, in whichever form matches the calling skill's own working directory:

```
# From the quickstart-factory root (discovery, architect, scaffold):
.rhoai-qs/<slug>/pipeline/<skill>-spec.yaml
.rhoai-qs/<slug>/prds/prd.md
.rhoai-qs/<slug>/designs/design.md

# From inside .rhoai-qs/<slug>/ itself (implement, deploy, verify-deploy,
# document, test-suite, ship):
pipeline/<skill>-spec.yaml
prds/prd.md
designs/design.md
```

## Relationship to Other Foundation Docs

- **[pipeline-convention.md](pipeline-convention.md)** — defines the `.rhoai-qs/<slug>/` layout that `validation-skill` resolves into
- **[skill-directory-structure.md](skill-directory-structure.md)** — lists `subagents/validation-skill-prompt.md` as a required subagent for every skill
