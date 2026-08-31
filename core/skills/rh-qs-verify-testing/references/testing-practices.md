# Testing Practices for Red Hat AI Quickstarts

This document is the definition of a sound testing strategy for a Red Hat AI quickstart. It is the only rubric `rh-qs-verify-testing` uses.

It states **what kinds of tests a quickstart should have and why**. It does not say how to write tests, which framework to use, or how to wire a CI system.

## Purpose

A quickstart is a production-oriented reference. People copy it. Tests exist so that:

- a change is caught before a user hits it
- Kind and OpenShift are not treated as the same environment
- the strategy is reviewable by a human and checkable by a tool, using the same bar

The practices apply to any AI quickstart. They are not tied to one product, one repo layout, or one toolchain.

## What this document is not

- A tutorial on writing tests
- A requirement to use a named framework, runner, or CI vendor
- An implementation, a generator, or a pipeline
- A substitute for exploratory testing while building the product
- A demand that every quickstart implement every kind of test below

## Principles

1. **Test the risk, not the ritual.** Each kind of test exists because a different class of failure is cheap to catch there and expensive later.
2. **The product decides applicability.** If the quickstart has no UI, UI tests are not applicable. If it never talks to a model, model-quality tests are not applicable. Absence of an inapplicable kind is not a gap.
3. **Kind is not OpenShift.** A passing Kind suite does not prove the OpenShift path. An OpenShift suite does not replace fast Kind feedback.
4. **Reduced on Kind, full on OpenShift.** Kind E2E uses a smaller, mocked surface. OpenShift E2E uses the real surface a customer would run.
5. **Functional proof and quality proof are different.** “It installed and answered” is not the same as “the model behavior is acceptable.”

## Test kinds

### 1. Unit tests

**What:** Isolated checks of one unit of logic (a function, module, or component) with no live network, cluster, database, or model.

**Why:** They are the cheapest way to lock down domain rules, parsing, state transitions, and error branches. They should fail in seconds and not depend on credentials or infrastructure.

**Applies when:** The quickstart contains logic that can be wrong independently of deployment (almost always).

### 2. Integration tests

**What:** Checks that two or more real parts of the product work together (for example API and data store, or two services) without requiring Kubernetes or OpenShift.

**Why:** Unit tests will not catch broken contracts between parts. Full-cluster tests are too slow and too coarse to be the first place those breaks show up.

**Applies when:** The quickstart has more than one runtime part that collaborate, or a part that talks to a real local dependency (database, queue, object store).

### 3. Deployment-artifact checks

**What:** Checks that installable artifacts are well-formed *before* any cluster is created. Typical targets are chart or compose rendering, manifest validity, and required values or secrets being referenced rather than hardcoded.

**Why:** Many quickstart failures are “it will not even install.” Those failures do not need a cluster to detect.

**Applies when:** The quickstart ships a deployable description (Helm, compose, or equivalent).

### 4. End-to-end tests on Kind (reduced scope, with mocking)

**What:** The product is installed into a local Kubernetes (Kind or equivalent) and exercised through a **reduced** path: only the components that can honestly run there, with OpenShift-only APIs and expensive dependencies **mocked, stubbed, or turned off**.

**Why:** This is the pre-merge confidence that “the chart installs and the app responds” without an OpenShift cluster, GPUs, or real operators. It exists to be repeatable and relatively cheap.

**Kind E2E must:**

- Use a smaller surface than production: disable or stub anything that only exists on OpenShift (platform CRDs, Routes as a real ingress, operators, GPUs, cluster-only controllers)
- Mock or substitute model inference when local GPUs or cluster serving are not available (fake endpoint, remote hosted model, or recorded replies)
- State clearly that it is a Kind/reduced run, not a customer OpenShift run

**Kind E2E must not:**

- Be presented as proof that the OpenShift install works
- Require a real OpenShift API, real GPU nodes, or real cluster operators to pass
- Enable the full production graph and then skip the parts that fail on Kind

**Applies when:** The quickstart is meant to be installed onto Kubernetes.

### 5. End-to-end tests on OpenShift (full scope)

**What:** The product is installed onto a real OpenShift cluster (including OpenShift AI when that is the target) and exercised on the **full** path a user would run: real routing, real security context, real operators and custom resources, and real model serving when the product uses it.

**Why:** Customers run OpenShift, not Kind. Platform behavior (SCC, Routes, operators, serving, GPU scheduling) does not show up in a mocked Kind cluster. This is the proof that the quickstart works as shipped.

**OpenShift E2E must:**

- Install the same chart (or equivalent) a user is told to install, not a Kind-only fork presented as the product
- Use real platform APIs, not stubs
- Include real inference or serving when the documented happy path uses a model
- Cover the primary user journey, not only a health endpoint

**OpenShift E2E must not:**

- Be skipped on the grounds that Kind already passed
- Silently drop platform components to make the run look green

**Applies when:** The quickstart is meant to run on OpenShift (the expected case for Red Hat AI quickstarts).

**When it runs:** This suite is allowed to be heavier and less frequent than Kind (for example a cluster job, a scheduled run, or a documented manual gate). Rarity is not an excuse for absence of the *strategy*. If full OpenShift E2E cannot run in the repo’s automation, the strategy still names how and where it is run, and what it covers.

### 6. Model and agent quality checks

**What:** Checks that the AI behavior is acceptable: retrieval quality, tool use, refusals, known-bad conversations, or other product-specific quality bars. Distinct from “the process came up.”

**Why:** A green install can still produce wrong, unsafe, or empty answers. Functional E2E will not catch that unless it is designed to.

**Applies when:** The quickstart’s value depends on model or agent behavior (generation, RAG, tools, multi-step agents). It does not apply to a quickstart that only wraps infrastructure with no model-facing path.

## Kind versus OpenShift

These are two environments with two jobs. A complete strategy treats them as a pair, not as alternatives.

| | Kind (or equivalent local Kubernetes) | OpenShift |
|---|---|---|
| Job | Fast, repeatable confidence before merge | Proof the customer path works |
| Scope | Reduced | Full |
| OpenShift-only APIs | Mocked, stubbed, or disabled | Real |
| Model serving | Mocked or substituted | Real when the product uses it |
| GPU / operators | Not required | Used when the product needs them |
| What a pass means | Install + reduced journey work in this stand-in | The shipped path works on the real platform |

A strategy that only has Kind E2E is incomplete for an OpenShift quickstart. A strategy that only has OpenShift E2E is incomplete as a day-to-day check: there is no reduced, mocked path for cheap feedback.

## What “complete” means

A quickstart has a correct and complete testing strategy when **all of the following hold**:

1. **Every applicable kind in this document is present.** Inapplicable kinds are absent on purpose, with a reason that follows from the product (no UI, no model, not Kubernetes, and so on).
2. **Each present kind has a way to run it** — a documented command, job, or gate — so the strategy is not only a paragraph in a README.
3. **Kind E2E, if applicable, is actually reduced and mocked.** A Kind run that assumes a full OpenShift cluster is not Kind E2E as defined here.
4. **OpenShift E2E, if applicable, is actually full.** A run that stubs out the platform does not count as OpenShift E2E.
5. **The two E2E environments are not collapsed into one.** Naming, docs, or jobs make the distinction visible.
6. **Quality checks exist when the product is model- or agent-shaped.** Health of a process is not a quality check.

Completeness is about the strategy matching the product. It is not about a target number of tests, a coverage percentage, or a named tool.

## Evidence a reviewer should find

For each applicable kind, some combination of the following should exist. The form can vary; the role cannot.

- Tests (or equivalent executable checks) whose scope matches the kind
- A documented way to run that kind alone
- Automation or a recorded gate that actually runs it, at a frequency that matches its cost (unit often; OpenShift E2E less often)
- For Kind and OpenShift E2E: an explicit reduced-vs-full split (separate jobs, suites, configs, or documented procedures)

Missing documentation of *how* to run an existing suite is a gap in the strategy. A paragraph that promises tests with no executable check is also a gap.

## Gaps versus non-goals

**Gap:** An applicable kind has no executable check, or Kind/OpenShift are conflated, or quality is claimed but only health is tested.

**Not a gap:**

- An inapplicable kind is missing
- A particular framework or CI vendor is not used
- Exploratory or manual testing during development is not automated (this document does not replace that)
- OpenShift E2E is infrequent, as long as the strategy still defines it and it is full-scope when it runs
