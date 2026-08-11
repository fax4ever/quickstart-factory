---
name: react-frontend
description: React + PatternFly chatbot frontend with TanStack Router, SSE streaming, and role-based admin/user layouts
summary: "Provides a React 18 + PatternFly 6 (@patternfly/chatbot) chatbot frontend for LlamaStack AI agents with SSE streaming, TanStack Router file-based routing with code-splitting, TanStack Query for server-state, and TanStack Form for admin config panels (agents, knowledge bases, MCP servers, models, users) with dark theme toggle via pf-v6-theme-dark class persisted to localStorage under key app-theme. Use for quickstarts needing a production chatbot UI with role-based OAuth-protected routing -- the _protected guard uses window.location.href (full page reload, not React Router) for external OAuth redirect, _admin routes add role checks, and Vite proxies /api to http://backend:8000 for local dev; in production the frontend is baked into the FastAPI backend container via multi-stage Containerfile. Critical pattern: useChat hook batches SSE token updates via requestAnimationFrame reducing re-renders, dispatches typed events through handler functions (handleReasoning, handleToolCall, handleResponse, handleNodeStarted), models content as a SimpleContentItem discriminated union (output_text, reasoning, tool_call, graph_node, input_image), and uses a LlamaStack constants library with isToolExecutionType()/isStructuralItemType() type guards for UI rendering decisions. Gotchas: Vite requires watch.usePolling:true for container file events, NODE_OPTIONS=--max-old-space-size=512 needed for production builds, reasoning items are stripped on [DONE] stream completion (transient only), chunkSizeWarningLimit raised to 2000 for large PatternFly bundles, session switching during streaming requires flushPendingUpdates() with confirmation modal, and fetchSessionsData is intentionally excluded from useEffect deps to prevent infinite re-render loops."
metadata:
  type: component
tags:
  tech_stack: [react, patternfly, typescript, vite, tanstack-router, tanstack-query, tanstack-form]
  ai_pattern: [agents, rag, mcp]
  platform: [openshift]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "PatternFly Chatbot UI with SSE streaming for LlamaStack agents, role-based routing, admin config panels"
    approach: "A"
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
