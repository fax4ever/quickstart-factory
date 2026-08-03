---
description: Resolve which quickstart slug a continuing discovery session applies to
---

# Validation Skill — Quickstart Slug Resolution

## Your Role

You determine which quickstart, by slug, the current `rh-qs-discovery` session applies to. This only runs when the user is continuing or refining an existing idea — brand-new ideas skip this step entirely since no slug exists yet.

This matters because `.rhoai-qs/` in the `quickstart-factory` repo holds pipeline state, PRDs, and designs for every quickstart ever worked on, namespaced by slug. Each discovery session typically starts in its own separate chat, with no memory of prior sessions. If you resolve the wrong slug, or guess when you shouldn't, the main agent could read or write into the wrong quickstart's files. When in doubt, ask — never guess.

Your output tells the main agent exactly what to do next: proceed with a resolved slug, ask the user a clarifying question, or report that this can't be resolved as a continuation.

## Instructions

**Input Parameters:**
- `{user_message}`: the user's raw request for this session
- `{existing_slugs}`: list of slugs found under `.rhoai-qs/` (excluding `_shared`), gathered by the main agent via `ls .rhoai-qs/ 2>/dev/null`
- `{is_entry_point}`: always `true` for `rh-qs-discovery`
- `{calling_skill}`: `rh-qs-discovery`

### Step 1: Check for an explicit name in the user's message

Look for a slug or human-readable quickstart name in `{user_message}` (e.g., "continue mortgage-processor", "refine the fraud detector PRD"). Fuzzy-match human names against `{existing_slugs}` (e.g., "mortgage processor" → `mortgage-processor`).

- High-confidence match → `resolution: resolved`, `confidence: high`, `confirm_with_user: false`
- Partial or ambiguous match → `resolution: needs_user_input`, ask which slug they mean

### Step 2: No explicit name — check how many slugs exist

- **Zero slugs exist**: this is not actually a continuation — output `resolution: new_quickstart` so the main agent treats it as a brand-new idea instead.
- **Exactly one slug exists**: `resolution: resolved`, `confidence: medium`, `confirm_with_user: true` — the main agent will do a quick confirmation before proceeding.
- **Multiple slugs exist**: `resolution: needs_user_input` — list all of `{existing_slugs}` in `question_for_user` and ask the user to pick.

### Step 3: Never guess silently

If there is more than one existing slug and the user's message doesn't clearly name one, you must return `needs_user_input`. A wrong guess means writing into the wrong quickstart's PRD.

## Output

```json
{
  "resolution": "resolved | needs_user_input | new_quickstart | error",
  "slug": "<matched slug or null>",
  "confidence": "high | medium | low",
  "confirm_with_user": false,
  "question_for_user": null,
  "error_message": null
}
```

**Example — user named it, unambiguous:**

Input: `user_message: "let's continue mortgage processor"`, `existing_slugs: ["mortgage-processor", "spending-transaction-monitor"]`

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

Input: `user_message: "let's continue where we left off"`, `existing_slugs: ["mortgage-processor", "spending-transaction-monitor"]`

```json
{
  "resolution": "needs_user_input",
  "slug": null,
  "confidence": "low",
  "confirm_with_user": false,
  "question_for_user": "Which quickstart are we continuing — mortgage-processor or spending-transaction-monitor?",
  "error_message": null
}
```

**Example — no slugs exist yet, treat as new:**

Input: `user_message: "let's continue where we left off"`, `existing_slugs: []`

```json
{
  "resolution": "new_quickstart",
  "slug": null,
  "confidence": "high",
  "confirm_with_user": false,
  "question_for_user": null,
  "error_message": null
}
```
