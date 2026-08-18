---
name: copilot-ui
description: SvelteKit 2 chat UI with SSE streaming, Vega-Lite chart rendering, runtime config injection via ConfigMap, and nginx static hosting
summary: "Provides a SvelteKit 2 chat interface for AI copilot agents, consuming SSE streaming with 8 typed ProgressEvent variants (llm_thinking, llm_content_delta, tool_call, tool_result, timing_summary, final_response, error) and rendering Vega-Lite charts inline from markdown code blocks detected by vega.github.io/schema/vega-lite URL. Use when building a static SPA chat frontend needing real-time SSE streaming, runtime backend URL injection via ConfigMap (not build-time env vars), and interactive data visualization -- built with Svelte 5 runes, adapter-static, pnpm (engine-strict), served by nginx-unprivileged:alpine on port 8080 (USER 1001) from a multi-stage node:20-alpine Containerfile with Helm subchart at helm/copilot-ui/. Critical config: backend URL injected at runtime through Helm-generated ConfigMap mounting /config.js (sets window.__RUNTIME_CONFIG__) into nginx html directory, VITE_COPILOT_BACKEND_URL is local-dev-only fallback; retryFetchSSE provides 7 retries with 1s-5s exponential backoff for pod startup resilience; policy upload adapts per provider_mode (mcp_direct uploads immediately, llama_stack warns about agent recreation). Gotchas: nginx must set Cache-Control no-cache on /index.html and /config.js to prevent stale backend URLs after Helm upgrades, OpenShift Route requires cookie affinity (haproxy.router.openshift.io/disable_cookies: \"false\") for session stickiness across the default 2 replicas, reasoning toggle is disabled for llama_stack provider, and duplicate submissions are guarded by isStreaming state check."
metadata:
  type: component
tags:
  tech_stack: [svelte, sveltekit, typescript, vite, nginx, pnpm, vega-lite, marked, highlight-js]
  ai_pattern: [agents, mcp]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "SvelteKit 2 chat frontend with SSE streaming to copilot-backend, Vega-Lite data visualization, policy upload, and runtime config via ConfigMap-mounted /config.js"
    approach: "A"
---

# Copilot UI

## Overview

A SvelteKit 2 single-page application providing a chat interface for AI copilot agents. Built with Svelte 5 runes (`$state`, `$effect`, `$props`), the UI connects to a backend via SSE streaming for real-time progress updates including LLM thinking, tool calls, and timing summaries. In production the app is compiled to static HTML/JS via `adapter-static` and served by `nginxinc/nginx-unprivileged:alpine` on port 8080, with backend URL injected at runtime through a ConfigMap-mounted `/config.js` file rather than build-time environment variables.

## Tech Stack & Dependencies

- **Runtime:** Svelte 5 / SvelteKit 2, TypeScript ~5.9, Vite 7, Node 20 (build only)
- **Container image:** Multi-stage build -- `node:20-alpine` builder, `nginxinc/nginx-unprivileged:alpine` runtime (port 8080, `USER 1001`)
- **Key dependencies:** `marked` ^12.0 (markdown rendering), `highlight.js` ^11.9 (SQL syntax highlighting), `vega` ^5.30 / `vega-lite` ^5.21 / `vega-embed` ^6.26 (data visualization charts)
- **Package manager:** pnpm with `engine-strict=true`
- **Helm subchart:** Standalone chart at `helm/copilot-ui/` (Chart.yaml `apiVersion: v2`, `type: application`, `version: 0.1.0`)

## Key Patterns

### Runtime Config Injection via ConfigMap

The backend URL is injected at runtime (not baked at build time) through a `/config.js` file that sets `window.__RUNTIME_CONFIG__`. The HTML loads this script before the SvelteKit app boots, and a TypeScript config loader reads it with a fallback for local dev:

```html
<!-- app.html -->
<head>
  <!-- Load runtime config before app starts -->
  <script src="/config.js"></script>
  %sveltekit.head%
</head>
```

```typescript
// src/lib/config.ts
export function getConfig(): RuntimeConfig {
  if (typeof window !== 'undefined' && window.__RUNTIME_CONFIG__) {
    config = window.__RUNTIME_CONFIG__;
    return config;
  }
  // Fallback to build-time env vars for local development
  config = {
    backendUrl: import.meta.env.VITE_COPILOT_BACKEND_URL || 'http://localhost:8080'
  };
  return config;
}
```

The Helm chart generates the ConfigMap and volume-mounts it into the nginx html directory:

```yaml
# templates/configmap.yaml
data:
  config.js: |
    window.__RUNTIME_CONFIG__ = {
      backendUrl: {{ .Values.backend.url | quote }}
    };
```

```yaml
# templates/deployment.yaml (excerpt)
volumeMounts:
- name: config
  mountPath: /usr/share/nginx/html/config.js
  subPath: config.js
```

### SSE Streaming with Typed Progress Events

The chat interface consumes Server-Sent Events from `POST /query/stream` with a discriminated union of event types. Each event type triggers specific UI updates -- thinking content streams into collapsible reasoning panels, tool calls display with timing, and `llm_content_delta` events stream response text in real-time:

```typescript
// src/lib/types/chat.ts
export type ProgressEvent =
  | { type: 'iteration_start'; iteration: number; max_iterations: number }
  | { type: 'llm_thinking'; content: string; iteration: number; llm_time: number }
  | { type: 'llm_content_delta'; content: string; iteration?: number }
  | { type: 'tool_call'; tool_name: string; arguments: Record<string, any>; iteration: number }
  | { type: 'tool_result'; tool_name: string; result: string; mcp_time: number; iteration: number }
  | { type: 'timing_summary'; total_time: number; llm_time: number; mcp_time: number; ... }
  | { type: 'final_response'; content: string; tool_calls: ToolCall[]; conversation_id?: string }
  | { type: 'error'; message: string; traceback?: string };
```

The stream is parsed manually from the fetch response body reader, splitting on `\n\n` boundaries and extracting `data: ` prefixed JSON:

```typescript
// ChatInterface.svelte (SSE parsing loop)
const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '';
while (true) {
  const { done, value } = await reader.read();
  if (value) buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split('\n\n');
  buffer = lines.pop() || '';
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const event: ProgressEvent = JSON.parse(line.slice(6));
      // switch on event.type...
    }
  }
  if (done) break;
}
```

### Retry with Exponential Backoff for SSE Connections

A `retryFetchSSE` utility wraps fetch with up to 7 retries, exponential backoff (1s initial, 5s max, 2x multiplier), covering ~27 seconds of retry attempts. This handles pod startup/restart scenarios on OpenShift where the backend may not be immediately available:

```typescript
// src/lib/utils/retryFetch.ts
export async function retryFetchSSE(
  url: string,
  init?: RequestInit,
  onRetry?: (attempt: number, error: Error) => void
): Promise<Response> {
  return retryFetch(url, init, {
    maxRetries: 7,
    initialDelayMs: 1000,
    maxDelayMs: 5000,
    backoffMultiplier: 2,
    retryableStatuses: [503, 502, 504],
    onRetry
  });
}
```

### Vega-Lite Chart Rendering in Chat Messages

The `MessageBubble` component extracts Vega-Lite specifications from markdown code blocks (both explicit ` ```vega-lite ` and ` ```json ` blocks containing the Vega-Lite schema URL) and renders them as interactive charts using `vega-embed`. Specs are replaced with HTML comment placeholders during markdown processing, then Svelte components render the charts in-place:

```typescript
// MessageBubble.svelte (excerpt)
const vegaLiteRegex = /```\s*vega-lite\s*\n([\s\S]*?)```/gi;
const jsonVegaRegex = /```\s*json\s*\n([\s\S]*?vega\.github\.io\/schema\/vega-lite[\s\S]*?)```/gi;
```

```svelte
<!-- VegaLiteChart.svelte -->
<script lang="ts">
  import embed from 'vega-embed';
  onMount(async () => {
    const parsedSpec = typeof spec === 'string' ? JSON.parse(spec) : spec;
    await embed(chartContainer, parsedSpec, {
      actions: { export: true, source: false, compiled: false, editor: false },
      theme: 'latimes'
    });
  });
</script>
```

### Policy Upload with Provider-Aware Confirmation

The `PolicyUpload` component supports uploading `.txt` governance policy files. It adapts its behavior based on the backend's `provider_mode`: in `mcp_direct` mode, policies upload immediately; in `llama_stack` mode, a confirmation dialog warns that uploading recreates the agent and deletes the current conversation. The component fetches provider info from `GET /provider/info` on mount:

```typescript
// PolicyUpload.svelte (provider-aware upload logic)
if (requiresRestart) {
  pendingFileContent = text;
  showConfirmDialog = true;
} else {
  await uploadPolicy(text);
}
```

### Static Build with adapter-static and nginx SPA Config

SvelteKit is configured with `adapter-static` to produce a static build with `fallback: 'index.html'` for SPA routing. The Containerfile embeds a custom nginx config that serves the static files and disables caching for `index.html` and `config.js`:

```javascript
// svelte.config.js
adapter: adapter({
  pages: 'build',
  assets: 'build',
  fallback: 'index.html',
  precompress: false,
  strict: true
})
```

```dockerfile
# Containerfile (nginx config excerpt)
RUN echo 'server { \
    listen 8080; \
    root /usr/share/nginx/html; \
    location / { try_files $uri $uri/ /index.html; } \
    location = /index.html { add_header Cache-Control "no-cache, no-store, must-revalidate"; } \
    location = /config.js { add_header Cache-Control "no-cache, no-store, must-revalidate"; } \
}' > /etc/nginx/conf.d/default.conf
```

## Configuration

- **Environment variables:**
  - `VITE_COPILOT_BACKEND_URL` -- Backend URL for local development only (build-time, via `.env`); ignored in production where runtime config is used
- **Config files:**
  - `svelte.config.js` -- adapter-static configuration
  - `vite.config.ts` -- Vitest browser testing with Playwright provider, split into client (browser) and server (node) test projects
- **Helm values:**
  - `backend.url` -- Injected into the ConfigMap as the runtime backend URL
  - `replicaCount: 2` -- Default two replicas for availability
  - `route.enabled: true` -- Creates an OpenShift Route with TLS edge termination
  - `route.host: ""` -- Auto-generated by OpenShift when empty

## Known Gotchas

- **Runtime config vs build-time config:** The `VITE_COPILOT_BACKEND_URL` env var only works during local development. In production, the backend URL must be set via `backend.url` in Helm values, which generates a ConfigMap mounted as `/config.js`. The `app.html` file loads `/config.js` via a `<script>` tag before SvelteKit boots, so the config is available synchronously.
- **Cache-Control for config.js:** The nginx config explicitly disables caching for both `index.html` and `/config.js` with `Cache-Control: no-cache, no-store, must-revalidate`. Without this, browsers may cache stale backend URLs after a Helm upgrade changes `backend.url`.
- **OpenShift Route cookie affinity:** The Route template enables cookie-based session affinity (`haproxy.router.openshift.io/disable_cookies: 'false'` and `cookie_name: 'copilot-ui-route'`) for load balancing across UI replicas, and the fetch calls use `credentials: 'include'` to ensure session cookies are sent.
- **Reasoning toggle disabled for Llama Stack:** The reasoning toggle button in the header is disabled when `providerMode === 'llama_stack'` since Llama Stack does not support extended thinking. The tooltip changes to explain this restriction.
- **Duplicate submission guard:** The `handleSendMessage` function checks `isStreaming` state to prevent duplicate SSE requests if the user double-clicks send or presses Enter twice while a response is in flight.
- **Vega-Lite JSON block detection:** The `MessageBubble` component handles LLM responses that use ` ```json ` instead of ` ```vega-lite ` code fences by checking for the Vega-Lite schema URL (`vega.github.io/schema/vega-lite`) in the content.

## Testing Notes

- **Unit tests:** Vitest with browser-based Svelte component testing via `@vitest/browser-playwright` (Chromium headless). Tests split into `client` project (`.svelte.{test,spec}.ts` files) and `server` project (plain `.{test,spec}.ts` files).
- **E2E tests:** Playwright with `npm run build && npm run preview` as the web server on port 4173.
- **Verify after deployment:** Confirm the OpenShift Route returns HTTP 200, check that `/config.js` contains the correct `backendUrl` pointing to the copilot-backend Route, and test that the chat sends a query and receives SSE streaming events.

## Related Patterns

- Backend streaming endpoint that produces the SSE events consumed by this UI
- Helm ConfigMap pattern for runtime configuration injection
- OpenShift Route with cookie-based session affinity for stateful frontend connections
