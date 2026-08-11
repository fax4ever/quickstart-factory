---
name: evaluations
description: "DeepEval-based conversation evaluation framework for AI agent testing with LLM-as-judge metrics"
summary: "DeepEval-based evaluation framework for validating deployed AI agents and RAG applications end-to-end through LLM-as-judge conversation metrics, with Approach A testing conversational agents via oc exec subprocess pipeline with pluggable flow registry auto-discovery (flows/ containing flow.py + metrics.py) and Approach B testing RAG apps via Playwright browser automation against Streamlit UIs with two-stage evaluation (response quality + retrieval chunk quality). Use Approach A when validating agent state-machine behavior with ConversationSimulator generation via live model callback (--conversation-source generate|export), RetryableConversationalGEval addressing judge non-determinism, and deterministic metadata evaluation for state transitions without LLM; use Approach B when evaluating RAG retrieval quality with Stage 1 ConversationalGEval response metrics (with ground truth context injection) and Stage 2 chunk metrics (ChunkCountMetric, ChunkDeduplicationMetric via Jaccard >= 0.8, ContextualPrecision, ContextualRelevancy, Faithfulness); both support negative testing via --check (--expect-failures for Approach B). Both approaches require LLM_API_TOKEN/LLM_URL env vars and CustomLLM adapter wrapping any OpenAI-compatible endpoint as judge with optional instructor structured output; Approach A uses multiprocessing with disjoint authoritative_user_ids partitions and parses :DONE terminators and TOKEN_SUMMARY: lines for token tracking, while Approach B uses asyncio.Semaphore (--max-concurrent-calls default 16) and endpoint auto-detection (RAG_UI_ENDPOINT > oc get route > localhost). DeepEval's wrap_up_test_run must be monkey-patched to no-op preventing login prompts, GPT-OSS-120b requires workaround for malformed JSON wrapping in {\"final\": ...}, ConversationalTestCase.context type hint says Optional[str] but runtime expects List[str], --concurrency N cannot exceed authoritative_user_ids count, Streamlit chunk extraction requires three DOM fallback strategies across versions, and DEEPEVAL_PER_TASK_TIMEOUT_SECONDS_OVERRIDE defaults to 600s because the default is too short for RAG evaluations."
metadata:
  type: component
tags:
  tech_stack: [python, deepeval, openai, instructor, pydantic, playwright, pytest, markdownify, streamlit]
  ai_pattern: [evaluation, agents, guardrails, rag, vector-search]
  platform: [openshift]
  data_layer: []
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Full conversation evaluation pipeline with flow registry, LLM-as-judge metrics, conversation generation, and known-bad validation"
    approach: "A"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Playwright-based RAG evaluation with two-stage pipeline (conversational quality + retrieval chunk metrics), custom chunk deduplication/count metrics, and UI-driven conversation capture"
    approach: "B"
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

---

## Approach B: Playwright-Based RAG Evaluation (from RAG)

### When to Use

When evaluating a RAG application that has a Streamlit web UI, where both response quality and retrieval chunk quality need separate assessment. Unlike Approach A's agent-focused testing via `oc exec`, this approach drives a browser against the live UI to capture both the assistant's response and the actual retrieved chunks, then runs a two-stage evaluation pipeline.

### Differences from Approach A

- **Conversation generation:** Playwright browser automation against a Streamlit UI instead of `oc exec` subprocess into an agent pod
- **Evaluation stages:** Two distinct stages -- Stage 1 (ConversationalGEval for response quality) and Stage 2 (LLMTestCase-based metrics for retrieval chunk quality) -- instead of a single-stage flow-based evaluation
- **Test data format:** JSON files in `conversations/` subdirectories (organized by domain, e.g., `hr/`, `legal/`) with `expected_rag_content` and `expected_output` fields, rather than a flow registry with `flow.py`/`metrics.py` plugins
- **Custom non-LLM metrics:** ChunkCountMetric and ChunkDeduplicationMetric (Jaccard similarity) that run without an LLM judge, in addition to LLM-based metrics
- **RAG-specific LLM metrics:** Chunk Alignment (GEval), ContextualPrecision, ContextualRelevancy, Faithfulness -- all operating on `retrieval_context` vs `context` fields
- **No flow registry:** Static JSON test definitions instead of pluggable flow directories
- **No conversation generation via simulator:** Tests are predefined; conversations are captured by replaying them through the UI, not generated by DeepEval's ConversationSimulator

### Tech Stack & Dependencies

- **Runtime:** Python >=3.11
- **Key dependencies:** deepeval>=1.2.6, pytest>=8.3.0, pytest-playwright>=0.5.0, playwright>=1.48.0, instructor>=1.7.0, openai>=1.0.0, markdownify>=0.11.0
- **Build system:** pyproject.toml (standalone, no workspace dependencies)

### Pipeline Orchestrator

The `evaluate.py` wrapper chains two steps: (1) run pytest to capture conversations through the UI, (2) run `deep_eval_rag.py` to evaluate them. A `--check` mode skips conversation generation and evaluates known-bad conversations instead.

```python
# evaluate.py -- two-step pipeline
if check_mode:
    cmd = [sys.executable, str(EVALUATIONS_DIR / "deep_eval_rag.py")]
    # Override --results-dir to bad-conversations/
    if "--results-dir" not in " ".join(deep_eval_extra):
        deep_eval_extra += ["--results-dir", str(KNOWN_BAD_DIR)]
    if "--expect-failures" not in deep_eval_extra:
        deep_eval_extra += ["--expect-failures"]
else:
    # Step 1: pytest captures conversations via Playwright
    pytest_cmd = [sys.executable, "-m", "pytest",
                  str(EVALUATIONS_DIR / "test_conversations_ui.py"), "-v", "-s"]
    # Step 2: evaluate captured conversations
    deep_eval_cmd = [sys.executable, str(EVALUATIONS_DIR / "deep_eval_rag.py")]
```

### Playwright UI Conversation Capture

The `ConversationTestRunner` class drives Playwright against the Streamlit RAG UI. It configures mode (direct/agent), selects vector databases via Streamlit's multiselect widget, sends messages, waits for streaming responses to stabilize, and extracts actual RAG chunks from search result expanders.

```python
# test_conversations_ui.py -- ConversationTestRunner
def send_message(self, content: str) -> tuple[str, Optional[Dict[str, Any]]]:
    chat_input = self.page.get_by_placeholder("Ask a question...", exact=False)
    chat_input.fill(content)
    chat_input.press("Enter")
    self.page.wait_for_load_state("networkidle")
    response_text = self._wait_for_assistant_response(content)
    actual_rag_content = self._extract_actual_rag_content()
    return response_text, actual_rag_content
```

### RAG Chunk Extraction from UI

The `_extract_actual_rag_content` method locates Streamlit expanders containing search results, attempts three extraction strategies (data-value attribute, React props via JS evaluation, text parsing with regex), and returns the chunks as a list of strings.

```python
# test_conversations_ui.py -- chunk extraction strategies
json_data_attr = json_element.get_attribute("data-value")
if json_data_attr:
    search_results = json.loads(json_data_attr)
elif json_element.get_attribute("data-json"):
    search_results = json.loads(json_element.get_attribute("data-json"))
else:
    raw_json = json_element.evaluate("""(element) => {
        const key = Object.keys(element).find(k => k.startsWith('__react'));
        if (key && element[key] && element[key].memoizedProps) {
            const props = element[key].memoizedProps;
            if (props.src) return JSON.stringify(props.src);
        }
        return null;
    }""")
```

### Two-Stage Evaluation Metrics

Stage 1 uses ConversationalGEval metrics for response quality (Response Accuracy, Response Completeness, Answer Relevance). Stage 2 uses LLMTestCase-based metrics for retrieval quality (ChunkCountMetric, ChunkDeduplicationMetric, Chunk Alignment GEval, ContextualPrecision, ContextualRelevancy, Faithfulness).

```python
# get_rag_metrics.py -- Stage 1 conversational metrics
metrics.append(ConversationalGEval(
    name="Response Accuracy",
    criteria="Every factual claim must be verifiable against retrieval_context...",
    evaluation_params=[TurnParams.CONTENT, TurnParams.ROLE, TurnParams.RETRIEVAL_CONTEXT],
    threshold=0.7, model=custom_model,
))
# Stage 2 retrieval metrics
metrics.append(ChunkCountMetric(max_chunks=max_chunks, threshold=1.0))
metrics.append(ChunkDeduplicationMetric(similarity_threshold=0.8, threshold=1.0))
metrics.append(ContextualPrecisionMetric(threshold=0.7, model=custom_model))
```

### Custom Chunk Deduplication Metric

A non-LLM metric that detects near-duplicate chunks using word-level Jaccard similarity. Compares all pairs of retrieved chunks; any pair with similarity >= 0.8 is flagged as a duplicate.

```python
# get_rag_metrics.py -- ChunkDeduplicationMetric
@staticmethod
def _jaccard_similarity(set1: set, set2: set) -> float:
    if not set1 and not set2:
        return 1.0
    union = set1 | set2
    return len(set1 & set2) / len(union) if union else 0.0

def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
    chunks = test_case.retrieval_context or []
    tokenized = [self._tokenize(chunk) for chunk in chunks]
    for i in range(len(tokenized)):
        for j in range(i + 1, len(tokenized)):
            sim = self._jaccard_similarity(tokenized[i], tokenized[j])
            if sim >= self.similarity_threshold:
                duplicate_pairs.append((i + 1, j + 1, sim))
```

### Custom LLM with Concurrency Control

The CustomLLM adapter adds an asyncio.Semaphore to limit total concurrent API calls across all metrics and test cases. DeepEval fires approximately 15 calls per test case simultaneously across all metrics; the semaphore prevents server overload.

```python
# helpers/custom_llm.py -- concurrency control
class CustomLLM(DeepEvalBaseLLM):
    def __init__(self, ..., max_concurrent_calls: int = 4):
        self._semaphore = asyncio.Semaphore(max_concurrent_calls)
        self.instructor_client = instructor.from_openai(
            self.client, mode=instructor.Mode.JSON
        )

    async def a_generate(self, prompt, schema=None):
        async with self._semaphore:
            # ... API call with concurrency limit
```

### Endpoint Auto-Detection

The `helpers/endpoint.py` module auto-detects the RAG UI endpoint through a priority chain: explicit `RAG_UI_ENDPOINT` env var, OpenShift route lookup via `NAMESPACE` env var, current `oc project` context, or localhost fallback.

```python
# helpers/endpoint.py
def get_rag_ui_endpoint() -> str:
    if os.getenv("RAG_UI_ENDPOINT"):
        return os.getenv("RAG_UI_ENDPOINT")
    namespace = os.getenv("NAMESPACE")
    if namespace:
        result = subprocess.run(
            ["oc", "get", "route", "rag", "-n", namespace,
             "-o", "jsonpath={.spec.host}"], ...)
```

### Conversation Test Data Format

JSON files define conversations with expected RAG content (ground truth chunks) and expected output for each user message. The evaluator compares actual retrieved chunks against expected chunks.

```json
{
  "metadata": { "description": "Test EAP query against HR Benefits document" },
  "config": { "mode": "direct", "vector_dbs": ["hr-vector-db-v1-0"] },
  "messages": [{
    "role": "user",
    "content": "What is the employee assistance program?",
    "expected_output": "While FantaCo does not have a traditional EAP...",
    "expected_rag_content": {
      "chunks": ["The \"Cry Closet\" (Actually a \"Champagne..."]
    }
  }]
}
```

### Ground Truth Context Injection

The evaluator injects ground truth context into ConversationalGEval scenarios with explicit instructions that the judge must treat the content as real, regardless of how unusual it appears.

```python
# deep_eval_rag.py -- ground truth prompt
context.append("IMPORTANT: The following chunks are the EXACT, ACTUAL content from the source")
context.append("document. Regardless of how unusual, whimsical, or unrealistic this content may")
context.append("appear, it IS the real ground truth content that was retrieved by the RAG system.")
context.append("You MUST evaluate the assistant's response based SOLELY on whether it accurately")
context.append("reflects THIS content, not on whether the content seems realistic or plausible.")
```

### Configuration

- **Environment variables:**
  - `OPENAI_API_KEY` or `LLM_API_TOKEN` -- API key for the evaluator LLM judge
  - `OPENAI_API_BASE` or `LLM_URL` -- Base URL for the LLM endpoint
  - `LLM_ID` or `LLM` -- Model identifier (defaults to `gpt-4`)
  - `RAG_UI_ENDPOINT` -- Explicit Streamlit UI URL override
  - `NAMESPACE` -- OpenShift namespace for auto-detecting the UI route
  - `DEEPEVAL_PER_TASK_TIMEOUT_SECONDS_OVERRIDE` -- Per-task timeout (defaults to 600s)
- **CLI arguments:** `--api-endpoint`, `--api-key`, `--results-dir`, `--output-dir`, `--max-limited-chunks` (default 10), `--max-tokens`, `--sequential`, `--max-concurrent` (default 4), `--max-concurrent-calls` (default 16), `--stage 1|2|both`, `--check`, `--expect-failures`, `--debug`, `--subdir` (pytest filter for conversation subdirectory)

### Known Gotchas

- DeepEval's `global_test_run_manager.wrap_up_test_run` is monkey-patched to a no-op (same pattern as Approach A) to prevent online login prompts.
- The `DEEPEVAL_PER_TASK_TIMEOUT_SECONDS_OVERRIDE` environment variable is set to 600 seconds by default in `deep_eval_rag.py` if not already present, because the default timeout is too short for RAG evaluations with many chunks.
- Playwright browsers are installed to a project-local `evaluations/bin/` directory via `ensure_playwright_browsers()` rather than the system-wide default, controlled by `PLAYWRIGHT_BROWSERS_PATH`.
- Extracting RAG chunks from Streamlit's `st.json` expanders requires three fallback strategies because the DOM structure varies between Streamlit versions (data-value attribute, React fiber props via JS evaluation, regex text parsing).
- The `_wait_for_assistant_response` method checks for both the Streamlit "Running..." indicator disappearing and response text stabilization (5 consecutive identical reads at 1-second intervals) to handle streaming responses.
- The `--max-concurrent-calls` flag (default 16) caps total in-flight API requests via an asyncio.Semaphore because DeepEval fires approximately 15 calls per test case simultaneously across all metrics, which can overload the LLM server.
- Stage 2 retrieval evaluation can fail if the LLM truncates its response (`finish_reason=length`). The error message suggests `--max-tokens 8192` and the pipeline continues with Stage 1 results only rather than aborting.
- ContextualRecallMetric is commented out in `get_rag_metrics.py` with the note "Not working with current judge LLMs" -- left for possible future inclusion.
- The `conftest.py` resets chat state before each test by clicking "Clear Chat & Reset Config" in the Streamlit UI, handling the case where the button may not exist.
- Bad-conversation JSON files use the `conversation` key (pre-captured results) while normal test files use `messages` key (to be played through the UI), handled by different code paths.

### Testing Notes

- Run full pipeline (generate + evaluate): `python evaluate.py`
- Run evaluation only on existing results: `python deep_eval_rag.py`
- Validate metrics catch known-bad conversations: `python evaluate.py --check`
- Run only Stage 1 (conversational quality): `python deep_eval_rag.py --stage 1`
- Run only Stage 2 (retrieval quality): `python deep_eval_rag.py --stage 2`
- Filter to a specific conversation subdirectory: `python evaluate.py --subdir hr`
- Requires a running RAG Streamlit UI accessible via route, port-forward, or localhost

### Related Patterns

- `streamlit-frontend` -- the RAG UI that Playwright drives for conversation capture
- `pgvector` -- the vector database backend whose retrieval quality is evaluated
- `rag-service` -- the backend RAG service producing the chunks being assessed

---

## Choosing Between Approaches

| Criteria | Approach A (it-self-service-agent) | Approach B (RAG) |
|----------|-----------------------------------|-------------------|
| **Application type** | Conversational agent with state machine (ticket lifecycle) | RAG chatbot with document retrieval |
| **Conversation generation** | DeepEval ConversationSimulator with live agent via `oc exec` | Predefined JSON conversations replayed through Playwright UI |
| **UI interaction** | None (CLI-based agent pod) | Streamlit web UI via Playwright browser automation |
| **Evaluation focus** | Response quality + deterministic metadata (state transitions) | Response quality + retrieval chunk quality (two stages) |
| **Custom metrics** | RetryableConversationalGEval, ConversationMetadataDeterministicEval | ChunkCountMetric, ChunkDeduplicationMetric (Jaccard), Chunk Alignment GEval |
| **Test organization** | Pluggable flow registry (`flows/` with `flow.py` + `metrics.py`) | Static JSON files in `conversations/` subdirectories by domain |
| **Concurrency model** | Multiprocessing workers with disjoint user ID partitions | asyncio.Semaphore limiting total in-flight LLM API calls |
| **RAG chunk assessment** | Not applicable | Full retrieval evaluation (precision, relevancy, faithfulness, deduplication) |
| **Known-bad validation** | `--check` flag verifies all bad conversations fail | `--check` with `--expect-failures` inverts exit code logic |
