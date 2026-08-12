---
name: guardrails-proxy
description: Lightweight Flask wrapper around nemoguardrails library with Presidio PII detection and dual-mode deployment (compose/CRD)
summary: "Adds content safety guardrails to AI quickstarts by wrapping nemoguardrails in a Flask endpoint (/v1/guardrail/checks) that combines Presidio PII detection (credit cards, SSNs, phones), regex matching for secrets/tokens, and a custom Colang @action for domain-specific topic filtering. Use when you need a lightweight, self-contained guardrails proxy without LLM-based self-check rails — prefer nemo-guardrails (TrustyAI-managed) for LLM self-check prompts or guardrails-orchestrator for dedicated ML detector models with gateway routing. Dual-mode deployment via standalone Flask container with :ro,z bind-mounted config for compose or TrustyAI NemoGuardrails CRD (RHOAI 3.3+) with ConfigMap embedding config.yaml/rails.co/actions.py, feature-flagged by guardrails.enabled in Helm; orchestrator client is fail-open with separate check_input()/check_output() functions. Spacy en_core_web_lg download at build time adds significant image size to the UBI10 python-312-minimal multi-stage build, OPENAI_API_KEY must be set to \"not-used\" on the CR since no LLM rails are used, and service naming diverges between compose (guardrails) and Helm (guardrails-internal) requiring matching GUARDRAILS_URL."
metadata:
  type: component
tags:
  tech_stack: [flask, nemo-guardrails, presidio, spacy, python, helm]
  ai_pattern: [guardrails, agents]
  platform: [rhoai, openshift, trustyai]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Flask-based NeMo Guardrails proxy with Presidio PII detection, regex patterns, and custom financial-topic Colang action"
    approach: "A"
---

# Guardrails Proxy

## Overview

A lightweight Flask application that wraps the `nemoguardrails` Python library and exposes a `/v1/guardrail/checks` endpoint compatible with the OpenShift AI NemoGuardrails microservice API. It combines Presidio-based sensitive data detection (credit cards, SSNs, phone numbers), regex pattern matching for secrets/tokens, and a custom Colang action for domain-specific topic filtering. The component supports dual-mode deployment: a standalone Flask container for local development via docker-compose, and a TrustyAI `NemoGuardrails` CRD for cluster deployment on RHOAI.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12, Flask 3.1.2, nemoguardrails 0.22.0
- **Container image:** `registry.access.redhat.com/ubi10/python-312-minimal` (multi-stage: installs gcc-c++ and python3.12-devel for build, removes after pip install)
- **Key dependencies:** presidio-analyzer 2.2.362, presidio-anonymizer 2.2.362, spacy 3.8.7 with `en_core_web_lg` model, TrustyAI operator (RHOAI 3.3+ for cluster deployment)
- **Helm subchart:** None (integrated into the quickstart's umbrella Helm chart via `guardrails.enabled` toggle)

## Key Patterns

### Flask Wrapper Around nemoguardrails Library

The application is a thin HTTP layer that initializes `LLMRails` from a config directory and delegates all validation to the nemoguardrails library. The `/v1/guardrail/checks` endpoint accepts the same payload format as the TrustyAI-managed NemoGuardrails service.

```python
# tools/guardrails/src/app.py
from nemoguardrails import LLMRails, RailsConfig
from nemoguardrails.rails.llm.options import RailStatus

CONFIG_PATH = os.getenv("GUARDRAILS_CONFIG_PATH", "/config")
config = RailsConfig.from_path(CONFIG_PATH)
rails = LLMRails(config)

@app.route("/v1/guardrail/checks", methods=["POST"])
def guardrail_checks():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages", [])
    result = rails.check(messages=messages)
    if result.status == RailStatus.BLOCKED:
        rails_status = {}
        if result.rail:
            rails_status[result.rail] = {"status": "blocked"}
        return jsonify({"status": "blocked", "rails_status": rails_status,
                        "content": result.content or ""}), 200
    return jsonify({"status": "success"}), 200
```

### Presidio-Based Sensitive Data Detection

The config uses nemoguardrails' built-in `sensitive_data_detection` rail backed by Presidio (which requires the `presidio-analyzer`, `presidio-anonymizer`, and `spacy` dependencies). PII entity types are declared in the config YAML.

```yaml
# tools/guardrails/config/config.yaml
rails:
  config:
    sensitive_data_detection:
      input:
        entities:
          - CREDIT_CARD
          - US_SSN
          - PHONE_NUMBER
      output:
        entities:
          - CREDIT_CARD
          - US_SSN
          - PHONE_NUMBER
    regex_detection:
      input:
        patterns:
          - "\\b(password|secret|api[_-]?key|token)\\b"
          - "\\d{3}-\\d{2}-\\d{4}"
        case_insensitive: true
```

### Custom Colang Action for Domain-Specific Filtering

A custom `@action` handler blocks messages unrelated to the application domain (finance/investments) using keyword matching. The action is registered as a system action and wired into the input rail flows via a Colang `.co` file.

```python
# tools/guardrails/config/actions.py
@action(is_system_action=True)
async def check_financial_topic(context: Optional[dict] = None) -> str:
    """Block messages that are clearly unrelated to finance/investments."""
    user_message = (context or {}).get("user_message", "").lower()
    for keyword in OFF_TOPIC_KEYWORDS:
        if keyword in user_message:
            return "blocked"
    return "allowed"
```

```
# tools/guardrails/config/rails.co
define flow check financial topic
  $result = execute check_financial_topic
  if $result == "blocked"
    bot inform off topic
    stop
```

### Dual-Mode Deployment: Compose vs CRD

For local development, the Flask app runs directly as a container with the config directory bind-mounted. For cluster deployment, a `NemoGuardrails` CRD is used with a ConfigMap containing the same config files, managed by the TrustyAI operator.

```yaml
# deploy/local/compose.yml (local mode)
guardrails:
  build:
    context: ../../tools/guardrails/src
  environment:
    PORT: "8000"
    GUARDRAILS_CONFIG_PATH: "/config"
  volumes:
    - ../../tools/guardrails/config:/config:ro,z
```

```yaml
# deploy/helm/templates/nemoguardrails-cr.yaml (cluster mode)
apiVersion: trustyai.opendatahub.io/v1alpha1
kind: NemoGuardrails
metadata:
  name: guardrails
  annotations:
    security.opendatahub.io/enable-auth: "true"
spec:
  nemoConfigs:
    - name: guardrails-config
      configMaps:
        - guardrails-config
  env:
    - name: OPENAI_API_KEY
      value: not-used
```

### Fail-Open Client Integration

The orchestrator's guardrails client gracefully degrades: if `GUARDRAILS_URL` is unset or the service is unreachable, all messages are allowed through. This is the opposite of fail-closed behavior used in regulated-lending guardrails patterns.

```python
# orchestrator/src/guardrails.py
GUARDRAILS_URL = os.getenv("GUARDRAILS_URL", "").rstrip("/")
_TIMEOUT = float(os.getenv("GUARDRAILS_TIMEOUT", "10"))

def _check(messages: list[dict], model: str = "test") -> CheckResult:
    if not GUARDRAILS_URL:
        return CheckResult(allowed=True, detail="guardrails not configured")
    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
    except requests.RequestException as exc:
        logger.warning(f"Guardrails service unreachable: {exc}")
        return CheckResult(allowed=True, detail=f"guardrails unavailable: {exc}")
```

The client provides separate `check_input()` and `check_output()` functions, where `check_output()` sends both the user message and the assistant response as a message pair for output rail evaluation.

### Feature-Flagged Helm Deployment

The guardrails component is conditionally deployed via `guardrails.enabled` in Helm values. When enabled, the Helm chart creates a ConfigMap, the NemoGuardrails CR, and an internal ClusterIP Service, and injects `GUARDRAILS_URL` into the orchestrator deployment.

```yaml
# deploy/helm/templates/deployment-orchestrator.yaml
{{- if .Values.guardrails.enabled }}
- name: GUARDRAILS_URL
  value: "http://guardrails-internal:8000"
{{- end }}
```

## Configuration

- **Environment variables:**
  - `GUARDRAILS_CONFIG_PATH` -- path to the nemoguardrails config directory (default: `/config`)
  - `PORT` -- Flask app listening port (default: `8000`)
  - `GUARDRAILS_URL` -- orchestrator-side URL to the guardrails service (e.g., `http://guardrails:8000` for compose, `http://guardrails-internal:8000` for cluster)
  - `GUARDRAILS_TIMEOUT` -- HTTP request timeout in seconds for the orchestrator client (default: `10`)
  - `OPENAI_API_KEY` -- set to `not-used` on the NemoGuardrails CR since this config does not use LLM-based self-check rails
- **Config files:** Three files mounted into `/config`: `config.yaml` (rail definitions), `rails.co` (Colang flow definitions), `actions.py` (custom Python actions)
- **Helm values:**
  - `guardrails.enabled` -- master toggle for the entire guardrails stack (default: `true`)

## Known Gotchas

- **Spacy model download in Dockerfile:** The Dockerfile downloads the `en_core_web_lg` spacy model at build time (`python -m spacy download en_core_web_lg`), which is required by Presidio for entity recognition. This adds significant image size and build time. The gcc-c++ and python3.12-devel packages are installed for building native extensions and then removed after pip install.
- **OPENAI_API_KEY set to "not-used":** The NemoGuardrails CR requires the `OPENAI_API_KEY` env var to be set, but since this config uses Presidio/regex/keyword rails (no LLM-based self-check), the value is set to a dummy `not-used` string (from `nemoguardrails-cr.yaml`).
- **ConfigMap embeds all three config files:** The Helm ConfigMap template (`configmap-guardrails.yaml`) embeds the full content of `config.yaml`, `rails.co`, and `actions.py` inline. Updates to the config require a ConfigMap update and pod restart.
- **Compose uses `:ro,z` volume mount:** The config volume is mounted read-only with SELinux relabeling (`:ro,z`) in the compose file, which is necessary for Podman on Fedora/RHEL but may cause issues on non-SELinux systems.
- **Internal service naming divergence:** The compose service is named `guardrails` (accessed at `http://guardrails:8000`) while the Helm Service is named `guardrails-internal` (accessed at `http://guardrails-internal:8000`). The orchestrator's `GUARDRAILS_URL` env var must match the correct name per deployment mode.

## Testing Notes

- Integration tests cover both local-only and cluster-only scenarios, with `@pytest.mark.local_only` and `@pytest.mark.cluster_only` markers
- Local tests validate the `/health` endpoint, safe input passthrough, and blocking of SSN, credit card, and off-topic messages
- Cluster tests verify the ConfigMap contains all three config keys (`config.yaml`, `rails.co`, `actions.py`), the NemoGuardrails CR reaches `Ready` phase, pods are running, and the orchestrator has `GUARDRAILS_URL` pointing to `guardrails-internal:8000`
- Orchestrator-level tests confirm that PII and off-topic messages receive HTTP 422 responses from the `/chat` endpoint

## Related Patterns

- `nemo-guardrails` -- TrustyAI-managed NeMo Guardrails using LLM-based self-check prompts (Approach A) or regex/content-safety model with nginx proxy (Approach B)
- `guardrails-orchestrator` -- dedicated ML detector models with gateway routing instead of nemoguardrails library wrapping
- `flask-backend` -- Flask application patterns used in other quickstart components
