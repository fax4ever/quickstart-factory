---
name: container-build-ubi10-minimal-python312-pip-microdnf
description: UBI10 python-312-minimal base with microdnf upgrade, pip install with --only-binary numpy/scipy/scikit-learn, USER 1001
summary: "Builds lightweight Python 3.12 microservice images on ubi10/python-312-minimal using microdnf (smaller than full python-312 with dnf) and pip, targeting multi-agent Flask architectures where five services (orchestrator, risk, portfolio, guidelines, guardrails) share an identical Dockerfile pattern differing only in port (5000/7001/7002/7003/8000) and app code. Use when deploying multiple Python microservices on OpenShift needing UBI10 compliance and minimal image size -- prefer over full ubi10/python-312 when dnf and weak deps are unnecessary, and over python-slim when Red Hat certification is required. Standard Dockerfile runs microdnf -y upgrade --setopt=install_weak_deps=0, installs ca-certificates explicitly (minimal image may lack them), runs pip install --no-cache-dir --only-binary=:all: numpy scipy scikit-learn as a separate step before requirements.txt, and switches to USER 1001. The --only-binary=:all: flag must be a separate pip install before requirements.txt to prevent numpy/scipy/scikit-learn source compilation; guardrails variant must install then remove gcc-c++ and python3.12-devel after spaCy compilation (including spacy download en_core_web_lg); guidelines variant requires chgrp -R 0 and chmod -R g+rwX on writable directories to support OpenShift's arbitrary UID policy."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, flask]
  ai_pattern: [agents]
  platform: [openshift]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "5 Flask tool-agent microservices use identical UBI10 minimal base pattern with microdnf upgrade and --only-binary numpy/scipy/scikit-learn"
    approach: "A"
---

# UBI10 Minimal Python 3.12 with pip and microdnf

## Overview

This pattern builds lightweight Python microservice images using the UBI10 minimal Python 3.12 base image (`ubi10/python-312-minimal`), keeping images lean with `microdnf` for system packages and `pip` for Python dependencies. It is suited for multi-agent architectures where many services share the same base image pattern but differ only in application code and port.

## Pattern Description

Each microservice Dockerfile follows an identical structure: start from `ubi10/python-312-minimal`, switch to root to run `microdnf -y upgrade` with weak deps disabled, install `ca-certificates` (plus optional build deps), install Python packages with `pip` using `--only-binary=:all:` for binary-heavy packages like numpy/scipy/scikit-learn, copy application code, and switch to non-root user 1001. The `python-312-minimal` image uses `microdnf` instead of `dnf`, reducing image size compared to the full `python-312` image.

## Implementation

### Standard Tool Agent Dockerfile

Five services (orchestrator, risk, portfolio, guidelines, guardrails) follow this exact structure, differing only in port and application-specific requirements:

```dockerfile
# tools/value_at_risk/src/Dockerfile
FROM registry.access.redhat.com/ubi10/python-312-minimal

USER 0
RUN microdnf -y upgrade --setopt=install_weak_deps=0 && \
    microdnf -y install ca-certificates && \
    microdnf clean all

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --only-binary=:all: \
        numpy scipy scikit-learn && \
    pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY . /app

EXPOSE 7001

USER 1001
CMD ["python", "app.py"]
```

### Guardrails Agent with Build Dependencies

The guardrails proxy requires `gcc-c++` and `python3.12-devel` for compiling spaCy dependencies, then removes them after install to keep image size down:

```dockerfile
# tools/guardrails/src/Dockerfile
FROM registry.access.redhat.com/ubi10/python-312-minimal

USER 0
RUN microdnf -y upgrade --setopt=install_weak_deps=0 && \
    microdnf -y install ca-certificates gcc-c++ python3.12-devel && \
    microdnf clean all

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    python -m spacy download en_core_web_lg && \
    microdnf -y remove gcc-c++ python3.12-devel && \
    microdnf clean all

WORKDIR /app
COPY app.py /app/

EXPOSE 8000

USER 1001
CMD ["python", "app.py"]
```

### Guidelines Agent with Directory Permissions

The guidelines agent pre-creates writable directories for model and document storage:

```dockerfile
# tools/guidelines/src/Dockerfile (excerpt)
RUN mkdir -p /app/models /app/docs && \
    chgrp -R 0 /app && \
    chmod -R g+rwX /app
```

## Configuration

- **Key settings:** `--setopt=install_weak_deps=0` minimizes installed packages; `--only-binary=:all:` for numpy/scipy/scikit-learn avoids source compilation; `--no-cache-dir` reduces image size
- **Defaults:** Base image is `registry.access.redhat.com/ubi10/python-312-minimal`; runs as USER 1001; each service has its own port (5000, 7001, 7002, 7003, 8000)
- **Dependencies:** UBI10 minimal image requires `microdnf` instead of `dnf`; `ca-certificates` installed explicitly since the minimal image may not include them

## Gotchas

- The `--only-binary=:all:` flag is applied specifically to `numpy scipy scikit-learn` before the general `requirements.txt` install because these packages would otherwise attempt source compilation requiring additional build tools (see all five service Dockerfiles)
- The guardrails Dockerfile installs `gcc-c++` and `python3.12-devel` then removes them after pip install, keeping them only for the compilation step -- this reduces the final image size while allowing native extension compilation for spaCy (see `tools/guardrails/src/Dockerfile`)
- The guidelines Dockerfile uses `chgrp -R 0 /app && chmod -R g+rwX /app` to support OpenShift's arbitrary UID policy, since runtime model/document files need to be writable by the container process (see `tools/guidelines/src/Dockerfile`)
- The orchestrator Dockerfile includes an inline comment "Use a non-root user if you like (UBI has 1001 by default)" suggesting USER 1001 is a convention inherited from UBI's default non-root user (see `orchestrator/src/Dockerfile`)

## Related Patterns

- `container-build-ubi-uv-python-multistage.md` -- UBI base images with uv instead of pip
- `container-build-python-slim-nonroot-fastapi.md` -- python-slim base instead of UBI
