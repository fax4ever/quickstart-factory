---
name: gradio-ui
description: Gradio-based frontend for AI Quickstarts with async backend calls, CSS-only expandable UI, and OpenShift Route support
summary: "Gradio provides a Python-native frontend (no JavaScript) for AI Quickstarts, using httpx.AsyncClient for backend API calls with CSS-only expand/collapse via hidden checkbox + CSS sibling selectors in gr.HTML, and gr.Blocks with customized gr.themes.Soft forced to dark mode via head JS injection. Use when backend engineers need interactive web UIs without JavaScript expertise -- the single-approach pattern (from ansible-log-analysis on Python 3.12/UBI8, image quay.io/rh-ai-quickstart/alm-ui) builds with multi-stage uv (ghcr.io/astral-sh/uv:0.9.7, uv sync --no-dev) and deploys on port 7860 with Helm-managed OpenShift Route (edge TLS) or Kubernetes Ingress, HPA autoscaling 1-5 replicas at CPU 70%/memory 80%. Helm wires BACKEND_URL from either backendRouteHost (HTTPS Route) or global.servicesNames (internal ClusterIP http://<service>:8000), GRADIO_SERVER_NAME=0.0.0.0 for container binding, and liveness probe targets GET / on port 7860 with 30s initialDelaySeconds. Gradio sync handlers require manual asyncio.new_event_loop() per invocation with loop.close() in finally to avoid resource leaks; nginx ingress needs six WebSocket annotations (proxy-read-timeout, proxy-send-timeout, websocket-services, proxy-buffering, proxy-http-version, upgrade/connection) or real-time updates break; module-level global state (current_alerts_data etc.) breaks concurrent users across replicas; and markdown.markdown() with fenced_code/tables/nl2br extensions is required for solution HTML rendering."
metadata:
  type: component
tags:
  tech_stack: [gradio, python, httpx, markdown, uv]
  ai_pattern: []
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Gradio dashboard for log analysis with expandable cluster/log views and label filtering"
    approach: "A"
---

# Gradio UI

## Overview

Gradio provides a Python-native frontend for AI Quickstarts, allowing backend engineers to build interactive web interfaces without JavaScript. In the ansible-log-analysis quickstart it serves as the primary dashboard for browsing, filtering, and inspecting log alerts fetched from a FastAPI backend. This pattern is relevant to RHOAI deployments because Gradio apps require WebSocket-aware ingress/route configuration and connect to backend services via Helm-managed global service names.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 on `registry.access.redhat.com/ubi8/python-312`
- **Container image:** `quay.io/rh-ai-quickstart/alm-ui:latest`
- **Key dependencies:** gradio>=5.42.0, httpx>=0.27.0, markdown>=3.6, pandas>=2.0.0, python-dotenv>=1.1.0
- **Package manager:** uv (copied from `ghcr.io/astral-sh/uv:0.9.7` multi-stage)
- **Helm subchart:** `deploy/helm/ansible-log-monitor/charts/ui` (v0.1.0)

## Key Patterns

### Async Backend Communication via httpx

The UI uses `httpx.AsyncClient` for all backend calls rather than `requests`, which aligns with Gradio's async event loop. However, Gradio's synchronous event handlers require manual event loop management:

```python
# From services/ui/app.py — async fetch wrapped for sync Gradio handler
async def fetch_all_alerts() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BACKEND_URL}/grafana-alert/")
        response.raise_for_status()
        return response.json()

def on_expert_change(expert: str):
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        alerts = loop.run_until_complete(fetch_all_alerts())
        # ... process alerts
    finally:
        loop.close()
```

### CSS-Only Expandable UI (No JavaScript)

The UI implements expand/collapse functionality using hidden checkboxes and CSS sibling selectors, avoiding JavaScript entirely. This works within Gradio's `gr.HTML` component constraints:

```css
/* From services/ui/app.py — CSS-only toggle pattern */
input[type="checkbox"]:checked ~ .log-details-content {
    max-height: none !important;
    padding: 1.5rem !important;
    border-width: 2px !important;
}
input[type="checkbox"]:not(:checked) ~ label .toggle-text::before {
    content: "Click to expand details";
}
```

### Gradio Blocks with Dark Theme Configuration

The app uses `gr.Blocks` with a customized `gr.themes.Soft` theme and forces dark mode via JavaScript injection in the `head` parameter:

```python
# From services/ui/app.py — theme and dark-mode setup
with gr.Blocks(
    title="Ansible Logs Viewer",
    theme=gr.themes.Soft(
        primary_hue="blue",
        secondary_hue="slate",
        neutral_hue="slate",
        font=gr.themes.GoogleFont("Inter"),
        font_mono=gr.themes.GoogleFont("JetBrains Mono"),
    ).set(
        body_background_fill="*neutral_950",
        body_text_color="*neutral_200",
        block_background_fill="*neutral_900",
    ),
    css=custom_css,
    head=head_js,  # JS to auto-set ?__theme=dark
) as demo:
```

### Helm Backend URL Wiring via Global Service Names

The deployment template resolves the backend URL from either an explicit Route hostname or the Helm global service name, enabling both external and internal connectivity:

```yaml
# From charts/ui/templates/deployment.yaml
env:
  - name: BACKEND_URL
    {{- if .Values.backendRouteHost }}
    value: "https://{{ .Values.backendRouteHost }}"
    {{- else }}
    value: "http://{{ .Values.global.servicesNames.backend }}:8000"
    {{- end }}
```

The global service names are defined in `global-values.yaml`:

```yaml
# From deploy/helm/ansible-log-monitor/global-values.yaml
global:
  servicesNames:
    backend: "alm-backend"
    ui: "alm-ui"
```

### uv-Based Container Build

The Containerfile uses a multi-stage copy to get `uv` from its official image, avoiding pip entirely:

```dockerfile
# From services/ui/Containerfile
FROM registry.access.redhat.com/ubi8/python-312
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY app.py .
ENTRYPOINT ["python","app.py"]
```

## Configuration

- **Environment variables:**
  - `BACKEND_URL` — Full URL to the backend API (set by Helm, see wiring pattern above)
  - `GRADIO_SERVER_NAME` — Bind address, defaults to `0.0.0.0` for container use
  - `GRADIO_SERVER_PORT` — Listen port, defaults to `7860`
- **Config files:** None; all configuration is via environment variables
- **Helm values:**
  - `image.repository` / `image.tag` — Container image reference (`quay.io/rh-ai-quickstart/alm-ui:latest`)
  - `service.port` / `service.targetPort` — Both set to `7860`
  - `route.enabled` — Creates an OpenShift Route with edge TLS termination
  - `ingress.enabled` — Creates a Kubernetes Ingress with WebSocket annotations
  - `backendRouteHost` — When set, UI connects to backend via HTTPS Route instead of internal ClusterIP
  - `autoscaling.enabled` — HPA with CPU (70%) and memory (80%) targets, 1-5 replicas

## Known Gotchas

- **Manual async event loop in Gradio handlers:** The code creates a new `asyncio` event loop per handler invocation (`asyncio.new_event_loop()`) because Gradio's `change` callbacks are synchronous. This is visible in `on_expert_change` (line 199-269 of `app.py`) and `generate_clusters_html` (line 333-338). Forgetting to close the loop in a `finally` block would leak resources.
- **WebSocket proxy annotations required:** The Helm ingress values include six nginx annotations for WebSocket support (`proxy-read-timeout`, `proxy-send-timeout`, `websocket-services`, `proxy-buffering`, `proxy-http-version`, `upgrade`, `connection`). Without these, Gradio's real-time updates break behind an nginx ingress.
- **Global state for filtering:** The app uses module-level global variables (`current_alerts_data`, `current_category_alerts`, `current_view_mode`, etc.) to track filter state between Gradio event handlers. This pattern does not support concurrent users correctly in a multi-replica deployment.
- **Markdown rendering in solutions:** Step-by-step solution fields are rendered via `markdown.markdown()` with extensions `fenced_code`, `tables`, and `nl2br`, then injected as raw HTML into `gr.HTML`. This requires the `markdown` library as an explicit dependency.

## Testing Notes

- Verify the UI pod starts by checking liveness probe at `GET /` on port 7860 (configured in `values.yaml` with 30s initial delay)
- Confirm backend connectivity by selecting an expert class in the dropdown; a working connection shows log clusters
- Check the OpenShift Route is created: `oc get route <release>-ui` should show edge TLS termination
- If using ingress, verify WebSocket connectivity by watching for real-time Gradio updates without connection drops

## Related Patterns

- Backend API patterns: see `fastapi-backend.md`
