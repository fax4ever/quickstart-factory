# Scaffold Subagents

This directory contains the `validation-skill` subagent used by `rh-qs-scaffold` ([../SKILL.md](../SKILL.md)) to resolve which quickstart a session applies to before creating a repository.

## Subagent Prompts

### 1. validation-skill-prompt.md

| Field | Description |
|-------|-------------|
| **Name** | `validation-skill-prompt.md` |
| **Purpose** | Resolve which quickstart (by slug) this session applies to |
| **Input** | User's raw message, list of existing slugs under `.rhoai-qs/` (excluding `_shared`), `is_entry_point: false`, calling skill name |
| **Output** | Resolution status as JSON — resolved/needs_user_input/error, with slug and confidence |
| **When used** | Phase 0 — before reading the design doc or creating the GitHub repo |
| **Why subagent** | Mechanical slug matching against a list, self-contained — see [validation-skill-template.md](../../../../docs/foundation/validation-skill-template.md) for the full spec |

**Output schema:**

```json
{
  "resolution": "resolved|needs_user_input|error",
  "slug": "mortgage-processor",
  "confidence": "high|medium|low",
  "confirm_with_user": false,
  "question_for_user": null,
  "error_message": null
}
```

## Important Notes

**DO NOT read `validation-skill-prompt.md` directly.** Pass it by file path to the Agent tool — see [../SKILL.md](../SKILL.md) Phase 0.

If zero slugs exist under `.rhoai-qs/`, that's an error state — a PRD and design doc must already exist, so the user needs to run `rh-qs-discovery` and `rh-qs-architect` first.
