---
name: nextjs-frontend
description: "Next.js 16 frontend with gateway proxy, WebSocket/SSE streaming, Zustand state, and pluggable OAuth"
summary: "Provides a Next.js 16 chat-and-research UI for AI agent quickstarts, using a custom gateway server.js (port 3000) that proxies HTTP to Next.js and WebSocket /websocket to a Python backend, with SSE for long-running deep research jobs — deployed via Docker Compose from NVIDIA Ubuntu base image (0.5 CPU / 512M). Use when building a React-based agent UI needing real-time streaming over both WebSocket (chat via NAT protocol with system_response/intermediate/interaction/error types and atomic rotate() for socket replacement) and SSE (12 event types including artifact.update for todo/citation/file/output with lastEventId reconnection), with pluggable NextAuth v4 OAuth. Gateway enables runtime config without rebuilds via AppConfigContext (server component reads BACKEND_URL, REQUIRE_AUTH, FILE_UPLOAD_* at request time, passes through React context); adapter-based architecture routes all KUI imports through src/adapters/ui/index.ts; Zustand store persists to localStorage with QuotaExceededError pruning, storing only conversation ID references to avoid duplication. Session IDs use underscores not hyphens (Milvus constraint), proxy.ts replaces middleware.ts in Next.js 16+ (Node.js not Edge runtime), token refresh must only happen in NextAuth JWT callback never in proxy (loses rotating refresh tokens), connection errors are stripped on rehydration, deep research todo persistence is debounced at 1s, and production Dockerfile removes .env files and npm binaries for defense-in-depth."
metadata:
  type: component
tags:
  tech_stack: [nextjs, react, typescript, tailwindcss, zustand, zod, nodejs]
  ai_pattern: [agents, rag]
  platform: []
  data_layer: []
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "Next.js 16 research agent UI with gateway server, WebSocket chat, SSE deep research, KUI design system, and pluggable NextAuth OAuth"
    approach: "A"
---

# Next.js Frontend

## Overview

A Next.js 16 frontend used as the web UI for AI agent quickstarts. It serves as a chat-and-research interface backed by a Python agent service, with real-time communication via WebSocket (chat) and SSE (deep research jobs). The architecture uses a custom Node.js gateway server that proxies both HTTP and WebSocket traffic to the backend, avoiding CORS issues and enabling runtime configuration without container rebuilds.

## Tech Stack & Dependencies

- **Runtime:** Node.js 22 / Next.js 16 with Turbopack (dev), React 18, TypeScript 5.9
- **Container image:** Built from `nvcr.io/nvidia/base/ubuntu:jammy-20260217` (NVIDIA authorized base) with Node.js installed via NodeSource
- **Key dependencies:** `zustand` (state management), `next-auth` (OAuth), `zod` (schema validation), `@nvidia/foundations-react-core` (KUI design system), `http-proxy` (gateway), `react-markdown` + `marked` (rendering), `@react-pdf/renderer` (PDF export)
- **Testing:** Vitest 4 with happy-dom, Testing Library, MSW 2 for API mocking, v8 coverage
- **Helm subchart:** None standalone; deployed via Docker Compose as the `frontend` service

## Key Patterns

### Gateway Server Architecture

The frontend uses a custom `server.js` gateway (not Next.js built-in server) running on port 3000 as the single entry point. In development, it proxies HTTP to Next.js dev server on port 3001 and WebSocket `/websocket` to the backend. In production, it runs Next.js in-process while still proxying WebSocket connections to the backend.

```js
// server.js — production mode runs Next.js in-process
if (!dev) {
  const next = require('next')
  nextApp = next({ dev: false, hostname, port: 3001 })
  nextHandle = nextApp.getRequestHandler()
}

// WebSocket upgrade routes /websocket to backend
server.on('upgrade', (req, socket, head) => {
  const pathname = parsedUrl.pathname || '/'
  if (pathname === '/websocket' || pathname.startsWith('/websocket')) {
    req.url = '/websocket' + (parsedUrl.search || '')
    backendProxy.ws(req, socket, head,
      { target: BACKEND_WS_URL, changeOrigin: true })
    return
  }
  // Other WS (HMR) goes to Next.js
})
```

### Runtime Configuration via AppConfigContext

Server-side environment variables are read in the root layout (server component) and passed to client components through a React context, avoiding `NEXT_PUBLIC_` prefixed variables and enabling runtime config changes without container rebuilds.

```tsx
// layout.tsx — server component reads env at runtime
const getAppConfig = (): AppConfig => ({
  authRequired: isAuthRequired(),
  authProviderId: AUTH_PROVIDER_ID,
  sessionRefreshIntervalSeconds: Math.max(60, TOKEN_REFRESH_BUFFER_SECONDS - 60),
  fileUpload: getFileUploadConfigFromEnv(process.env),
})
```

```tsx
// providers.tsx — client wrapper
<AppConfigProvider config={config}>
  <SessionProvider ...>
    <ThemeWrapper>
      <DeepResearchRestorer>{children}</DeepResearchRestorer>
    </ThemeWrapper>
  </SessionProvider>
</AppConfigProvider>
```

### Adapter-Based Architecture

Features never import external packages directly. All third-party UI components from NVIDIA KUI are re-exported through `src/adapters/ui/index.ts`, and all API calls go through adapter clients in `src/adapters/api/`. This creates clean swap points.

```ts
// src/adapters/ui/index.ts — sole import point for KUI
// Features should NEVER import directly from @nvidia/foundations-react-core.
export { Button, Flex, Text, ... } from '@nvidia/foundations-react-core'
export { ThemeProvider } from '@nvidia/foundations-react-core'
```

### WebSocket Client with NAT Protocol

Chat communication uses a custom WebSocket client implementing the NVIDIA Agent Toolkit (NAT) protocol. It supports structured message types including `system_response`, `system_intermediate`, `system_interaction` (HITL prompts), and `error`. The client includes a `rotate()` method for atomic socket replacement that prevents race conditions between `onclose` events from old sockets and `connect()` for new ones.

```ts
// websocket-client.ts — NAT protocol message handling
switch (message.type) {
  case NATMessageType.SYSTEM_RESPONSE:
    // Final or streaming content
    break
  case NATMessageType.SYSTEM_INTERMEDIATE:
    // Thinking steps, tool calls
    break
  case NATMessageType.SYSTEM_INTERACTION:
    // Human-in-the-loop prompts
    break
  case NATMessageType.ERROR:
    // Auth errors trigger silent reconnect
    break
}
```

### Deep Research SSE Streaming

Long-running research jobs use Server-Sent Events via a separate `DeepResearchClient` that handles 12 event types (`stream.start`, `job.status`, `workflow.start/end`, `llm.start/chunk/end`, `tool.start/end`, `artifact.update`). The client supports reconnection via `lastEventId` and normalizes Python repr strings from backend tool inputs.

```ts
// deep-research-client.ts — artifact.update dispatching
switch (artifactData.type) {
  case 'todo':
    callbacks.onTodoUpdate?.(artifactData.content as TodoItem[])
    break
  case 'citation_source':
    callbacks.onCitationUpdate?.(artifactData.url || '', content, false)
    break
  case 'citation_use':
    callbacks.onCitationUpdate?.(artifactData.url || '', content, true)
    break
  case 'file':
    callbacks.onFileUpdate?.(fileName, content)
    break
  case 'output':
    callbacks.onOutputUpdate?.(content, outputCategory, workflow)
    break
}
```

### Zustand Store with Resilient localStorage Persistence

The chat store uses Zustand with a custom `PersistStorage` wrapper that handles `QuotaExceededError` by pruning and, as a last resort, clearing all conversations. It avoids serializing `currentConversation` twice by storing only its ID reference, then reconstructing on read.

```ts
// store.ts — deduplication: store only ID, reconstruct on read
const prunePersistedChatState = (value) => {
  const currentConversationId = state.currentConversation?.id ?? null
  return {
    ...value,
    state: {
      currentUserId: state.currentUserId ?? null,
      conversations,
      currentConversation: currentConversationId as unknown as Conversation | null,
      pendingInteraction: state.pendingInteraction ?? null,
    },
  }
}
```

### Pluggable OAuth via NextAuth

Authentication uses NextAuth v4 with a pluggable provider architecture. The active provider is determined by a single swap-point file (`providers/index.ts`). When `REQUIRE_AUTH=false`, a dummy `CredentialsProvider` is used that always returns `null`. The proxy layer (`proxy.ts`, replacing `middleware.ts` in Next.js 16+) extracts the `idToken` from the NextAuth JWT and sets it as an httpOnly cookie for backend authentication.

```ts
// proxy.ts — idToken cookie for backend auth
if (cookieDecision === 'set') {
  response.cookies.set('idToken', token.idToken as string, {
    httpOnly: true,
    sameSite: 'lax',
    path: '/',
    secure: shouldUseSecureCookies(),
    maxAge: idTokenCookieMaxAgeSeconds(expiresAt!, SESSION_MAX_AGE_SECONDS),
  })
}
```

## Configuration

- **Environment variables:**
  - `BACKEND_URL` - Backend API URL (default: `http://localhost:8000`); read at runtime, no rebuild needed
  - `REQUIRE_AUTH` - Set to `true` to require OAuth login (default: `false`)
  - `NEXTAUTH_SECRET` - Session encryption secret (required if auth enabled)
  - `NEXTAUTH_URL` - Public URL; also determines cookie security (http vs https)
  - `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_ISSUER` - OIDC provider config
  - `SECURE_COOKIES` - Explicit cookie security override
  - `TOKEN_REFRESH_BUFFER_MINUTES` - Buffer before token expiry for proactive refresh (default: 15)
  - `SESSION_MAX_AGE_HOURS` - Session lifetime (default: 24)
  - `FILE_UPLOAD_MAX_SIZE_MB` - Max upload size (default: 100)
  - `FILE_UPLOAD_ACCEPTED_TYPES` - Accepted file extensions (default: `.pdf,.docx,.txt,.md`)
  - `FILE_UPLOAD_MAX_FILE_COUNT` - Max files per session
  - `FILE_EXPIRATION_CHECK_INTERVAL_HOURS` - File TTL check interval
- **Config files:**
  - `next.config.ts` - Minimal; configures `serverActions.bodySizeLimit` from `FILE_UPLOAD_MAX_SIZE_MB`
  - `tailwind.config.ts` - Content paths include `node_modules/@nvidia/foundations-react-core`
  - `vitest.config.ts` - Uses happy-dom, inlines `@nvidia` deps, aliases `@/` paths
- **Helm values:** Not a standalone Helm chart; runs as Docker Compose `frontend` service with resource limits (0.5 CPU / 512M memory)

## Known Gotchas

- **Session IDs use underscores, not hyphens:** `createNewConversation` generates IDs as `s_<uuid-with-underscores>` because Milvus vector DB only accepts letters, numbers, and underscores (from code comment in `store.ts`).
- **proxy.ts replaces middleware.ts:** In Next.js 16+, the file `proxy.ts` runs in Node.js runtime (not Edge), replacing the traditional `middleware.ts` pattern. The code explicitly documents this shift.
- **Token refresh only in NextAuth JWT callback, never in proxy:** The proxy does NOT refresh tokens. A comment in `proxy.ts` explains that refreshing there would lose rotating refresh tokens since the new token cannot be persisted back to the NextAuth JWT session.
- **Connection errors stripped on rehydration:** The resilient storage layer strips `connection.*` error messages during `getItem` to prevent stale "failed to connect" banners persisting across page reloads (from `createResilientStorage` in `store.ts`).
- **Defense-in-depth .env removal in Dockerfile:** The builder stage explicitly removes `.env*` files that may have leaked past `.dockerignore` (`RUN rm -f .env .env.local ...`).
- **npm removed from production image:** The runner stage removes npm/npx binaries (`rm -rf /usr/lib/node_modules/npm /usr/bin/npm /usr/bin/npx`) to reduce attack surface.
- **Deep research todo persistence is debounced:** SSE can emit many todo events in quick succession; the store debounces persistence writes to localStorage at 1-second intervals to keep the UI responsive (from `DEEP_RESEARCH_TODO_PERSIST_DEBOUNCE_MS` in `store.ts`).
- **WebSocket rotate() prevents onclose race:** The `NATWebSocketClient.rotate()` method detaches handlers from the old socket before closing it and uses an `rotationInFlight` promise to coalesce concurrent rotation requests, preventing event handler races documented in the method's JSDoc.

## Testing Notes

- Run `npm run lint`, `npm run type-check`, and `npm run test:ci` from `frontends/ui/`
- Tests use `happy-dom` environment with MSW for API mocking (`src/mocks/`)
- Vitest aliases mirror the TypeScript path aliases (`@/`, `@/adapters/`, `@/features/`, `@/shared/`)
- The `server-only` import is mocked in tests via `config/vitest/mocks/server-only.ts`
- Coverage provider is v8 with reporters: text, text-summary, cobertura, html

## Related Patterns

- Gateway proxy pattern relates to deployment-level backend wiring
- WebSocket/SSE streaming connects to the backend agent architecture
- OAuth/NextAuth patterns relate to authentication deployment patterns
