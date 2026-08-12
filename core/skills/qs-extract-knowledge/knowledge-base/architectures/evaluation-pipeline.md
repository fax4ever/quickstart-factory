---
name: evaluation-pipeline
description: LLM-as-judge evaluation framework using DeepEval GEval with database snapshot isolation and dual eval modes
summary: "Validates LLM application endpoints via two modes: chat evaluation using DeepEval GEval with custom rubrics (score ranges 0-2/5-7/8-9/10, threshold 0.5) where a VLLMJudge wraps the project's vLLM endpoint via ChatOpenAI (OPENAI_API_ENDPOINT/OPENAI_API_TOKEN) as DeepEval-compatible LLM scoring INPUT/ACTUAL_OUTPUT/EXPECTED_OUTPUT, and alert evaluation comparing string-cast first-row/first-column SQL results between generated and golden queries via psycopg2. Use chat mode for correctness scoring of /api/chat responses against golden answers in JSON experiment datasets (datasets/<feature>/<dataset>/ with DATASET_APP_CONFIG_ID scoping), and alert mode for /api/alerts SQL generation -- both send concurrent asyncio.gather requests with unique session_ids and save results to timestamped JSON in preds/. Database snapshot isolation via save_snapshot/restore_snapshot saves the full live PostgreSQL state (all tables), loads db_seed_data.sql seed data, runs evaluation against seeded state, and restores in a finally block even on error. The same LLM serves as both application and judge (shared bias risk inflating scores), application writes during eval are lost on full-table snapshot restore, alert comparison fails for multi-row/multi-column results, the Flask backend must be running separately before evals, and exit code 1 on any test failure enables CI pipeline gating."
metadata:
  type: architecture
tags:
  tech_stack: [python, deepeval, langchain, flask, postgresql]
  ai_pattern: [evaluation, agents]
  platform: [vllm, rhoai, openshift]
  data_layer: [postgresql]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Dual-mode eval framework: LLM-as-judge GEval for chat quality (correctness scoring with rubrics) and SQL result comparison for alert accuracy, with database snapshot/restore isolation"
    approach: "A"
---

# Evaluation Pipeline

## Overview

This architecture provides an automated evaluation framework for validating LLM-powered application endpoints. It supports two evaluation modes: a chat evaluation that uses an LLM-as-judge (via DeepEval's GEval metric with custom rubrics) to score response correctness against golden answers, and an alert evaluation that compares SQL query results between generated and reference queries. Both modes operate against a controlled database state -- the live database is snapshotted before evaluation, replaced with seed data, and restored afterward -- ensuring reproducible results without affecting production data.

## Data Flow

1. The eval script discovers experiment JSON files from `datasets/<feature>/<dataset>/` directory
2. Live database is snapshotted to a volume-backed file via `save_snapshot()`
3. Eval seed data (pre-built detection records) is loaded from `db_seed_data.sql` via `load_seed()`
4. For chat evaluation: questions are sent concurrently to the running `/api/chat` endpoint, responses are collected, and DeepEval GEval scores each response against the golden answer using a custom `VLLMJudge` model backed by the same vLLM endpoint the application uses
5. For alert evaluation: rules are sent concurrently to `/api/alerts`, generated SQL is executed against the seeded database, and results are compared against golden SQL output
6. Results are saved to timestamped JSON files in `preds/<feature>/<dataset>/`
7. Live database is restored from snapshot in a `finally` block (even on error)

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| run_eval.py | Flask /api/chat | REST (POST) | Send evaluation questions with description context |
| run_eval.py | Flask /api/alerts | REST (POST) | Send alert rules for SQL generation |
| run_eval.py | PostgreSQL | psycopg2 | Snapshot/restore live data, load seed data, execute golden SQL |
| VLLMJudge | vLLM endpoint | REST (OpenAI-compatible) | Judge LLM evaluates response correctness |
| DeepEval GEval | VLLMJudge | Python method call | Scoring via custom DeepEvalBaseLLM implementation |

## Key Integration Points

### Custom VLLMJudge for DeepEval

The judge model wraps the project's own vLLM endpoint as a DeepEval-compatible LLM, reusing the same connection configuration as the application. This means the same model that serves the application also evaluates its own outputs.

```python
# app/evals/judge_model.py (lines 9-35)
class VLLMJudge(DeepEvalBaseLLM):
    """Wraps the project's OpenAI-compatible VLLM endpoint for use as a
    DeepEval LLM-as-a-judge evaluator."""

    def __init__(self) -> None:
        self._chat = ChatOpenAI(
            base_url=os.environ["OPENAI_API_ENDPOINT"],
            api_key=os.environ["OPENAI_API_TOKEN"],
            model=os.getenv("OPENAI_MODEL", "llama-4-scout-17b-16e-w4a16"),
            temperature=0.7,
        )

    def generate(self, prompt: str) -> str:
        return self._chat.invoke(prompt).content

    async def a_generate(self, prompt: str) -> str:
        res = await self._chat.ainvoke(prompt)
        return res.content
```

### GEval Correctness Metric with Custom Rubrics

The chat evaluation uses DeepEval's GEval with explicit evaluation steps and score rubrics, focusing on numerical accuracy between actual and expected outputs.

```python
# app/evals/run_eval.py (lines 142-172)
correctness = GEval(
    name="Correctness",
    evaluation_steps=[
        "Check that the actual output directly answers the core question in the input.",
        "Verify all numerical values and yes/no conclusions match between the actual output and the expected output. Treat 'no'/'none' as 0.",
        "Penalize contradicted or omitted key facts; extra detail or phrasing differences are acceptable.",
    ],
    rubric=[
        Rubric(
            score_range=(0, 2),
            expected_outcome="Numerical values not matching between the actual output and the expected output.",
        ),
        Rubric(
            score_range=(5, 7),
            expected_outcome="numberical values matching between the actual output and the expected output. there is some additional information.",
        ),
        Rubric(score_range=(8, 9), expected_outcome="Correct but missing minor details."),
        Rubric(score_range=(10, 10), expected_outcome="100% correct."),
    ],
    evaluation_params=[
        LLMTestCaseParams.INPUT,
        LLMTestCaseParams.ACTUAL_OUTPUT,
        LLMTestCaseParams.EXPECTED_OUTPUT,
    ],
    model=judge,
    threshold=THRESHOLD,
)
```

### Database Snapshot Isolation

The evaluation framework snapshots the live database before loading seed data, ensuring the production state is restored even if the evaluation fails.

```python
# app/evals/run_eval.py (lines 518-541)
print("Saving live database snapshot to volume ... ", end="", flush=True)
stmt_count = save_snapshot()
print(f"done ({stmt_count} statements)")

try:
    print("Loading eval seed data ... ", end="", flush=True)
    counts = load_seed(SEED_SQL_PATH)
    summary = ", ".join(f"{t}: {n}" for t, n in counts.items())
    print(f"done ({summary})")
    run()
finally:
    print("\nRestoring live database from snapshot ... ", end="", flush=True)
    try:
        restored = restore_snapshot()
        summary = ", ".join(f"{t}: {n}" for t, n in restored.items())
        print(f"done ({summary})")
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
```

### Alert Evaluation via SQL Result Comparison

The alert evaluation mode bypasses LLM judging entirely, instead comparing the numeric output of generated SQL against golden SQL queries executed against the seeded database.

```python
# app/evals/run_eval.py (lines 350-373)
try:
    predicted_result = execute_sql(predicted_sql)
except Exception as exc:
    # ...SQL execution failed...

try:
    actual_golden = execute_sql(golden_sql)
except Exception as exc:
    actual_golden = golden_result

passed = str(predicted_result).strip() == str(actual_golden).strip()
score = 1.0 if passed else 0.0
```

## Prompt / Chain Patterns

The evaluation framework does not define its own prompts -- it evaluates the application's existing chat and alert LangGraph pipelines end-to-end by calling their REST endpoints. The GEval metric delegates prompt construction to DeepEval internally, which builds a judge prompt from the evaluation steps, rubrics, and test case parameters.

Experiment datasets are JSON arrays where each entry contains:
- Chat: `{"id": "...", "question": "...", "description": "...", "golden_answer": "..."}`
- Alerts: `{"id": "...", "rule": "...", "golden_sql": "...", "golden_result": "..."}`

Dataset-specific `app_config_id` values are mapped via a hardcoded dictionary (`DATASET_APP_CONFIG_ID`), scoping all queries to the correct detection configuration within the seeded database.

## Gotchas

- The same LLM model serves as both the application's response generator and the evaluation judge. This means the judge may share the same biases or failure modes as the application model, potentially inflating scores.
- Chat evaluation requests are sent concurrently (`asyncio.gather`) to the running backend, which must be started separately before running evals. Each test case uses a unique session_id (`{eval_run_id}_{entry_id}`) to prevent conversation memory cross-contamination.
- The `THRESHOLD` is set to 0.5 (on a 0-1 scale, where GEval scores 0-10 are normalized). The rubric score ranges (0-2, 5-7, 8-9, 10) mean that only responses with matching numerical values score above the pass threshold.
- The `save_snapshot` and `restore_snapshot` functions operate on the full database (all tables). If the application writes to the database during evaluation (e.g., from ongoing video processing), those writes will be lost when the snapshot is restored.
- Alert evaluation compares first-row, first-column string representations of SQL results. This is intentionally simple -- it works for aggregate queries (COUNT, SUM) but would fail for multi-row or multi-column results.
- The eval script exits with code 1 if any test case fails (`sys.exit(0 if all_passed else 1)`), making it suitable for CI pipeline gating.

## Related Architectures

- [multimodal-video-analytics](multimodal-video-analytics.md) -- The chat and alert endpoints being evaluated are part of the multimodal video analytics pipeline
- [agent-orchestration](agent-orchestration.md) -- The LangGraph chat and alert graphs being evaluated
