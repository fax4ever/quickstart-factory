---
name: event-driven-ai-app
description: "Event-driven data pipeline that correlates streaming data and applies LLM analysis at enrichment points"
summary: "Processes streaming data (telemetry, logs, events, IoT) through deterministic integration routes that ingest, transform, correlate, and enrich events, then apply LLM analysis at specific pipeline stages for automated root cause analysis, anomaly explanation, or pattern detection -- no vector database or custom model training required. Choose over agentic-app when the LLM analyzes pre-correlated structured context without tool calling or multi-step reasoning; over rag-chatbot when context comes from streaming correlation (Kafka + Infinispan trace-ID grouping) not vector similarity search; over model-serving-app when end-to-end pipeline matters beyond model deployment; over ml-pipeline-app when using pre-trained LLMs. Reference implementation (smart-telemetry-pipeline) uses three Apache Camel Quarkus apps: correlator ingesting OpenTelemetry via Kafka with Kaoto XSLT data mapping and Infinispan trace-ID grouping, analyzer invoking Granite LLM via Camel's OpenAI component with Micrometer timer/counter metrics, and UI console with PVC-backed file persistence, per-trace Infinispan prompt cache, and interactive re-analysis via JMS/Artemis queues. Runs on Developer Sandbox shared compute with RHOAI shared models (no dedicated GPU); pipeline observability requires Prometheus ServiceMonitors and PrometheusRules; Tekton pipelines handle application builds; the LLM is a passive analysis step receiving pre-processed data, not an autonomous agent driving workflow decisions."
metadata:
  type: archetype
tags:
  tech_stack: [apache-camel, quarkus, kafka, infinispan, artemis, opentelemetry, kaoto]
  ai_pattern: [data-pipeline, model-serving]
  platform: [rhoai, openshift]
  data_layer: [infinispan]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Observability pipeline that ingests OpenTelemetry logs and traces via Kafka, correlates them by trace ID in Infinispan using Apache Camel routes, and sends correlated context to a Granite LLM (OpenShift AI shared model) for automated root cause analysis with interactive re-analysis via embedded web console"
    approach: "A"
---

# Event-Driven AI App

## Overview

An event-driven AI app processes streaming data through a deterministic pipeline -- ingesting, transforming, correlating, and enriching events -- then applies LLM analysis at specific points in the pipeline to produce AI-powered insights from the processed data. Unlike agentic apps where an agent reasons and dispatches tools, the pipeline logic is deterministic (defined by integration routes, stream processors, or workflow engines) and the LLM acts as an analysis step receiving pre-processed data rather than driving the workflow. On RHOAI, this pattern leverages model serving for LLM inference while the integration framework handles data flow, transformation, and correlation across message brokers and caches.

## Typical Components

- **Model serving:** OpenShift AI shared models or KServe + vLLM for LLM inference via OpenAI-compatible API, called at specific analysis points in the pipeline
- **Backend:** Integration framework (Apache Camel, Flink, Spark Streaming) defining deterministic routes for data ingestion, transformation, correlation, and LLM invocation -- no custom Python/Java application logic beyond route definitions
- **Frontend:** Lightweight web console (embedded HTML UI or standalone dashboard) for reviewing AI-generated analysis results and optionally triggering interactive re-analysis with custom prompts
- **Data layer:** In-memory data grid (Infinispan) or streaming cache for transient event correlation and grouping, with file-based or database persistence for analysis results -- no vector database required
- **Supporting:** Message brokers (Kafka for ingestion, JMS/Artemis for internal routing), OpenTelemetry Collector for telemetry ingestion, Prometheus ServiceMonitors and PrometheusRules for pipeline observability, Tekton pipelines for application builds

## When to Use

- **Business problem:** Automating the analysis of streaming data (telemetry, logs, events, IoT signals, transactions) where the value is in correlating related signals across a distributed system and applying AI to generate actionable insights -- such as root cause analysis, anomaly explanation, event summarization, or pattern detection -- without requiring human experts to manually sift through raw data
- **RHOAI capabilities:** Demonstrates OpenShift AI model serving for LLM inference integrated into an event-driven architecture, showing how AI analysis can be embedded as a stage in enterprise integration pipelines rather than as a standalone chatbot or agent
- **Scale/complexity:** Low to medium complexity; suitable for the Red Hat Developer Sandbox with shared compute resources and pre-provisioned shared models -- the pipeline components (Kafka, Infinispan, Artemis, Camel apps) run as lightweight containers without dedicated GPU requirements

## Example Quickstarts

| Quickstart | What It Demonstrates |
|------------|---------------------|
| smart-telemetry-pipeline | Observability pipeline with three Apache Camel (Quarkus) applications: a correlator that ingests OpenTelemetry logs and traces from Kafka and groups them by trace ID in Infinispan (with Kaoto data mapper XSLT transformations), an analyzer that retrieves correlated events and calls a Granite LLM via Camel's OpenAI component for root cause analysis (with Micrometer timer/counter metrics), and a UI console that persists results to PVC-backed file storage and provides REST APIs for trace browsing, custom per-trace prompt management via Infinispan cache, and interactive re-analysis via JMS request queues |

## Decision Criteria

### vs agentic-app

Pick **event-driven-ai-app** when the data processing pipeline is deterministic (integration routes, stream processors) and the LLM is called at specific enrichment points to analyze pre-correlated data without tool calling, multi-step reasoning, or agent orchestration. The LLM receives structured context and produces analysis text -- it does not decide what to do next. Pick **agentic-app** when the LLM drives the workflow through tool dispatch, function calling, or multi-step reasoning via an agent framework (LangGraph, LlamaStack, CrewAI).

### vs rag-chatbot

Pick **event-driven-ai-app** when the LLM analyzes live streaming data (telemetry, events, transactions) that flows through message brokers and correlation caches, not documents uploaded by users and embedded in a vector database. There is no retrieval-augmented generation -- the context comes from the pipeline's correlation step, not from vector similarity search. Pick **rag-chatbot** when the primary interaction is document-grounded Q&A where users upload documents that are chunked, embedded, and retrieved to augment LLM prompts.

### vs model-serving-app

Pick **event-driven-ai-app** when a full application pipeline (ingestion, transformation, correlation, analysis, result persistence, UI) surrounds the model serving endpoint and the value is in the end-to-end data flow, not just model deployment. Pick **model-serving-app** when the focus is on deploying and configuring KServe/vLLM model endpoints with optional orchestration layers but without a custom data processing pipeline.

### vs ml-pipeline-app

Pick **event-driven-ai-app** when the pipeline processes streaming operational data in real-time using a pre-trained LLM for analysis (no custom model training). Pick **ml-pipeline-app** when the pipeline trains custom ML models via Kubeflow Pipelines with feature engineering, batch scoring, and model lifecycle management.
