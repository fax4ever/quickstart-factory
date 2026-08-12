---
name: risk-tool-agent
description: "Flask-based VaR tool microservice exposing JSON Schema tool definitions for agentic orchestration"
summary: "A Flask microservice calculating parametric (variance-covariance) VaR for US equity portfolios, operating as an agentic tool server that advertises JSON Schema function definitions at GET /tools and accepts portfolio risk invocations at POST /tools/value_at_risk using scipy norm.ppf over a pandas covariance matrix of 1-year daily returns from yfinance. Use when building multi-tool agentic architectures needing decoupled financial computation — the orchestrator discovers tools via the TOOL_SERVERS env var (comma-separated service URLs like http://risk:7001), and Knative deployment (serverless.enabled: true) enables scale-to-zero with configurable minScale/maxScale/concurrency/timeoutSeconds. The endpoint normalizes LLM-generated confidence values across int/float/string formats and uses ast.literal_eval() to parse stringified portfolio arrays; the Helm readiness probe targets /tools so pods report ready only when Flask serves tool definitions, running on UBI 10 python-312-minimal (quay.io/ikatav/portfolio-manager-agent:risk) with --only-binary=:all: for numpy/scipy. Yahoo Finance fetches live prices on every request with no caching layer — network outages or rate limits cause direct failures with no fallback — and PYTHONUNBUFFERED=1 is required for real-time container log output."
metadata:
  type: component
tags:
  tech_stack: [flask, python, pandas, scipy, yfinance, numpy]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Value-at-Risk tool agent using variance-covariance method with live Yahoo Finance data"
    approach: "A"
---

# Risk Tool Agent

## Overview

A lightweight Flask microservice that calculates Value at Risk (VaR) for US equity portfolios using the parametric (variance-covariance) method. It operates as a tool server in an agentic architecture: the orchestrator discovers available tools via a `/tools` endpoint that returns JSON Schema definitions, then invokes them by posting to `/tools/value_at_risk`. This pattern decouples financial computation from LLM orchestration, allowing tools to be developed and scaled independently.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 on UBI 10 minimal (`registry.access.redhat.com/ubi10/python-312-minimal`)
- **Container image:** `quay.io/ikatav/portfolio-manager-agent:risk`
- **Key dependencies:** Flask 3.1.2, pandas 2.3.3, scipy 1.17.1, numpy 2.3.4, yfinance 0.2.66
- **Helm subchart:** None (standalone templates in `deploy/helm/templates/deployment-risk.yaml`)

## Key Patterns

### Tool Discovery via /tools Endpoint

Each tool server advertises its capabilities as a JSON array of function definitions at `GET /tools`. The orchestrator fetches these at startup to build the tool registry for the LLM.

```python
# tools/value_at_risk/src/app.py
TOOLS = [
    {
        "type": "function",
        "name": "value_at_risk",
        "description": "Calculate value at risk (VaR) for a specified portfolio.",
        "parameters": {
            "type": "object",
            "properties": {
                "confidence": {
                    "type": "integer",
                    "description": "Confidence interval (i.e. 90, 95 or 99)",
                    "minimum": 50,
                    "maximum": 99,
                },
                "portfolio": {
                    "type": "array",
                    "items": { ... },
                },
            },
        },
    }
]

@app.get("/tools")
def list_tools():
    return jsonify(TOOLS)
```

### Flexible Confidence Input Handling

The endpoint normalizes confidence values whether they arrive as integers (95), floats (0.95), or strings, allowing resilient handling of LLM-generated arguments.

```python
# tools/value_at_risk/src/app.py
confidence = request_data.get("confidence", 0.99)
if isinstance(confidence, str):
    confidence = int(confidence)
if 1 < confidence < 100:
    confidence = round(confidence / 100, 2)
```

### Variance-Covariance VaR Calculation

Uses the parametric method with scipy's `norm.ppf` to compute VaR from portfolio weights, a covariance matrix of daily returns, and the inverse CDF of the normal distribution.

```python
# tools/value_at_risk/src/value_at_risk.py
def _parametricVaR(self, confidence, portfolio_value, mean, std_dev):
    var_pct = norm.ppf(1 - confidence, mean, std_dev)
    var = portfolio_value * var_pct * -1
    return var
```

### Live Market Data from Yahoo Finance

The `MarketData` class fetches one year of daily closing prices per symbol via `yfinance`. Historical prices are assembled into a pandas DataFrame used to compute daily percentage changes and the covariance matrix.

```python
# tools/value_at_risk/src/market_data.py
def _fetch_yahoo_data(self, symbol, start, end):
    data = yf.download(
        symbol, start=start, end=end, multi_level_index=False, progress=False
    )
    return data
```

### Multi-Tool Orchestrator Wiring

The orchestrator discovers tool servers via the `TOOL_SERVERS` environment variable, which lists comma-separated base URLs. Each tool server is independent and addressable by its service name.

```yaml
# deploy/local/compose.yml (orchestrator service)
environment:
  TOOL_SERVERS: >-
    http://risk:7001, http://portfolio:7002, http://guidelines:7003
```

## Configuration

- **Environment variables:**
  - `PORT` (default `7001`): TCP port the Flask server listens on
  - `PYTHONUNBUFFERED` (set to `1`): Ensures real-time log output in containers
- **Config files:** None; the tool is self-contained with no external config files
- **Helm values:**
  - `image.tags.risk`: Image tag for the risk container (default: `risk`)
  - `serverless.enabled`: When `true`, deploys as a Knative Service instead of a Deployment
  - `serverless.minScale` / `maxScale` / `concurrency` / `timeoutSeconds`: Knative autoscaling parameters

## Known Gotchas

- **String portfolio argument from LLMs:** The endpoint uses `ast.literal_eval()` to parse the portfolio when the LLM sends it as a string rather than a JSON array (`tools/value_at_risk/src/app.py`, line 107). This handles a real-world issue where LLM tool-call arguments arrive as stringified JSON.
- **Yahoo Finance as live dependency:** The tool fetches real-time and historical prices from Yahoo Finance on every request (`market_data.py` and `portfolio.py`). There is no caching layer, so network issues or Yahoo rate limits will cause failures. A commented-out section in `portfolio.py` references an alternative data grid approach that was not implemented.
- **Binary-only installs for numeric libraries:** The Dockerfile pins `numpy`, `scipy`, and `scikit-learn` with `--only-binary=:all:` to avoid compiling C extensions on the minimal UBI image (`Dockerfile`, line 11-13).
- **Readiness probe on /tools:** The Helm deployment uses `GET /tools` as the readiness probe path (`deployment-risk.yaml`, line 23-26), which means the pod is only considered ready once Flask is serving and the tool definitions are loadable.

## Testing Notes

- Verify the tool responds to `GET /tools` with a valid JSON array of function definitions
- Post a sample portfolio to `/tools/value_at_risk` and confirm a numeric `valueAtRisk` is returned
- Confirm the orchestrator's `TOOL_SERVERS` environment variable includes the risk service URL
- When deploying with `serverless.enabled: true`, verify the Knative Service scales from zero and responds within `timeoutSeconds`

## Related Patterns

- `flask-backend.md` -- Flask application component pattern
- `nemo-guardrails.md` -- Guardrails layer in the same quickstart architecture
- `minio.md` -- MinIO used for model storage in the same deployment
