# Quickstart Factory

An AI-powered tool for managing the full lifecycle of [Red Hat AI Quickstarts](https://docs.redhat.com/en/learn/ai-quickstarts) — from idea to published quickstart. Just say **"hello"** and your AI assistant takes it from there.

## What it does

Quickstart Factory connects your AI coding assistant (Claude, Cursor, Gemini, or Codex) to the [AI Quickstart backlog](https://github.com/rh-ai-quickstart/ai-quickstart-contrib/issues) on GitHub, giving you a conversational interface to:

- **Browse and search** the backlog — filter by author, assignee, label, or keyword
- **Create issues** — add new quickstart suggestions with metadata
- **Groom the backlog** — readiness scoring, prioritization, coverage analysis
- **Write blog posts** — generate drafts for completed quickstarts
- **Identify gaps** — find missing industries, technologies, or use cases

## How it works

Open the project in your AI client and say **"hello"** or run `/rh-qs-session-start`. The assistant fetches the live backlog from GitHub and presents a dashboard:

![Dashboard](screenshots/06-dashboard.png)

From there, just ask what you need in natural language — query issues, drill into details, discover linked implementation repos, and generate blog drafts:

![Blog draft](screenshots/12-blog-draft-preview.png)

See the [full walkthrough with screenshots](screenshots/README.md) for the complete workflow.

## Getting started

### Prerequisites

- Python 3
- [`gh` CLI](https://cli.github.com/) installed and authenticated (`gh auth status`)
- An AI coding client: [Claude Code](https://docs.anthropic.com/en/docs/claude-code), [Cursor](https://cursor.sh), [Gemini Code Assist](https://cloud.google.com/gemini/docs/codeassist/overview), or [Codex](https://openai.com/index/codex/)

### Setup

1. Clone the repository:

```bash
git clone https://github.com/ccamacho/quickstart-factory.git
cd quickstart-factory
```

2. Open in your AI client and say **"hello"**:

```bash
claude                       # Claude Code
cursor quickstart-factory/   # Cursor IDE
```

Skills are included as symlinks in the repo — no manual setup needed.

## Skills

| Skill | What it does |
|-------|-------------|
| **gh-backlog-reader** | Read, filter, and summarize GitHub issues. Supports `--issue` (single issue with comments and linked repos), `--author`, `--assignee`, `--label`, `--search`, `--state`, `--detail`. |
| **gh-issue-creator** | Create new `[Quickstart suggestion]` issues with duplicate detection. Supports `--name`, `--description`, `--technology`, `--industry`, `--dry-run`. |
| **pipeline-grooming** | AI-assisted backlog grooming with readiness scoring, industry/technology coverage analysis, and prioritization recommendations. |
| **blog-writer** | Generate blog post drafts for completed quickstarts using standard templates and messaging guidelines. |
| **quickstart-identifier** | Gap analysis comparing the current backlog against industry trends and technology adoption targets. |

## CLI usage

You can also run the scripts directly:

```bash
# Backlog summary
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --summary

# Single issue with comments and linked repos
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --issue 39

# Issues by a specific author
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --author ccamacho

# Search for topics
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --search "Financial Services"

# Filter by label
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --label Acknowledged

# Create an issue (dry-run first)
python3 core/skills/gh-issue-creator/scripts/create_issues.py \
  --name "GraphRAG" \
  --technology "Llama Stack" \
  --dry-run
```

## Resources

- **Backlog:** https://github.com/rh-ai-quickstart/ai-quickstart-contrib/issues
- **Quickstart template:** https://github.com/rh-ai-quickstart/ai-quickstart-template
- **Quickstart catalog:** https://docs.redhat.com/en/learn/ai-quickstarts
- **GitHub org:** https://github.com/rh-ai-quickstart

## Project structure

```
AGENTS.md               ← AI agent guidelines (read by all clients)
CLAUDE.md               ← Imports AGENTS.md (for Claude Code)
GEMINI.md               ← Symlink → AGENTS.md (for Gemini)
core/
  skills/
    gh-backlog-reader/  ← Read GitHub backlog
    gh-issue-creator/   ← Create GitHub issues
    pipeline-grooming/  ← Backlog grooming
    blog-writer/        ← Blog post generation
    quickstart-identifier/ ← Gap analysis
  scripts/
    sync-clients.sh     ← Sync skills to AI clients
data/                   ← Generated output (gitignored)
  blog-drafts/          ← Blog post drafts
  reports/              ← Grooming reports
```

## Multi-client support

The same skills work across Claude, Cursor, Gemini, and Codex. Each client reads `AGENTS.md` through its preferred file:

| Client | Reads from |
|--------|-----------|
| Claude Code | `CLAUDE.md` → `AGENTS.md` |
| Gemini | `GEMINI.md` → `AGENTS.md` |
| Codex | `AGENTS.md` directly |
| Cursor | `.cursor/rules/agents.md` → `AGENTS.md` |

Skills are committed as relative symlinks in each client's directory. Run `bash core/scripts/sync-clients.sh` to regenerate after adding new skills.

Skills update a per-quickstart progress dashboard at `.rhoai-qs/<qs-name>/flow/dashboard.md` via `core/flow/pipeline-checkpoint.py`. Claude pre-allows that command in `.claude/settings.json`; Cursor intentionally does not ship a repo `permissions.json` (default Auto-review + sandbox is enough).

## License

Licensed under Apache License 2.0. See [`LICENSE`](./LICENSE).
