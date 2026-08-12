---
name: react-frontend
description: React frontend patterns for AI Quickstarts -- PatternFly/SSE, shadcn+Tailwind/WebSocket, or CRA+serve video monitoring
summary: "Provides three React frontend patterns for AI Quickstarts -- Approach A (React 18 + PatternFly 6 + @patternfly/chatbot) for chatbot-first UIs with SSE streaming via requestAnimationFrame batching, TanStack Router/Query/Form, OAuth redirect, and single-container deployment baked into FastAPI; Approach B (React 19 + shadcn/ui + Tailwind CSS 4 + Radix) for multi-persona enterprise apps with WebSocket JSON protocol streaming, Keycloak OIDC with PKCE and dev-mode role headers, Zod-validated layered API (Component->Hook->TanStack Query->Service->Schema), atomic design with Storybook 8, pnpm monorepo, and separate nginx container with window.__RUNTIME_CONFIG__ injection; Approach C (React 17 + CRA JavaScript + serve) for MJPEG video monitoring with SSE cross-tab config sync, setInterval polling with stale detection guards, feedNonce cache-buster for stream switching, ConfigMap-mounted window.__ENV__ with protocol auto-upgrade, and Helm-deployed separate container. Choose A for chatbot apps needing PatternFly design system, SSE rAF-batched streaming, TanStack Form admin panels, any OAuth provider, and single-container deploy -- choose B for multi-role domain-rich UIs needing Keycloak OIDC, role-based persona routing (ROLE_HOME mapping), WebSocket chat sidebar, Zod schema validation, and two-container nginx+API deploy -- choose C for video/multimodal monitoring needing MJPEG feeds via <img> tags, polling-based detection, SSE config sync, plain JavaScript frontend, and Helm-deployed serve+ConfigMap container. Critical patterns: A and B use TanStack Router file-based routing with code-splitting; A models chat content as SimpleContentItem discriminated union (output_text, reasoning, tool_call, graph_node, input_image) with LlamaStack isToolExecutionType()/isStructuralItemType() type guards; B injects Keycloak/company config at container start via nginx location returning JavaScript snippet with envsubst-substituted values; C uses ConfigMap env.js with fallback chain (runtime -> REACT_APP_API_URL -> location.origin/api) and natural language alert rules with CRUD management. Gotchas: Vite requires watch.usePolling:true in containers; A needs NODE_OPTIONS=--max-old-space-size=512 for builds, strips reasoning items on [DONE], raises chunkSizeWarningLimit to 2000, requires flushPendingUpdates() with confirmation modal on session switch during streaming, and excludes fetchSessionsData from useEffect deps to prevent infinite loops; B requires WebSocket upgrade map in nginx.conf (not conf.d/ where envsubst mangles $ variables), passes JWT as WebSocket query parameter (MVP trade-off), needs OpenShift arbitrary UID chmod/chgrp on nginx dirs, downgrades Vite 7 UNRESOLVED_IMPORT errors for pnpm hoisted deps, and uses deprecated ROPC grant for demo convenience; C requires --openssl-legacy-provider for Node 18+, must avoid <img> remounting to prevent MJPEG connection stacking, disables ESLint during Docker build, and polls inference readiness every 200ms until OVMS model processes first frame."
metadata:
  type: component
tags:
  tech_stack: [react, patternfly, typescript, vite, tanstack-router, tanstack-query, tanstack-form, tailwindcss, shadcn-ui, radix-ui, zod, keycloak, storybook, vitest, pnpm, javascript, create-react-app, axios, react-markdown, serve]
  ai_pattern: [agents, rag, mcp, multimodal, model-serving]
  platform: [openshift, kserve]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "PatternFly Chatbot UI with SSE streaming for LlamaStack agents, role-based routing, admin config panels"
    approach: "A"
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "React 19 + shadcn/ui + Tailwind CSS frontend with WebSocket chat streaming, Keycloak OIDC auth, role-based persona routing, separate nginx container"
    approach: "B"
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "React 17 CRA JavaScript frontend with MJPEG video feed, SSE config sync, polling-based detection results, serve static server, Helm-deployed separate container with ConfigMap env injection"
    approach: "C"
---

# React Frontend

## Overview

A React 18 single-page application providing a chatbot interface for AI virtual agents backed by LlamaStack. Built with PatternFly 6 (including the `@patternfly/chatbot` extension), TanStack Router for file-based routing with code splitting, and TanStack Query for server-state management. In production the frontend is compiled to static assets and served by the FastAPI backend from a single container; for local development a dedicated Vite dev server with API proxying runs in its own container.

## Tech Stack & Dependencies

- **Runtime:** React 18, TypeScript ~5.7, Vite 6 with SWC plugin
- **Container image:** `registry.access.redhat.com/ubi9/nodejs-22:latest` (dev), multi-stage with `ubi9/nodejs-22` builder (prod)
- **Key dependencies:** `@patternfly/chatbot` ^6.3, `@patternfly/react-core` ^6.3, `@tanstack/react-router` ^1.119, `@tanstack/react-query` ^5.75, `@tanstack/react-form` ^1.9, `rehype-raw`, `rehype-sanitize`, `remark-gfm`
- **Helm subchart:** None (frontend is baked into the backend container for cluster deployment via multi-stage Containerfile)

## Key Patterns

### File-Based Routing with TanStack Router

Routes are organized under `src/routes/` with automatic code-splitting enabled by the Vite plugin. The route tree is auto-generated (`routeTree.gen.ts`). Layout nesting is used for auth guards and admin layouts:

```
src/routes/
  __root.tsx             # QueryClientProvider + UserProvider
  oauth.sign_in.tsx      # Public login page
  _protected/
    route.tsx            # Auth guard (redirects to OAuth if no user)
    index.tsx            # Main chat page
    config/
      route.tsx          # Non-admin config layout (profile only)
      profile.tsx
    _admin/
      route.tsx          # Admin role check
      config/
        route.tsx        # Admin sidebar with Agents, KB, MCP, Models, Users
        agents.tsx
        knowledge-bases.tsx
        mcp-servers.tsx
        models.tsx
        users.tsx
```

The `_protected/route.tsx` guard checks user context and redirects to OAuth sign-in:

```tsx
function ProtectedPages() {
  const { currentUser, isLoading, error } = useCurrentUser();
  if (error || !currentUser) {
    const redirectUrl = `/oauth/sign_in?redirect=${encodeURIComponent(window.location.href)}`;
    window.location.href = redirectUrl;
    return <div>Redirecting to Login...</div>;
  }
  return <Outlet />;
}
```

### SSE-Based Chat Streaming with requestAnimationFrame Batching

The `useChat` hook in `src/hooks/useChat.ts` implements Server-Sent Events streaming against the backend `/api/v1/chat` endpoint. It uses `requestAnimationFrame`-based batching to reduce React re-renders during fast token streaming:

```typescript
const scheduleUpdateRef = useRef((updateFn: (prev: ChatMessage[]) => ChatMessage[]) => {
  pendingUpdatesRef.current.push(updateFn);
  if (rafIdRef.current === null) {
    rafIdRef.current = requestAnimationFrame(() => {
      const updates = pendingUpdatesRef.current;
      pendingUpdatesRef.current = [];
      rafIdRef.current = null;
      setMessages((prev) => {
        let current = prev;
        for (const update of updates) {
          current = update(current);
        }
        return current;
      });
    });
  }
});
```

Stream events are parsed from SSE `data:` lines and dispatched to typed handler functions in `useChat.helpers.ts`: `handleReasoning`, `handleToolCall`, `handleResponse`, `handleError`, `handleNodeStarted`, `handleNodeCompleted`, `handleTokenUsage`.

### Rich Content Types in Chat Messages

The chat system uses a discriminated union `SimpleContentItem` to model different content types within a single message (defined in `src/types/chat.ts`):

```typescript
export type SimpleContentItem =
  | TextContentItem       // { type: 'input_text', text }
  | OutputTextContentItem // { type: 'output_text', text, id? }
  | ReasoningContentItem  // { type: 'reasoning', text, isComplete? }
  | ToolCallContentItem   // { type: 'tool_call', name, status, output?, error? }
  | ImageContentItem      // { type: 'input_image', image_url }
  | GraphNodeContentItem; // { type: 'graph_node', node_id, label, status }
```

Expandable UI sections render reasoning traces, tool call details (with arguments/output), and graph node progress using PatternFly's `ExpandableSection` and `ProgressStepper` components (see `src/components/ExpandableContent.tsx`).

### PatternFly Chatbot Integration

The main chat UI in `src/components/chat.tsx` uses `@patternfly/chatbot` components: `Chatbot`, `ChatbotContent`, `ChatbotConversationHistoryNav`, `ChatbotHeader`, `ChatbotFooter`, `MessageBar`, `MessageBox`, `Message`. The conversation history drawer supports session search, creation, deletion, and switching with a safety modal when a response is in progress.

### Vite Proxy for Backend API

The Vite dev server proxies `/api` requests to the backend, enabling frontend-only development:

```typescript
server: {
  host: '0.0.0.0',
  port: 5173,
  watch: { usePolling: true, interval: 1000 },
  proxy: {
    '/api': {
      target: process.env.VITE_API_BASE_URL || 'http://backend:8000',
      changeOrigin: true,
    },
  },
},
```

### Dark Theme Toggle with localStorage Persistence

The masthead component (`src/components/masthead.tsx`) implements PatternFly v6 dark theme toggling by adding/removing the `pf-v6-theme-dark` CSS class on the `<html>` element with localStorage persistence under the key `app-theme`.

### LlamaStack Streaming Constants Library

The `src/lib/llamastack/constants.ts` module defines typed constants for LlamaStack streaming event types (e.g., `response.output_text.delta`, `response.reasoning_text.delta`, `response.mcp_call.arguments.done`) and output item types (e.g., `mcp_call`, `function_call`, `web_search_call`). It includes type guards `isToolExecutionType()` and `isStructuralItemType()` for distinguishing UI-renderable tool calls from structural items.

## Configuration

- **Environment variables:**
  - `VITE_API_BASE_URL` - Backend API URL; defaults to empty string for relative paths in production, `http://localhost:8000` in `.env` for local dev
- **Config files:**
  - `src/config/api.ts` - Centralizes all API endpoint paths (agents, chat, sessions, users, models, tools, knowledge bases, attachments, shields, MCP servers, providers)
  - `src/config/samplingParametersConfig.ts` - Defines LLM sampling parameter UI fields (temperature, top_p, top_k, max_tokens, repetition_penalty) with conditional visibility based on sampling strategy
  - `.prettierrc.json` - Prettier config: 100 char width, single quotes, trailing commas
  - `eslint.config.js` - Flat ESLint config with TypeScript type-checked rules, React hooks, JSX accessibility, React Refresh, and Prettier integration
- **Helm values:** N/A (frontend is embedded into backend container at build time)

## Known Gotchas

- **Polling required for container file watching:** Vite's `watch.usePolling` is set to `true` with a 1-second interval in `vite.config.ts` because native filesystem events do not propagate into containers (comment: "Enable polling for container file watching").
- **Chunk size warning limit raised:** `build.chunkSizeWarningLimit` is set to `2000` in `vite.config.ts`, indicating the PatternFly + chatbot bundle is large and the default 500kB warning was noisy.
- **Reasoning items stripped on stream completion:** The `useChat` hook filters out `reasoning` content items from the assistant message when `[DONE]` is received, meaning reasoning traces are transient during streaming but removed from the final rendered message.
- **Session switch safety during streaming:** The chat component shows a confirmation modal (`isSwitchWarningOpen`) when the user attempts to switch sessions while a response is being generated, and calls `flushPendingUpdates()` before switching to avoid losing batched state updates.
- **OAuth redirect is a full page navigation:** The `_protected/route.tsx` guard uses `window.location.href` assignment (not React Router navigation) to redirect to OAuth sign-in, which causes a full page reload. This is intentional because the OAuth flow is external.
- **Frontend build needs NODE_OPTIONS memory limit:** The production Containerfile sets `ENV NODE_OPTIONS=--max-old-space-size=512` before running `npm run build` to prevent OOM during TypeScript compilation + Vite bundling.
- **fetchSessionsData dependency suppression:** In `chat.tsx`, `fetchSessionsData` is intentionally excluded from the `useEffect` dependency array for `selectedAgent` changes (with an eslint-disable comment) to prevent infinite re-render loops.

## Testing Notes

- Run `npm run format:check` and `npm run lint` to validate code style and linting
- The `npm run build` command runs `tsc -b` before Vite build, catching TypeScript errors early
- Husky pre-commit hooks with `lint-staged` enforce formatting and linting on commit
- Verify the Vite proxy connects to the backend by checking chat functionality at `http://localhost:5173`
- After cluster deployment, verify the frontend loads from the backend's static file serving (the built frontend is copied to `backend/public/` in the multi-stage Containerfile)

## Related Patterns

- Architecture: LlamaStack agent orchestration (agents, MCP tools, knowledge bases, shields)
- Deployment: Multi-stage Containerfile baking frontend into backend
- Component: FastAPI backend (serves both API and static frontend assets)

---

## Approach B: shadcn/ui + Tailwind CSS with WebSocket Chat and Keycloak OIDC (from multi-agent-loan-origination)

### When to Use

Use when the quickstart needs a multi-persona application UI beyond a single chatbot -- role-specific dashboards, domain-specific data views, and chat as a sidebar complement rather than the primary interface. Also preferred when Keycloak OIDC is the auth provider and the frontend is deployed as a separate container behind nginx rather than baked into the backend.

### Differences from Approach A

| Concern | Approach A | Approach B |
|---------|-----------|-----------|
| UI framework | PatternFly 6 + @patternfly/chatbot | shadcn/ui (Radix primitives) + Tailwind CSS 4 |
| Streaming | SSE with requestAnimationFrame batching | WebSocket with JSON message protocol |
| Deployment | Frontend baked into backend container | Separate nginx:alpine container serving static assets |
| Auth | OAuth redirect via window.location.href | Keycloak OIDC with JWT + dev-mode role headers |
| Component org | Flat components/ directory | Atomic design (atoms/molecules/organisms) |
| Form handling | TanStack Form for admin panels | No form library (minimal form needs) |
| Schema validation | None at service layer | Zod schemas validate all API responses |
| Component dev | None | Storybook 8 |
| React version | React 18 | React 19 |
| Package manager | npm | pnpm (monorepo workspaces) |
| Theme | PatternFly pf-v6-theme-dark class | CSS custom properties with ThemeProvider context |

### Tech Stack & Dependencies

- **Runtime:** React 19, TypeScript ~5.9, Vite 7 with @vitejs/plugin-react
- **Container image:** `node:20-alpine` (builder), `docker.io/nginx:alpine` (runtime)
- **Key dependencies:** `@tanstack/react-router` ^1.31, `@tanstack/react-query` ^5.32, `@radix-ui/*` (dialog, dropdown-menu, label, separator, slot, tooltip, avatar), `keycloak-js` ^26.2, `zod` ^3.22, `tailwindcss` ^4.1, `class-variance-authority` ^0.7, `lucide-react` ^0.378
- **Helm subchart:** None documented (UI is a standalone container)

### Key Patterns

#### Layered API Integration (Component -> Hook -> TanStack Query -> Service -> Zod Schema)

Components never call services directly. Each domain entity follows a strict layering pattern with Zod validation at the service boundary:

```typescript
// schemas/applications.ts -- Zod schemas define the contract
export const ApplicationResponseSchema = z.object({
    id: z.number(),
    stage: ApplicationStageSchema,
    loan_amount: z.coerce.number().nullable().optional(),
    // ...
});

// services/applications.ts -- service parses response through schema
export async function fetchApplications(params?: ApplicationsQueryParams): Promise<ApplicationListResponse> {
    const data = await apiGet<unknown>(`/api/applications/${qs ? `?${qs}` : ''}`);
    return ApplicationListResponseSchema.parse(data);
}

// hooks/use-applications.ts -- TanStack Query wrapper
export function useApplications() {
    return useQuery({ queryKey: ['applications'], queryFn: () => fetchApplications() });
}
```

#### WebSocket Chat with JSON Message Protocol

Chat uses WebSocket instead of SSE. The `connectChat` function in `src/lib/ws.ts` establishes a WebSocket connection with auth token or dev-mode identity passed as query parameters. Messages follow a typed JSON protocol:

```typescript
// Client -> Server
{ "type": "message", "content": "user text" }

// Server -> Client
{ "type": "tool_start", "tool_name": "...", "tool_input": {...} }
{ "type": "tool_result", "tool_name": "...", "tool_output": ... }
{ "type": "done", "content": "complete response text" }
{ "type": "error", "content": "error description" }
```

The `useChat` hook manages WebSocket lifecycle, message history loading, connection state tracking, and pending message queuing when the socket is still connecting.

#### Keycloak OIDC with Dev-Mode Fallback

The `AuthProvider` in `src/contexts/auth-context.tsx` supports two auth modes determined by whether `KEYCLOAK_URL` is set. In Keycloak mode it uses `keycloak-js` with `check-sso` initialization and PKCE (`pkceMethod: 'S256'`). In dev mode it uses a hardcoded `DEV_USERS` map with role-based headers:

```typescript
// Keycloak config: runtime config (container) takes precedence over Vite env (local dev)
const _rtc = (window as unknown as Record<string, unknown>).__RUNTIME_CONFIG__;
const KEYCLOAK_URL = _rtc?.KEYCLOAK_URL || import.meta.env.VITE_KEYCLOAK_URL || undefined;
const IS_KEYCLOAK_ENABLED = !!KEYCLOAK_URL;

// Dev mode headers sent instead of JWT
return {
    'X-Dev-Role': user.role,
    'X-Dev-User-Id': user.user_id,
    'X-Dev-User-Email': user.email,
    'X-Dev-User-Name': user.name,
};
```

#### Nginx Reverse Proxy with Runtime Config Injection

The Containerfile uses a multi-stage build: `node:20-alpine` builds the Vite SPA, then `nginx:alpine` serves static assets and proxies `/api/` to the backend. Runtime configuration (Keycloak URLs, company name) is injected at container start via an nginx location that returns a JavaScript snippet:

```nginx
location = /runtime-config.js {
    default_type application/javascript;
    return 200 'window.__RUNTIME_CONFIG__={KEYCLOAK_URL:"${KEYCLOAK_EXTERNAL}",KEYCLOAK_REALM:"${KEYCLOAK_REALM}",KEYCLOAK_CLIENT_ID:"${KEYCLOAK_CLIENT_ID}",COMPANY_NAME:"${COMPANY_NAME}",AGENT_NAME:"${AGENT_NAME}"};';
}
```

WebSocket upgrade is handled via an nginx `map` block injected into `nginx.conf` at build time via `sed`:

```dockerfile
RUN sed -i '/http {/a \    map $http_upgrade $connection_upgrade {\n        default upgrade;\n        ""      close;\n    }' /etc/nginx/nginx.conf
```

#### Role-Based Routing with Persona Guards

TanStack Router file-based routing uses a `_authenticated` layout route that checks auth state, redirects unauthenticated users to sign-in, and enforces role-based route access:

```typescript
const ROLE_HOME: Record<UserRole, string> = {
    prospect: '/sign-in',
    borrower: '/borrower',
    loan_officer: '/loan-officer',
    underwriter: '/underwriter',
    ceo: '/executive',
};

function isRouteAllowed(pathname: string, role: UserRole): boolean {
    if (pathname.startsWith('/borrower')) return role === 'borrower';
    if (pathname.startsWith('/loan-officer')) return role === 'loan_officer';
    // ...
}
```

#### Atomic Design Component Organization

Components follow atomic design: `atoms/` (button, badge, card, input, label, tooltip, separator, skeleton, chat-bubble, dropdown-menu), `molecules/` (affordability-form), `organisms/` (chat-panel, chat-sidebar, product-grid). Each component optionally has co-located `.stories.tsx` and `.test.tsx` files. shadcn/ui configuration uses `components.json` with "new-york" style and Radix primitives aliased to `@/components/atoms`.

### Configuration

- **Environment variables:**
  - `API_UPSTREAM` - Backend host:port for nginx reverse proxy (default: `mortgage-ai-api:8000`)
  - `KEYCLOAK_EXTERNAL` - Browser-reachable Keycloak URL (empty = auth disabled in UI)
  - `KEYCLOAK_REALM` - Keycloak realm name (default: `mortgage-ai`)
  - `KEYCLOAK_CLIENT_ID` - Keycloak client ID (default: `mortgage-ai-ui`)
  - `COMPANY_NAME` - Displayed company name (default: `Acme FinTech Company`)
  - `AGENT_NAME` - Optional agent display name
- **Config files:**
  - `components.json` - shadcn/ui configuration (style: "new-york", icon library: lucide, aliases)
  - `vite.config.ts` - Vite 7 with TanStack Router plugin, Tailwind CSS plugin, path aliases, and dev proxy
  - `vitest.config.ts` - Vitest with jsdom environment and React plugin
  - `.storybook/` - Storybook 8 configuration
- **Helm values:** Not applicable (standalone container)

### Known Gotchas

- **Vite 7 unresolved import workaround:** Vite 7 treats unresolved-import warnings as errors by default. In pnpm workspaces, transitive deps (e.g., `@radix-ui` sub-packages) are hoisted to root `node_modules/` but not symlinked into each workspace package. The `vite.config.ts` includes a custom `onLog` handler to downgrade `UNRESOLVED_IMPORT` errors back to warnings (comment in source: "Vite 7 treats unresolved-import warnings as errors by default").
- **OpenShift arbitrary UID compatibility:** The Containerfile explicitly sets `chmod -R g+rwx` and `chgrp -R 0` on nginx directories (`/var/cache/nginx`, `/var/log/nginx`, `/etc/nginx/conf.d`, `/var/run/nginx`) and rewrites the PID path so the container runs under OpenShift's arbitrary UID without root.
- **WebSocket upgrade map must be in nginx.conf, not conf.d/:** The `$http_upgrade` / `$connection_upgrade` variables are injected into `nginx.conf` via `sed` rather than placed in `conf.d/` because `envsubst` (used by the official nginx image entrypoint) would mangle the `$` variables (comment: "NOT in conf.d/ where envsubst would mangle the $http_upgrade / $connection_upgrade variables").
- **JWT in WebSocket query string:** The WebSocket API does not support custom headers, so the JWT token is passed as a query parameter. A source comment notes: "JWT in query string is an accepted MVP trade-off. For production, use a short-lived ticket token exchanged via REST, or send the JWT as the first WS message."
- **ROPC used for MVP demo convenience:** The sign-in flow uses Keycloak's Resource Owner Password Credentials (direct access) grant for demo convenience. Source comment: "ROPC is deprecated in OAuth 2.1. For production, switch to Authorization Code + PKCE flow (already configured on the client)."
- **Runtime config loaded via script tag:** `index.html` includes `<script src="/runtime-config.js"></script>` before the module entry point. In development, this returns 404 (no nginx) and the auth context falls back to Vite env vars. In production, nginx serves the runtime config with envsubst-substituted values.

### Testing Notes

- Run `pnpm --filter ui test` (Vitest with jsdom) for unit tests
- Run `pnpm --filter ui lint` and `pnpm --filter ui format:check` for code quality
- Run `pnpm --filter ui type-check` for TypeScript validation
- Storybook available at port 6006 via `pnpm --filter ui dev:storybook`
- Verify WebSocket chat connectivity at `http://localhost:3000` (Vite proxies `/api` to backend at port 8000)

### Related Patterns

- Component: Keycloak (identity management, OIDC)
- Component: FastAPI backend (WebSocket chat endpoints, REST API)
- Deployment: nginx reverse proxy with envsubst runtime config

---

## Approach C: CRA + serve with MJPEG Video Monitoring and Polling (from multimodal-compliance-monitor)

### When to Use

Use when the quickstart is a real-time video monitoring or multimodal compliance application where the primary interface is a live video feed with detection overlays, a chat assistant as a secondary feature, and dynamic configuration of video sources and OVMS model endpoints. Preferred when the frontend is lightweight JavaScript (no TypeScript), uses Create React App, and deploys as a separate container serving pre-built static assets via `serve`.

### Differences from Approach A

| Concern | Approach A | Approach C |
|---------|-----------|-----------|
| Language | TypeScript | JavaScript (plain) |
| Build tooling | Vite 6 + SWC | Create React App (react-scripts 4) |
| UI framework | PatternFly 6 + @patternfly/chatbot | Plain CSS (no component library) |
| Primary UI | Chatbot-first | MJPEG video feed with detection panels |
| Streaming | SSE for chat token streaming | MJPEG `<img>` for video; SSE (EventSource) for cross-tab config sync |
| Data fetching | TanStack Query | Direct axios calls with `setInterval` polling |
| Static server | Frontend baked into FastAPI backend | `serve` npm package in its own container |
| React version | React 18 | React 17 |
| Routing | TanStack Router (file-based) | React Router v6 (two routes) |
| Runtime config | Vite env vars | `window.__ENV__` via ConfigMap-mounted `env.js` |
| Helm deployment | None (baked into backend) | Separate Deployment + Service + ConfigMap |

### Tech Stack & Dependencies

- **Runtime:** React 17, JavaScript (ES2020), Create React App (react-scripts 4.0.3)
- **Container image:** `registry.access.redhat.com/ubi9/nodejs-18:1-62` (single-stage build + `serve`)
- **Key dependencies:** `axios` ^0.21, `react-router-dom` ^6.30, `react-markdown` ^8.0
- **Helm subchart:** None (uses standalone Helm templates in `deploy/helm/ppe-compliance-monitor/templates/frontend-*.yaml`)

### Key Patterns

#### MJPEG Video Feed via `<img>` Tag

The video feed is rendered as a standard `<img>` element pointing at the backend's `/video_feed` MJPEG endpoint. The `VideoPlayer` component avoids remounting the `<img>` on source switches (which would stack open HTTP connections) and instead clears `src` on the existing DOM node:

```jsx
// app/frontend/src/components/VideoPlayer.js
useLayoutEffect(() => {
  if (!hasSource) {
    setInferenceReady(false);
    return;
  }
  /* Abort prior multipart response: same <img> node + new src cancels the old fetch */
  if (imgRef.current) {
    imgRef.current.removeAttribute('src');
  }
  setInferenceReady(false);
  setFeedNonce((n) => n + 1);
}, [hasSource, activeConfigId]);
```

A `feedNonce` counter is appended to the URL as a cache-buster to force the browser to open a fresh MJPEG stream on each source switch.

#### SSE for Cross-Tab Active Config Sync

The Dashboard component subscribes to Server-Sent Events at `/active_config/events` so all browser tabs update when any user switches the active video source:

```jsx
// app/frontend/src/app.js
useEffect(() => {
  const eventSource = new EventSource(`${API_URL}/active_config/events`);
  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    setSelectedConfigId(data.active_config_id);
    setActiveConfigId(data.active_config_id);
  };
  eventSource.onerror = (err) => {
    console.error('SSE connection error:', err);
    // EventSource automatically reconnects, no action needed
  };
  return () => eventSource.close();
}, []);
```

#### Polling-Based Detection Results

The `PPEDescription` component polls `/latest_info` every 5 seconds to get the latest detection description, safety trend summaries, and alert results. There is no WebSocket or SSE for detection data -- polling is used for simplicity:

```jsx
// app/frontend/src/components/PPEDescription.js
useEffect(() => {
  if (!activeConfigId) return undefined;
  const fetchLatestInfo = async () => {
    const response = await axios.get(`${API_URL}/latest_info`);
    const data = response.data;
    if (data.active_config_id !== activeConfigId) return;
    setDescription(data.description);
    setSummaries((prev) => [
      { text: data.summary, isCurrent: true },
      ...prev.slice(0, 2).map(s => ({ ...s, isCurrent: false })),
    ]);
    setAlerts(Array.isArray(data.alerts) ? data.alerts : []);
  };
  fetchLatestInfo();
  const intervalId = setInterval(fetchLatestInfo, 5000);
  return () => clearInterval(intervalId);
}, [activeConfigId]);
```

#### Runtime Configuration via `window.__ENV__` and ConfigMap

Runtime configuration is injected via a `public/env.js` script loaded before the React app. In local development, this file contains empty defaults. On Kubernetes, a ConfigMap mounts the file with the actual API URL:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/frontend-configmap.yaml
data:
  env.js: |
    window.__ENV__ = { API_URL: {{ .Values.frontend.apiUrl | default "/api" | quote }} };
```

The `config.js` module reads from `window.__ENV__` with fallback chain: runtime config -> `REACT_APP_API_URL` env var -> `window.location.origin + /api` -> `http://localhost:8888`:

```javascript
// app/frontend/src/config.js
const runtimeConfig = window.__ENV__ || {};
const configuredApiUrl = normalizeApiUrl(
  runtimeConfig.API_URL || process.env.REACT_APP_API_URL
);
export const API_URL =
  configuredApiUrl ||
  `${window.location.origin}/api` ||
  'http://localhost:8888';
```

#### Protocol Auto-Upgrade (HTTP to HTTPS)

The `normalizeApiUrl` function in `config.js` automatically upgrades `http://` URLs to `https://` when the page is served over HTTPS (but not for localhost), preventing mixed-content browser errors:

```javascript
// app/frontend/src/config.js
if (
  window.location.protocol === 'https:' &&
  value.startsWith('http://') &&
  !value.includes('localhost') &&
  !value.includes('127.0.0.1')
) {
  return value.replace(/^http:\/\//, 'https://');
}
```

#### Chat Assistant with Session Management

The `ChatBot` component implements a conversational chat sidebar that sends the current detection description as context with each question. Sessions are managed client-side with random IDs and reset when the active video source changes:

```jsx
// app/frontend/src/components/ChatBot.js
const response = await axios.post(`${API_URL}/chat`, {
  question,
  description,          // Current detection context
  session_id: sessionIdRef.current,
  app_config_id: activeConfigId,
});
```

#### Natural Language Alert Rules with CRUD Management

The `AlertPanel` component (used in `ConfigPage`) provides full CRUD for alert rules defined in plain English. Alerts have severity levels (low/medium/high) and display results with violation counts. The panel polls every 5 seconds to refresh alert status:

```jsx
// app/frontend/src/components/AlertPanel.js
await axios.post(`${API_URL}/alerts`, {
  app_config_id: configId,
  rule,                  // Plain English alert rule
  severity: alertSeverity,
});
```

#### Three-Column Dashboard Layout

The main dashboard uses a three-column CSS layout: a left sidebar for video source selection (RTSP dropdown or MP4 thumbnails), a center column for the live video feed with detection results, and a right sidebar for the chat assistant.

### Configuration

- **Environment variables:**
  - `REACT_APP_API_URL` - Backend API URL (build-time, via CRA env convention)
  - `FRONTEND_API_URL` - Runtime API URL for podman-compose (injected into `env.js` at container start)
- **Config files:**
  - `public/env.js` - Runtime config injected via `window.__ENV__` object
  - `public/index.html` - Loads Font Awesome 5 via CDN, loads `env.js` before React app
- **Helm values:**
  - `frontend.replicas` - Number of frontend pod replicas (default: 1)
  - `frontend.port` - Container port (default: 3000)
  - `frontend.apiUrl` - API URL injected into ConfigMap env.js (default: `/api`)
  - `frontend.image.repository` - Image name (default: `ppe-compliance-monitor-frontend`)
  - `frontend.image.tag` - Image tag (default: `latest`)
  - `frontend.image.pullPolicy` - Pull policy (default: `Always`)

### Known Gotchas

- **OpenSSL legacy provider required:** Both `start` and `build` scripts pass `--openssl-legacy-provider` to `react-scripts` because CRA 4 / webpack 4 uses a hashing algorithm removed in newer Node.js OpenSSL versions. Without this flag, the build fails with `ERR_OSSL_EVP_UNSUPPORTED` on Node 18+.
- **MJPEG connection stacking on rapid source switches:** The `VideoPlayer` component comment warns against using React `key` to remount the `<img>` element: "remounting created a NEW stream without reliably closing the old one, so rapid thumbnail switches stacked many /video_feed connections." Instead, it clears `src` on the existing element via `imgRef.current.removeAttribute('src')`.
- **ESLint disabled during Docker build:** The Dockerfile sets `ENV DISABLE_ESLINT_PLUGIN=true` before `npm run build` to prevent lint errors from failing the container build.
- **Stale detection guard:** The `PPEDescription` polling callback checks `data.active_config_id !== activeConfigId` and returns early, preventing stale detection results from a previous source from rendering after a source switch.
- **Video inference readiness polling:** The `VideoPlayer` component polls `/latest_info` every 200ms checking `inference_ready` to show a "Loading model..." overlay until the OVMS model has processed its first frame. The interval self-clears once ready.
- **Podman-compose env.js override:** In the podman-compose setup, the frontend container's command rewrites `env.js` at container start using `printf` and the `FRONTEND_API_URL` env var, overriding the build-time default before `serve` starts.
- **`@babel/plugin-proposal-private-property-in-object` pinned:** Added as a devDependency to suppress a CRA 4 deprecation warning that would otherwise emit noisy console output during `npm install`.

### Testing Notes

- Run `npm test` (Jest with react-scripts) for unit tests
- Verify the frontend loads at `http://localhost:3000` after `make local-build-up`
- Check that selecting a video source shows the MJPEG feed and detection results update every 5 seconds
- After cluster deployment, verify the ConfigMap-mounted `env.js` is served correctly by checking browser console for `API_URL` value
- Verify SSE config sync by opening two browser tabs and switching the video source in one

### Related Patterns

- Component: FastAPI backend (serves `/video_feed` MJPEG stream, `/latest_info` detection results, `/chat` endpoint, `/active_config/events` SSE)
- Component: OVMS model server (object detection model inference)
- Deployment: Helm chart with separate frontend Deployment + Service + ConfigMap

---

## Choosing Between Approaches

| Criteria | Approach A (PatternFly + SSE) | Approach B (shadcn/ui + WebSocket) | Approach C (CRA + serve + Video) |
|----------|-------------------------------|-------------------------------------|-----------------------------------|
| Primary UI purpose | Chatbot-first with admin config panels | Multi-persona app with chat as sidebar | Live video monitoring with detection overlays |
| Language | TypeScript | TypeScript | JavaScript |
| UI framework | PatternFly 6 (Red Hat design system) | shadcn/ui + Tailwind CSS (custom design) | Plain CSS (no component library) |
| Build tooling | Vite 6 + SWC | Vite 7 + React plugin | Create React App (react-scripts 4) |
| Chat streaming | SSE with rAF batching | WebSocket with JSON protocol | REST POST (no streaming) |
| Real-time data | SSE for chat tokens | WebSocket for chat messages | MJPEG `<img>` for video; `setInterval` polling for detection data; SSE for config sync |
| Auth provider | External OAuth (any provider) | Keycloak OIDC specifically | None (open access) |
| Deployment model | Single container (baked into backend) | Two containers (nginx + API) | Two containers (serve + API) with Helm |
| Runtime config | Vite env vars | nginx `window.__RUNTIME_CONFIG__` | ConfigMap-mounted `window.__ENV__` via env.js |
| API validation | Unvalidated responses | Zod schema validation at service layer | Unvalidated responses |
| Component library | @patternfly/chatbot for chat UI | Custom components with Radix primitives | Custom components with plain HTML/CSS |
| Container base | UBI9/nodejs-22 | node:20-alpine + nginx:alpine | UBI9/nodejs-18 |
| Static server | FastAPI (serves built assets) | nginx | serve (npm package) |
| React version | React 18 | React 19 | React 17 |
| Package manager | npm | pnpm (monorepo workspaces) | npm |
| Best for | Chatbot apps, single-user personas | Multi-role enterprise apps, domain-rich UIs | Video/multimodal monitoring, OVMS-backed detection |
| Dev tooling | Lint + format only | Storybook + Vitest + lint + format | CRA defaults only |
