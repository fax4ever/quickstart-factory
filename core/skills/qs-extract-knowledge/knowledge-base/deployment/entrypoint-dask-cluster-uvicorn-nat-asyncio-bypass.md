---
name: entrypoint-dask-cluster-uvicorn-nat-asyncio-bypass
description: Container entrypoint that bootstraps Dask scheduler+worker then starts uvicorn directly to bypass NAT asyncio conflict
summary: "Solves bootstrapping a local Dask distributed cluster (scheduler + worker) inside a container alongside a NeMo Agent Toolkit (NAT) FastAPI web server, where NAT's `nat serve` cannot be used because its internal `asyncio.run()` conflicts with anyio's event loop in FastAPI/Starlette. Use this two-script entrypoint pattern (entrypoint.py + start_web.py) when NAT's FastAPI frontend needs in-container Dask compute; four alternatives were rejected -- nest_asyncio (subtle bugs), subprocess wrapping (complexity), NAT source modification (not a dependency fork) -- leaving uvicorn direct startup as the only viable bypass. The start_web.py bypass loads config via `nat.runtime.loader.load_config`, sets `NAT_CONFIG_FILE` and `NAT_FRONT_END_WORKER` env vars, then calls `uvicorn.run(\"nat.front_ends.fastapi.main:get_app\", factory=True, loop=\"asyncio\")`; the entrypoint verifies scheduler readiness using a `distributed.Client` probe (30 retries, 1s interval) before starting the worker and web server with reverse-order SIGTERM/SIGINT graceful shutdown (10s grace then kill). `NAT_DASK_SCHEDULER_ADDRESS` must be set programmatically after the scheduler starts (never in Dockerfile/compose), `DASK_LIFETIME_RESTART` defaults to `true` causing automatic worker recycling, `sys.argv` passthrough via `os.execvp` replaces the entrypoint with arbitrary commands for debugging, and the Dask dashboard on port 8787 is not exposed by default."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, fastapi]
  ai_pattern: [agents]
  platform: [kubernetes]
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "AI-Q Blueprint entrypoint.py starts local Dask cluster, then start_web.py bypasses NAT's asyncio.run() by launching uvicorn directly"
    approach: "A"
---

# Container Entrypoint with Dask Cluster Bootstrap and uvicorn NAT Bypass

## Overview

A two-script container entrypoint pattern where `entrypoint.py` bootstraps a local Dask distributed computing cluster (scheduler + worker) inside the container before starting the web server, and `start_web.py` launches the FastAPI application through uvicorn directly instead of through the framework's CLI command (`nat serve`). This bypass is necessary because the NeMo Agent Toolkit's `nat serve` command uses `asyncio.run()` internally, which conflicts with anyio's event loop management in FastAPI/Starlette.

## Pattern Description

The entrypoint script starts a Dask scheduler subprocess, waits for it to accept connections, starts a Dask worker connected to that scheduler, then launches the web server as a third subprocess. All three processes are managed with proper signal handling for graceful shutdown. The web server startup script (`start_web.py`) loads the NAT configuration, extracts the worker class, and runs uvicorn directly with `loop="asyncio"` to let uvicorn create and manage its own event loop without conflicting with nested loops.

## Implementation

### Entrypoint: Dask Cluster Bootstrap

The entrypoint starts the Dask scheduler, waits for it, starts the worker, then launches the web server. All subprocesses are tracked for signal-based shutdown.

```python
def main() -> int:
    if len(sys.argv) > 1:
        os.execvp(sys.argv[1], sys.argv[1:])

    scheduler_port = int(os.getenv("DASK_SCHEDULER_PORT", "8786"))
    nworkers = os.getenv("DASK_NWORKERS", "1")
    nthreads = os.getenv("DASK_NTHREADS", "4")
    memory_limit = os.getenv("DASK_MEMORY_LIMIT")

    scheduler_proc = subprocess.Popen([
        "dask-scheduler", "--port", str(scheduler_port),
        "--dashboard-address", ":8787",
    ])

    _wait_for_scheduler(scheduler_port)

    worker_args = [
        "dask-worker", f"tcp://localhost:{scheduler_port}",
        "--nworkers", str(nworkers),
        "--nthreads", str(nthreads), "--no-dashboard",
    ]
    if memory_limit:
        worker_args += ["--memory-limit", memory_limit]

    worker_proc = subprocess.Popen(worker_args)
    os.environ["NAT_DASK_SCHEDULER_ADDRESS"] = f"tcp://localhost:{scheduler_port}"

    web_proc = subprocess.Popen(["python", "/app/deploy/start_web.py"])
    _install_signal_handlers(scheduler_proc, worker_proc, web_proc)
    return web_proc.wait()
```

### Scheduler Wait with Dask Client Probe

The scheduler readiness check uses the Dask distributed Client to verify the scheduler is accepting connections, not just that the port is open.

```python
def _wait_for_scheduler(port: int) -> None:
    from distributed import Client
    for attempt in range(1, 31):
        try:
            Client(f"tcp://localhost:{port}", timeout="2s").close()
            print("Scheduler ready.", flush=True)
            return
        except Exception as exc:
            if attempt == 30:
                raise RuntimeError("Scheduler failed to start") from exc
            time.sleep(1)
```

### Web Server: uvicorn Direct Startup (Bypass nat serve)

The `start_web.py` script documents the asyncio conflict extensively and runs uvicorn directly with the ASGI app factory.

```python
# The problem: nat serve -> asyncio.run() -> FastAPI/anyio conflict
# Solution: load config ourselves, set env vars, run uvicorn directly

from nat.runtime.loader import load_config

config = load_config(config_file)
os.environ["NAT_CONFIG_FILE"] = config_file

# Extract runner_class from config for NAT's FastAPI app
runner_class_name = getattr(config.general.front_end, "runner_class", None)
if runner_class_name:
    os.environ["NAT_FRONT_END_WORKER"] = runner_class_name

# Key: uvicorn manages its own event loop, no conflict
uvicorn.run(
    "nat.front_ends.fastapi.main:get_app",
    host=host, port=port,
    factory=True,
    loop="asyncio",
)
```

### Signal-Based Graceful Shutdown

The entrypoint installs SIGTERM and SIGINT handlers that shut down processes in reverse order (web, worker, scheduler) with a 10-second grace period before killing.

```python
def _terminate_process(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

def _install_signal_handlers(scheduler_proc, worker_proc, web_proc):
    def _handle_signal(_signum, _frame):
        _terminate_process(web_proc)
        _terminate_process(worker_proc)
        _terminate_process(scheduler_proc)
        sys.exit(0)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
```

## Configuration

- **Key settings:** `DASK_SCHEDULER_PORT` (default 8786), `DASK_NWORKERS` (default 1), `DASK_NTHREADS` (default 4), `DASK_MEMORY_LIMIT` (optional), `DASK_LIFETIME` (optional worker recycling), `CONFIG_FILE` (default `config_web_default_llamaindex.yml`)
- **Defaults:** 1 worker, 4 threads, no memory limit, no lifetime recycling; dev target starts with config_web_default_llamaindex.yml
- **Dependencies:** `dask[distributed]` package in the container; NAT framework with FastAPI frontend plugin

## Gotchas

- If `sys.argv` has arguments beyond the script name, `entrypoint.py` uses `os.execvp` to replace itself with that command -- this allows the container to run arbitrary commands (e.g., `python`, `bash`) instead of the web server when needed for debugging
- The `NAT_DASK_SCHEDULER_ADDRESS` environment variable is set programmatically AFTER the scheduler starts -- it must not be in the Dockerfile or compose env because the scheduler URL is only known at runtime
- The `start_web.py` script documents four alternative approaches that were considered and rejected: `nest_asyncio` (subtle bugs), subprocess wrapping (complexity), NAT source modification (not a dependency fork), and the chosen uvicorn direct approach
- The `DASK_LIFETIME_RESTART` env var defaults to `true` -- setting it to `false` changes worker lifecycle from "recycle after N seconds" to "exit gracefully after N seconds without respawning"
- Dask dashboard runs on port 8787 inside the container but is not exposed in the compose file -- it can be accessed for debugging by adding a port mapping

## Related Patterns

- `container-build-nvidia-distroless-uv-dev-release-target.md` -- the Dockerfile that packages these entrypoint scripts
- `compose-local-dev-prebuilt-ngc-fallback-build-target-dask.md` -- compose file that configures DASK_* env vars
