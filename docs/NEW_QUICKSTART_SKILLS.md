# New Quickstart Skills 

# Goal
The greenfield skills pipeline flow is a set of skills executed in a particular order, with the goal of creating a totally new AI Quickstart

# What skills make up this flow?

```mermaid
flowchart TB
    Input["User input<br/>(idea, document, or hello)"]

    D["1. rh-qs-discovery<br/>Ideation → interview → PRD"]
    A["2. rh-qs-architect<br/>PRD → tech mapping → design"]
    Sec["2b. rh-qs-secure<br/>Security considerations"]
    S["3. rh-qs-scaffold<br/>Design → repo setup"]
    I["4. rh-qs-implement<br/>Scaffold → vertical slice"]
    VB["4b. rh-qs-verify-build<br/>Local build verification"]
    Dep["5. rh-qs-deploy<br/>Helm + Makefile deploy"]
    T["5b. rh-qs-test-suite<br/>GitHub Actions CI/E2E"]
    VD["5c. rh-qs-verify-deploy<br/>On-cluster verification"]
    Doc["6. rh-qs-document<br/>README after verified deploy"]
    Sh["7. rh-qs-ship<br/>Docs → PR → announce"]

    Input --> D
    D -->|"PRD<br/>.rhoai-qs/&lt;slug&gt;/prds/prd.md"| A
    A --> Sec
    Sec -->|"Design doc + security<br/>.rhoai-qs/&lt;slug&gt;/designs/design.md"| S
    S -->|"GitHub repo + CI/CD"| I
    I -->|"Working app"| VB
    VB --> Dep
    Dep --> T
    T --> VD
    Dep --> VD
    VD -->|"verify-deploy report"| Doc
    Doc -->|"README.md + catalog metadata"| Sh
    Sh -->|"PR URL + blog draft"| Review["Human review"]
```

| Stage | Skill | Output | Location |
|-------|-------|--------|----------|
| 1 | rh-qs-discovery | `.rhoai-qs/<slug>/prds/prd.md` | `core/skills/rh-qs-discovery/` |
| 2 | rh-qs-architect | `.rhoai-qs/<slug>/designs/design.md` | `core/skills/rh-qs-architect/` |
| 2b | rh-qs-secure | Security section in design doc | `core/skills/rh-qs-secure/` |
| 3 | rh-qs-scaffold | GitHub repo + CI/CD | `core/skills/rh-qs-scaffold/` |
| 4 | rh-qs-implement | Working application code | `core/skills/rh-qs-implement/` |
| 4b | rh-qs-verify-build | Local build verified | `core/skills/rh-qs-verify-build/` |
| 5 | rh-qs-deploy | Helm chart + compose.yml | `core/skills/rh-qs-deploy/` |
| 5b | rh-qs-test-suite | GitHub Actions (PR/E2E/nightly) | `core/skills/rh-qs-test-suite/` |
| 5c | rh-qs-verify-deploy | `.rhoai-qs/<slug>/reports/verify-deploy-*.md` | `core/skills/rh-qs-verify-deploy/` |
| 6 | rh-qs-document | README.md + docs/ | `core/skills/rh-qs-document/` |
| 7 | rh-qs-ship | PR URL + blog draft | `core/skills/rh-qs-ship/` |

**Maintenance (any time):** `rh-qs-bump-versions` — dependency and chart version updates.

# Flow

When using the skills please start with the `rh-qs-discovery` and the skills will lead you to the next step in the process.
Some steps like 1–3 need to be done in order because the data needs to be in place before the next skill runs.

**Documentation comes after deploy verification** — do not run `rh-qs-document` until `rh-qs-verify-deploy` passes.

**Cluster access:** agents use Helm/Makefile only — no raw `oc`/`kubectl`. See `rh-qs-secure`.

## Where Everything Lives

Every skill above runs inside the `quickstart-factory` repo. Everything for a quickstart — pipeline state, PRD, design, blog drafts, reports, **and its application code** — lives together under `quickstart-factory/.rhoai-qs/<slug>/`, namespaced by quickstart slug. Starting at stage 3, that folder also becomes the working directory of a real, separate GitHub repo (`rh-ai-quickstart/<slug>`), set up there by `rh-qs-scaffold` — it's a distinct git repository with its own remote and history, just nested inside `.rhoai-qs/<slug>/` rather than sitting next to it.

Because each skill typically runs in a fresh, separate chat session, and `.rhoai-qs/` can hold data for many quickstarts at once, **every skill resolves which quickstart it's working on before doing anything else**, via the `validation-skill` subagent (Phase 0). See [pipeline-convention.md](foundation/pipeline-convention.md) and [validation-skill-template.md](foundation/validation-skill-template.md).
