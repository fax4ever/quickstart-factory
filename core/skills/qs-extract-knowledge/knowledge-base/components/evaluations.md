---
name: evaluations
description: "DeepEval-based conversation evaluation framework for AI agent testing with LLM-as-judge metrics"
summary: "DeepEval-based conversation evaluation framework for AI agents that orchestrates a three-step subprocess pipeline — run predefined conversation flows, generate conversations via ConversationSimulator (with live agent model callback through OpenShift oc exec) or export from API (--conversation-source generate|export), then evaluate with ConversationalGEval LLM-as-judge metrics — using a flow registry that auto-discovers pluggable flows/ subdirectories each containing flow.py (scenarios, chatbot role) and metrics.py (per-flow evaluation criteria). Use when validating deployed AI agents end-to-end on OpenShift with both LLM-judged quality metrics (via RetryableConversationalGEval that auto-retries below-threshold scores addressing judge non-determinism) and deterministic metadata evaluation for state machine transitions without LLM; supports negative testing via --check flag verifying known-bad conversations all fail as expected. Configure with LLM_API_TOKEN/LLM_URL/NAMESPACE env vars; CustomLLM adapter wraps any OpenAI-compatible endpoint as judge with optional instructor structured output (--use-structured-output); OpenShift chat client parses :DONE terminators and TOKEN_SUMMARY: lines from oc exec subprocess for conversation recording and app token tracking. DeepEval's wrap_up_test_run is monkey-patched to no-op preventing online login prompts, GPT-OSS-120b requires workaround for malformed JSON wrapping output in {\"final\": ...}, DeepEval ConversationalTestCase.context type hint says Optional[str] but runtime expects List[str], and --concurrency N cannot exceed the count of authoritative_user_ids since workers get disjoint user partitions."
metadata:
  type: component
tags:
  tech_stack: [python, deepeval, openai, instructor, pydantic]
  ai_pattern: [evaluation, agents, guardrails]
  platform: [openshift]
  data_layer: []
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Full conversation evaluation pipeline with flow registry, LLM-as-judge metrics, conversation generation, and known-bad validation"
    approach: "A"
---

# Evaluations

## Overview

A standalone evaluation framework for testing AI agent conversations using DeepEval's LLM-as-judge pattern. The component runs a multi-step pipeline: generate (or export) conversations with a live deployed agent via OpenShift exec, then evaluate them against configurable ConversationalGEval metrics. It supports pluggable evaluation flows with per-flow metrics, scenarios, and conversation metadata validation.

## Tech Stack & Dependencies

- **Runtime:** Python >=3.12,<3.14
- **Container image:** N/A (runs locally against a deployed agent, not containerized itself)
- **Key dependencies:** deepeval>=3.3.9, openai>=1.99.0, instructor>=1.7.0, pydantic
- **Build system:** hatchling with uv for workspace dependencies
- **Helm subchart:** N/A

## Key Patterns

### Pipeline Orchestrator

The `evaluate.py` script chains three steps in sequence: (1) run predefined conversation flows, (2) generate or export conversations, (3) run DeepEval metrics. Each step is a subprocess call with timeout and error handling.

```python
# evaluate.py -- pipeline steps
def run_evaluation_pipeline(...) -> int:
    _cleanup_generated_files(flow_name=flow)
    # Step 1: run predefined conversation flows (only when generating)
    if conversation_source == "generate":
        run_script("run_conversations.py", args=run_conversations_args, timeout=timeout)
    # Step 2: generate or export
    if conversation_source == "generate":
        run_script("generator.py", args=generator_args, timeout=timeout)
    else:
        run_script("export_conversations_from_api.py", args=export_args, timeout=120)
    # Step 3: deepeval evaluation
    run_script("deep_eval.py", args=deep_eval_args, timeout=timeout)
```

### Flow Registry

A plugin system that discovers evaluation flows from `flows/` subdirectories. Each flow has its own `flow.py` (scenario config, chatbot role, defaults) and `metrics.py` (flow-specific evaluation metrics). The registry auto-discovers flows by scanning for directories containing `flow.py`.

```python
# flow_registry.py
FLOWS_DIR = Path(__file__).parent / "flows"

def list_flows() -> List[str]:
    return sorted(
        [d.name for d in FLOWS_DIR.iterdir() if d.is_dir() and (d / "flow.py").exists()]
    )

@dataclass
class FlowPaths:
    name: str
    conversations_dir: Path
    known_bad_dir: Path
    context_dir: Path
    results_conv_dir: Path
    results_eval_dir: Path
    results_known_bad_dir: Path
```

### Custom LLM Adapter for DeepEval

Wraps any OpenAI-compatible endpoint (including RHOAI-served models) for use as the DeepEval evaluation judge. Supports both standard JSON mode and instructor-based structured output with automatic retries.

```python
# helpers/custom_llm.py
class CustomLLM(DeepEvalBaseLLM):
    def __init__(self, api_key, base_url, model_name=None, use_structured_output=False):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def generate(self, prompt, schema=None):
        if self.use_structured_output and schema is not None:
            instructor_client = instructor.from_openai(client)
            resp, completion = instructor_client.chat.completions.create_with_completion(
                model=self.model_name, messages=[...], response_model=schema, max_retries=3,
            )
            return resp
```

### OpenShift Chat Client for Live Agent Testing

Connects to the deployed agent inside an OpenShift pod via `oc exec`, piping stdin/stdout for interactive conversation. Parses custom protocol markers (`agent:` prefix, `:DONE` terminator, `TOKEN_SUMMARY:` lines) from the subprocess output.

```python
# helpers/openshift_chat_client.py
class OpenShiftChatClient:
    def start_session(self):
        cmd = ["oc", "exec", "-it", "deploy/self-service-agent-request-manager",
               "--", "bash", "-c", f"{env_vars} {script_cmd}"]
        self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, ...)

    def _read_full_agent_message(self, timeout=None):
        # Reads until AGENT_MESSAGE_TERMINATOR (":DONE") is found
        # Parses TOKEN_SUMMARY lines for app token tracking
```

### RetryableConversationalGEval

A wrapper around DeepEval's ConversationalGEval that automatically retries a metric evaluation once when it scores below threshold. This addresses LLM-as-judge non-determinism where the evaluator model may produce inconsistent results on the same conversation.

```python
# get_deepeval_metrics.py
class RetryableConversationalGEval(ConversationalGEval):
    async def a_measure(self, test_case, *args, **kwargs):
        self.retry_performed = False
        await super().a_measure(test_case, *args, **kwargs)
        if self.score is not None and self.score < self.threshold:
            first_score = self.score
            self.score = None; self.reason = None; self.success = None
            await super().a_measure(test_case, *args, **kwargs)
            self.retry_performed = True
            if self.reason:
                self.reason = f"[RETRY: 1st={first_score:.2f}] {self.reason}"
        return self.score if self.score is not None else 0.0
```

### Conversation Generation with DeepEval Simulator

Uses DeepEval's `ConversationSimulator` with a custom model callback that sends each simulated user message to the real deployed agent. Supports concurrent generation with multiprocessing, partitioning user IDs across workers so each worker uses a disjoint set.

```python
# generator.py
simulator = ConversationSimulator(
    model_callback=worker_model_callback,
    simulator_model=custom_llm,
)
conversational_test_cases = simulator.simulate(
    conversational_goldens=[conversation_golden],
    max_user_simulations=max_turns,
)
```

### Known-Bad Conversation Validation

A negative-testing pattern: the framework ships a set of conversations that should fail evaluation (missing ticket numbers, wrong laptop options, etc.). The `--check` flag runs DeepEval on these and verifies that all metrics fail as expected, validating that the metrics themselves catch real problems.

```python
# evaluate.py -- check mode
def run_check_known_bad_conversations(...) -> int:
    # Run deepeval on known bad conversations
    run_script("deep_eval.py", args=[
        "--results-dir", str(known_bad_dir),
        "--output-dir", str(deep_eval_results_dir),
    ], ...)
    # Verify all known bad conversations have failing metrics
    conversations_failing_as_expected = len(failing_conversations)
    if conversations_failing_as_expected == total_known_bad:
        exit_code = 0  # all bad conversations correctly flagged
```

### Deterministic Metadata Evaluation

Custom non-LLM metrics that compare expected vs actual conversation metadata per turn pair. Used for validating ticket state machine transitions (open/closed/escalated) without relying on an LLM judge.

```python
# helpers/conversation_metadata_deterministic_eval.py
class ConversationMetadataDeterministicEval(BaseConversationalMetric):
    def measure(self, test_case, *args, **kwargs):
        for i, turn in enumerate(test_case.turns):
            if turn.role != "user" or turn.additional_metadata is None:
                continue
            expected = turn.additional_metadata
            actual = turns[i + 1].additional_metadata
            for key in expected.keys() | actual.keys():
                if expected.get(key) != actual.get(key):
                    mismatches.append(...)
        self.score = 0.0 if mismatches else 1.0
```

## Configuration

- **Environment variables:**
  - `LLM_API_TOKEN` -- API key for the LLM endpoint used as evaluator judge
  - `LLM_URL` -- Base URL for the LLM API endpoint (OpenAI-compatible)
  - `LLM_ID` -- (Optional) Model identifier for the evaluator LLM
  - `NAMESPACE` -- OpenShift namespace for the deployed agent pod
  - `AUTHORITATIVE_USER_ID` -- Set per-conversation for the OpenShift chat client
- **Config files:** `conversations_config/authoritative_user_ids` (one user ID per line), `conversations_config/default_context/` (context files loaded for all evaluations), `conversations_config/conversations/` (predefined conversation flows as JSON)
- **CLI arguments:** `-n` (number of conversations), `--concurrency` (parallel workers), `--flow` (named evaluation flow), `--check` (known-bad validation mode), `--use-structured-output` (instructor mode for models like Gemini), `--conversation-source generate|export`

## Known Gotchas

- DeepEval's `global_test_run_manager.wrap_up_test_run` is monkey-patched to a no-op in `deep_eval.py` to prevent DeepEval from attempting to connect to online services and suggesting user login.
- The `CustomLLM.generate` method includes a workaround for GPT-OSS-120b which wraps output in `{"final": "{...}"}` or emits malformed keys like `{"final{": 0}` -- the code unwraps/remaps any key starting with "final" before parsing as Pydantic (found in `helpers/custom_llm.py`).
- DeepEval's type hints say `ConversationalTestCase.context` is `Optional[str]` but the runtime `__post_init__` implementation expects `List[str]` -- a type: ignore comment is used at the call site.
- The `OpenShiftChatClient._read_full_agent_message` method appends a `[TIMEOUT]` marker to partial responses when timeout is exceeded, ensuring the timeout shows up in recorded conversations and can be detected by metrics.
- Concurrency for conversation generation (`--concurrency N`) cannot exceed the number of user IDs in `authoritative_user_ids` because each worker gets a disjoint partition of users.
- Token tracking is split into "app tokens" (from the chat agent, parsed from `TOKEN_SUMMARY:` output) and "evaluation tokens" (from the LLM judge, captured via response.usage). Both are aggregated in the pipeline summary.

## Testing Notes

- Run the full pipeline: `uv run evaluate.py -n 5` (generates 5 conversations and evaluates them)
- Run only DeepEval metrics on existing results: `uv run deep_eval.py`
- Validate metrics catch known problems: `uv run evaluate.py --check`
- Run a specific flow: `uv run evaluate.py --flow ticket_laptop_refresh`
- Run all flows: `uv run evaluate.py --all-flows`
- Export real conversations from the API instead of generating: `uv run evaluate.py --conversation-source export -n 20`
- Requires a running agent deployment accessible via `oc exec`

## Related Patterns

- `shared-clients` -- shared API clients used by `export_conversations_from_api.py`
- `shared-models` -- shared data models referenced via workspace dependency
- `request-manager` -- the agent pod targeted by `oc exec` in the OpenShift chat client
