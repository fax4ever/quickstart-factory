---
name: portfolio-tool-agent
description: "Flask tool-agent exposing portfolio construction and symbol replacement via JSON Schema-advertised REST endpoints"
summary: "Flask tool-agent microservice exposing portfolio_equities and portfolio_replace_symbol REST endpoints in a multi-agent investment advisor on RHOAI, where an orchestrator discovers JSON Schema function definitions via GET /tools (doubles as Helm readiness probe) and invokes them via convention-based POST /tools/<tool_name>. Use this pattern when building domain-specific tool servers that peer alongside sibling agents (value_at_risk on 7001, guidelines on 7003, guardrails on 8000) and need runtime discovery -- deploys as a standard Deployment on port 7002 or optionally as a Knative Service via serverless.enabled Helm value. Runs on UBI 10 minimal as non-root user 1001, installs numpy/scipy/scikit-learn as --only-binary=:all: wheels to avoid compilation on toolchain-less images, and builds equal-weight random portfolios from a hardcoded S&P 100 universe sized with live yfinance prices. Yfinance makes uncached external HTTP calls per invocation (slow or fails in network-restricted OpenShift), random.choice loop lacks deduplication allowing duplicate symbols in a portfolio, endpoint returns a bare JSON list but orchestrator expects a {\"portfolio\": ...} dict wrapper, and Flask dev server (app.run(debug=True)) is used as the production CMD despite gunicorn/waitress being recommended."
metadata:
  type: component
tags:
  tech_stack: [flask, python, yfinance]
  ai_pattern: [agents]
  platform: [openshift, rhoai]
  data_layer: []
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Flask tool-agent for equities portfolio construction, consumed by an orchestrator via HTTP tool discovery"
    approach: "A"
---

# Portfolio Tool Agent

## Overview

A lightweight Flask microservice that acts as a "tool server" in a multi-agent investment advisor system on RHOAI. It exposes domain-specific financial tools (portfolio construction, symbol replacement) as REST endpoints, each described by a JSON Schema definition that an orchestrator discovers at runtime via `GET /tools`. The service uses yfinance for real-time stock price lookups against a hardcoded S&P 100 universe.

## Tech Stack & Dependencies
- **Runtime:** Python 3.12 on UBI 10 minimal (`registry.access.redhat.com/ubi10/python-312-minimal`)
- **Container image:** `quay.io/ikatav/portfolio-manager-agent:portfolio`
- **Key dependencies:**
  - Flask 3.1+ with flask-cors
  - yfinance 0.2.66 for live stock price data
  - numpy, scipy, scikit-learn (installed as binary-only wheels in Dockerfile)
  - openai, pandas, pydantic (present in requirements.txt, likely shared across tools)
- **Helm chart:** `deploy/helm/` (monolithic chart with per-tool deployment templates)

## Key Patterns

### JSON Schema Tool Advertisement

Each tool server exposes a `GET /tools` endpoint returning an array of JSON Schema function definitions. The orchestrator discovers available tools at startup by hitting this endpoint on every registered tool server, then maps tool names to their hosting server for invocation.

```python
# From tools/portfolio/src/app.py
TOOLS = [
    {
        "type": "function",
        "name": "portfolio_equities",
        "description": "Build an equities portfolio of a given size without excluded symbols",
        "parameters": {
            "type": "object",
            "properties": {
                "portfolio_value": {
                    "type": "number",
                    "description": "Do not exceed value of portfolio",
                    "minimum": 0,
                },
                # ... qty_symbols, symbols_exclusion
            },
        },
    },
]

@app.get("/tools")
def list_tools():
    return jsonify(TOOLS)
```

### Convention-Based Tool Invocation

Tool endpoints follow the pattern `POST /tools/<tool_name>`. The orchestrator calls `POST /tools/portfolio_equities` with JSON arguments matching the advertised schema. This convention allows the orchestrator to invoke any discovered tool without tool-specific client code.

```python
# From orchestrator/src/orchestrator.py (consumer side)
class HttpToolServer:
    def discover(self) -> list[DiscoveredTool]:
        url = urljoin(self.base_url, "tools")
        resp = requests.get(url, timeout=self.timeout)
        # ...
    def call(self, tool_name: str, arguments: dict) -> dict:
        url = urljoin(self.base_url, f"tools/{tool_name}")
        resp = requests.post(url, json=arguments, timeout=self.timeout)
```

### Equal-Weight Random Portfolio Construction

The portfolio builder randomly selects stocks from a hardcoded S&P 100 list, excluding specified symbols, then sizes positions for equal dollar weight using live prices from yfinance.

```python
# From tools/portfolio/src/app.py
while len(portfolio) < qty_symbols:
    symbol = random.choice(SP_100)
    if symbol not in symbols_exclusion:
        price = last_price(symbol)
        shares = int(requested_portfolio_value / qty_symbols / price)
        portfolio.append(
            {"symbol": symbol, "quantity": shares, "last_price": price}
        )
```

### Symbol Replacement Preserving Portfolio Structure

A second tool (`portfolio_replace_symbol`) swaps one holding for a new random eligible symbol while keeping all other positions unchanged. It reuses the equal-weight sizing logic for the replacement slot.

```python
# From tools/portfolio/src/app.py
def pick_replacement_symbol(held_symbols, symbols_exclusion):
    blocked = set(symbols_exclusion) | set(held_symbols)
    candidates = [s for s in SP_100 if s not in blocked]
    if not candidates:
        raise ValueError("No eligible replacement symbols after applying exclusions")
    return random.choice(candidates)
```

### UBI 10 Minimal with Binary-Only Wheels

The Dockerfile uses UBI 10 minimal and installs numpy/scipy/scikit-learn as binary-only wheels before the main requirements to avoid compilation. It runs as non-root user 1001.

```dockerfile
# From tools/portfolio/src/Dockerfile
FROM registry.access.redhat.com/ubi10/python-312-minimal
USER 0
RUN microdnf -y upgrade --setopt=install_weak_deps=0 && \
    microdnf -y install ca-certificates && \
    microdnf clean all
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --only-binary=:all: \
        numpy scipy scikit-learn && \
    pip install --no-cache-dir -r /tmp/requirements.txt
USER 1001
CMD ["python", "app.py"]
```

## Configuration
- **Environment variables:**
  - `PORT` (default `7002`): HTTP listen port for this tool server
  - `PYTHONUNBUFFERED` (`1`): set in Helm deployment for immediate log flushing
- **Config files:** None; the S&P 100 universe is hardcoded in `app.py` (the source notes "In prod, this would likely be available via a web service or sitting in cache")
- **Helm values:**
  - `image.tags.portfolio`: image tag for the portfolio container (default `portfolio`)
  - `serverless.enabled`: when true, deploys as a Knative Service instead of a Deployment
  - `serverless.minScale`, `maxScale`, `concurrency`, `timeoutSeconds`: Knative autoscaling parameters
- **Compose:** `deploy/local/compose.yml` builds from `../../tools/portfolio/src` and maps port 7002

## Known Gotchas
- The `last_price` function fetches 10 days of history via `yf.Ticker(symbol).history(period="10d")["Close"].iloc[-1]` and takes the last close. This means the tool server makes external HTTP calls to Yahoo Finance on every tool invocation, which can be slow and may fail if network-restricted on OpenShift. There is no caching layer.
- The portfolio builder uses `random.choice` in a while loop without deduplication checks, so the same symbol could theoretically be selected multiple times in one portfolio (the exclusion list only filters user-specified symbols, not already-selected ones).
- The `portfolio_equities` endpoint returns a bare list (not wrapped in a JSON object), while the orchestrator pipeline's `build_portfolio` function expects the response to be a dict with a `"portfolio"` key (`if isinstance(raw, dict) and "portfolio" in raw`), suggesting a contract mismatch that the pipeline code works around.
- The Helm readiness probe uses `GET /tools` on port 7002, so the tool discovery endpoint doubles as a health check.
- The Dockerfile installs numpy, scipy, and scikit-learn as `--only-binary=:all:` before the main `requirements.txt` to ensure pre-built wheels are used, avoiding native compilation failures on UBI minimal images that lack build toolchains.
- The Flask dev server (`app.run(debug=True)`) is used as the production entrypoint via `CMD ["python", "app.py"]`. The source comment notes "use gunicorn/waitress for production" but neither is configured.

## Testing Notes
- The tool server has no unit tests of its own; integration tests in `tests/integration/test_granular_pipeline.py` exercise the portfolio endpoint through the UI nginx proxy (`POST /api/pipeline/portfolio`)
- Verify tool discovery: `GET http://<host>:7002/tools` should return a JSON array with `portfolio_equities` and `portfolio_replace_symbol` entries
- Verify portfolio construction: `POST http://<host>:7002/tools/portfolio_equities` with `{"portfolio_value": 1000000, "qty_symbols": 5, "symbols_exclusion": []}` should return a JSON array of holdings with `symbol`, `quantity`, and `last_price` fields
- Debug endpoints `POST /tools/echo`, `/tools/echo2`, `/tools/post-text`, `/tools/post-json` are present in the source for development troubleshooting

## Related Patterns
- Orchestrator tool discovery and invocation (see architecture KB files for agent-orchestration patterns)
- Other tool servers in the same repo: `value_at_risk` (port 7001), `guidelines` (port 7003), `guardrails` (port 8000)
- Knative serverless deployment option via `serverless.enabled` Helm value (see deployment KB files)
