---
name: multimodal-app
description: "AI app processing multiple data modalities (video, image, audio, text) with CV and LLM on RHOAI"
summary: "Covers AI applications that process non-text modalities (video streams, images, audio, sensor data) with specialized perception models (YOLO/Ultralytics via OVMS or KServe/Triton with OpenVINO) and provide LLM-powered conversational access to detection results on RHOAI/OpenShift. Choose over agentic-app when real-time perception of non-text data is the primary function (not agent reasoning/tool dispatch), over model-serving-app when a full pipeline (ingestion, inference, tracking, persistence, visualization) surrounds the served models, and over rag-chatbot when insights come from CV analysis rather than document retrieval. Typical stack pairs Flask/FastAPI backend with React monitoring dashboard, PostgreSQL-persisted detection data, BoxMOT/BoostTrack++ multi-object tracking, LangGraph router pipelines with MCP postgres-mcp SQL tools for structured querying, MinIO for media/model storage, DeepEval LLM-as-judge evaluation, and optional Arize Phoenix tracing. Medium-to-high complexity due to integrating real-time perception, tracking, persistence, and LLM layers across multiple serving runtimes — the reference implementation (multimodal-compliance-monitor) demonstrates dual OVMS and KServe/Triton runtime support with optional Label Studio annotation and Jupyter-based custom model training."
metadata:
  type: archetype
tags:
  tech_stack: [flask, react, postgresql, python, langchain, langgraph, opencv, mcp, openai-sdk, minio, boxmot, ultralytics]
  ai_pattern: [multimodal, model-serving, agents, evaluation, tool-calling, object-detection, video-analytics, observability]
  platform: [rhoai, openshift, openvino, kserve, triton]
  data_layer: [postgresql]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Real-time video analytics combining YOLO object detection (OVMS or KServe/Triton) with LLM-powered conversational insights (LangGraph router + MCP postgres-mcp SQL tools), multi-object tracking (BoxMOT/BoostTrack++), React monitoring dashboard, DeepEval LLM-as-judge evaluation, and optional Label Studio annotation"
    approach: "A"
---

# Multimodal App

## Overview

A multimodal app processes multiple data modalities -- such as video streams, images, audio, or sensor data -- alongside text-based LLM interactions to produce AI-powered insights. Unlike agentic apps where the primary function is tool-calling agent orchestration, the primary function here is real-time or batch processing of non-text modalities using specialized AI models (object detection, classification, segmentation), with an LLM layer providing conversational access to the processed results. On RHOAI, these apps leverage model serving infrastructure for both specialized CV/perception models and general-purpose LLMs.

## Typical Components

- **Model serving:** OVMS or KServe/Triton for computer vision model inference (object detection, classification), plus an OpenAI-compatible LLM endpoint for conversational insights
- **Backend:** Flask or FastAPI handling video/image processing pipelines, inference orchestration, and chat endpoints
- **Frontend:** React dashboard for real-time monitoring with detection overlays, video feeds, and conversational chat
- **Data layer:** PostgreSQL for persisting detection results (tracks, observations, classes), configuration, and structured analytics data
- **Supporting:** MinIO for media and model storage, multi-object tracking (BoxMOT), LangGraph/LangChain for conversational pipelines, MCP tools for structured data querying, Arize Phoenix for LLM tracing

## When to Use

- **Business problem:** Monitoring, analyzing, or extracting insights from non-text data sources (live video feeds, uploaded media, sensor streams) where AI models detect, classify, or track objects/events and an LLM provides human-friendly conversational access to the detection results
- **RHOAI capabilities:** Demonstrates model serving for specialized perception models (OVMS, KServe/Triton), OpenAI-compatible LLM integration, real-time inference pipelines, and multi-modal AI composition on OpenShift
- **Scale/complexity:** Medium to high complexity; suitable when the application combines real-time perception (CV, audio, etc.) with LLM-powered analytics and requires persistent storage of detection data for historical querying

## Example Quickstarts

| Quickstart | What It Demonstrates |
|------------|---------------------|
| multimodal-compliance-monitor | Real-time workplace safety monitoring combining YOLO object detection (OVMS or KServe/Triton with dual runtime support) with LangGraph-orchestrated conversational analytics (router pipeline with MCP postgres-mcp SQL tools), multi-object tracking (BoxMOT/BoostTrack++), React dashboard with detection overlays, PostgreSQL-persisted detection data, DeepEval LLM-as-judge evaluation, optional Arize Phoenix tracing, optional Label Studio annotation, and custom model training via Jupyter notebooks |

## Decision Criteria

### vs agentic-app

Pick **multimodal-app** when the primary function is processing non-text modalities (video, images, audio) with specialized AI models and the LLM/agent layer provides conversational access to the processed results. Pick **agentic-app** when the primary function is agent-based reasoning, tool dispatch, and multi-step workflows, regardless of the data modality.

### vs model-serving-app

Pick **multimodal-app** when the application includes a full processing pipeline (ingestion, inference, tracking, persistence, visualization) around the served models, not just model deployment and exposure. Pick **model-serving-app** when the focus is on deploying and configuring model endpoints without an application stack.

### vs rag-chatbot

Pick **multimodal-app** when the AI insights come from real-time perception of non-text data (video/image analysis), not from retrieval over a text document corpus. Pick **rag-chatbot** when the primary interaction is document-grounded Q&A via vector search.
