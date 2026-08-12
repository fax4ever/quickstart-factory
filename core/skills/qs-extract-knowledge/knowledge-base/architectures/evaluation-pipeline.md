---
name: evaluation-pipeline
description: LLM-as-judge evaluation frameworks from DeepEval GEval with DB snapshots to NAT eval harness with benchmark scoring
summary: "Provides two LLM-as-judge evaluation frameworks for validating AI application outputs end-to-end against golden answers. Approach A (DeepEval GEval + DB Snapshots) wraps the app's vLLM endpoint as a VLLMJudge via LangChain ChatOpenAI with custom rubrics (0-10 normalized to 0-1, threshold 0.5) and compares alert SQL via first-row string match with PostgreSQL snapshot/restore isolation -- use when evaluating a running REST application with database-dependent state and dataset JSON files scoped by app_config_id; Approach B (NAT Eval Harness) registers evaluators via @register_evaluator with YAML config, invokes workflow functions directly (no REST), and produces structured JSON grading with per-answer correctness, precision/recall/F1, Wilson-score CIs, and leaderboard output -- use when evaluating NAT agent workflows against academic benchmarks (DeepSearchQA, FreshQA, DeepResearch Bench). Critical config: Approach A requires VLLMJudge wrapping DeepEvalBaseLLM with ChatOpenAI pointed at OPENAI_API_ENDPOINT and GEval correctness metric with explicit Rubric score ranges; Approach B requires DeepSearchQAEvaluatorConfig with llm_name for the judge and max_concurrency via asyncio.Semaphore. Both approaches risk inflated scores from shared app/judge model bias; A requires a pre-started backend and loses concurrent DB writes on snapshot restore; B's exponential retry backoff (5 retries, 1+2^i seconds) causes hours-long runs on rate-limited endpoints; alert eval (A) only handles single-value aggregate SQL queries."
metadata:
  type: architecture
tags:
  tech_stack: [python, deepeval, langchain, flask, postgresql, nemo-agent-toolkit, nvidia-nim]
  ai_pattern: [evaluation, agents, deep-research]
  platform: [vllm, rhoai, openshift, nvidia-api]
  data_layer: [postgresql, chromadb]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Dual-mode eval framework: LLM-as-judge GEval for chat quality (correctness scoring with rubrics) and SQL result comparison for alert accuracy, with database snapshot/restore isolation"
    approach: "A"
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "NAT eval harness with multiple benchmark evaluators (DeepSearchQA, FreshQA, DeepResearch Bench) using LLM-as-judge with structured correctness grading, confidence intervals, precision/recall/F1, and leaderboard output"
    approach: "B"
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

---

## Approach B: NAT Eval Harness with LLM-as-Judge Benchmark Scoring (from rh-research)

### When to Use

When evaluating an agent-based research system end-to-end using established academic benchmarks (DeepSearchQA, FreshQA) with LLM-as-judge grading, and when the evaluation framework is integrated into the same NAT (NeMo Agent Toolkit) infrastructure as the application itself. Use this approach when you need precision/recall/F1 scoring with confidence intervals, per-category breakdown, and leaderboard-compatible output formats.

### Differences from Approach A

Approach A evaluates a running application's REST endpoints with database snapshot isolation and uses DeepEval GEval with custom rubrics. Approach B evaluates an agent workflow inline via the NAT eval harness (`nat eval` CLI), using custom evaluator classes that extend `BaseEvaluator` registered via `@register_evaluator`. There is no database snapshot mechanism -- the eval runs the workflow function directly and compares output against golden answers. The judge uses a custom prompt template (not DeepEval) that produces structured JSON with per-answer correctness details, excessive answer detection, and item-level precision/recall/F1. Multiple benchmark configs can be composed (DeepSearchQA for factual QA, FreshQA for temporal freshness, DeepResearch Bench for report quality).

### Data Flow

1. `nat eval --config_file configs/config_deepsearch_qa.yml` loads the workflow and evaluator from YAML
2. NAT framework invokes the configured workflow function (e.g., `deep_research_workflow`) for each dataset item
3. The workflow processes the query through the full agent pipeline (intent classification, research, synthesis)
4. The evaluator receives `EvalInput` with input/expected/actual output triplets
5. For each item, the evaluator builds a grader prompt from the `DEEPSEARCH_QA_PROMPT` template with the question, correct answer, answer type, and agent response
6. A separate judge LLM evaluates the response and returns structured JSON with `Answer Correctness` containing `Explanation`, `Correctness Details` (per-answer booleans), and `Excessive Answers`
7. Item-level ratings are aggregated into `ProjectRating` with precision, recall, F1, confidence intervals, and category breakdown
8. Results are output as `DeepSearchQAEvalOutput` with leaderboard-compatible format

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| NAT eval CLI | Workflow function | Python method call | Execute agent on each dataset item |
| NAT eval CLI | Evaluator function | Python method call | Score agent outputs against golden answers |
| DeepSearchQAEvaluator | Judge LLM (NVIDIA NIM) | REST (OpenAI-compatible) | LLM-as-judge grading of each response |
| Evaluator | JSONL dataset files | File I/O | Load questions, expected answers, answer types |

### Key Integration Points

#### NAT Evaluator Registration

Evaluators are registered as NAT evaluator functions with `@register_evaluator`, binding a Pydantic config class to an evaluator implementation. The config specifies the judge LLM and concurrency settings.

```python
# frontends/benchmarks/deepsearch_qa/src/register.py (lines 488-493, 720-733)
class DeepSearchQAEvaluatorConfig(EvaluatorBaseConfig, name="deepsearchqa_evaluator"):
    llm_name: LLMRef = Field(description="LLM to use as judge for quality evaluation")
    max_retries: int = Field(default=5, description="Maximum retries for LLM calls")

@register_evaluator(config_type=DeepSearchQAEvaluatorConfig)
async def register_deepsearchqa_evaluator(config: DeepSearchQAEvaluatorConfig, builder: EvalBuilder):
    llm = await builder.get_llm(config.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    evaluator = DeepSearchQAEvaluator(llm=llm, max_concurrency=builder.get_max_concurrency())
    yield EvaluatorInfo(config=config, evaluate_fn=evaluator.evaluate,
                        description="DeepSearchQA Evaluator (Official DeepMind Methodology)")
```

#### Structured Correctness Grading with Per-Answer Breakdown

The judge prompt requests structured JSON output with per-answer correctness booleans and excessive answer detection. The evaluator parses this into `ItemRating` dataclasses and computes item-level precision/recall/F1 from true positives (correct expected answers), false positives (excessive answers), and false negatives (missed expected answers).

```python
# frontends/benchmarks/deepsearch_qa/src/register.py (lines 633-648)
if item_rating.grader_ratings_list:
    num_correct = sum(1 for r in item_rating.grader_ratings_list if r)
    total = len(item_rating.grader_ratings_list)
    has_excessive = bool(item_rating.response_wrong_answers_list)

    if num_correct == total and not has_excessive:
        score = 100.0  # Fully correct
    elif num_correct == total and has_excessive:
        score = 75.0   # Correct but with excessive answers
    elif num_correct > 0:
        score = (num_correct / total) * 50.0  # Partially correct
    else:
        score = 0.0    # Fully incorrect
```

#### Confidence Intervals and Leaderboard Output

Aggregate statistics include Wilson-score-style confidence intervals (z=1.96) for correctness percentages, precision/recall/F1 averages via numpy, per-category breakdown, and a `LeaderboardEntry` data class with table formatting for comparison against published benchmarks.

```python
# frontends/benchmarks/deepsearch_qa/src/register.py (lines 311-328)
def _calculate_ci_str(count: int, total: int, z: float = 1.96) -> str:
    if total == 0:
        return f"N/A ({count}/{total})"
    p = count / total
    p_percent = p * 100.0
    variance = p * (1.0 - p)
    margin_of_error = z * math.sqrt(variance / total)
    moe_percent = margin_of_error * 100.0
    result_str = f"{round(p_percent, 2):.2f} +/- {round(moe_percent, 2):.2f} ({count}/{total})"
    if total <= 5:
        result_str += " (CI not robust for n<=5)"
    return result_str
```

### Gotchas

- The judge LLM is typically the same model used by the application (e.g., `nemotron_super_llm` in the eval config). This shared bias risk is the same as Approach A but is more explicit here because the config file wires both the workflow and evaluator LLMs.
- LLM judge calls include exponential backoff retry logic (`1 + 2^(i + random())` seconds) with up to 5 retries per item. Long eval runs over large datasets can take hours due to serial retries on rate-limited endpoints.
- The `_parse_json_response` function handles markdown code blocks (`\`\`\`json ... \`\`\``) from the judge response, but other wrapping formats may cause `invalid_auto_rater_response` failures that are silently excluded from aggregate scoring.
- The CI calculation warns when `n<=5` but still computes a value -- results from very small datasets should not be compared against published benchmarks.
- Multiple evaluator configs exist for different benchmarks (deepsearch_qa, freshqa, deepresearch_bench) but they share the same `nat eval` invocation pattern. Each requires its own dataset format and config YAML.
- The `max_concurrency` semaphore limits concurrent judge LLM calls (via `asyncio.gather` + `asyncio.Semaphore`), but the workflow execution runs sequentially per item inside NAT's eval loop.

### Related Architectures

- [agent-orchestration](agent-orchestration.md) -- The agent workflows being evaluated (Approach H: NAT+DeepAgents multi-tier research)

---

## Choosing Between Approaches

| Criteria | Approach A (DeepEval GEval + DB Snapshots) | Approach B (NAT Eval Harness + Benchmark Scoring) |
|----------|--------------------------------------------|----------------------------------------------------|
| Use case | Evaluating a running REST application with database-dependent state | Evaluating an agent workflow inline via the NAT framework |
| Judge framework | DeepEval GEval with custom rubrics | Custom evaluator extending NAT BaseEvaluator with structured JSON grading |
| Application integration | Evaluates running REST endpoints; requires separate application startup | Evaluates workflow function directly; NAT loads both workflow and evaluator from config |
| State isolation | Database snapshot/restore for reproducible evaluation state | No database isolation; evaluates against live or default knowledge state |
| Scoring metrics | GEval 0-10 correctness score normalized to 0-1 with threshold 0.5 | Per-answer correctness booleans, precision/recall/F1, confidence intervals, leaderboard output |
| Multi-benchmark support | Single eval script for two modes (chat + alert) | Multiple evaluator configs for different benchmarks (DeepSearchQA, FreshQA, DeepResearch Bench) |
| CI integration | Exit code 1 on failure for pipeline gating | NAT eval outputs structured results; CI integration via GitHub Actions workflow |
| Concurrency | asyncio.gather for concurrent test case submission | asyncio.Semaphore-limited concurrent judge calls; sequential workflow execution |
