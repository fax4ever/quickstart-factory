---
name: benchmarks
description: "NAT evaluation plugin benchmarks for deep research agents with LLM-as-judge scoring and profiling"
summary: "Provides three pip-installable NAT evaluation plugin benchmarks for scoring deep research agents via LLM-as-judge: FreshQA (factual accuracy using FreshEval Relaxed with 15 few-shot demos, multi-dimensional breakdown by fact type/premise/complexity/time), DeepSearchQA (precision/recall/F1 with confidence intervals, structured JSON judge output parsed from markdown code blocks), and DeepResearch Bench (research report quality scored by external evaluator after JSONL export via export_drb_jsonl.py). Use FreshQA or DeepSearchQA for automated GPT-4o judge scoring through `nat eval --config_file`; use DRB when evaluating full research reports, noting it requires external submission and offers optional profiling with token uniqueness/runtime forecasting, bottleneck analysis, concurrency spike detection, and prediction trie. Each benchmark registers via `@register_evaluator(config_type=...)` decorator and setuptools `nat.plugins` entry point, with YAML configs wiring agent workflows, datasets, and four API keys (NVIDIA_API_KEY for agent, OPENAI_API_KEY for judge, TAVILY_API_KEY for web search, SERPER_API_KEY for DRB paper search). Datasets must be downloaded separately before running (FreshQA from FreshLLMs GitHub, DeepSearchQA from Kaggle CSV, DRB via download_drb_dataset.py), config_tokenomics_pricing.yml must be passed to `python -m aiq_agent.tokenomics.report` separately since NAT's config schema rejects unknown keys, and W&B Weave tracing is configured in some benchmark configs but Phoenix tracing is commented out."
metadata:
  type: component
tags:
  tech_stack: [python, pydantic, pandas, numpy, langchain, openai, setuptools]
  ai_pattern: [evaluation, agents, rag]
  platform: [nvidia-nat, vllm]
  data_layer: []
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "Three NAT eval plugin benchmarks (FreshQA, DeepSearchQA, DeepResearch Bench) for evaluating deep research agents"
    approach: "A"
---

# Benchmarks

## Overview

A suite of evaluation harnesses for benchmarking deep research agents built on the NVIDIA NeMo Agent Toolkit (NAT). Each benchmark is a standalone pip-installable Python package that registers as a NAT plugin via the `nat.plugins` entry point, allowing it to be invoked through the `nat eval` CLI. The component includes three benchmark suites: FreshQA (factual accuracy), DeepSearchQA (question-answering precision/recall/F1), and DeepResearch Bench (research report quality). All three use an LLM-as-judge pattern for automated scoring.

## Tech Stack & Dependencies

- **Runtime:** Python >=3.11,<3.14
- **Container image:** N/A (runs within the agent's Python environment)
- **Key dependencies:** `nvidia-nat-eval==1.7.0`, `pydantic>=2.0.0`, `pytz>=2024.1` (FreshQA), `httpx>=0.24.0` (DeepSearchQA), `pandas` (dataset scripts)
- **Helm subchart:** N/A (evaluation runs locally via `nat eval` CLI)

## Key Patterns

### NAT Plugin Registration

Each benchmark is a separate Python package that registers itself as a NAT evaluator plugin via setuptools entry points. The evaluator class extends `BaseEvaluator` and is registered with the `@register_evaluator` decorator.

```toml
# frontends/benchmarks/freshqa/pyproject.toml
[project.entry-points."nat.plugins"]
freshqa_eval = "freshqa_eval.register"
```

```python
# frontends/benchmarks/freshqa/src/evaluator.py
@register_evaluator(config_type=FreshQAConfig)
async def register_freshqa_evaluator(config: FreshQAConfig, builder: EvalBuilder):
    llm = await builder.get_llm(config.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    evaluator = FreshQAEvaluator(
        llm=llm,
        max_concurrency=builder.get_max_concurrency(),
        max_retries=config.max_retries,
        dataset_file=config.dataset_file,
    )
    yield EvaluatorInfo(
        config=config,
        evaluate_fn=evaluator.evaluate,
        description="FreshQA Evaluator using FreshEval Relaxed methodology",
    )
```

### Config-Driven Evaluation

All benchmarks are driven by YAML config files that wire together LLMs, tools, workflow type, dataset path, and evaluator settings. The same config specifies both the agent workflow to run and the evaluator to score it.

```yaml
# frontends/benchmarks/deepsearch_qa/configs/config_deepsearch_qa.yml
eval:
  general:
    output_dir: frontends/benchmarks/deepsearch_qa/results
    max_concurrency: 3
    dataset:
      _type: csv
      file_path: frontends/benchmarks/deepsearch_qa/data/DSQA-full.csv
      structure:
        question_key: problem
        answer_key: answer
        generated_answer_key: generated_answer

  evaluators:
    deepsearchqa:
      _type: deepsearchqa_evaluator
      llm_name: judge_llm
      max_retries: 5
```

### LLM-as-Judge with Few-Shot Prompting (FreshQA)

The FreshQA evaluator implements the FreshEval Relaxed methodology with a carefully constructed few-shot prompt containing 15 demonstration examples that teach the judge nuanced evaluation criteria (false premise handling, name accuracy, numerical precision).

```python
# frontends/benchmarks/freshqa/src/evaluator.py
FRESHEVAL_PREFIX = (
    "Please evaluate the response to a question under relaxed evaluation, where"
    " hallucinations, outdated information, and ill-formed answers are allowed,"
    " as long as the primary answer is accurate. ..."
)

def build_fresheval_prompt(question: str, response: str, correct_answers: list[str]) -> str:
    demo_examples = get_demo_examples()
    # ... builds 15 few-shot demo examples + target question
    return FRESHEVAL_PREFIX + "\n\n\n" + fresheval_demo + fresheval_question
```

### LLM-as-Judge with Structured JSON Output (DeepSearchQA)

The DeepSearchQA evaluator expects the judge to return structured JSON with correctness details per answer component and excessive answer detection. It parses the JSON from markdown code blocks.

```python
# frontends/benchmarks/deepsearch_qa/src/register.py
def _parse_json_response(ori_json_response: str) -> Any:
    json_str = ori_json_response.strip()
    start_marker = "```json"
    start_idx = json_str.find(start_marker)
    if start_idx != -1:
        json_str = json_str[start_idx + len(start_marker):].strip()
        end_marker = "```"
        end_idx = json_str.rfind(end_marker)
        if end_idx != -1:
            json_str = json_str[:end_idx].strip()
    return json.loads(json_str)
```

### Multi-Dimensional Accuracy Breakdown (FreshQA)

The FreshQA evaluator computes accuracy across multiple dimensions: overall (all/test/dev splits), by fact type (fast-changing, slow-changing, never-changing), by premise type (valid vs false premise), by question complexity (one-hop vs multi-hop), and by time period (old vs new questions).

```python
# frontends/benchmarks/freshqa/src/evaluator.py
class FreshQAEvalOutput(EvalOutput):
    accuracy: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_fast_changing: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_slow_changing: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_never_changing: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_valid_premise: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_false_premise: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
```

### Scoring with Confidence Intervals (DeepSearchQA)

The DeepSearchQA evaluator produces leaderboard-compatible output with confidence intervals for fully-correct, fully-incorrect, and correct-with-excessive-answers rates, plus precision/recall/F1 aggregated across items.

```python
# frontends/benchmarks/deepsearch_qa/src/register.py
def _calculate_ci_str(count: int, total: int, z: float = 1.96) -> str:
    if total == 0:
        return f"N/A ({count}/{total})"
    p = count / total
    p_percent = p * 100.0
    variance = p * (1.0 - p)
    margin_of_error = z * math.sqrt(variance / total)
    moe_percent = margin_of_error * 100.0
    result_str = f"{round(p_percent, 2):.2f} +/- {round(moe_percent, 2):.2f} ({count}/{total})"
    return result_str
```

### External Dataset Download Scripts

Datasets are not bundled in the repo. The DeepResearch Bench provides a download script that fetches query and reference data from GitHub and joins them with pandas.

```python
# frontends/benchmarks/deepresearch_bench/scripts/download_drb_dataset.py
def download_dataset(data_dir: Path) -> None:
    queries = pd.read_json(QUERY_URL, lines=True)
    references = pd.read_json(REFERENCES_URL, lines=True)[["id", "article"]]
    dataset = (
        queries.merge(references, on="id", how="left")
        .assign(article=lambda df: df["article"].fillna(""), id=lambda df: df["id"].astype(str))
        .rename(columns={"prompt": "question", "article": "expected_output"})
    )
    dataset.to_json(dataset_path, orient="records", force_ascii=False, indent=2)
```

### Profiling and Tokenomics Configuration

The profiling config enables advanced analysis features including token uniqueness forecasting, runtime forecasting, bottleneck analysis, concurrency spike detection, and prediction trie for routing hints. A separate tokenomics config tracks per-model and per-tool costs.

```yaml
# frontends/benchmarks/deepresearch_bench/configs/config_deep_research_bench_profiling.yml
eval:
  general:
    profiler:
      token_uniqueness_forecast: true
      workflow_runtime_forecast: true
      compute_llm_metrics: true
      prompt_caching_prefixes:
        enable: true
        min_frequency: 0.1
      bottleneck_analysis:
        enable_nested_stack: true
      concurrency_spike_analysis:
        enable: true
        spike_threshold: 7
      prediction_trie:
        enable: true
        auto_sensitivity: true
```

## Configuration

- **Environment variables:**
  - `NVIDIA_API_KEY` -- agent execution via integrate.api.nvidia.com
  - `OPENAI_API_KEY` -- judge LLM (GPT-4o) for FreshQA and DeepSearchQA evaluators
  - `TAVILY_API_KEY` -- web search tool used by the agent during evaluation
  - `SERPER_API_KEY` -- paper search tool (DeepResearch Bench only)
- **Config files:**
  - `frontends/benchmarks/freshqa/configs/config_shallow_research_only.yml` -- FreshQA with shallow research agent only
  - `frontends/benchmarks/freshqa/configs/config_full_workflow.yml` -- FreshQA with intent classification and depth routing
  - `frontends/benchmarks/deepsearch_qa/configs/config_deepsearch_qa.yml` -- DeepSearchQA with Nemotron agent and OpenAI judge
  - `frontends/benchmarks/deepresearch_bench/configs/config_deep_research_bench.yml` -- DRB default config
  - `frontends/benchmarks/deepresearch_bench/configs/config_deep_research_bench_profiling.yml` -- DRB with profiling enabled
  - `frontends/benchmarks/deepresearch_bench/configs/config_tokenomics_pricing.yml` -- cost analysis config (not used by `nat eval` directly)
- **Helm values:** N/A (evaluation harness, not deployed as a service)

## Known Gotchas

- Datasets must be downloaded separately before running evaluations. FreshQA requires `FreshQA_v112425.json` from the FreshLLMs GitHub repo. DeepSearchQA requires `DSQA-full.csv` from Kaggle. DRB has a download script (`download_drb_dataset.py`) that builds `drb_full_dataset.json` from two upstream JSONL files.
- The FreshQA evaluator's `extract_ratings` function has a control flow where the `evaluation is None` check on line 408 is unreachable because `evaluation` is always assigned in the prior `if/else` block on lines 403-406. The function still works because the earlier assignment covers the cases.
- DRB does not include its own evaluator plugin -- it generates reports that must be submitted to the external DRB evaluator from the [deep_research_bench GitHub repo](https://github.com/Ayanami0730/deep_research_bench). An export script (`export_drb_jsonl.py`) converts `workflow_output.json` to the required JSONL submission format.
- The FreshQA CSV-to-JSON conversion runs at evaluation time inside the `register_freshqa_evaluator` function (not at plugin load), so it is safe but means the first run with a CSV file has a brief conversion delay.
- The `config_tokenomics_pricing.yml` file is not loaded by `nat eval` because NAT's top-level config schema rejects unknown keys. It must be passed to `python -m aiq_agent.tokenomics.report --config ...` separately.
- W&B Weave tracing is configured in some benchmark configs (DeepSearchQA, FreshQA shallow). Phoenix tracing is available but commented out in DRB configs.
- The profiling config uses a `dataset.filter.allowlist` to run a subset of 16 questions by ID, useful for quick profiling runs without evaluating the full dataset.

## Testing Notes

- Run any benchmark with: `dotenv -f deploy/.env run nat eval --config_file <path-to-config.yml>`
- Check `results/` subdirectory under each benchmark for output files (e.g., `workflow_output.json`)
- For DRB, convert output to JSONL with `export_drb_jsonl.py` and submit to the external evaluator
- Verify the judge LLM is accessible (OpenAI API key set) before running FreshQA or DeepSearchQA

## Related Patterns

- `evaluations.md` -- DeepEval-based evaluation for different quickstart patterns
- `agent-evaluation.md` -- MLflow GenAI evaluation framework for LangGraph agents
