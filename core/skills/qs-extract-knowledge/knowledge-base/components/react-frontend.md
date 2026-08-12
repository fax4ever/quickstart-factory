---
name: react-frontend
description: React frontend patterns for AI Quickstarts -- PatternFly/SSE or shadcn+Tailwind/WebSocket with TanStack Router
summary: "Provides two React frontend patterns for AI Quickstarts -- Approach A (React 18 + PatternFly 6 + @patternfly/chatbot) for chatbot-first UIs with SSE streaming via requestAnimationFrame batching, TanStack Router/Query/Form, OAuth redirect, and single-container deployment baked into FastAPI; Approach B (React 19 + shadcn/ui + Tailwind CSS 4 + Radix) for multi-persona enterprise apps with WebSocket JSON protocol streaming, Keycloak OIDC with PKCE and dev-mode role headers, Zod-validated layered API (Component->Hook->TanStack Query->Service->Schema), atomic design with Storybook 8, pnpm monorepo, and separate nginx container with window.__RUNTIME_CONFIG__ injection. Choose A for simple chatbot apps needing PatternFly design system, SSE rAF-batched streaming, TanStack Form admin panels, and any OAuth provider with single-container deploy -- choose B for multi-role domain-rich UIs needing Keycloak OIDC, role-based persona routing (ROLE_HOME mapping), WebSocket chat sidebar, Zod schema validation, and two-container nginx+API deploy. Critical patterns: both use TanStack Router file-based routing with code-splitting; A models chat content as SimpleContentItem discriminated union (output_text, reasoning, tool_call, graph_node, input_image) with LlamaStack isToolExecutionType()/isStructuralItemType() type guards; B injects Keycloak/company config at container start via nginx location returning JavaScript snippet with envsubst-substituted values. Gotchas: Vite requires watch.usePolling:true in containers; A needs NODE_OPTIONS=--max-old-space-size=512 for builds, strips reasoning items on [DONE], raises chunkSizeWarningLimit to 2000, requires flushPendingUpdates() with confirmation modal on session switch during streaming, and excludes fetchSessionsData from useEffect deps to prevent infinite loops; B requires WebSocket upgrade map in nginx.conf (not conf.d/ where envsubst mangles $ variables), passes JWT as WebSocket query parameter (MVP trade-off), needs OpenShift arbitrary UID chmod/chgrp on nginx dirs, downgrades Vite 7 UNRESOLVED_IMPORT errors for pnpm hoisted deps, and uses deprecated ROPC grant for demo convenience."
metadata:
  type: component
tags:
  tech_stack: [react, patternfly, typescript, vite, tanstack-router, tanstack-query, tanstack-form, tailwindcss, shadcn-ui, radix-ui, zod, keycloak, storybook, vitest, pnpm]
  ai_pattern: [agents, rag, mcp]
  platform: [openshift]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "PatternFly Chatbot UI with SSE streaming for LlamaStack agents, role-based routing, admin config panels"
    approach: "A"
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "React 19 + shadcn/ui + Tailwind CSS frontend with WebSocket chat streaming, Keycloak OIDC auth, role-based persona routing, separate nginx container"
    approach: "B"
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

## Choosing Between Approaches

| Criteria | Approach A (PatternFly + SSE) | Approach B (shadcn/ui + WebSocket) |
|----------|-------------------------------|-------------------------------------|
| Primary UI purpose | Chatbot-first with admin config panels | Multi-persona app with chat as sidebar |
| UI framework | PatternFly 6 (Red Hat design system) | shadcn/ui + Tailwind CSS (custom design) |
| Chat streaming | SSE with rAF batching | WebSocket with JSON protocol |
| Auth provider | External OAuth (any provider) | Keycloak OIDC specifically |
| Deployment model | Single container (baked into backend) | Two containers (nginx + API) |
| API validation | Unvalidated responses | Zod schema validation at service layer |
| Component library | @patternfly/chatbot for chat UI | Custom components with Radix primitives |
| Best for | Simple chatbot apps, single-user personas | Multi-role enterprise apps, domain-rich UIs |
| Package manager | npm | pnpm (monorepo workspaces) |
| Dev tooling | Lint + format only | Storybook + Vitest + lint + format |
