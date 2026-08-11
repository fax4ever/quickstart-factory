---
name: shiny-dashboard
description: "R Shiny dashboard for real-time Prometheus metrics visualization of AI guardrail detections"
summary: "R Shiny dashboard (bslib-themed with Red Hat Display/Text fonts) providing real-time AI guardrail metrics visualization by regex-parsing a Prometheus /metrics endpoint via invalidateLater auto-refresh, replacing a full Grafana/Prometheus stack. Use when a lightweight self-contained monitoring UI is needed for guardrail_requests_total, blocked input/output tallies, and per-detector bar charts (CSS --width); deployed via standalone Helm subchart (not ai-architecture-charts) with OpenShift Route TLS edge termination and image quay.io/sara_banderby/shinydashboard:fedora. Configure METRICS_URL (default http://lemonade-stand:8080/metrics) and REFRESH_INTERVAL via Helm values; container runs shiny::runApp() on port 3838 as uid 1001/group 0 with g=u for restricted SCC; liveness probe at / with 30s initialDelaySeconds; resources 512Mi-1Gi memory, 250m-500m CPU. Gotchas: REFRESH_INTERVAL defaults to 1s in app.R but 5s in deployment.yaml causing mismatch, Containerfile COPY references lowercase app.r (fails on case-sensitive Linux), single R process (no Shiny Server) cannot scale for multi-user, and approved_requests is derived as total minus blocked which misleads if upstream counting semantics differ."
metadata:
  type: component
tags:
  tech_stack: [r-shiny, bslib, httr, prometheus]
  ai_pattern: [guardrails, monitoring]
  platform: [openshift]
  data_layer: []
source_examples:
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "R Shiny dashboard polling Prometheus /metrics endpoint for guardrail detection counts"
    approach: "A"
---

# Shiny Dashboard

## Overview

R Shiny dashboard that provides real-time visualization of AI guardrail metrics by polling a Prometheus-format `/metrics` endpoint. It serves as a lightweight, self-contained monitoring UI alternative to Grafana for displaying guardrail request counts, blocked input/output tallies, and per-detector detection breakdowns. Deployed on OpenShift with a Helm chart, OpenShift Route, and TLS edge termination.

## Tech Stack & Dependencies

- **Runtime:** R (Fedora base image), Shiny framework
- **Container image:** `quay.io/sara_banderby/shinydashboard:fedora` (built from `fedora:latest` with R installed via `dnf`)
- **Key dependencies:** `shiny`, `httpuv`, `httr`, `stringr`, `bslib`
- **Helm subchart:** Standalone chart (`shiny-dashboard/chart/`) -- not using ai-architecture-charts

## Key Patterns

### Prometheus Metrics Polling

The dashboard fetches raw Prometheus text-format metrics via HTTP GET and parses them with regex, rather than using a Prometheus client library. This avoids needing a full Prometheus/Grafana stack.

```r
# From shiny-dashboard/app.R (lines 7-8)
METRICS_URL <- Sys.getenv("METRICS_URL", "http://lemonade-stand:8080/metrics")
REFRESH_INTERVAL <- as.integer(Sys.getenv("REFRESH_INTERVAL", "1")) # seconds
```

The polling loop uses Shiny's `invalidateLater` for auto-refresh:

```r
# From shiny-dashboard/app.R (lines 244-251)
observe({
  invalidateLater(REFRESH_INTERVAL * 1000, session)
  new_metrics <- fetch_metrics()
  if (!is.null(new_metrics)) {
    metrics_data(new_metrics)
  }
})
```

### Prometheus Text Format Parsing

Metrics are parsed line-by-line with regex instead of using a dedicated Prometheus parser. The function extracts three metric families: `guardrail_requests_total`, `guardrail_detections_by_direction` (split by `input`/`output`), and `guardrail_detections_by_detector`.

```r
# From shiny-dashboard/app.R (lines 27-30)
if (grepl("^guardrail_requests_total", line)) {
  value <- as.numeric(str_extract(line, "\\d+$"))
  metrics$total_requests <- metrics$total_requests + value
}
```

### Red Hat Branded bslib Theme

The UI uses `bslib::bs_theme()` with Red Hat brand fonts and colors, providing a consistent look without external CSS frameworks.

```r
# From shiny-dashboard/app.R (lines 87-94)
theme = bs_theme(
  bg = "#151515",
  fg = "#FFFFFF",
  primary = "#EE0000",  # Red Hat Red
  secondary = "#FFFFFF",
  base_font = font_google("Red Hat Text"),
  heading_font = font_google("Red Hat Display")
)
```

### Dynamic Detector Bar Chart

Per-detector detections are rendered as CSS-styled bars using `--width` CSS custom properties, sorted by count descending. Detector names are mapped to display names in a `switch` statement.

```r
# From shiny-dashboard/app.R (lines 296-297)
width_pct <- (count / max_val) * 100
div(
  class = paste0("detector-bar detector-", gsub("_", "-", detector)),
  style = paste0("--width: ", width_pct, "%;"),
  tags$span(sprintf("%s: %s", display_name, format(count, big.mark = ",")))
)
```

### OpenShift-Compatible Containerfile

The Containerfile creates a non-root user (`uid 1001`) with group `0` ownership and `g=u` permissions, following OpenShift's restricted SCC requirements.

```dockerfile
# From shiny-dashboard/Containerfile (lines 17-19)
RUN useradd -r -u 1001 shiny && \
    mkdir -p /srv/shiny-server && \
    chown -R 1001:0 /srv/shiny-server && \
    chmod -R g=u /srv/shiny-server
```

The app runs directly via `R -e` rather than using Shiny Server:

```dockerfile
# From shiny-dashboard/Containerfile (line 35)
CMD ["R", "-e", "shiny::runApp('/srv/shiny-server/app.R', host='0.0.0.0', port=3838)"]
```

## Configuration

- **Environment variables:**
  - `METRICS_URL` -- URL of the Prometheus `/metrics` endpoint to poll (default: `http://lemonade-stand:8080/metrics`)
  - `REFRESH_INTERVAL` -- Polling interval in seconds (default: `1` in app.R, `5` in deployment.yaml)
- **Config files:** None beyond the R source file itself
- **Helm values:**
  - `image.repository` / `image.tag` -- Container image coordinates
  - `metrics.url` -- Injected as `METRICS_URL` env var
  - `metrics.refreshInterval` -- Injected as `REFRESH_INTERVAL` env var
  - `route.enabled` -- Toggle OpenShift Route creation
  - `route.host` -- Optional custom hostname (empty = auto-generated)
  - `resources.requests/limits` -- Memory: 512Mi-1Gi, CPU: 250m-500m

## Known Gotchas

- **REFRESH_INTERVAL default mismatch:** `app.R` defaults to `1` second while `deployment.yaml` sets `5` seconds. The Helm values also default to `1`. The actual refresh rate depends on which layer sets the env var last.
- **Containerfile case sensitivity:** The COPY instruction references `app.r` (lowercase) but the actual file is `app.R` (uppercase). This works on case-insensitive filesystems but may fail on Linux build hosts: `COPY app.r /srv/shiny-server/app.R` (Containerfile line 24).
- **No Shiny Server:** The container runs R Shiny directly with `shiny::runApp()` instead of Shiny Server, meaning it handles only one R process. This is adequate for a monitoring dashboard but would not scale for multi-user interactive analytics.
- **Approved requests is a derived metric:** `approved_requests` is calculated as `total_requests - (input_blocked + output_blocked)` (app.R line 64). This can produce misleading numbers if the upstream metrics have different counting semantics.

## Testing Notes

- Verify the dashboard loads at port 3838 and shows `"--"` placeholder values when the metrics endpoint is unreachable
- Confirm the `METRICS_URL` resolves to the backend service from within the cluster (e.g., `http://lemonade-stand:8080/metrics`)
- Check the OpenShift Route is created with TLS edge termination by inspecting `oc get route shiny-dashboard`
- Liveness probe hits `/` on port 3838 with 30s `initialDelaySeconds` -- R package loading can be slow on first start

## Related Patterns

- Guardrails orchestrator components that expose the `/metrics` endpoint this dashboard consumes
- Prometheus metrics format parsing as an alternative to deploying a full Grafana/Prometheus stack
