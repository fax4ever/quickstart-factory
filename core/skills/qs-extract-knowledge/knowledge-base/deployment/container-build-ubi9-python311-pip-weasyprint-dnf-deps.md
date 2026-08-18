---
name: container-build-ubi9-python311-pip-weasyprint-dnf-deps
description: UBI9/python-311 container with system deps via dnf for WeasyPrint PDF generation and pip requirements.txt
summary: "Builds UBI9/python-311 containers needing native C libraries (pango, cairo, harfbuzz, fontconfig, freetype, libxml2, libxslt, gcc, python3-devel) installed via dnf before pip can compile Python packages like WeasyPrint for PDF generation. Use when Python packages require system-level C library dependencies that pip cannot provide alone; for containers needing only pip packages without native deps, use the minimal variant with inline-pinned pip install, no dnf, and no USER root escalation. Single-stage build with temporary USER root for dnf install then USER 1001 for pip and runtime; Makefile sets build context to parent src/ via \"-f src/mcp_server/Dockerfile src\" enabling COPY of sibling packages (core, common, chatbots) with PYTHONPATH=/app; dnf clean all reduces image size. WeasyPrint produces blank PDFs without dejavu-sans-fonts; gcc and python3-devel are build-time-only deps for C extension compilation; alerting variant pins versions inline (requests==2.32.5) instead of requirements.txt; build context must be broader than Dockerfile directory to copy sibling packages."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, fastapi]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "UBI9/python-311 with dnf system deps (WeasyPrint fonts, pango, cairo, gcc) as root, then USER 1001 for pip install, shared src/ build context for mcp-server and alerting"
    approach: "A"
---

# UBI9 Python 3.11 Container with System Dependencies via dnf and pip

## Overview

This pattern builds Python containers on Red Hat UBI9/python-311 with system-level dependencies installed via `dnf` (for libraries like WeasyPrint that require native C libraries) followed by pip-based Python dependency installation. It uses a single-stage build with temporary root escalation for system packages, then drops back to non-root for pip install and runtime.

## Pattern Description

The MCP server requires WeasyPrint for PDF report generation, which depends on system libraries (pango, cairo, harfbuzz, fontconfig, freetype). These must be installed via `dnf` as root before pip can compile the Python bindings. The Dockerfile temporarily switches to `USER root` for dnf, then back to `USER 1001` for pip and runtime. The build context is the `src/` directory, and multiple Python packages (core, common, chatbots, mcp_server) are copied from sibling directories within that context.

## Implementation

### MCP Server Dockerfile (System Deps + pip)

```dockerfile
# src/mcp_server/Dockerfile
FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

USER root

# Install system dependencies for WeasyPrint
RUN dnf install -y \
    fontconfig \
    harfbuzz \
    pango \
    cairo \
    libxml2 \
    libxslt \
    freetype \
    openjpeg2 \
    python3-devel \
    gcc \
    gcc-c++ \
    libffi-devel \
    dejavu-sans-fonts \
    && dnf clean all

USER 1001

# Copy and install Python dependencies via pip
COPY mcp_server/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /app/requirements.txt

# Copy source code from multiple sibling directories
COPY core /app/core
COPY common /app/common
COPY chatbots /app/chatbots
COPY mcp_server /app/mcp_server

ENV PYTHONPATH=/app
EXPOSE 8085

CMD ["python", "-m", "mcp_server.main"]
```

### Alerting Service Dockerfile (Minimal pip)

The alerting service uses the same UBI9/python-311 base but with no system deps and only 2 pip packages:

```dockerfile
# src/alerting/Dockerfile
FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

RUN pip install requests==2.32.5 llama-stack-client==0.2.12

COPY alerting/ .

CMD ["python3", "alert_receiver.py"]
```

### Build Context Configuration in Makefile

Both images use the `src/` directory as build context, allowing them to copy sibling packages:

```makefile
# Makefile
build-mcp-server:
	@$(BUILD_TOOL) buildx build --platform $(PLATFORM) \
		-f src/mcp_server/Dockerfile \
		-t $(MCP_SERVER_IMAGE):$(VERSION) \
		src

build-alerting:
	@$(BUILD_TOOL) buildx build --platform $(PLATFORM) \
		-f src/alerting/Dockerfile \
		-t $(METRICS_ALERTING_IMAGE):$(VERSION) \
		src
```

## Configuration

- **Key settings:** Build context is `src/` (not the Dockerfile's directory), enabling `COPY core /app/core` to copy sibling packages; `PYTHONPATH=/app` ensures all packages are importable
- **Defaults:** UBI9/python-311 includes pip; no uv or poetry used
- **Dependencies:** WeasyPrint's native deps (pango, cairo, harfbuzz) must be installed before pip install; `gcc` and `python3-devel` are build-time deps for compiling C extensions

## Gotchas

- The build context (`src/`) is broader than the Dockerfile's directory (`src/mcp_server/`), specified via `-f src/mcp_server/Dockerfile src` in the Makefile -- this is necessary because the MCP server depends on sibling Python packages (core, common, chatbots)
- `USER root` is needed only for `dnf install`; the Dockerfile switches back to `USER 1001` before pip install, keeping the runtime non-root
- `dejavu-sans-fonts` is installed for PDF rendering -- without a font package, WeasyPrint produces blank PDFs
- `dnf clean all` is called after install to reduce image size by removing cached RPMs
- The alerting Dockerfile pins exact package versions inline (`requests==2.32.5`) instead of using a requirements.txt file

## Related Patterns

- `container-build-ubi-uv-python-multistage.md` -- UBI with uv instead of pip
- `container-build-python-slim-pip-uv-version-sed.md` -- python-slim with pip/uv hybrid
