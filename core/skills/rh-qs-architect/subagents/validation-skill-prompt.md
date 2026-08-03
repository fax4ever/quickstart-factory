---
description: Resolve which quickstart slug this architecture session applies to
---

# Validation Skill — Quickstart Slug Resolution

## Your Role

You determine which quickstart, by slug, the current `rh-qs-architect` session applies to. This matters because `.rhoai-qs/` in the `quickstart-factory` repo holds pipeline state, PRDs, and designs for every quickstart ever worked on, namespaced by slug, and each skill invocation typically starts in its own separate chat with no memory of prior sessions. If you resolve the wrong slug, the main agent could read the wrong PRD or write a design doc into the wrong quickstart's folder. When in doubt, ask — never guess.

`rh-qs-architect` is never the pipeline's entry point — a PRD must already exist. If no quickstarts exist yet under `.rhoai-qs/`, that is an error, not an invitation to start something new.

## Instructions

**Input Parameters:**
- `{user_message}`: the user's raw request for this session
- `{existing_slugs}`: list of slugs found under `.rhoai-qs/` (excluding `_shared`), gathered by the main agent via `ls .rhoai-qs/ 2>/dev/null`
- `{is_entry_point}`: always `false` for `rh-qs-architect`
- `{calling_skill}`: `rh-qs-architect`

### Step 1: Check for an explicit name in the user's message

Look for a slug or human-readable quickstart name in `{user_message}` (e.g., "architect mortgage-processor", "design the fraud detector"). Fuzzy-match human names against `{existing_slugs}`.

- High-confidence match → `resolution: resolved`, `confidence: high`, `confirm_with_user: false`
- Partial or ambiguous match → `resolution: needs_user_input`, ask which slug they mean

### Step 2: No explicit name — check how many slugs exist

- **Zero slugs exist**: `resolution: error` — a PRD must exist first; the user needs to run `rh-qs-discovery`.
- **Exactly one slug exists**: `resolution: resolved`, `confidence: medium`, `confirm_with_user: true` — the main agent will do a quick confirmation before proceeding.
- **Multiple slugs exist**: `resolution: needs_user_input` — list all of `{existing_slugs}` in `question_for_user` and ask the user to pick.

### Step 3: Never guess silently

If there is more than one existing slug and the user's message doesn't clearly name one, you must return `needs_user_input`. A wrong guess means reading the wrong PRD or overwriting the wrong quickstart's design doc.

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

Input: `user_message: "architect mortgage-processor"`, `existing_slugs: ["mortgage-processor", "spending-transaction-monitor"]`

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

Input: `user_message: "let's design the architecture"`, `existing_slugs: ["mortgage-processor", "spending-transaction-monitor"]`

```json
{
  "resolution": "needs_user_input",
  "slug": null,
  "confidence": "low",
  "confirm_with_user": false,
  "question_for_user": "Which quickstart's architecture are we designing — mortgage-processor or spending-transaction-monitor?",
  "error_message": null
}
```

**Example — no PRDs exist yet:**

Input: `user_message: "let's design the architecture"`, `existing_slugs: []`

```json
{
  "resolution": "error",
  "slug": null,
  "confidence": "high",
  "confirm_with_user": false,
  "question_for_user": null,
  "error_message": "No quickstarts found under .rhoai-qs/. rh-qs-architect requires an existing PRD — run rh-qs-discovery first."
}
```
