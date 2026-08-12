---
name: helm-video-stream-minio-download-ffmpeg-mediamtx-sidecar
description: Helm Deployment with init container downloading video from MinIO and two sidecar containers (MediaMTX + FFmpeg) creating an RTSP stream
summary: "Solves in-cluster RTSP video stream simulation for development/demos using a Helm-templated Deployment with an mc CLI init container (downloads MP4 from MinIO with retry and non-zero-size validation), dual sidecars (MediaMTX RTSP server tunable via MTX_WRITEQUEUESIZE, and FFmpeg loop publisher), sharing an emptyDir volume — conditionally deployed only when videoStream.streamUrl is empty. Use when demos need a simulated camera without external hardware; skip by setting videoStream.streamUrl to a real camera URL; configure stream endpoint via videoStream.port (default 8554) and videoStream.path (default \"live\"). Critical pattern: FFmpeg adds sleep 5 before streaming since sidecar ordering lacks healthchecks; the backend adds a wait-for-video-stream init container polling via nc -z; MC_CONFIG_DIR=/tmp/.mc is required because OpenShift arbitrary UIDs cannot write to ~/.mc. Common gotcha: the ffmpegImage values key confusingly names the mc init container image (not the actual FFmpeg container which uses linuxserver/ffmpeg:latest); the backend Route needs haproxy.router.openshift.io/timeout: 1h for long-lived MJPEG connections; the init container validates downloads with both file existence and [ ! -s ] checks to catch silent mc failures."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, minio]
  ai_pattern: [multimodal]
  platform: [openshift]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Video stream Deployment with mc init container, MediaMTX + FFmpeg sidecars, conditional creation based on videoStream.streamUrl"
    approach: "A"
---

# Video Stream Deployment: MinIO Download Init + FFmpeg/MediaMTX Sidecars

## Overview

A Helm-templated Deployment that creates an in-cluster RTSP video stream by combining an init container (downloads video from MinIO using `mc` CLI), a MediaMTX RTSP server container, and an FFmpeg container that loops the downloaded video as a live RTSP source. The entire Deployment is conditionally created only when no external camera stream URL is configured.

## Pattern Description

This pattern simulates a live camera feed for development and demos by downloading a pre-uploaded MP4 from MinIO and streaming it on a loop via FFmpeg to MediaMTX. The Deployment is conditionally rendered (`{{- if not .Values.videoStream.streamUrl }}`) so that when a real camera URL is provided, the simulated stream pod is not deployed. The init container handles MinIO authentication with retry logic, and the FFmpeg sidecar validates the downloaded file before starting the stream.

## Implementation

### Conditional Deployment

The Deployment only creates when no external stream URL is set:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/video-stream-deployment.yaml
{{- if not .Values.videoStream.streamUrl }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "ppe-compliance-monitor.fullname" . }}-video-stream
```

### Init Container: MinIO Download with Retry

The init container uses `minio/mc` to download the video file from MinIO to an emptyDir volume, with retry logic for MinIO alias setup:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/video-stream-deployment.yaml (init)
initContainers:
  - name: download-video
    image: "{{ .Values.videoStream.ffmpegImage.repository }}:{{ .Values.videoStream.ffmpegImage.tag }}"
    command:
      - /bin/sh
      - -c
      - |
        set -e
        export MC_CONFIG_DIR=/tmp/.mc
        SRC="myminio/{{ .Values.storage.video.bucket }}/{{ .Values.storage.video.key }}"
        until mc alias set myminio "${MINIO_ENDPOINT}" "{{ .Values.minio.secret.user }}" "{{ .Values.minio.secret.password }}"; do
          sleep 2
        done
        if ! mc stat "${SRC}"; then
          echo "[download-video] mc stat failed"
          exit 1
        fi
        mc cp "${SRC}" /data/video.mp4
        if [ ! -s /data/video.mp4 ]; then
          echo "[download-video] ERROR: /data/video.mp4 missing or empty after mc cp"
          exit 1
        fi
    volumeMounts:
      - name: video-data
        mountPath: /data
```

### Dual Sidecar Containers

Two containers run in the pod: MediaMTX as the RTSP server and FFmpeg as the video publisher:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/video-stream-deployment.yaml (containers)
containers:
  - name: mediamtx
    image: "{{ .Values.videoStream.image.repository }}:{{ .Values.videoStream.image.tag }}"
    {{- if or $wq $ur }}
    env:
      {{- if $wq }}
      - name: MTX_WRITEQUEUESIZE
        value: {{ $wq | quote }}
      {{- end }}
    {{- end }}
    ports:
      - containerPort: {{ .Values.videoStream.port }}
        name: rtsp
  - name: ffmpeg
    image: docker.io/linuxserver/ffmpeg:latest
    command:
      - /bin/sh
      - -c
      - |
        if [ ! -f /data/video.mp4 ]; then
          exit 1
        fi
        sleep 5
        exec ffmpeg -re -stream_loop -1 -i /data/video.mp4 \
          -c copy -f rtsp rtsp://localhost:{{ .Values.videoStream.port }}/{{ .Values.videoStream.path }}
    volumeMounts:
      - name: video-data
        mountPath: /data
volumes:
  - name: video-data
    emptyDir: {}
```

### Backend Init Container Waits for Video Stream

The backend Deployment conditionally adds an init container that waits for the video stream service to be ready:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/backend-deployment.yaml (excerpt)
{{- $waitVideo := not .Values.videoStream.streamUrl }}
{{- if $waitVideo }}
initContainers:
  - name: wait-for-video-stream
    image: "{{ .Values.initUtils.busybox.repository }}:{{ .Values.initUtils.busybox.tag }}"
    command:
      - /bin/sh
      - -c
      - |
        until nc -z {{ include "ppe-compliance-monitor.fullname" . }}-video-stream {{ .Values.videoStream.port }}; do
          sleep 2
        done
{{- end }}
```

## Configuration

- **Key settings:** `videoStream.streamUrl` (empty = deploy simulated stream; set = use external camera, skip deployment); `videoStream.port` (RTSP port, default 8554); `videoStream.path` (RTSP path, default "live"); `videoStream.mediamtx.writeQueueSize` and `udpReadBufferSize` for MediaMTX tuning
- **Defaults:** MediaMTX uses `bluenviron/mediamtx:latest`; FFmpeg image uses `minio/mc:latest` for the init container (reused for mc CLI); video source defaults to `data/combined-video-no-gap-rooftop.mp4` in MinIO
- **Dependencies:** MinIO must contain the video file (uploaded by the init-data Job); the emptyDir volume is shared between init and runtime containers

## Gotchas

- The FFmpeg container adds a `sleep 5` before starting the stream to give MediaMTX time to initialize, since there is no healthcheck-based ordering between sidecar containers in the same pod
- The init container validates the download by checking both file existence and non-zero size (`[ ! -s /data/video.mp4 ]`), protecting against silent mc failures
- `MC_CONFIG_DIR=/tmp/.mc` is set because the default `~/.mc` may not be writable under OpenShift's arbitrary UID
- The `minio/mc` image is used for the init container (reused from `videoStream.ffmpegImage`) even though it is named `ffmpegImage` in values -- the actual ffmpeg container uses `linuxserver/ffmpeg:latest`
- The OpenShift Route for the backend has `haproxy.router.openshift.io/timeout: 1h` annotation (in `openshift-backend-route.yaml`) specifically for long-lived MJPEG streaming connections

## Related Patterns

- `container-build-multistage-7z-yolo-export-minio-upload.md` -- uploads the video files that this deployment downloads from MinIO
