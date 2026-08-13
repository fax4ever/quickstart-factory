---
name: ui-console
description: Camel YAML DSL frontend combining static HTML UI, REST API, JMS result storage, and Prometheus metrics proxy
summary: "Implements a Camel YAML DSL + Quarkus backend-for-frontend serving a Carbon Design System v10.58.0 static HTML UI with vanilla JavaScript SVG topology diagrams, a REST API for trace data stored as files on a RWO PVC via pollEnrich/Groovy, JMS consumption from Artemis queues (analysis-result, error-logs-interactive) for result persistence, and a Prometheus metrics proxy aggregating sibling services plus Infinispan cache stats via Digest auth. Use when building a monolithic BFF combining static UI serving, REST file-based storage with directory listing, JMS message consumption for result persistence (standard .txt and interactive -it.txt files with Micrometer counters), and multi-service metrics aggregation in a single Camel deployment. Critical config: components.ui-console.strategy must be Recreate because RWO PVC prevents RollingUpdate; Artemis connections pooled via JmsPoolConnectionFactory with maxSessionsPerConnection=500; Quarkus observability on port 9876 with camel.metrics.enabled=false to disable incompatible standalone Camel metrics. Gotchas: Netty native transport fails on OpenShift without -Dio.netty.transport.noNative=true in JAVA_OPTS_APPEND, interactive re-analysis requires Groovy Files.deleteIfExists on stale -it.txt files before JMS send so frontend poll distinguishes 404 (pending) from old results, and dev mode needs explicit camel.server.staticEnabled=true for static file serving."
metadata:
  type: component
tags:
  tech_stack: [apache-camel, camel-yaml-dsl, quarkus, carbon-design-system, javascript, jms, artemis, micrometer]
  ai_pattern: []
  platform: [openshift, kubernetes]
  data_layer: [infinispan]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Camel-based UI console serving static HTML, REST trace API, JMS file storage consumer, and infrastructure metrics proxy"
    approach: "A"
---

# UI Console

## Overview

The UI Console is an Apache Camel component that acts as both a frontend and a backend-for-frontend (BFF) in the smart-telemetry-pipeline quickstart. It serves a static single-page HTML application with IBM Carbon Design System styling, exposes a REST API for trace data, consumes JMS messages to persist analysis results to disk, and proxies Prometheus metrics from sibling Camel services. On RHOAI it runs as a Quarkus-native deployment with a PVC for file-based result storage.

## Tech Stack & Dependencies

- **Runtime:** Apache Camel YAML DSL; runs via Camel JBang locally, exported to Quarkus for production
- **Container image:** Built by Tekton pipeline using `camel export` to Quarkus, then Maven build + Buildah
- **Key dependencies:** `camel-jms`, `camel-observability-services`, `camel-quarkus-platform-http`, `artemis-jakarta-client-all`, `quarkus-pooled-jms`, `camel-groovy`, `camel-http`, `camel-jq`
- **Helm subchart:** None (generic Helm chart shared across all three Camel components via `range` loop in templates)

## Key Patterns

### Camel YAML DSL REST API with File-Based Storage

The REST API is defined entirely in Camel YAML DSL (`rest-api.camel.yaml`). Trace results are stored as plain text files on a PVC. The route uses `pollEnrich` to read files on demand and Groovy scripts to list directory contents.

```yaml
# From rest-api.camel.yaml — list trace files using Groovy
- setBody:
    groovy: |
      import java.nio.file.*
      import java.nio.file.attribute.BasicFileAttributes
      return Files.list(Paths.get(exchange.getVariable('storagePath')))
        .filter(Files::isRegularFile)
        .filter(p -> p.getFileName().toString().endsWith('.txt'))
        .filter(p -> !p.getFileName().toString().endsWith('-it.txt'))
        .sorted((p1, p2) -> Files.readAttributes(p2, BasicFileAttributes.class)
          .creationTime().compareTo(Files.readAttributes(p1, BasicFileAttributes.class)
          .creationTime()))
        .map(p -> [id: p.getFileName().toString().replace('.txt', '')])
        .collect()
```

### JMS Consumer for Result Persistence

The `jms-file-storage.camel.yaml` route consumes analysis results from the Artemis `analysis-result` queue and writes them to the file system, distinguishing interactive results (`-it.txt` suffix) from standard ones.

```yaml
# From jms-file-storage.camel.yaml
- route:
    id: jms-to-file-storage
    from:
      uri: jms:{{camel.jms.queue.analysis-result}}
      steps:
        - choice:
            when:
              - simple: "${header.op} == 'interactive'"
                steps:
                  - setHeader:
                      name: CamelFileName
                      simple: ${header.traceId}-it.txt
            otherwise:
              steps:
                - setHeader:
                    name: CamelFileName
                    simple: ${header.traceId}.txt
        - to:
            uri: file:{{analyzer.storage.root}}
        - to:
            uri: "micrometer:counter:ui.results.stored"
```

### Prometheus Metrics Proxy

The `infra-api.camel.yaml` acts as a metrics aggregation gateway, proxying Prometheus scrape endpoints from the correlator, analyzer, and its own service. It also proxies Infinispan cache stats (via REST with Digest auth) and Artemis queue depths (via JMS management queue).

```yaml
# From infra-api.camel.yaml — proxy pattern with graceful fallback
- route:
    id: route-correlator-metrics
    from:
      uri: direct:correlator-metrics
      steps:
        - doTry:
            steps:
              - removeHeaders:
                  pattern: "*"
              - setHeader:
                  name: CamelHttpMethod
                  constant: GET
              - toD:
                  uri: "http://{{infra.correlator.metrics.url}}"
            doCatch:
              - exception:
                  - java.lang.Exception
                steps:
                  - setHeader:
                      name: CamelHttpResponseCode
                      constant: 503
                  - setBody:
                      constant: "# Correlator metrics unavailable"
```

### Static HTML UI with Carbon Design System

The frontend is a single `index.html` file using IBM Carbon Design System (v10.58.0 via CDN) with vanilla JavaScript. It provides two views: a trace analysis sidebar/detail layout and an SVG-based infrastructure topology diagram with live Prometheus metric overlays.

```html
<!-- From index.html — Carbon header with view switching -->
<header class="bx--header" role="banner">
    <a class="bx--header__name" href="javascript:void(0)">
        <span class="bx--header__name--prefix">Smart Log</span> Analyzer
    </a>
    <nav class="bx--header__nav">
        <ul class="bx--header__menu-bar">
            <li><a class="bx--header__menu-item" onclick="switchView('trace')">Trace Analysis</a></li>
            <li><a class="bx--header__menu-item" onclick="switchView('infra')">Infrastructure</a></li>
        </ul>
    </nav>
</header>
```

### Frontend Prometheus Parsing

The frontend JavaScript includes a custom Prometheus text format parser that fetches metrics from the proxy API and renders them as live counters on the SVG topology diagram and in detail modals.

```javascript
// From index.html — client-side Prometheus text parser
function parsePrometheus(text) {
    const metrics = {};
    for (const line of text.split('\n')) {
        if (line.startsWith('#') || !line.trim()) continue;
        const match = line.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*(?:\{[^}]*\})?) +([^ ]+)/);
        if (match) metrics[match[1]] = parseFloat(match[2]);
    }
    return metrics;
}
```

### Interactive Analysis via JMS

The UI supports user-triggered re-analysis with custom prompts. It saves the prompt via JMS request/reply to the correlator, then sends the trace ID to a dedicated `error-logs-interactive` queue. The analyzer picks it up, processes it, and writes the result as a `-it.txt` file that the UI polls for.

```yaml
# From rest-api.camel.yaml — trigger interactive analysis
- to:
    uri: "jms:queue:{{camel.jms.queue.error-logs-interactive}}?exchangePattern=InOnly"
- to:
    uri: "micrometer:counter:ui.interactive.triggered"
```

## Configuration

- **Environment variables:**
  - `ARTEMIS_BROKER_URL` — Artemis broker connection URL (prod default: `tcp://artemis:61616`)
  - `AMQ_USERNAME` / `AMQ_PASSWORD` — Artemis credentials (from `infra-accounts` secret)
  - `ANALYZER_STORAGE_ROOT` — file storage path (set to `/storage` via Helm `extraEnv`)
  - `INFINISPAN_HOSTS` — Infinispan host for cache stats proxy (prod default: `infinispan:11222`)
  - `DATAGRID_USERNAME` / `DATAGRID_PASSWORD` — Infinispan credentials
- **Config files:**
  - `application-dev.properties` — local development config with localhost endpoints
  - `chart/properties/ui-console/application-prod-quarkus.properties` — production config with env var placeholders
- **Helm values:**
  - `components.ui-console.expose: true` — creates an OpenShift Route
  - `components.ui-console.strategy: Recreate` — required because PVC is RWO
  - `components.ui-console.storage.mountPath: /storage` — PVC mount point
  - `components.ui-console.storage.size: 1Gi` — PVC size for analysis result files

## Known Gotchas

- **Recreate strategy required for RWO PVC:** The ui-console uses `strategy: Recreate` in `values.yaml` instead of `RollingUpdate` because the PVC is `ReadWriteOnce` — two pods cannot mount it simultaneously during a rolling update.
- **Quarkus disables standalone Camel metrics:** The production config explicitly sets `camel.metrics.enabled=false` and `camel.management.enabled=false` because standalone Camel metrics/management features are not compatible with Quarkus runtime. Metrics are instead exposed via the Quarkus observability stack on port 9876.
- **Netty native transport workaround:** All components including ui-console set `JAVA_OPTS_APPEND` with `-Dio.netty.transport.noNative=true` via the Helm chart to avoid Netty native transport issues on OpenShift.
- **Static file serving requires explicit config:** In dev mode, `camel.server.staticEnabled=true` must be set in properties for the Camel HTTP server to serve the `index.html` file. This property is absent in the prod config because Quarkus handles static resources natively.
- **Pooled JMS connections:** The Artemis connection factory is wrapped in a `JmsPoolConnectionFactory` with `maxSessionsPerConnection=500` to handle concurrent JMS operations without exhausting connections.
- **Interactive result file cleanup:** When triggering a new interactive analysis, the route explicitly deletes any existing `-it.txt` file via Groovy (`Files.deleteIfExists`) before sending the request, so the frontend poll loop can distinguish between "not yet ready" (404) and "old stale result."

## Testing Notes

- Verify the REST API is reachable at the Route URL: `GET /api/traces` should return a JSON array
- Check that JMS consumption is working: analysis results from the `analysis-result` queue should appear as `.txt` files under `/storage`
- The infrastructure view polls every 3 seconds; verify metrics proxy returns data at `/api/metrics/correlator`, `/api/metrics/analyzer`, `/api/metrics/ui`
- Interactive analysis can be tested by selecting a trace, clicking "Interactive Analysis", and submitting a prompt

## Related Patterns

- Camel YAML DSL route definitions for event-driven microservices
- JMS-based async communication between Camel components
- Prometheus metrics proxy/aggregation pattern for multi-service observability
- File-based storage with PVC on OpenShift (Recreate strategy for RWO)
