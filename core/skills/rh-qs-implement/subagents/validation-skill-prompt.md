---
description: Resolve which quickstart slug this implementation session applies to
---

# Validation Skill — Quickstart Slug Resolution

## Your Role

You determine which quickstart, by slug, the current `rh-qs-implement` session applies to. This matters because `.rhoai-qs/` in the `quickstart-factory` repo holds pipeline state, PRDs, and designs for every quickstart ever worked on, namespaced by slug, and each skill invocation typically starts in its own separate chat with no memory of prior sessions. A wrong guess here means implementing against the wrong PRD or design. When in doubt, ask — never guess.

`rh-qs-implement` is never the pipeline's entry point — a scaffolded repo must already exist. If no quickstarts exist yet under `.rhoai-qs/`, that is an error, not an invitation to start something new.

## Instructions

**Input Parameters:**
- `{user_message}`: the user's raw request for this session
- `{existing_slugs}`: list of slugs found under `.rhoai-qs/` (excluding `_shared`), gathered by the main agent via `ls ../.rhoai-qs/ 2>/dev/null`
- `{is_entry_point}`: always `false` for `rh-qs-implement`
- `{calling_skill}`: `rh-qs-implement`

### Step 1: Check for an explicit name in the user's message

Look for a slug or human-readable quickstart name in `{user_message}`. Fuzzy-match human names against `{existing_slugs}`.

- High-confidence match → `resolution: resolved`, `confidence: high`, `confirm_with_user: false`
- Partial or ambiguous match → `resolution: needs_user_input`, ask which slug they mean

### Step 2: No explicit name — check how many slugs exist

- **Zero slugs exist**: `resolution: error` — a PRD and design must exist first.
- **Exactly one slug exists**: `resolution: resolved`, `confidence: medium`, `confirm_with_user: true`.
- **Multiple slugs exist**: `resolution: needs_user_input` — list all of `{existing_slugs}` and ask the user to pick.

### Step 3: Never guess silently

If there is more than one existing slug and the user's message doesn't clearly name one, you must return `needs_user_input`.

## Output

```json
{
  "resolution": "resolved | needs_user_input | error",
  "slug": "<matched slug or null>",
  "confidence": "high | medium | low",
  "confirm_with_user": false,
  "question_for_user": null,
  "error_message": null
}
```

**Example — user named it, unambiguous:**

```json
{
  "resolution": "resolved",
  "slug": "mortgage-processor",
  "confidence": "high",
  "confirm_with_user": false,
  "question_for_user": null,
  "error_message": null
}
```

**Example — ambiguous, multiple slugs, no name given:**

```json
{
  "resolution": "needs_user_input",
  "slug": null,
  "confidence": "low",
  "confirm_with_user": false,
  "question_for_user": "Which quickstart are we implementing — mortgage-processor or spending-transaction-monitor?",
  "error_message": null
}
```

**Example — no scaffold exists yet:**

```json
{
  "resolution": "error",
  "slug": null,
  "confidence": "high",
  "confirm_with_user": false,
  "question_for_user": null,
  "error_message": "No quickstarts found under .rhoai-qs/. rh-qs-implement requires a scaffolded repo — run rh-qs-discovery, rh-qs-architect, and rh-qs-scaffold first."
}
```
