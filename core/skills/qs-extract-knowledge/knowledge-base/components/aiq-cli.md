---
name: aiq-cli
description: Interactive CLI frontend for NVIDIA AI-Q Blueprint using prompt_toolkit, Rich, and NAT SessionManager
summary: "Terminal-based interactive CLI for NVIDIA AI-Q Blueprint that wraps NAT's load_workflow/SessionManager in an async REPL with Rich Markdown panels, prompt_toolkit FileHistory (~/.aiq/cli_history), and a custom ANSI spinner subscribing to IntermediateStep TOOL_START/TOOL_END events via _on_step callback. Packaged as a separate uv workspace member (frontends/cli/, entry point aiq-research) for dev-time use only (no Helm subchart) -- use when building a terminal interface to NAT agent workflows; prefer the web UI frontend (frontends/ui/) for browser-based access to the same SessionManager. Loads env vars (NVIDIA_API_KEY, SERPER_API_KEY) from deploy/.env via python-dotenv and validates LLM API keys via validate_llm_configs against workflow YAML (default configs/config_cli_default.yml) before entering the loop -- missing keys trigger os._exit(1) skipping Python atexit handlers. Critical gotchas: os._exit(0) in main() finally block prevents NAT async cleanup hangs, global warnings.filterwarnings(\"ignore\") at import time hides library warnings unless PYTHONWARNINGS is set, HITL supports only HumanPromptModelType.TEXT (others raise ValueError directing to nat serve), and spinner replaces sys.stdout/sys.stderr with wrapper objects causing capture-order-dependent filtering behavior."
metadata:
  type: component
tags:
  tech_stack: [python, argparse, prompt-toolkit, rich, pydantic, python-dotenv]
  ai_pattern: [agents, prompt-chaining]
  platform: []
  data_layer: []
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "CLI frontend for AI-Q research agent with async spinner, HITL callback, and NAT workflow integration"
    approach: "A"
---

# AIQ CLI

## Overview

A terminal-based interactive frontend for the NVIDIA AI-Q Blueprint. It wraps the NeMo Agent Toolkit (NAT) `SessionManager` in an async REPL loop with Rich-formatted output, prompt_toolkit input with persistent history, and a custom async spinner that tracks tool-call progress. It is installed as a separate Python package (`aiq-research-cli`) and registered as the `aiq-research` console script entry point.

## Tech Stack & Dependencies

- **Runtime:** Python >=3.11, <3.14
- **Container image:** Installed via `uv pip install --no-deps -e ./frontends/cli` in the dev stage of the multi-stage Dockerfile
- **Key dependencies:** `aiq-agent` (the main backend package), `rich>=13.0.0`, `prompt_toolkit>=3.0.0`, `python-dotenv>=1.0.0`, `httpx>=0.24.0`, `pydantic>=2.0.0`
- **Helm subchart:** None (CLI is a dev-time tool, not deployed as a service)

## Key Patterns

### Separate Installable Package via uv Workspace

The CLI is its own Python package under `frontends/cli/` with a dedicated `pyproject.toml`. It is wired into the root monorepo as a uv workspace member and installed as an editable package during setup.

```toml
# frontends/cli/pyproject.toml
[project]
name = "aiq-research-cli"
version = "2.0.1"
dependencies = [
    "aiq-agent",
    "rich>=13.0.0",
    "python-dotenv>=1.0.0",
    "httpx>=0.24.0",
    "pydantic>=2.0.0",
    "prompt_toolkit>=3.0.0",
]

[project.scripts]
aiq-research = "aiq_research_cli.cli:main"
```

The root `pyproject.toml` references it as:

```toml
aiq-research-cli = { workspace = true }
```

### NAT SessionManager Integration

The CLI loads a NAT workflow from a YAML config and runs an interactive session. The `load_workflow` context manager yields a `SessionManager`, and each user turn is processed through `session.run()`.

```python
async with load_workflow(args.config_file) as session_manager:
    await interactive_loop(session_manager, verbose=args.verbose)
```

Inside the loop, a session is opened with a HITL callback:

```python
async with session_manager.session(user_input_callback=cli_user_input_callback) as session:
    async with session.run(user_input) as runner:
        result = await runner.result(to_type=str)
```

### Async Spinner with Tool-Call Progress

A custom `_Spinner` class uses raw ANSI escape codes (not Rich Live) to avoid cursor-control artifacts. It subscribes to NAT `IntermediateStep` events to update the spinner text with the currently executing tool name.

```python
def _on_step(step: IntermediateStep) -> None:
    if step.event_type == IntermediateStepType.TOOL_START and step.name:
        tool_label = f"{_BOLD_CYAN}Using tool:{_RESET} {step.name}"
        spinner.update(f"{prefix} {tool_label}")
    elif step.event_type == IntermediateStepType.TOOL_END:
        spinner.update(f"{prefix} {thinking}")

subscription = runner.context.intermediate_step_manager.subscribe(on_next=_on_step)
```

While spinning, the CLI installs a `_BlankLineFilter` on `sys.stdout` to suppress blank-line noise, and a `_StderrTracker` to detect log output and clear orphaned spinner lines.

### Human-in-the-Loop (HITL) Callback

The CLI implements NAT's HITL protocol via `cli_user_input_callback`. When the agent workflow requests human input, the spinner is paused, a Rich Panel is displayed, and the user is prompted via prompt_toolkit. Only `HumanPromptModelType.TEXT` is supported; other types raise `ValueError` directing users to `nat serve` for full HITL support.

```python
async def cli_user_input_callback(prompt: InteractionPrompt) -> HumanResponse:
    if prompt.content.input_type == HumanPromptModelType.TEXT:
        was_spinning = _active_spinner is not None
        if was_spinning:
            _active_spinner.stop()
        # ... prompt user ...
        return HumanResponseText(text=user_response)
    raise ValueError(
        f"Unsupported human prompt input type: {prompt.content.input_type}. "
        "The CLI only supports 'HumanPromptText' input type. "
        "Please use 'nat serve' for full HITL support."
    )
```

### Pre-Run API Key Validation

Before entering the interactive loop, the CLI reads the workflow YAML config, extracts LLM definitions, and validates that required API key environment variables are set. If any are missing, it exits immediately with `os._exit(1)`.

```python
from aiq_agent.common.config_validation import validate_llm_configs

is_valid, missing_keys = validate_llm_configs(config)
if not is_valid:
    console.print(
        f"\n[bold red]Error: Missing required API keys ({', '.join(missing_keys)})[/bold red]\n"
    )
    os._exit(1)
```

### Response Parsing with Think-Tag Stripping

Responses from the agent may contain `<think>...</think>` tags (from models with chain-of-thought). The CLI strips these before rendering the final answer in a Rich Panel with Markdown formatting.

```python
def parse_and_display_response(response: str, verbose: bool = False) -> None:
    think_pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL)
    response_without_think = think_pattern.sub("", response).strip()
    if response_without_think:
        console.print(Panel(Markdown(response_without_think), title="Answer", border_style="bright_white"))
```

## Configuration

- **Environment variables:** Loaded from `deploy/.env` via `python-dotenv`; key variables include `NVIDIA_API_KEY`, `SERPER_API_KEY` (optional), `AIQ_DEV_ENV` (set to `cli` by `start_cli.sh`), `AIQ_VERBOSE`
- **Config files:** `configs/config_cli_default.yml` is the default workflow YAML; specifies LLM providers (NIM endpoints), tool registrations (Tavily web search), and agent pipeline (intent classifier, clarifier, shallow/deep research agents)
- **CLI arguments:** `--config_file` (workflow YAML path), `--env_file` (dotenv path, default `deploy/.env`), `--verbose` / `-v` (enables tool-call tracing)
- **Persistent history:** Arrow-key command recall stored at `~/.aiq/cli_history` via `prompt_toolkit.history.FileHistory`

## Known Gotchas

- The CLI uses `os._exit(0)` in the `finally` block of `main()` to force-terminate the process. This is likely to avoid hanging from background async tasks or NAT cleanup that does not complete cleanly.
- The CLI uses `os._exit(1)` rather than `sys.exit(1)` for missing API keys, which skips Python cleanup (atexit handlers, finally blocks). This is intentional to avoid triggering NAT teardown on a startup failure.
- Warning suppression is applied globally at module import time (`warnings.filterwarnings("ignore")`) unless the `PYTHONWARNINGS` environment variable is set. This means library-level warnings are hidden by default even before argparse runs.
- The spinner manipulates `sys.stdout` and `sys.stderr` by replacing them with wrapper objects during execution. Code that captures `sys.stdout` before the spinner starts (as the CLI itself does with `_real_stdout`) will bypass the filter, while code that reads `sys.stdout` during spinning will get the filtered version.
- Only `HumanPromptModelType.TEXT` is supported for HITL prompts. File upload or multi-choice prompts from NAT workflows will raise `ValueError` at runtime.

## Testing Notes

- Start the CLI via `./scripts/start_cli.sh` or directly with `aiq-research --config_file configs/config_cli_default.yml`
- Verify HITL by using a config with `enable_clarifier: true` and `enable_plan_approval: true` -- the clarifier agent will prompt for user input
- Check verbose mode with `-v` to confirm tool-call intermediate steps are displayed
- Missing API keys should produce a clear error and exit before the interactive loop starts

## Related Patterns

- NAT workflow configuration and agent pipeline are defined in the config YAML (see architecture KB)
- The web UI frontend (`frontends/ui/`) provides an alternative browser-based interface to the same NAT SessionManager
- API key validation logic lives in `src/aiq_agent/common/config_validation.py`
