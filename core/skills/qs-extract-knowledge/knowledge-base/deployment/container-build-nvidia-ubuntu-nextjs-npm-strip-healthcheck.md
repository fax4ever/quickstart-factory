---
name: container-build-nvidia-ubuntu-nextjs-npm-strip-healthcheck
description: NVIDIA Ubuntu Next.js 4-stage build with npm removal in production, custom server.js, and HEALTHCHECK
summary: "Provides a 4-stage Next.js production Dockerfile on NVIDIA Ubuntu (nvcr.io/nvidia/base/ubuntu:jammy) with Node.js 22 from nodesource, for frontends requiring NVIDIA-authorized base images instead of standard node:alpine. Use when deploying Next.js on NVIDIA/NGC-compliant infrastructure requiring hardened containers with npm stripped from production -- single approach using custom server.js replacing `next start`. Stages: base (nodesource Node 22 + curl), deps (`npm ci`), builder (build + `npm ci --omit=dev --ignore-scripts` + defense-in-depth `.env` removal + NEXT_TELEMETRY_DISABLED=1), runner (dedicated nextjs user UID 1001, npm/npx binary deletion, curl-based HEALTHCHECK --interval=30s on port 3000, `CMD [\"node\", \"server.js\"]`). npm/npx removal means no runtime `npm install` so all dependencies must be baked at build time; custom server.js must exist in source; HEALTHCHECK silently fails if curl is absent from base stage; cookie security auto-derives from NEXTAUTH_URL scheme with explicit SECURE_COOKIES override available."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [nodejs, react]
  ai_pattern: []
  platform: [kubernetes]
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "AI-Q Blueprint UI with NVIDIA Ubuntu base, Node 22 from nodesource, OAuth runtime config, npm stripped in prod"
    approach: "A"
---

# NVIDIA Ubuntu Next.js Build with npm Removal and HEALTHCHECK

## Overview

A 4-stage Next.js production Dockerfile built on NVIDIA-authorized Ubuntu images rather than the standard Node.js base images. The pattern installs Node.js from nodesource, strips npm from the production image for reduced attack surface, uses a custom `server.js` entry point (not the Next.js built-in server), and adds a Docker HEALTHCHECK directive. All configuration is runtime via environment variables -- no rebuild is needed to change backend URL, auth settings, or OAuth provider.

## Pattern Description

The four stages are: (1) base -- installs Node.js 22 on NVIDIA Ubuntu, (2) deps -- runs `npm ci` to install dependencies, (3) builder -- builds Next.js with dev dependencies then prunes to production-only, (4) runner -- creates a minimal production image with a dedicated `nextjs` user, copies only build artifacts, and removes npm entirely. A defense-in-depth step deletes any `.env` files that may have leaked past `.dockerignore`.

## Implementation

### Base Stage with Node.js from Nodesource

NVIDIA Ubuntu is used as the base instead of `node:22-alpine` or similar. Node.js is installed via the nodesource setup script.

```dockerfile
FROM nvcr.io/nvidia/base/ubuntu:jammy-20260217 AS base

RUN apt-get update && apt-get install -y \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*
```

### Defense-in-Depth .env Cleanup

During the build stage, any `.env` files are explicitly removed as a safety measure even though `.dockerignore` should prevent them from entering the context.

```dockerfile
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Defense-in-depth: remove any env files that may have leaked past .dockerignore
RUN rm -f .env .env.local .env.*.local .env.development .env.production 2>/dev/null || true

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
RUN npm ci --omit=dev --ignore-scripts
```

### Production Runner with npm Removal

The runner stage creates a dedicated user, copies only the needed artifacts, and removes npm and npx binaries entirely.

```dockerfile
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs nextjs \
    && rm -rf /usr/lib/node_modules/npm /usr/bin/npm /usr/bin/npx

COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json
COPY --from=builder --chown=nextjs:nodejs /app/next.config.ts ./next.config.ts
COPY --from=builder --chown=nextjs:nodejs /app/server.js ./server.js

USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
```

### Runtime Environment Variables

All configuration is runtime -- no rebuild needed. Key variables include:

```bash
# Backend connection
BACKEND_URL=http://backend:8000

# Authentication (all optional -- disable with REQUIRE_AUTH=false)
REQUIRE_AUTH=false
NEXTAUTH_SECRET=$(openssl rand -base64 32)
NEXTAUTH_URL=http://localhost:3000
OAUTH_CLIENT_ID=your-client-id
OAUTH_CLIENT_SECRET=your-client-secret
OAUTH_ISSUER=https://your-oidc-provider.com

# Cookie security auto-derived from NEXTAUTH_URL scheme
# SECURE_COOKIES=true  # Explicit override available
```

## Configuration

- **Key settings:** `BACKEND_URL` for API connection; `REQUIRE_AUTH` toggle; `NEXTAUTH_*` for OAuth
- **Defaults:** Auth disabled (`REQUIRE_AUTH=false`), port 3000, hostname `0.0.0.0`
- **Dependencies:** NVIDIA NGC registry access for base image; backend service must be reachable at `BACKEND_URL`

## Gotchas

- npm and npx are removed from the production image (`rm -rf /usr/lib/node_modules/npm /usr/bin/npm /usr/bin/npx`), so `npm install` cannot run inside the production container -- all dependencies must be baked in at build time
- The custom `server.js` is used instead of `next start` -- this file must be present in the frontend source directory
- Cookie security is auto-derived from the `NEXTAUTH_URL` scheme (http vs https), with an explicit `SECURE_COOKIES` override available
- The HEALTHCHECK uses `curl` which is installed in the base stage -- if curl were not present, the healthcheck would silently fail

## Related Patterns

- `container-build-nvidia-distroless-uv-dev-release-target.md` -- backend Dockerfile using same NVIDIA base image family
- `compose-local-dev-prebuilt-ngc-fallback-build-target-dask.md` -- compose file that builds this frontend image
