---
name: test-suite
description: "Pytest-based test suite with marker-driven tiers (unit/integration/llm/cluster), containerized runner, and MicroShift E2E CI"
summary: "Provides a multi-tier pytest test suite for AI Quickstarts spanning multiple services (orchestrator, tools, UI, guardrails), using marker-based tiers (unit/integration/llm/cluster_only/local_only) with Makefile targets composing marker expressions so users select test scope without learning pytest syntax. Use when building multi-service quickstarts that need testing across local dev, CI, and OpenShift cluster environments — the marker-driven approach lets one test directory serve all tiers without conditional skipping in test bodies. Root conftest.py injects monorepo service source dirs into sys.path for cross-service imports; a containerized runner (python:3.12-slim, pytest entrypoint, both test and app requirements installed) enables CI execution; MicroShift E2E GitHub Actions parallelizes cluster boot (ci/setup-microshift.sh &) with test image loading, then deploys via Helm and runs --network=host integration tests with 300s pytest-timeout for slow LLM responses. LlmConfig placeholder detection (\"your-\", \"example.com\", \"sk-your\") auto-skips LLM tests but may incorrectly skip real keys containing those substrings; assert_stack_ready() only probes tool agent ports on localhost (skipped in cluster mode); E2E tests route through UI nginx proxy (/api/*) to catch proxy misconfiguration that direct-to-orchestrator tests miss."
metadata:
  type: component
tags:
  tech_stack: [pytest, httpx, python, python-dotenv, pandas, numpy, scipy]
  ai_pattern: [agents, guardrails, evaluation]
  platform: [openshift, microshift, podman]
  data_layer: []
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Multi-tier pytest suite with marker-based selection, containerized test runner, MicroShift E2E CI, and cluster verification via oc"
    approach: "A"
---

# Test Suite

## Overview

A structured pytest test suite designed for AI Quickstarts that span multiple services (orchestrator, tool agents, UI, guardrails). The suite uses pytest markers to select tests by environment tier -- unit tests run anywhere, integration tests require a local compose stack, LLM tests require real API credentials, and cluster tests require an OpenShift namespace. A containerized test runner (Dockerfile with pytest entrypoint) enables consistent execution in CI and on-cluster environments.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12
- **Container image:** `python:3.12-slim` (test runner Dockerfile)
- **Key dependencies:** pytest>=8.0, pytest-timeout>=2.0, httpx>=0.28, python-dotenv>=1.0, numpy>=1.26, pandas>=2.0, scipy>=1.11
- **Helm subchart:** N/A (tests run externally against deployed services)

## Key Patterns

### Marker-Based Test Tiers

pytest markers classify tests into tiers that match different execution environments. This enables a single test directory to serve local dev, CI, and cluster validation without skipping or conditionals in the test body.

```ini
# tests/pytest.ini
[pytest]
testpaths = unit integration
markers =
    unit: pure logic, no live stack
    integration: requires live compose stack on localhost
    llm: requires real OPENAI_API_* in .env
    local_only: requires direct localhost access (skipped on cluster)
    cluster_only: requires OpenShift cluster access (skipped locally)
    requires_controllers: needs KServe/NemoGuardrails controllers running
timeout = 300
```

### Makefile Test Targets

Makefile targets compose marker expressions for each environment, removing the need for users to remember pytest marker syntax.

```makefile
test-unit:
	pytest tests/unit -m unit -v

test-integration:
	pytest tests/integration -m "integration and not llm and not cluster_only" -v

test-cluster:
	UI_BASE=http://$(shell oc get route ui -n $(NAMESPACE) ...) \
	ORCH_BASE=http://$(shell oc get route orchestrator -n $(NAMESPACE) ...) \
	pytest tests/integration -m "integration and not llm and not local_only" -v
```

### Monorepo sys.path Injection

The root conftest adds source directories from multiple services to `sys.path` so unit tests can import modules directly without installing packages.

```python
# tests/conftest.py
ROOT = Path(__file__).resolve().parents[1]

for rel in (
    "orchestrator/src",
    "tools/guidelines/src",
    "tools/value_at_risk/src",
):
    path = str(ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)
```

### Stack Readiness Assertion

Integration tests use a session-scoped fixture that probes all service health endpoints before any test runs, providing a clear error message if the stack is down.

```python
# tests/integration/conftest.py
def assert_stack_ready() -> None:
    probes = [
        ("orchestrator health", f"{ORCH_BASE}/health"),
        ("UI static", f"{UI_BASE}/"),
        ("UI api health", f"{UI_API_BASE}/health"),
    ]
    if "localhost" in UI_BASE:
        for port in TOOL_PORTS:
            probes.append((f"tool {port}", f"http://localhost:{port}/tools"))

    with httpx.Client(timeout=10.0) as client:
        for label, url in probes:
            try:
                response = client.get(url)
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"{label} unreachable at {url}: {exc}. "
                    "Start the stack with: make deploy-local"
                ) from exc
```

### LLM Config with Placeholder Detection

An `LlmConfig` dataclass loaded from `.env` or environment variables detects placeholder credentials and auto-skips LLM tests when real API keys are not available.

```python
# tests/integration/conftest.py
@dataclass
class LlmConfig:
    llm_url: str
    api_key: str
    model: str

    @property
    def is_real(self) -> bool:
        if not self.llm_url or not self.api_key or not self.model:
            return False
        placeholders = ("your-", "example.com", "sk-your")
        combined = f"{self.llm_url} {self.api_key} {self.model}".lower()
        return not any(token in combined for token in placeholders)
```

### E2E Tests Through UI Proxy

End-to-end tests call the same `/api/*` route that the browser uses (through the UI nginx proxy), rather than hitting the orchestrator directly, verifying the full request path.

```python
# tests/integration/test_e2e.py — Flow:
#   1. POST /api/pipeline/guidelines  -> prohibited tickers
#   2. POST /api/pipeline/portfolio   -> build portfolio
#   3. POST /api/pipeline/var         -> calculate VaR
#   4. POST /api/pipeline/email       -> LLM drafts client email
#   5. POST /api/chat                 -> swap a symbol, verify update
```

### Cluster Verification Tests via oc CLI

Cluster-only tests use `subprocess.run(["oc", ...])` to verify Kubernetes resources (ConfigMaps, pods, services, deployments) match expected state.

```python
# tests/integration/test_guardrails.py
@pytest.mark.integration
@pytest.mark.cluster_only
def test_guardrails_configmap_exists():
    result = _oc("get", "configmap", "guardrails-config",
                 "-n", NAMESPACE, "-o", "jsonpath={.data}")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    for key in ("config.yaml", "rails.co", "actions.py"):
        assert key in data
```

### Containerized Test Runner

A dedicated Dockerfile builds a test runner image with both test and application dependencies, using `pytest` as the entrypoint. This image runs in CI and can be cached.

```dockerfile
# tests/Dockerfile
FROM python:3.12-slim
COPY tests/requirements.txt /tmp/test-requirements.txt
COPY orchestrator/src/requirements.txt /tmp/orchestrator-requirements.txt
RUN pip install --no-cache-dir \
        -r /tmp/test-requirements.txt \
        -r /tmp/orchestrator-requirements.txt
WORKDIR /workspace
ENTRYPOINT ["pytest"]
```

### MicroShift E2E in GitHub Actions

The E2E CI workflow boots a MicroShift cluster inside the runner, deploys the app via Helm, and runs integration tests in the containerized runner with `--network=host`. MicroShift setup and test image preparation run in parallel to reduce total CI time.

```yaml
# .github/workflows/e2e-microshift.yml — key steps:
# 1. Boot MicroShift (ci/setup-microshift.sh &) in background
# 2. Load/pull cached tests container image in foreground
# 3. Deploy app via: make deploy-cluster NAMESPACE="$NAMESPACE"
# 4. Run non-LLM integration tests via containerized runner
# 5. Conditionally run LLM tests if OPENAI_API_TOKEN is set
```

## Configuration

- **Environment variables:**
  - `UI_BASE` — UI service URL (default: `http://localhost:8080`)
  - `ORCH_BASE` — Orchestrator service URL (default: `http://localhost:5000`)
  - `GUARDRAILS_BASE` — Guardrails service URL (default: `http://localhost:8000`)
  - `NAMESPACE` — OpenShift namespace for cluster tests
  - `OPENAI_API_ENDPOINT`, `OPENAI_API_TOKEN`, `OPENAI_MODEL` — LLM credentials (from `.env` or environment)
  - `ENV_FILE` — Path to `.env` file (default: repo root `.env`)
  - `CURL_MAX_TIME` — HTTP timeout for integration test client (default: 60s)
  - `PORTFOLIO_VALUE`, `QTY_SYMBOLS`, `MAX_VAR` — Domain-specific test parameters with sensible defaults
- **Config files:** `tests/pytest.ini` (markers, timeout, testpaths), `.env` (LLM credentials)
- **Helm values:** N/A (tests run externally)

## Known Gotchas

- The root `conftest.py` injects multiple `sys.path` entries for the monorepo's separate service directories (`orchestrator/src`, `tools/guidelines/src`, `tools/value_at_risk/src`). Without this, unit tests cannot import application modules since each service has its own source root.
- The test Dockerfile must install both `tests/requirements.txt` and `orchestrator/src/requirements.txt` -- missing the application requirements causes import errors when the containerized runner executes tests that import application modules.
- `LlmConfig.is_real()` checks for common placeholder patterns (`"your-"`, `"example.com"`, `"sk-your"`) to auto-skip LLM tests. If a real API key happens to contain these substrings, the test will be incorrectly skipped.
- The `assert_stack_ready()` function probes tool agent ports (7001, 7002, 7003) only when `UI_BASE` contains `"localhost"`, so these checks are implicitly skipped in cluster mode where routes are used instead.
- Cluster-only tests call `oc` via `subprocess.run` rather than the Kubernetes Python client, keeping the test dependency footprint minimal but requiring `oc` to be available on the PATH.
- The MicroShift E2E workflow parallelizes cluster boot and test image loading (`ci/setup-microshift.sh &`), which means a failure in setup only surfaces when the background process is `wait`-ed on.
- E2E tests that go through the UI nginx proxy (`/api/*`) will catch proxy misconfiguration that direct-to-orchestrator tests would miss, which is why both paths are tested.

## Testing Notes

- Run `make test-unit` for fast feedback -- no services needed.
- Run `make deploy-local` first, then `make test-integration` for local integration tests without LLM.
- Set real `OPENAI_API_*` values in `.env`, then run `make test-integration-llm` for LLM-dependent tests.
- For cluster tests: `make test-cluster NAMESPACE=<ns>` (auto-resolves route URLs via `oc get route`).
- The 300-second pytest timeout in `pytest.ini` accommodates slow LLM responses in integration tests.
- Unit tests use `importlib.util.spec_from_file_location` to import modules by absolute file path when `sys.path` injection alone is insufficient (seen in `test_extract_tickers.py`).

## Related Patterns

- Containerized test runner pattern relates to CI/CD pipeline architecture
- Marker-based test tiers relate to the Makefile targets deployment pattern
- Stack readiness checks relate to health endpoint patterns in fastapi-backend
