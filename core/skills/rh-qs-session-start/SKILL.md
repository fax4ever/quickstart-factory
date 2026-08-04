---
name: rh-qs-session-start
description: Interactive hello flow — fetch backlog, show dashboard, offer action menu. Triggered when the user says hello or hi.
---

# Session Start

When the user says **"hello"** or **"hi"**:

1. **Fetch the backlog** by running:
   ```bash
   python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --summary
   ```
2. **Present the dashboard** using the format below.
3. **Offer the action menu** and wait for the user to pick.

## Dashboard Format

```
# Quickstart Factory Dashboard

## Backlog
- Open issues: X
- By label: [summary from --summary output]
- By assignee: [summary from --summary output]

## In-Progress Quickstarts
[list slugs found under `ls .rhoai-qs/ 2>/dev/null`, excluding `reports` and `blog-drafts`, or "None yet" if empty]

## What would you like to do?

1. **View backlog** — Browse open issues, search, or filter by label
2. **Groom the backlog** — Readiness scoring, prioritization, coverage analysis
3. **Create an issue** — Add a new quickstart suggestion
4. **Write a blog post** — Draft an announcement for a completed quickstart
5. **Identify gaps** — Find missing industries, technologies, or use cases
6. **Check completed** — See which quickstarts are done (closed issues)
7. **Filter by label** — Show only Acknowledged, quickstart_suggestion, or kickstart_request
```

After the user picks an option, use the corresponding skill. When the action is complete, offer the menu again.

## Purpose

Manage the full lifecycle of Red Hat AI Quickstarts: backlog tracking, issue creation, grooming, blog drafting, and gap analysis.

## Data Source

**GitHub Issues** is the single source of truth for the backlog:
- **Backlog:** https://github.com/rh-ai-quickstart/ai-quickstart-contrib/issues
- **Template:** https://github.com/rh-ai-quickstart/ai-quickstart-template
- **Catalog:** https://docs.redhat.com/en/learn/ai-quickstarts
- **GitHub org:** https://github.com/rh-ai-quickstart

## Issue Labels

| Label | Meaning |
|-------|---------|
| `quickstart_suggestion` | A proposed quickstart idea (default for new issues) |
| `Acknowledged` | The suggestion has been reviewed and acknowledged by the team |
| `kickstart_request` | An external request for a quickstart (from outside the team) |

Use `--label` with gh-backlog-reader to filter by label:
```bash
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --label Acknowledged
```

## Skills

| Skill | When to Use |
|-------|-------------|
| gh-backlog-reader | Read, filter, or summarize the GitHub issues backlog |
| gh-issue-creator | Create new quickstart suggestion issues |
| pipeline-grooming | Groom, prioritize, or categorize the backlog |
| blog-writer | Generate blog post drafts for completed quickstarts |
| quickstart-identifier | Identify potential new quickstarts from trends and gaps |
| rh-qs-secure | Cluster access guardrails and application security (embedded in architect/deploy) |
| rh-qs-verify-deploy | Post-deploy verification before README documentation |
| rh-qs-bump-versions | Bump Python, Node, Helm, and image versions |

## Skill Execution

### gh-backlog-reader
```bash
# Summary
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --summary
# All open issues
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py
# Search
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --search "keyword"
# Closed/completed issues
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --state closed
# Full details
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --detail
# Filter by assignee
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --assignee username
```

### gh-issue-creator
```bash
# Always dry-run first
python3 core/skills/gh-issue-creator/scripts/create_issues.py --name "Name" --dry-run
# Create with metadata
python3 core/skills/gh-issue-creator/scripts/create_issues.py \
  --name "Name" --description "..." --technology "..." --industry "..."
```

### pipeline-grooming
Conversational. Read `core/skills/pipeline-grooming/SKILL.md` and `references/grooming-criteria.md`, then:
- Fetch the backlog with gh-backlog-reader
- Score each issue against the readiness rubric
- Produce a grooming report with gaps, coverage, and recommendations

### blog-writer
Conversational. Read `core/skills/blog-writer/SKILL.md`, `assets/blog-template.md`, and `references/messaging-guidelines.md`, then:
- Fetch the issue with `gh-backlog-reader --issue <N>` to get comments and linked repos
- If a linked implementation repo exists, browse its README to understand architecture and usage
- Generate a draft in `.rhoai-qs/{slug}/blog-drafts/{date}.md` (or the top-level `.rhoai-qs/blog-drafts/{slug}-{date}.md` if no slug folder exists for this quickstart yet — the slug is needed there since that folder mixes drafts for every quickstart lacking its own slug folder)

### quickstart-identifier
Conversational. Read `core/skills/quickstart-identifier/SKILL.md` and `references/industry-trends.md`, then:
- Fetch current backlog with gh-backlog-reader
- Compare against industry and technology targets
- Propose new quickstarts with rationale

## Request Routing

| User Request | Route To |
|--------------|----------|
| "Show backlog" / "List issues" / "Backlog summary" | gh-backlog-reader |
| "Show my issues" / "Issues by [user]" | gh-backlog-reader --author username (or --assignee) |
| "Create issue" / "Add to backlog" / "Suggest quickstart" | gh-issue-creator |
| "Groom backlog" / "Prioritize" / "Categorize" | pipeline-grooming |
| "Write blog draft" / "Announce quickstart" | blog-writer |
| "Blog for issue #39" / "Write blog for this quickstart" | gh-backlog-reader --issue N → blog-writer (uses linked repo) |
| "Identify gaps" / "Coverage analysis" / "New quickstart ideas" | quickstart-identifier |
| "Check completed" / "What's done" / "Closed issues" | gh-backlog-reader --state closed |
| "Show issue #39" / "Details on issue 39" | gh-backlog-reader --issue 39 (includes comments + linked repos) |

## Output Directory

All generated artifacts (blog drafts, grooming reports, coverage analyses, PRDs, designs, code, etc.) go under `.rhoai-qs/`, namespaced by quickstart slug:

```
.rhoai-qs/
  <slug>/
    pipeline/            ← Specs and manifests for that quickstart
    prds/                ← PRD from rh-qs-discovery
    designs/              ← Design doc from rh-qs-architect
    blog-drafts/          ← Blog post drafts for that quickstart
    reports/              ← Per-quickstart reports (verify-deploy, etc.)
    packages/, deploy/    ← The quickstart's own application code (separate git repo)
  reports/                ← Cross-cutting reports not tied to one quickstart (grooming, gap analysis)
  blog-drafts/             ← Fallback for quickstarts predating this convention
```

This directory is gitignored by the factory repo — nothing under `.rhoai-qs/` gets pushed to `quickstart-factory`'s own history. (The quickstart's own code still gets committed and pushed — just to its own separate GitHub repo.) See [pipeline-convention.md](../../../docs/foundation/pipeline-convention.md) for the full convention.

## Governance

- **Business outcome required** before development
- Issues follow `[Quickstart suggestion]` template
- Blog posts reference catalog and repo
- **No API keys or credentials** in any artifacts
- **Blog posts:** drafts requiring review before publication
