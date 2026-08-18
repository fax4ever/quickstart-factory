---
name: openshift-console-plugin
description: "OpenShift Console dynamic plugin with dual-mode deployment (console plugin + standalone React UI) for AI observability"
summary: "Embeds AI observability dashboards (vLLM metrics, GPU monitoring, AI chat) into the OpenShift admin console's Observe section using the dynamic plugin SDK, with a dual-build webpack architecture producing both a ConsolePlugin CR mode (ConsoleRemotePlugin, served via console proxy at /api/proxy/plugin/aiobs-console-plugin/mcp/mcp) and a standalone React UI mode (HtmlWebpackPlugin + nginx SPA), selected at runtime by getDeploymentMode() in src/shared/config.ts via pathname and OPENSHIFT_CONSOLE_PLUGIN_API detection. Use when AI observability needs native console integration with admin-perspective navigation registered via console-extensions.json under Observe > AI Observability -- the standalone React UI mode serves as the alternative for development or non-console deployments, sharing core code but with separate webpack configs, tsconfig files, output directories (dist/plugin/ vs dist/react-ui/), and Dockerfiles. Helm chart creates a ConsolePlugin CR with MCP proxy alias on port 9443 (TLS via service-serving cert from /var/cert/), a post-install Job auto-patches consoles.operator.openshift.io/cluster for plugin registration, and all backend calls use stateless JSON-RPC 2.0 via callMcpTool with runtime config fetched from MCP /config endpoint using promise caching to prevent race conditions; GPU detection queries DCGM and Intel Gaudi metrics, caches 5 minutes, and conditionally hides vLLM/Hardware Accelerators tabs when gpuAvailable===false. gpuAvailable must initialize as undefined (not boolean) to prevent UI flash on non-GPU clusters; plugin name must match exactly across Helm values.yaml, package.json#consolePlugin.name, and proxy path or MCP calls return 404; React 17 is pinned via yarn resolutions for @openshift-console/dynamic-plugin-sdk compatibility; two separate Dockerfiles exist (plugin expects pre-built assets, react-ui builds in-container); dev mode auto-injects sessionStorage credentials into MCP calls via provider regex detection (skipping add_model_to_config, save_provider_credentials, delete_secret); and NODE_OPTIONS=\"--max-old-space-size=4096\" is required to prevent webpack OOM."
metadata:
  type: component
tags:
  tech_stack: [react, patternfly, typescript, webpack, nginx, nodejs]
  ai_pattern: [model-serving, observability, multimodal]
  platform: [openshift, rhoai, vllm]
  data_layer: []
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "Console plugin with MCP-backed AI chat, vLLM/OpenShift metrics dashboards, and GPU-aware UI"
    approach: "A"
---

# OpenShift Console Plugin

## Overview

An OpenShift Console dynamic plugin that embeds AI observability dashboards directly into the OpenShift admin console under the Observe section. The component uses a dual-build architecture: a console plugin mode served as a `ConsolePlugin` CR, and a standalone React UI mode that runs as an independent SPA with its own nginx container. It communicates with a backend MCP server for metrics retrieval, AI-powered analysis, and chat functionality.

## Tech Stack & Dependencies
- **Runtime:** Node 24, React 17, TypeScript 5.2+
- **Container image (plugin):** `registry.access.redhat.com/ubi9/nginx-120:latest` (pre-built assets copied in)
- **Container image (react-ui):** `node:24` builder stage, then `ubi9/nginx-120` runtime
- **Key dependencies:** `@openshift-console/dynamic-plugin-sdk` ^1.6.0, `@openshift-console/dynamic-plugin-sdk-webpack` ^1.3.0, PatternFly 5 (`@patternfly/react-core` ^5.0.0, `@patternfly/react-charts` ^7.0.0), `react-markdown` ^8.0.7
- **Helm subchart:** `deploy/helm/openshift-console-plugin` (standalone chart, v0.1.0)

## Key Patterns

### Dual Deployment Mode (Console Plugin vs Standalone React UI)

The codebase produces two separate webpack builds from shared core code. The plugin mode uses `ConsoleRemotePlugin` with no explicit entry points; the React UI mode uses a standard `HtmlWebpackPlugin` entry. A runtime mode detector in `src/shared/config.ts` determines which proxy path to use for backend calls.

```typescript
// src/shared/config.ts — deployment mode detection
export const getDeploymentMode = (): 'plugin' | 'react-ui' => {
  if (typeof window !== 'undefined') {
    const isPluginContext = window.location.pathname.startsWith('/observe/ai-observability');
    const hasConsoleAPI = !!(window as any).OPENSHIFT_CONSOLE_PLUGIN_API;
    if (isPluginContext || hasConsoleAPI) {
      return 'plugin';
    }
  }
  return 'react-ui';
};
```

The webpack configs isolate the two builds via separate output directories (`dist/plugin` and `dist/react-ui`) and the plugin build explicitly excludes `src/react-ui/`:

```typescript
// config/webpack.plugin.ts — excludes react-ui sources
rules: [{
  test: /\.(jsx?|tsx?)$/,
  exclude: [/\/node_modules\//, /\/src\/react-ui\//],
  use: [{ loader: 'ts-loader', options: { configFile: '../tsconfig.plugin.json' } }],
}]
```

### ConsolePlugin CR with MCP Proxy

The Helm chart creates a `ConsolePlugin` CR that registers the plugin with the OpenShift console and defines a proxy alias for the MCP backend server. This proxy lets the plugin make `fetch()` calls through the console's built-in proxy mechanism without requiring direct network access to the backend.

```yaml
# templates/consoleplugin.yaml — proxy definition
spec:
  backend:
    type: Service
    service:
      name: {{ template "openshift-console-plugin.name" . }}
      namespace: {{ .Release.Namespace }}
      port: {{ .Values.plugin.port }}
      basePath: {{ .Values.plugin.basePath }}
  proxy:
    - alias: mcp
      authorization: None
      endpoint:
        type: Service
        service:
          name: {{ .Values.mcpServer.serviceName }}
          namespace: {{ default .Release.Namespace .Values.mcpServer.namespace }}
          port: {{ .Values.mcpServer.port }}
```

The frontend calls this proxy via `/api/proxy/plugin/aiobs-console-plugin/mcp/mcp` in plugin mode.

### Automatic Console Plugin Registration via Helm Hook

A post-install/post-upgrade Job patches the `consoles.operator.openshift.io/cluster` resource to add the plugin to the enabled plugins list, eliminating manual console configuration:

```yaml
# templates/patch-consoles-job.yaml
annotations:
  helm.sh/hook: post-install,post-upgrade
  helm.sh/hook-delete-policy: before-hook-creation
# ...
command:
  - /bin/bash
  - -c
  - |
    existingPlugins=$(oc get consoles.operator.openshift.io cluster -o json | jq -c '.spec.plugins // []')
    mergedPlugins=$(jq --argjson existingPlugins "${existingPlugins}" --argjson consolePlugin '["{{ template "openshift-console-plugin.name" . }}"]' -c -n '$existingPlugins + $consolePlugin | unique')
    patchedPlugins=$(jq --argjson mergedPlugins $mergedPlugins -n -c '{ "spec": { "plugins": $mergedPlugins } }')
    oc patch consoles.operator.openshift.io cluster --patch $patchedPlugins --type=merge
```

### GPU-Aware Dynamic UI

The UI conditionally renders tabs and features based on GPU/accelerator availability detected at runtime. GPU detection queries device metrics (DCGM for NVIDIA, Intel Gaudi) and caches the result in browser storage for 5 minutes:

```typescript
// src/core/services/mcpClient.ts — GPU detection pattern
const [dcgmResp, intelResp] = await Promise.all([
  fetchOpenShiftMetrics('Device (DCGM)', 'cluster_wide', '15m'),
  fetchOpenShiftMetrics('Device (Intel)', 'cluster_wide', '15m'),
]);
const nvidiaCount = dcgmMetrics['GPU Count']?.latest_value ?? 0;
const intelCount = intelMetrics['Device Count']?.latest_value ?? 0;
const hasGpu = nvidiaCount > 0 || intelCount > 0;
```

GPU state starts as `undefined` (loading) to prevent briefly showing GPU tabs on non-GPU clusters. When `gpuAvailable === false`, the vLLM Metrics and Hardware Accelerators tabs are hidden entirely.

### Stateless MCP Client via JSON-RPC

All backend communication goes through a single `callMcpTool` function that sends JSON-RPC 2.0 requests to the MCP server. It handles three response formats (structuredContent string, structuredContent array, and content array) and automatically injects dev-mode credentials:

```typescript
// src/core/services/mcpClient.ts — MCP call pattern
const response = await fetch(MCP_SERVER_URL, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
    'mcp-session-id': 'browser-session',
  },
  body: JSON.stringify({
    jsonrpc: '2.0',
    method: 'tools/call',
    params: { name: toolName, arguments: enhancedArgs },
    id: ++requestId,
  }),
});
```

### Runtime Config from MCP Server

Instead of environment variables baked into the container image, the plugin fetches runtime configuration (e.g., `devMode` flag) from the MCP server's `/config` endpoint on first load. Promise caching prevents race conditions when multiple components initialize simultaneously:

```typescript
// src/core/services/runtimeConfig.ts
let configPromise: Promise<RuntimeConfig> | null = null;
export async function fetchRuntimeConfig(): Promise<RuntimeConfig> {
  if (cachedConfig) return cachedConfig;
  if (configPromise) return configPromise;
  configPromise = (async () => { /* fetch logic */ })();
  // ...
}
```

### Dev Mode Credential Management

When `devMode` is enabled (fetched from MCP server), API keys are stored in `sessionStorage` (cleared on tab close) instead of Kubernetes secrets. The MCP client auto-injects these credentials into tool calls, detecting the AI provider from model ID patterns:

```typescript
// src/core/services/mcpClient.ts — provider detection
const patterns: Record<string, RegExp> = {
  openai: /^(openai\/|gpt-)/,
  anthropic: /^(anthropic\/|claude-)/,
  google: /^(google\/|gemini-)/,
  meta: /^(meta\/|llama-)/,
  maas: /^maas\//,
};
```

### Console Extensions (Navigation Registration)

The plugin registers under the admin perspective's "observe" section using `console.navigation/href` and `console.page/route` extension types in `console-extensions.json`:

```json
{
  "type": "console.navigation/href",
  "properties": {
    "id": "ai-observability",
    "perspective": "admin",
    "section": "observe",
    "name": "%plugin__aiobs-console-plugin~AI Observability%",
    "href": "/observe/ai-observability"
  }
}
```

The exposed modules are declared in `package.json` under `consolePlugin.exposedModules`.

## Configuration
- **Environment variables:** `NODE_ENV` (build mode), `NODE_OPTIONS="--max-old-space-size=4096"` (required for build)
- **Config files:** `console-extensions.json` (plugin route/nav registration), `nginx/default.conf` (React UI proxy config), `package.json#consolePlugin` (plugin metadata and exposed modules)
- **Helm values:**
  - `plugin.name`: Must match `consolePlugin.name` in `package.json` (default: `aiobs-console-plugin`)
  - `plugin.image.repository` / `plugin.image.tag`: Container image reference
  - `plugin.port`: Default `9443` (TLS via service-serving cert)
  - `mcpServer.serviceName`: Kubernetes service name of the MCP backend (default: `aiobs-mcp-server-svc`)
  - `mcpServer.port`: MCP server port (default: `8085`)
  - `plugin.jobs.patchConsoles.enabled`: Auto-register plugin with console (default: `true`)

## Known Gotchas
- **GPU state must start as `undefined`, not `true` or `false`**: The `AIObservabilityPage` explicitly initializes `gpuAvailable` as `undefined` and includes a code comment: "CRITICAL: Start with undefined (loading state), not true — This prevents briefly showing vLLM tab on non-GPU clusters". Setting it to a boolean default causes a UI flash.
- **Plugin name mismatch breaks proxy routing**: The `plugin.name` in Helm `values.yaml`, `consolePlugin.name` in `package.json`, and the proxy path in `config.ts` (`/api/proxy/plugin/aiobs-console-plugin/mcp/mcp`) must all use the same plugin name. A mismatch causes 404s on MCP calls.
- **Two Dockerfiles for two deployment modes**: `Dockerfile.plugin` expects pre-built assets (`dist/plugin/`) to already exist (built by Makefile before `docker build`). `Dockerfile.react-ui` runs the build inside the container. Confusing which to use for which mode is a common mistake.
- **React 17 pinned with resolutions**: The project pins React 17 via yarn resolutions to maintain compatibility with `@openshift-console/dynamic-plugin-sdk`, which does not support React 18. The `resolutions` block in `package.json` is required.
- **nginx TLS for plugin mode**: The Helm-deployed plugin serves over TLS on port 9443 using OpenShift's service-serving certificate (auto-generated secret). The configmap-injected `nginx.conf` configures `ssl_certificate` and `ssl_certificate_key` from `/var/cert/`. The React UI mode does not use TLS.
- **Dev mode credential injection is automatic**: In dev mode, `injectDevCredentials` runs on every MCP tool call. It modifies arguments transparently, which can be confusing when debugging. Certain tools (`add_model_to_config`, `save_provider_credentials`, `delete_secret`) are explicitly skipped.
- **`NODE_OPTIONS="--max-old-space-size=4096"` required for builds**: Both `package.json` scripts and `Dockerfile.react-ui` set this. Without it, the webpack build OOMs on default Node heap limits.

## Testing Notes
- Unit tests use Jest with `@testing-library/react` and `jest-environment-jsdom` -- run via `yarn test`
- Integration tests use Cypress (`integration-tests/`) for E2E testing within the console
- DevContainer setup (`.devcontainer/`) provides a local development environment with a console container and plugin container sharing a network. Requires `dev.env` with `OC_URL`, `OC_USER`, `OC_PASS` for cluster login
- After deployment, verify the plugin appears in the OpenShift console under Observe > AI Observability
- Check that the patcher Job completed: `oc get jobs -l app.kubernetes.io/name=aiobs-console-plugin`

## Related Patterns
- MCP server backend (paired component providing the `/mcp`, `/config`, `/health` endpoints)
- Helm deployment pattern with ConsolePlugin CR and patcher Job
- PatternFly 5 dashboard patterns with conditional GPU-aware rendering
