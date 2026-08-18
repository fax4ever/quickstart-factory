---
name: container-build-fedora-r-shiny-nonroot
description: Fedora-based Containerfile installing R and Shiny packages with non-root UID 1001 for OpenShift
summary: "Containerizes R Shiny monitoring dashboards using fedora:latest, installing R/R-devel and system libraries (libcurl-devel, openssl-devel, libxml2-devel, libuv-devel) via dnf with CRAN-compiled packages (shiny, httpuv, httr, stringr, bslib) for dashboards consuming FastAPI backend metrics via a METRICS_URL env var. Use when building R-based OpenShift dashboards requiring dnf-managed R on Fedora -- unlike UBI-based (container-build-ubi-uv-python-multistage) or python-slim (container-build-python-slim-pip-uv-version-sed) patterns, this single-approach pattern targets R workloads with fedora:latest as base. Non-root user created via useradd -r -u 1001 with chown -R 1001:0 and chmod -R g=u for OpenShift arbitrary UID compatibility, running shiny::runApp() directly on port 3838 without Shiny Server, with .containerignore excluding chart/ and README.md. fedora:latest base may fail production compliance requiring UBI; COPY source app.r vs destination app.R case mismatch breaks on case-sensitive Linux filesystems; CRAN packages compile from source on Fedora (no pre-compiled binaries like Ubuntu), causing slow builds."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [r-shiny]
  ai_pattern: [guardrails]
  platform: [openshift]
source_examples:
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "Fedora-based R Shiny monitoring dashboard container with dnf-installed R, CRAN packages, and non-root user for OpenShift"
    approach: "A"
---

# Fedora-based R Shiny Container with Non-Root User

## Overview

This pattern builds an R Shiny dashboard container from Fedora (not UBI or python-slim), installing R and required packages via `dnf` and CRAN, with OpenShift-compatible non-root user setup. It demonstrates how to containerize R-based monitoring dashboards that consume metrics from FastAPI backends.

## Pattern Description

The Containerfile uses `fedora:latest` as the base image and installs R plus system-level development dependencies via `dnf`. R packages (shiny, httpuv, httr, stringr, bslib) are installed from CRAN. A non-root user (UID 1001) is created with the standard OpenShift ownership pattern (`chown -R 1001:0` plus `chmod -R g=u`). The container runs a single R Shiny app directly via `shiny::runApp()`.

## Implementation

### Containerfile

```dockerfile
# shiny-dashboard/Containerfile
FROM fedora:latest

# Install R and dependencies
RUN dnf install -y \
    R \
    R-devel \
    libcurl-devel \
    openssl-devel \
    libxml2-devel \
    libuv-devel \
    && dnf clean all

# Install R packages
RUN R -e "install.packages(c('shiny', 'httpuv', 'httr', 'stringr', 'bslib'), repos='https://cloud.r-project.org/')"

# Create shiny user and app directory
RUN useradd -r -u 1001 shiny && \
    mkdir -p /srv/shiny-server && \
    chown -R 1001:0 /srv/shiny-server && \
    chmod -R g=u /srv/shiny-server

# Copy the app
COPY app.r /srv/shiny-server/app.R

# Fix permissions
RUN chown -R 1001:0 /srv/shiny-server

EXPOSE 3838

USER 1001

CMD ["R", "-e", "shiny::runApp('/srv/shiny-server/app.R', host='0.0.0.0', port=3838)"]
```

### Containerignore

A `.containerignore` excludes non-essential files from the build context:

```
# shiny-dashboard/.containerignore
chart/
README.md
```

## Configuration

- **Key settings:** Port 3838 (R Shiny default); UID 1001 with group 0 for OpenShift compatibility; R packages installed from CRAN (`cloud.r-project.org`)
- **Defaults:** Uses `fedora:latest` (not a pinned version); system R installed via dnf (not a specific R version); app runs via `shiny::runApp()` directly (no Shiny Server)
- **Dependencies:** System libraries `libcurl-devel`, `openssl-devel`, `libxml2-devel`, `libuv-devel` are required for R package compilation; the app expects a `METRICS_URL` env var pointing to the backend metrics endpoint at runtime

## Gotchas

- Uses `fedora:latest` as the base image rather than Red Hat UBI -- this may not meet production compliance requirements that mandate UBI base images (see `shiny-dashboard/Containerfile`)
- The `COPY app.r` source filename uses lowercase `.r` but the destination uses uppercase `.R` (`/srv/shiny-server/app.R`) -- R is case-sensitive on Linux file systems (see `shiny-dashboard/Containerfile`)
- R package compilation from CRAN can be slow during container builds since packages are compiled from source (not binary) on Fedora -- there are no pre-compiled binary packages for Fedora like there are for Ubuntu (see `shiny-dashboard/Containerfile`)
- The `useradd -r` flag creates a system account; combined with `-u 1001`, this matches the OpenShift arbitrary UID convention used by other containers in the same quickstart (see `shiny-dashboard/Containerfile` and `lemonade-stand-app/Containerfile`)

## Related Patterns

- `container-build-python-slim-pip-uv-version-sed.md` -- alternative container build pattern using python:slim base
- `container-build-ubi-uv-python-multistage.md` -- UBI-based Python container builds for comparison
