---
name: vendor-integration
description: "Quickstart integrating an ISV AI product with RHOAI model serving via operator or partner blueprint"
summary: "Demonstrates ISV AI product integration with RHOAI model serving via OLM-managed operators, Helm charts, or Ansible-deployed edge components that wrap, proxy, or augment inference — Approach A (f5-ai-guardrails) deploys Calypso AI Moderator proxy via OLM operator for AI-layer content inspection (prompt injection, PII, toxicity, topic enforcement) with dual-panel Streamlit UI and Red Team adversarial testing; Approach B (f5-api-security) deploys F5 Distributed Cloud Customer Edge pods via Ansible for network-layer API security (WAF, OpenAPI spec enforcement against shadow APIs, rate limiting for DoS prevention) with configurable XC URL endpoint switching in Streamlit UI. Choose over rag-chatbot when the primary purpose is evaluating a vendor product (RAG app serves as demo workload being protected/enhanced), and over model-serving-app when wrapping KServe/vLLM with vendor capabilities not in the base RHOAI stack; pick A for AI content-layer security (prompt/response inspection), B for traditional web app/API security (HTTP-level attack prevention). Approach A requires anyuid SCC bindings for F5 namespaces, private registry credentials (harbor.calypsoai.app), and F5 license key with guardrail policies managed via in-cluster Moderator UI across 5 namespaces; Approach B requires F5 XC API token and cluster token for site auto-approval (f5xc_auto_approve: true), HugePages kernel configuration on worker nodes, and dynamic PVC storage class with WAF/API/rate-limit policies managed via F5 XC Console (SaaS) across 2 namespaces (RAG app + ves-system). Medium-to-high complexity because the vendor product adds its own deployment footprint (operators, edge pods, storage, GPU resources) on top of the base RHOAI workload; Approach B CE Prometheus pods hit hostPort binding conflicts on OCP requiring automated patch, site registration needs manual Console approval or API-based auto-approval, and both approaches share LlamaStack + pgvector via ai-architecture-charts as the base RAG stack."
metadata:
  type: archetype
tags:
  tech_stack: [streamlit, llama-stack, postgresql, python, ansible]
  ai_pattern: [guardrails, model-serving, rag]
  platform: [rhoai, openshift, vllm, kserve]
  data_layer: [pgvector]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "F5 AI Guardrails (Calypso AI) operator integration with RHOAI -- OLM-managed operator deploys AI security proxy alongside a LlamaStack RAG workload for prompt/response policy enforcement"
    approach: "A"
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/f5-api-security"
    notes: "F5 Distributed Cloud (XC) WAAP integration with RHOAI -- Ansible-deployed Customer Edge pods provide network-layer API security (WAF, API spec enforcement, rate limiting) for LlamaStack inference endpoints"
    approach: "B"
---

# Vendor Integration

## Overview

A vendor integration quickstart demonstrates how to deploy and operate an ISV (Independent Software Vendor) AI product alongside Red Hat OpenShift AI model serving. The quickstart pairs a working RHOAI application workload (e.g., a RAG chatbot, model serving endpoint) with a partner product that extends the platform with capabilities not built into RHOAI itself -- such as AI-layer security, specialized inference blueprints, or enterprise document processing. On RHOAI, vendor integrations typically use OLM-managed operators or Helm-based deployment of partner components that wrap, proxy, or augment the model serving layer.

## Typical Components

- **Model serving:** KServe + vLLM or LlamaStack for RHOAI-native LLM inference
- **Backend:** Partner product backend (operator-managed or Helm-deployed) providing the vendor-specific capability
- **Frontend:** Demo UI showing the vendor product in action (Streamlit, React, or vendor-provided UI)
- **Data layer:** Application-specific (pgvector, Milvus, etc.) depending on the workload archetype
- **Supporting:** OLM operator or Helm chart for vendor product lifecycle management, private container registry credentials, vendor license keys

## When to Use

- **Business problem:** Evaluating or demonstrating a partner AI product on Red Hat OpenShift AI -- showing how the product integrates with RHOAI model serving, what operational requirements it introduces, and what value it adds to the platform
- **RHOAI capabilities:** Demonstrates RHOAI extensibility through ISV product integration, OLM operator lifecycle, multi-namespace deployment topology, and coexistence of vendor components with RHOAI model serving
- **Scale/complexity:** Medium to high complexity; the vendor product adds its own deployment footprint (operators, namespaces, storage, GPU resources) on top of the base RHOAI workload

## Example Quickstarts

| Quickstart | What It Demonstrates |
|------------|---------------------|
| f5-ai-guardrails | F5 AI Guardrails (Calypso AI) integration -- OLM-managed operator deploys Moderator proxy that intercepts model inference requests/responses for AI-layer content inspection (prompt injection, PII filtering, toxicity scanning, topic enforcement), with dual-panel Streamlit UI comparing guardrailed vs direct LlamaStack access and Calypso AI Red Team for adversarial testing |
| f5-api-security | F5 Distributed Cloud (XC) WAAP integration -- Ansible-deployed Customer Edge pods in ves-system namespace provide network-layer API security (WAF policy for XSS/SQL injection, OpenAPI spec enforcement against shadow APIs, rate limiting for DoS prevention) for LlamaStack inference endpoints, with Streamlit UI supporting configurable XC URL endpoint switching |

## Decision Criteria

### vs rag-chatbot

Pick **vendor-integration** when the primary purpose is demonstrating or evaluating an ISV AI product on RHOAI, where the RAG chatbot (or other workload) serves as the demo application being protected or enhanced by the vendor product. Pick **rag-chatbot** when the primary purpose is building a document-grounded Q&A application and the focus is on the RAG pipeline architecture itself.

### vs model-serving-app

Pick **vendor-integration** when the quickstart wraps RHOAI model serving with a vendor product that adds capabilities (security, observability, specialized inference) not present in the base model serving stack. Pick **model-serving-app** when the focus is on deploying and configuring KServe/vLLM model endpoints without vendor-specific layers.

---

## Approach B: Network-Layer API Security via F5 Distributed Cloud (from f5-api-security)

### When to Use

When the primary objective is demonstrating or enforcing network-layer API security on model inference endpoints -- protecting against web application attacks (XSS, SQL injection), preventing access to undocumented shadow APIs via OpenAPI spec enforcement, and rate limiting to prevent DoS abuse -- using F5 Distributed Cloud (XC) Web App & API Protection (WAAP) deployed as Customer Edge pods within the OpenShift cluster.

### Differences from Approach A

- **Security layer:** Approach A operates at the AI content layer (prompt/response inspection for injection, PII, toxicity, topic violations via Calypso AI Moderator proxy); Approach B operates at the network/HTTP layer (WAF rules, API specification enforcement, rate limiting via F5 XC HTTP Load Balancer) -- the two approaches are complementary and address different threat categories
- **Vendor product:** Approach A integrates F5 AI Guardrails (Calypso AI) as an application-layer proxy; Approach B integrates F5 Distributed Cloud (XC) as a network edge deployment with Customer Edge (CE) pods that discover and proxy cluster services via kube-API
- **Deployment method:** Approach A uses an OLM-managed operator (`f5-ai-security-operator` from `certified-operators` catalog) deployed via Helm; Approach B uses Ansible playbooks (`deploy/ansible/site.yml`) with `kubernetes.core` collection to deploy CE pods, configure HugePages, validate storage, and register the site with F5 XC Console
- **Namespace topology:** Approach A spans 5 namespaces (RAG + 4 F5 operator-managed); Approach B uses 2 namespaces -- the RAG app namespace (Helm) and `ves-system` (Ansible-deployed CE pods including vp-manager, etcd, ver, prometheus)
- **Security policy management:** Approach A configures guardrail policies through the Moderator UI (in-cluster); Approach B configures WAF policies, API definitions, and rate limiting rules through the F5 XC Console (SaaS) -- the included use case guide (`docs/securing_model_inference_use_cases.md`) walks through three scenarios: WAF for XSS protection, API spec enforcement to block shadow APIs, and rate limiting for DoS prevention
- **Infrastructure requirements:** Approach A requires private registry credentials (`harbor.calypsoai.app`) and F5 license key; Approach B requires F5 XC account credentials, API token for site auto-approval (`f5xc_api_token`), cluster token (`f5xc_token`), HugePages kernel configuration on worker nodes, and dynamic PVC storage class for CE pod state
- **SCC requirements:** Approach A requires `anyuid` SCC bindings for F5 namespaces; Approach B deploys CE pods in `ves-system` with standard SCC (no explicit anyuid requirements documented)
- **Frontend integration:** Approach A uses dual-panel Streamlit UI (guardrailed vs direct); Approach B uses a single Streamlit UI with configurable XC URL in the Settings page (`frontend/llama_stack_ui/distribution/ui/page/distribution/models.py`) -- switching between direct LlamaStack endpoint and F5 XC-proxied endpoint to demonstrate before/after security protection
- **Site registration:** Approach B includes a site registration workflow -- CE pods register with F5 XC Console and require approval (manual via Console UI or automated via F5 XC API with `f5xc_auto_approve: true`); Approach A has no equivalent site registration step
- **Prometheus fix:** Approach B includes an automated fix for CE Prometheus `hostPort` binding conflicts on OCP (`deploy/ansible/roles/f5xc_mesh/tasks/poll_prometheus.yml`) -- the playbook patches the Prometheus deployment to remove `hostPort` entries that conflict with OCP security policy

### Typical Components

- **Model serving:** vLLM via ai-architecture-charts `llm-service` subchart (0.5.10) for LLM inference; LlamaStack via ai-architecture-charts `llama-stack` subchart (0.8.6) for RAG orchestration and OpenAI-compatible API
- **Backend:** LlamaStack server providing RAG query/document APIs and model routing; F5 XC Customer Edge pods (`vp-manager`, `etcd`, `ver`, `prometheus`) in `ves-system` namespace for service discovery and traffic proxying
- **Frontend:** Streamlit (`frontend/llama_stack_ui/`) with configurable XC URL in Settings page for endpoint switching between direct and F5 XC-proxied access; chat UI with document collection selection and suggested questions
- **Data layer:** PostgreSQL + pgvector (ai-architecture-charts `pgvector` subchart) for document embeddings and semantic retrieval
- **Supporting:** Ansible playbooks for F5 XC CE deployment (preflight checks, HugePages configuration, storage validation, mesh setup, site registration); F5 XC Console (SaaS) for WAF policy, API definition, and rate limiting configuration; OpenAPI specification file (`deploy/openapi-swagger-v3-fixed2-version.json`) for API enforcement

---

## Choosing Between Approaches

| Criteria | Approach A (AI-Layer Guardrails) | Approach B (Network-Layer API Security) |
|----------|--------------------------------|----------------------------------------|
| Security layer | AI content inspection (prompt/response) | Network/HTTP layer (WAF, API spec, rate limiting) |
| Threat categories | Prompt injection, PII leakage, toxicity, topic violations | XSS, SQL injection, shadow APIs, DoS abuse |
| Vendor product | F5 AI Guardrails (Calypso AI) | F5 Distributed Cloud (XC) WAAP |
| Deployment method | OLM operator via Helm | Ansible playbooks with kubernetes.core |
| Policy management | In-cluster Moderator UI | F5 XC Console (SaaS) |
| Namespace count | 5 (RAG + 4 F5 operator-managed) | 2 (RAG app + ves-system) |
| Infrastructure requirements | Private registry + F5 license key | F5 XC account + API token + HugePages + dynamic PVC |
| Frontend | Dual-panel Streamlit (guardrailed vs direct) | Single Streamlit with configurable XC URL endpoint |
| RAG stack | LlamaStack + pgvector (ai-architecture-charts) | LlamaStack + pgvector (ai-architecture-charts) |
| Best for | Demonstrating AI-specific content security for model inference | Demonstrating traditional web app/API security for AI endpoints |
