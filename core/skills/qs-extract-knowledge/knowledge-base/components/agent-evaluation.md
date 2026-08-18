---
name: agent-evaluation
description: "MLflow GenAI agent evaluation framework with prompt registry, LLM-as-judge scorers, and KFP pipelines"
summary: "Evaluation framework for LangGraph agents on RHOAI using MLflow GenAI evaluate() with three execution modes -- Jupyter notebooks for exploratory evaluation and prompt regression detection via versioned Prompt Registry, CLI for CI integration, and KFP v2 four-step pipelines (setup-mlflow/create-dataset/evaluate/report) on DSPA -- plus TrustyAI EvalHub via Kustomize for standardized benchmarks (ARC-Easy, OpenLLM Leaderboard v2) using lm-evaluation-harness and garak providers. Use \"simple\" mode (deterministic @scorer checks like contains_expected/has_numeric_result, no LLM calls) for fast CI gates, \"llm-judge\" mode (adds ToolCallCorrectness, ToolCallEfficiency, RelevanceToQuery, Safety, and domain-specific Guidelines scorers against any OpenAI-compatible endpoint) for thorough evaluation, KFP pipelines for automated runs on DSPA with SA token auto-detection, and EvalHub for standardized model benchmarks with envsubst-templated configs. Critical pattern: async LangGraph ainvoke() bridged to sync predict_fn via dedicated threading.Thread with asyncio.run() (nest_asyncio alone insufficient), tool calls replayed as explicit TOOL spans for ToolCallCorrectness scoring since MLflow autolog does not capture across thread boundaries, test cases stored as MLflow persistent datasets via create_dataset()/merge_records(), and MLFLOW_TRACKING_AUTH=kubernetes with namespace auto-detected from SA mount at /var/run/secrets/kubernetes.io/serviceaccount/namespace. Gotchas: experiment name auto-appends \"-eval\" suffix (MLFLOW_EXPERIMENT_NAME=mortgage-ai becomes mortgage-ai-eval), both OPENAI_API_BASE and OPENAI_BASE_URL must be set for judge model routing, EvalHub UI \"API key\" field expects a K8s secret name not a raw key (RHOAIENG-68008), Kustomize RBAC files fix a TrustyAI operator gap where runtime SAs (evalhub-service, evalhub-*-job) lack ClusterRole bindings, and DSPA secret-patcher converts MinIO keys to AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY format."
metadata:
  type: component
tags:
  tech_stack: [python, mlflow, langchain, langgraph, openai, kfp, jupyter, pydantic, pydantic-settings, nest-asyncio]
  ai_pattern: [evaluation, agents, prompt-chaining]
  platform: [rhoai, openshift, kserve, trustyai]
  data_layer: []
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "MLflow GenAI evaluation with prompt registry, custom and built-in LLM-judge scorers, Kubeflow Pipelines, and TrustyAI EvalHub for model benchmarking"
    approach: "A"
---

# Agent Evaluation

## Overview

An agent evaluation framework built on MLflow GenAI's `evaluate()` API for testing LangGraph-based agents on RHOAI. The component provides three execution modes: interactive Jupyter notebooks for exploratory evaluation, a CLI script for CI integration, and Kubeflow Pipelines for automated evaluation on OpenShift AI Data Science Pipelines. It also includes TrustyAI EvalHub deployment manifests for running standardized model benchmarks (ARC-Easy, OpenLLM Leaderboard v2).

## Tech Stack & Dependencies

- **Runtime:** Python 3.11+
- **Container image:** `python:3.11-slim` (for KFP pipeline steps)
- **Key dependencies:** mlflow>=3.11, langchain>=0.3.0, langchain-core>=0.3.0, langchain-openai>=0.2.0, langgraph>=0.2.0, openai>=1.12.0, kfp (for pipeline definitions), nest_asyncio, pydantic>=2.5.0, pydantic-settings>=2.1.0, sentence-transformers>=3.0.0
- **Helm subchart:** N/A (EvalHub deployed via Kustomize, DSPA via CR)

## Key Patterns

### MLflow Prompt Registry for Versioned Evaluation

System prompts are registered in MLflow's Prompt Registry as versioned artifacts. During evaluation, loading a prompt inside a traced context automatically links each evaluation trace to the prompt version that produced it, enabling side-by-side comparison of prompt changes.

```python
# Register prompt as versioned artifact
registered_prompt = mlflow.genai.register_prompt(
    name="public-assistant-system-prompt",
    template=system_prompt_text,
    commit_message="Public assistant system prompt from config/agents/public-assistant.yaml",
    tags={"agent": "public-assistant", "type": "system-prompt"},
)
prompt_uri = f"prompts:/{prompt_name}/{registered_prompt.version}"

# Inside predict_fn, load prompt for trace linkage
@mlflow.trace
def predict_fn_with_prompt(user_message: str) -> str:
    mlflow.genai.load_prompt(prompt_uri)
    # ... invoke agent ...
```

### Async Agent Predictor Wrapping

LangGraph agents use async `ainvoke()`, but MLflow's `evaluate()` requires a synchronous `predict_fn`. The predictor bridges this by running the async agent in a dedicated thread with `asyncio.run()`, then replaying tool calls as MLflow TOOL spans so built-in scorers like `ToolCallCorrectness` can assess them.

```python
# predictors.py -- sync wrapper for async agent
def create_predict_fn(agent_name: str = "public-assistant") -> Callable[[str], str]:
    def predict_fn(user_message: str) -> str:
        async def _invoke() -> str:
            graph = get_agent(agent_name, checkpointer=None)
            initial_state = {
                "messages": [HumanMessage(content=user_message)],
                "user_role": "prospect",
                "user_id": "eval-user-001",
                # ... other state fields ...
            }
            result = await graph.ainvoke(initial_state)
            return str(result["messages"][-1].content)

        with mlflow.start_span(name=f"{agent_name}-eval") as span:
            span.set_inputs({"user_message": user_message})
            result = asyncio.run(_invoke())
            span.set_outputs({"response": result})
            return result
    return predict_fn
```

### Tool Call Replay as MLflow Spans

After agent invocation, tool calls from the agent's message history are replayed as explicit TOOL-type spans so MLflow's `ToolCallCorrectness` scorer can evaluate them. This is needed because the agent runs in a separate thread, and MLflow's autolog does not capture tool calls across thread boundaries.

```python
# Replay tool calls as trace spans
if result_box.get("messages"):
    tool_outputs = {}
    for msg in result_box["messages"]:
        if hasattr(msg, "tool_call_id") and hasattr(msg, "content"):
            tool_outputs[msg.tool_call_id] = msg.content
    for msg in result_box["messages"]:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                with mlflow.start_span(name=tc["name"], span_type="TOOL") as span:
                    span.set_inputs(tc.get("args", {}))
                    tc_id = tc.get("id", "")
                    if tc_id in tool_outputs:
                        span.set_outputs({"result": tool_outputs[tc_id]})
```

### Custom Deterministic Scorers with @scorer Decorator

Lightweight, no-LLM-call scorers using MLflow's `@scorer` decorator for fast evaluation passes. These complement the built-in LLM judges and can run independently in "simple" mode.

```python
# scorers/custom_scorers.py
from mlflow.genai.scorers import scorer

@scorer
def contains_expected(inputs: dict, outputs: str, expectations: dict) -> bool:
    """Check if output contains expected answer keyword."""
    expected = expectations.get("expected_answer", "")
    if not expected:
        return True
    return str(expected).lower() in str(outputs).lower()

@scorer
def has_numeric_result(outputs: str) -> bool:
    """Check if response contains numeric values."""
    patterns = [r"\$[\d,]+", r"\d+%", r"\d{1,3}(,\d{3})+"]
    for pattern in patterns:
        if re.search(pattern, str(outputs)):
            return True
    return False
```

### Two-Mode Evaluation (Simple vs LLM-as-Judge)

The CLI and notebooks support two modes: "simple" (deterministic only, no LLM calls) for fast CI gates, and "llm-judge" (adds MLflow built-in LLM scorers) for thorough evaluation. The judge model is configured via environment variables pointing to any OpenAI-compatible endpoint.

```python
# run_agent_eval.py -- built-in LLM judges
from mlflow.genai.scorers import (
    Guidelines, RelevanceToQuery, Safety,
    ToolCallCorrectness, ToolCallEfficiency,
)

judge_model = f"openai:/{model}"  # e.g. "openai:/gpt-oss-120b"
llm_scorers = [
    ToolCallCorrectness(model=judge_model, should_exact_match=True),
    ToolCallEfficiency(model=judge_model),
    RelevanceToQuery(model=judge_model),
    Safety(model=judge_model),
    Guidelines(
        name="public_assistant_guidelines",
        guidelines=["Response should be helpful about mortgage products",
                     "Response should NOT promise specific rates or pre-approval"],
        model=judge_model,
    ),
]
```

### MLflow Persistent Datasets

Test cases are stored as persistent datasets on the MLflow server using `create_dataset()` and `merge_records()`. Each test case has `inputs` (user message) and `expectations` (expected answer keyword, expected tool calls, expected topics, forbidden content).

```python
# Dataset format for agent evaluation
from mlflow.genai.datasets import create_dataset

test_cases = [
    {
        "inputs": {"user_message": "What loan products do you offer?"},
        "expectations": {
            "expected_answer": "30-year",
            "expected_tool_calls": [{"name": "product_info"}],
            "expected_topics": ["fixed", "FHA", "VA"],
            "forbidden_content": [],
        },
    },
]

dataset = create_dataset(
    name="public_assistant_eval",
    tags={"stage": "validation", "version": "1", "agent": "public-assistant"},
)
dataset = dataset.merge_records(test_cases)
```

### Prompt Regression Detection Workflow

A dedicated notebook (`evaluate_agent_v2.ipynb`) demonstrates detecting quality regressions caused by prompt changes. A modified prompt (TOOL USE MANDATORY changed to OPTIONAL) is registered as a new version, evaluated against the same dataset, and metrics are compared to the baseline. This pattern enables continuous prompt quality monitoring.

```python
# Compare V1 vs V2 metrics
v1_baseline = {"contains_expected/mean": 1.0, "has_numeric_result/mean": 0.5}
for metric, v1_val in v1_baseline.items():
    v2_val = v2_simple_results.metrics.get(metric, 0)
    delta = v2_val - v1_val
    indicator = "REGRESSION" if delta < 0 else "OK"
```

### Kubeflow Pipelines for Automated Evaluation

Evaluation pipelines are defined as KFP v2 components with four modular steps: setup MLflow, create dataset, run evaluation (simple or LLM-judge), and report results. Each step is a self-contained `@component` with its own package dependencies and auto-detects Kubernetes SA tokens for MLflow auth.

```python
# kfp_eval_pipeline.py -- pipeline definition
@dsl.pipeline(name="Agent LLM-Judge Evaluation Pipeline")
def llm_judge_eval_pipeline(
    mlflow_tracking_uri: str,
    llm_base_url: str,
    mlflow_workspace: str = "",
    llm_model: str = "qwen3-14b",
):
    setup_task = setup_mlflow_op(mlflow_tracking_uri=mlflow_tracking_uri, ...)
    dataset_task = create_dataset_op(experiment_name=setup_task.output, ...)
    eval_task = run_llm_judge_eval_op(
        dataset_id=dataset_task.outputs["dataset_id"],
        llm_base_url=llm_base_url, llm_model=llm_model, ...)
    kubernetes.use_secret_as_env(
        eval_task, secret_name="llm-credentials",
        secret_key_to_env={"OPENAI_API_KEY": "OPENAI_API_KEY"})
    report_results_op(metrics=eval_task.output, ...)
```

### TrustyAI EvalHub Deployment via Kustomize

The `evalhub/` directory contains seven Kustomize resources that deploy TrustyAI EvalHub, DSPA (Data Science Pipelines Application), and the RBAC bindings needed to connect them to MLflow. The EvalHub CR configures evaluation providers (garak, lm-evaluation-harness) and benchmark collections.

```yaml
# 01-evalhub-cr.yaml
apiVersion: trustyai.opendatahub.io/v1alpha1
kind: EvalHub
metadata:
  name: evalhub
  namespace: redhat-ods-applications
spec:
  database:
    type: sqlite
  env:
    - name: MLFLOW_TRACKING_URI
      value: https://mlflow.redhat-ods-applications.svc.cluster.local:8443
  providers:
    - garak
    - garak-kfp
    - lm-evaluation-harness
```

### EvalHub Benchmark Configs with envsubst

Evaluation configs use `${VAR}` placeholders so the same YAML can target different models without editing files. Variables are substituted via `envsubst` at runtime.

```yaml
# eval-leaderboard-v2.yaml
name: "openllm-leaderboard-v2"
model:
  url: "${MODEL_URL}"
  name: "${MODEL_NAME}"
  auth:
    secret_ref: "${MODEL_AUTH_SECRET}"
benchmarks:
  - id: leaderboard_ifeval
    provider_id: lm_evaluation_harness
    parameters:
      tokenizer: "${MODEL_TOKENIZER}"
```

### RHOAI MLflow Workspace Auto-Detection

Notebooks auto-detect the OpenShift namespace from the pod's service account mount to set `MLFLOW_WORKSPACE`, and use `MLFLOW_TRACKING_AUTH=kubernetes` for authentication instead of explicit tokens.

```python
# Auto-detect namespace for MLFLOW_WORKSPACE
if not os.environ.get("MLFLOW_WORKSPACE"):
    for ns_path in [
        Path("/run/secrets/kubernetes.io/serviceaccount/namespace"),
        Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace"),
    ]:
        if ns_path.is_file():
            os.environ["MLFLOW_WORKSPACE"] = ns_path.read_text().strip()
            break
```

## Configuration

- **Environment variables:**
  - `LLM_BASE_URL` -- OpenAI-compatible LLM endpoint for both agent and judge model
  - `LLM_API_KEY` -- API key for the LLM endpoint
  - `LLM_MODEL` -- Model name (e.g., `gpt-oss-120b`)
  - `MLFLOW_TRACKING_URI` -- MLflow server URL (no `/mlflow` suffix)
  - `MLFLOW_EXPERIMENT_NAME` -- Experiment name (auto-appends `-eval`)
  - `MLFLOW_TRACKING_AUTH` -- Set to `kubernetes` for RHOAI MLflow auth
  - `MLFLOW_TRACKING_INSECURE_TLS` -- Set to `true` for in-cluster TLS
  - `MLFLOW_WORKSPACE` -- Maps to K8s namespace; auto-detected from service account
  - `MLFLOW_TRACKING_TOKEN` -- Authentication token (via `oc whoami --show-token`)
  - `EVAL_JUDGE_MODEL` -- Optional override for judge model in MLflow format
  - `COMPANY_NAME` -- Company name injected into system prompts (default: "Fed Aura Capital")
- **Config files:** `evaluations/datasets/public_assistant_simple.py` (test case definitions)
- **Helm values:** N/A (EvalHub and DSPA deployed via Kustomize CRs in `evaluations/evalhub/`)

## Known Gotchas

- The experiment name auto-appends `-eval` suffix if not already present (in `run_agent_eval.py` line 134: `if not experiment_name.endswith("-eval"): experiment_name = f"{experiment_name}-eval"`). This means `MLFLOW_EXPERIMENT_NAME=mortgage-ai` creates an experiment named `mortgage-ai-eval`.
- KFP pipeline steps auto-detect the Kubernetes service account token from `/var/run/secrets/kubernetes.io/serviceaccount/token` for MLflow auth, so no explicit `MLFLOW_TRACKING_TOKEN` needs to be injected as a secret when running on DSPA (found in `kfp_eval_pipeline.py` `setup_mlflow_op`).
- The RBAC files in `evalhub/` (03, 04, 06) fix a gap in the TrustyAI operator: it creates ClusterRoles but only binds its own controller-manager service account, not the runtime service accounts (`evalhub-service`, `evalhub-redhat-ods-applications-job`) that actually need the permissions (documented in `evalhub.md`).
- The `predict_fn` in notebooks uses a dedicated `threading.Thread` with `asyncio.run()` inside it because LangGraph's `ainvoke()` is async, but MLflow's `evaluate()` calls `predict_fn` synchronously, and `nest_asyncio` alone is not sufficient in all environments (found in `evaluate_agent.ipynb` cell-18).
- The EvalHub UI "API key" field expects a Kubernetes secret name, not a raw key -- you must create the secret first with `oc create secret generic model-api-key --from-literal=api-key="<key>"` (documented in `evalhub.md`, references RHOAIENG-68008).
- The DSPA `05-secret-patcher.yaml` runs a job to patch the `ds-pipeline-s3-dspa` secret with AWS-style keys because downstream consumers expect `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` rather than MinIO's native key names.
- MLflow's `OPENAI_API_BASE` and `OPENAI_BASE_URL` must both be set for judge model calls to route correctly -- the code sets both in `configure_judge_model()` (found in `run_agent_eval.py` lines 103-104).

## Testing Notes

- Run simple (no LLM) evaluation: `MLFLOW_TRACKING_TOKEN=$(oc whoami --show-token) uv run python -m evaluations.run_agent_eval --mode simple`
- Run LLM-as-judge evaluation: `MLFLOW_TRACKING_TOKEN=$(oc whoami --show-token) uv run python -m evaluations.run_agent_eval --mode llm-judge`
- Save dataset to MLflow server: add `--save-dataset` flag
- Compile KFP pipelines to YAML: `uv run python evaluations/kfp_eval_pipeline.py --compile`
- Deploy EvalHub stack: `oc apply -k evaluations/evalhub/`
- Run EvalHub benchmarks: `envsubst < evaluations/eval-arceasy.yaml | evalhub eval run --config -`
- Use interactive notebooks (`evaluate_agent.ipynb`, `evaluate_agent_v2.ipynb`) in RHOAI workbenches for exploratory evaluation and prompt regression detection
- View results: navigate to MLflow UI, go to Experiments > your-experiment-eval, enable "All Assessments" in Columns dropdown

## Related Patterns

- `evaluations` -- DeepEval-based evaluation framework (different tech stack, complementary approach)
- `fastapi-backend` -- the LangGraph agent backend being evaluated
- `keycloak` -- identity provider bypassed during evaluation (`user_role: "prospect"` hardcoded in predictor state)
