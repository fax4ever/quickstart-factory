---
name: lemonade-stand-app
description: "FastAPI chat app with FMS guardrails orchestrator integration, local regex pre-filtering, SSE streaming, and Prometheus metrics"
summary: "Solves building a guardrailed chat API layer using FastAPI that proxies user messages to the FMS guardrails orchestrator's /api/v2/chat/completions-detection endpoint via aiohttp SSE streaming, with split input detectors (HAP, language_detection, prompt_injection) and output detectors (HAP, regex_competitor, language_detection), plus local regex pre-filtering in 14 languages to reduce orchestrator load. Use when building a chat frontend that needs FMS guardrails orchestrator integration with SSE streaming, Prometheus guardrail metrics (guardrail_requests_total, guardrail_detections_total, guardrail_local_regex_blocks_total via AsyncMetricsCollector with ServiceMonitor at 3s scrape interval and x-source header for per-source differentiation), and configurable system prompts via ConfigMap volume mount at /system-prompt/prompt. Critical config: orchestrator URL built from GUARDRAILS_ORCHESTRATOR_SERVICE_SERVICE_HOST/PORT env vars with protocol selection (https for in-cluster or port 443/80, http for localhost); connection pool keepalive 30s internal vs 5s external to avoid HAProxy timeouts; Route annotations haproxy.router.openshift.io/timeout: 300s for SSE; VLLM_MODEL defaults to llama32 with API key from Secret lemonade-stand-secrets. Gotchas: SSL verification disabled (check_hostname=False, CERT_NONE) for in-cluster self-signed certs, duplicate SSE chunks require deduplication logic, zero-delay retry on empty SSE response before exponential backoff (100ms base), MAX_INPUT_CHARS hard-limited to 100 (demo constraint enforced server-side and HTML), and container must run as user 1001 with chmod -R g=u for OpenShift arbitrary UID convention."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, aiohttp, uvicorn, pydantic]
  ai_pattern: [guardrails, model-serving]
  platform: [openshift, kubernetes, vllm]
  data_layer: []
source_examples:
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "FastAPI chat backend with FMS guardrails orchestrator, local multilingual regex filtering, SSE streaming, and Prometheus guardrail metrics"
    approach: "A"
---

# Lemonade Stand App

## Overview

A FastAPI-based chat application that acts as the user-facing frontend and API layer for the lemonade-stand-assistant quickstart. It proxies user messages to the FMS (Foundation Model Stack) guardrails orchestrator for content safety detection (HAP, prompt injection, language filtering, regex-based topic restriction), streams LLM responses back via SSE, performs local regex pre-filtering to reduce orchestrator load, and exposes Prometheus-format metrics for guardrail detection counts. The app also serves an embedded HTML chat UI with markdown rendering and typing animation.

## Tech Stack & Dependencies

- **Runtime:** Python 3.11 on `python:3.11-slim`
- **Container image:** `quay.io/ckavili/lemon-fastapi:1.0.26`
- **Key dependencies:**
  - `fastapi>=0.104.0` -- ASGI web framework
  - `uvicorn[standard]>=0.24.0` -- ASGI server with uvloop + httptools
  - `aiohttp>=3.9.0` -- async HTTP client for SSE streaming from orchestrator
  - `pydantic>=2.0.0` -- request/response validation
- **Helm subchart:** None (standalone Helm templates in `chart/templates/lemonade-stand-app.yaml`)

## Key Patterns

### Guardrails Orchestrator Integration via aiohttp SSE

The app uses `aiohttp` (not `httpx`) to consume SSE streams from the FMS guardrails orchestrator. It connects to the orchestrator's `/api/v2/chat/completions-detection` endpoint, which wraps the LLM response with input/output guardrail detection. The URL is built dynamically based on whether the service is running in-cluster or externally.

```python
# From app_fastapi.py - URL detection logic
ORCHESTRATOR_HOST = os.getenv("GUARDRAILS_ORCHESTRATOR_SERVICE_SERVICE_HOST", "localhost")
ORCHESTRATOR_PORT = os.getenv("GUARDRAILS_ORCHESTRATOR_SERVICE_SERVICE_PORT", "8080")
IS_INTERNAL_SERVICE = ORCHESTRATOR_HOST not in ("localhost", "") and ORCHESTRATOR_PORT not in ("443", "80")

if ORCHESTRATOR_PORT in ("443", "80"):
    API_URL = f"https://{ORCHESTRATOR_HOST}/api/v2/chat/completions-detection"
elif IS_INTERNAL_SERVICE:
    API_URL = f"https://{ORCHESTRATOR_HOST}:{ORCHESTRATOR_PORT}/api/v2/chat/completions-detection"
else:
    API_URL = f"http://{ORCHESTRATOR_HOST}:{ORCHESTRATOR_PORT}/api/v2/chat/completions-detection"
```

### Local Regex Pre-filtering

Before sending requests to the orchestrator, the app performs local regex matching against a comprehensive set of compiled patterns covering fruit names in 14 languages (English, Turkish, Swedish, Finnish, Dutch, French, Spanish, German, Japanese, Russian, Italian, Polish, Chinese, Hindi). This reduces load on the orchestrator by catching obvious topic violations locally.

```python
# From app_fastapi.py - pre-compiled patterns for efficient matching
COMPILED_REGEX_PATTERNS = [re.compile(pattern) for pattern in ALL_REGEX_PATTERNS]

def check_regex_locally(text: str) -> bool:
    for pattern in COMPILED_REGEX_PATTERNS:
        if pattern.search(text):
            return True
    return False
```

The local regex only handles input-side detection. Output-side regex detection is delegated to the orchestrator via the `detectors.output.regex_competitor` field in the request payload.

### Split Input/Output Detector Configuration

The request payload to the orchestrator separates input and output detectors. Input detectors run HAP, language detection, and prompt injection (regex handled locally). Output detectors run HAP, regex competitor (to catch the LLM mentioning non-lemon fruits), and language detection.

```python
# From app_fastapi.py - detector configuration in request payload
"detectors": {
    "input": {
        "hap": {},
        "language_detection": {},
        "prompt_injection": {}
    },
    "output": {
        "hap": {},
        "regex_competitor": {
            "regex": ALL_REGEX_PATTERNS
        },
        "language_detection": {}
    }
}
```

### Async Metrics Collection with Prometheus Format

The app implements a custom `AsyncMetricsCollector` class using `asyncio.Lock` for thread-safe metric tracking. Metrics are exposed at `/metrics` in Prometheus text format with per-source and per-detector breakdowns. A `ServiceMonitor` resource is included in the Helm chart for OpenShift monitoring integration.

```python
# From app_fastapi.py - metrics collector tracks per-source, per-detector, per-direction
class AsyncMetricsCollector:
    DETECTOR_NAMES = ["hap", "regex_competitor", "prompt_injection", "language_detection"]

    async def get_prometheus_metrics(self) -> str:
        # Emits: guardrail_requests_total, guardrail_local_regex_blocks_total,
        #        guardrail_detections_total, guardrail_detections_by_detector,
        #        guardrail_detections_by_direction
```

### System Prompt via ConfigMap Volume Mount

The system prompt is loaded from a ConfigMap mounted at `/system-prompt/prompt` rather than hardcoded. The Helm template bundles the ConfigMap and Deployment together, allowing the prompt to be updated without rebuilding the container image.

```yaml
# From chart/templates/lemonade-stand-app.yaml
volumeMounts:
  - name: system-prompt
    mountPath: /system-prompt
    readOnly: true
volumes:
  - name: system-prompt
    configMap:
      name: lemonade-stand-system-prompt
      items:
        - key: prompt
          path: prompt
```

### Connection Pool Tuning for OpenShift Routes

The aiohttp session is configured differently depending on whether the app is connecting to an internal cluster service or through an external OpenShift route. Internal connections use longer keepalive (30s) while external route connections use short keepalive (5s) to avoid HAProxy timeout issues.

```python
# From app_fastapi.py - connection pool tuning
if IS_INTERNAL_SERVICE:
    connector = aiohttp.TCPConnector(
        limit=200, limit_per_host=100, ssl=ssl_context,
        keepalive_timeout=30,  # Longer keepalive - internal services are stable
        enable_cleanup_closed=True,
    )
else:
    connector = aiohttp.TCPConnector(
        limit=200, limit_per_host=100, ssl=ssl_context,
        keepalive_timeout=5,  # Short - OpenShift routes close connections quickly
        enable_cleanup_closed=True,
    )
```

### Embedded HTML Chat UI with Semantic Error Styling

The app serves a full-featured chat UI from `static/index.html` with a fallback inline HTML. The UI uses Grafana-aligned color variables and applies different visual styles per guardrail detector type (HAP = pink/red, prompt injection = purple, regex/topic = yellow, language = blue). It includes markdown rendering via marked.js, typing animation, character count enforcement, mobile-responsive layout, and a stop-streaming button.

```css
/* From static/index.html - semantic error colors per detector */
--nonlemon: #FCE957;        /* regex/topic violation */
--nonenglish: #8CA3EF;      /* language detection */
--jailbreak: #C48AE6;       /* prompt injection */
--swearing: #F86877;        /* HAP detection */
--blocked: #D6182D;         /* generic blocked */
```

## Configuration

- **Environment variables:**
  - `GUARDRAILS_ORCHESTRATOR_SERVICE_SERVICE_HOST` -- orchestrator hostname (follows Kubernetes service env var naming)
  - `GUARDRAILS_ORCHESTRATOR_SERVICE_SERVICE_PORT` -- orchestrator port (default `8080`)
  - `VLLM_MODEL` -- model name to pass to orchestrator (default `llama32`)
  - `VLLM_API_KEY` -- optional API key for the model endpoint, sourced from Secret `lemonade-stand-secrets`
  - `LOG_LEVEL` -- logging verbosity (default `INFO`)
- **Config files:**
  - `/system-prompt/prompt` -- system prompt mounted from ConfigMap
  - `static/index.html` -- embedded chat UI
- **Helm values:**
  - `model.name` -- model name passed to the Deployment env (default `llama32`)
  - `model.api_key` -- API key stored in Secret (default `fake`)
  - `metrics.dashboard.enabled` -- whether to install an OpenShift monitoring dashboard (requires cluster-admin)

## Known Gotchas

- **SSL verification disabled for orchestrator connection:** The app creates an SSL context with `check_hostname = False` and `verify_mode = ssl.CERT_NONE` because the guardrails orchestrator uses self-signed certificates in-cluster. This is set up in the `lifespan` context manager and applied to the `aiohttp.TCPConnector`.
- **Duplicate chunk deduplication:** The SSE parser includes logic to skip duplicate content chunks -- a comment in the code notes "upstream orchestrator sometimes sends overlapping chunks" (`app_fastapi.py`). This strips leading whitespace and checks if the full response already ends with the incoming chunk.
- **MAX_INPUT_CHARS set to 100:** User messages are hard-limited to 100 characters (enforced both server-side and in the HTML input `maxlength`). This is a deliberate demo constraint, not a technical limitation.
- **OpenShift Route annotations for SSE:** The Route template includes `haproxy.router.openshift.io/timeout: 300s` and `haproxy.router.openshift.io/timeout-tunnel: 300s` to prevent HAProxy from terminating long-lived SSE connections prematurely.
- **Retry with zero-delay on empty response:** If the first attempt to the orchestrator returns an empty SSE stream, the app retries immediately (zero delay) on the assumption the connection was stale, then uses exponential backoff (100ms base) for subsequent retries.
- **Non-root user with OpenShift group permissions:** The Containerfile creates user `1001` and applies `chmod -R g=u` to the application directory, following the OpenShift arbitrary UID convention where the container runs as an arbitrary user in the root group.

## Testing Notes

- Verify the `/health` endpoint returns `{"status": "healthy"}` -- liveness and readiness probes depend on this
- Check `/metrics` returns valid Prometheus text format with `guardrail_requests_total`, `guardrail_detections_total`, and `guardrail_local_regex_blocks_total` counters
- The `ServiceMonitor` scrapes metrics every 3 seconds (very aggressive; suitable for demo dashboards)
- To test guardrail blocking, send messages containing fruit names in any of the 14 supported languages -- local regex should block before reaching the orchestrator
- The `x-source` request header allows differentiating metrics by source (defaults to `audience`)

## Related Patterns

- `guardrails-orchestrator.md` -- the FMS orchestrator this app connects to
- `prompt-injection-detector.md` -- one of the detectors invoked by the orchestrator
- `hate-and-profanity-detector.md` -- HAP detector used for content safety
- `regex-detector.md` -- regex-based topic restriction detector
- `fastapi-backend.md` -- other FastAPI backend patterns (agent dispatch, not guardrails chat)
