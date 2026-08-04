---
name: blog-writer
description: Generate blog post drafts for completed AI Quickstarts. Use when announcing new quickstarts to Red Hat audience.
---

# blog-writer

## Purpose

Generate blog post drafts for completed AI Quickstarts. Outputs to `.rhoai-qs/<slug>/blog-drafts/` (or the top-level `.rhoai-qs/blog-drafts/` if the quickstart's own slug folder doesn't exist, e.g. for older quickstarts predating this convention). Drafts require review before publication.

## Workflow

1. **Identify candidate:** Use `gh-backlog-reader --issue <N>` to view the issue, its comments, and linked repositories.
2. **Gather context:** If a linked implementation repo exists (auto-extracted from comments), browse the repo README and code to understand what the quickstart does, its architecture, and how to run it.
3. **Study reference examples:** Fetch the example blog posts listed in [references/blog-examples.md](references/blog-examples.md) using WebFetch. Analyze their structure, tone, and business framing. Use them as stylistic guides — match their narrative depth and enterprise perspective, not just the template structure.
4. **Draft the blog post:** Use the format and template below.

Issues with an implementation repo linked in the comments are prime candidates for blog posts — the quickstart is being built or is already done.

## Blog Format Selection

Choose format based on quickstart type:
- **Standard announcement:** Use template (Hook, What It Does, How It Works, Get Started, What's Next, CTA)
- **Technical deep-dive:** Add architecture diagram, code snippets
- **Use case spotlight:** Emphasize industry and outcome

## Standard Links

Include in every blog post:
- **Catalog:** https://docs.redhat.com/en/learn/ai-quickstarts
- **Repository:** Link to the quickstart's implementation GitHub repo (from issue comments)
- **Contrib:** https://github.com/rh-ai-quickstart/ai-quickstart-contrib

## Output

- **If the quickstart's slug folder exists:** `.rhoai-qs/<slug>/blog-drafts/YYYY-MM-DD.md` — no slug in the filename, the folder already disambiguates (e.g. `.rhoai-qs/vllm-cpu/blog-drafts/2025-03-11.md`)
- **Fallback (no slug folder, e.g. an older quickstart predating this convention):** `.rhoai-qs/blog-drafts/{quickstart-slug}-YYYY-MM-DD.md` — the slug **is** needed here since this top-level folder mixes drafts for every quickstart lacking its own slug folder (e.g. `vllm-cpu-2025-03-11.md`)

> **Note:** it isn't yet certain how often this fallback path will actually be used in practice — most quickstarts going forward should have their own slug folder from the start. See [pipeline-convention.md](../../../docs/foundation/pipeline-convention.md#cross-cutting-locations).

## References

- **Template:** [assets/blog-template.md](assets/blog-template.md)
- **Messaging:** [references/messaging-guidelines.md](references/messaging-guidelines.md)
- **Examples:** [references/blog-examples.md](references/blog-examples.md)
