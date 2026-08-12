---
name: video-stream
description: "RTSP video stream simulator using MediaMTX and FFmpeg to replay MP4 files from MinIO as live camera feeds"
summary: "Simulates RTSP camera feeds for multimodal AI quickstarts using a three-container pod where an mc-based init container downloads MP4 from MinIO (MC_CONFIG_DIR=/tmp/.mc for OpenShift restricted SCC) into an emptyDir volume, MediaMTX serves RTSP on port 8554/live, and FFmpeg loops video with `-re -stream_loop -1 -c copy` for low-CPU real-time streaming. Set `videoStream.streamUrl` to a real camera URL to skip the entire stack via Helm conditional (`{{- if not .Values.videoStream.streamUrl }}`); compose splits into two services with explicit `MTX_WRITEQUEUESIZE`/`MTX_UDPREADBUFFERSIZE` tuning absent from Helm defaults, and uses a custom Alpine+mc image versus Helm's separate `minio/mc` init + `linuxserver/ffmpeg` sidecar. The init container sets `MC_CONFIG_DIR=/tmp/.mc` for SCC writability, validates `/data/video.mp4` is non-empty for defense-in-depth against silent MinIO download failures, and the backend deployment includes a `wait-for-video-stream` init container using `nc -z` polling against the video-stream service. Helm's FFmpeg sidecar uses a hardcoded `sleep 5` instead of compose's `nc -z` polling for MediaMTX readiness (unreliable if startup exceeds 5s), and the OpenShift RTSP URL in `seed_demo_configs.py` hardcodes a duplicated release name pattern (`ppe-compliance-monitor-ppe-compliance-monitor-video-stream:8554`) that breaks with non-default Helm release names."
metadata:
  type: component
tags:
  tech_stack: [ffmpeg, mediamtx, minio, alpine, shell]
  ai_pattern: [multimodal, data-pipeline]
  platform: [openshift, kubernetes]
  data_layer: [minio]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "In-cluster RTSP video stream simulator for PPE compliance monitoring when no real camera is available"
    approach: "A"
---

# Video Stream

## Overview

Video stream provides a simulated RTSP camera feed for quickstarts that require real-time video input but lack access to a physical camera. It combines MediaMTX (an RTSP server) with FFmpeg (a video re-streamer) and MinIO (object storage for the source MP4 file) into a multi-container pod that loops an MP4 file as a live RTSP stream. The component is conditionally deployed -- when `videoStream.streamUrl` is set to a real camera URL, the entire video-stream stack is skipped.

## Tech Stack & Dependencies
- **Runtime:** Alpine Linux with FFmpeg and netcat; MediaMTX as RTSP server
- **Container images:**
  - `bluenviron/mediamtx:latest` -- RTSP/RTMP/HLS media server
  - `docker.io/linuxserver/ffmpeg:latest` -- FFmpeg publisher (Helm); custom Alpine image with `minio/mc` CLI (compose)
  - `minio/mc:latest` -- MinIO client for video download (init container)
- **Key dependencies:** MinIO for source video storage; downstream backend consumes the RTSP stream
- **Helm subchart:** None -- embedded in the parent `ppe-compliance-monitor` Helm chart templates

## Key Patterns

### Multi-Container Pod with Init Container

The Helm deployment uses a three-container pattern: an init container downloads the MP4 from MinIO, then two sidecar containers run concurrently -- MediaMTX serves the RTSP endpoint and FFmpeg loops the downloaded video into it. An `emptyDir` volume shares the video file between the init container and the FFmpeg container.

```yaml
# deploy/helm/ppe-compliance-monitor/templates/video-stream-deployment.yaml (lines 22-114)
initContainers:
  - name: download-video
    image: "{{ .Values.videoStream.ffmpegImage.repository }}:{{ .Values.videoStream.ffmpegImage.tag }}"
    command:
      - /bin/sh
      - -c
      - |
        set -e
        export MC_CONFIG_DIR=/tmp/.mc
        until mc alias set myminio "${MINIO_ENDPOINT}" "..." "..."; do
          sleep 2
        done
        mc cp "myminio/{{ .Values.storage.video.bucket }}/{{ .Values.storage.video.key }}" /data/video.mp4
    volumeMounts:
      - name: video-data
        mountPath: /data
containers:
  - name: mediamtx
    image: "{{ .Values.videoStream.image.repository }}:{{ .Values.videoStream.image.tag }}"
    ports:
      - containerPort: {{ .Values.videoStream.port }}
        name: rtsp
  - name: ffmpeg
    image: docker.io/linuxserver/ffmpeg:latest
    command:
      - /bin/sh
      - -c
      - |
        exec ffmpeg -re -stream_loop -1 -i /data/video.mp4 \
          -c copy -f rtsp rtsp://localhost:{{ .Values.videoStream.port }}/{{ .Values.videoStream.path }}
    volumeMounts:
      - name: video-data
        mountPath: /data
volumes:
  - name: video-data
    emptyDir: {}
```

### Conditional Deployment via streamUrl Toggle

The entire video-stream Deployment and Service are wrapped in `{{- if not .Values.videoStream.streamUrl }}`. When `streamUrl` is set to a real camera RTSP URL, no video-stream resources are created and the backend connects directly to the external feed. The backend's init container also skips the wait-for-video-stream check when `streamUrl` is set.

```yaml
# deploy/helm/ppe-compliance-monitor/templates/video-stream-deployment.yaml (line 1)
{{- if not .Values.videoStream.streamUrl }}
```

```yaml
# deploy/helm/ppe-compliance-monitor/values.yaml (lines 84-87)
# When empty: deploy in-cluster video-stream stack (MP4 from MinIO)
# When set: use external stream (real camera), do not deploy video-stream
videoStream:
  streamUrl: ""
```

### FFmpeg Infinite Loop Streaming

FFmpeg uses `-stream_loop -1` to loop the video indefinitely and `-re` to read at the native frame rate, simulating a real-time camera. The `-c copy` flag avoids transcoding for low CPU usage. The stream is published to MediaMTX on localhost since both containers share the pod network.

```sh
# app/video-stream-image/stream-from-minio.sh (line 38)
exec ffmpeg -re -stream_loop -1 -i "${VIDEO_PATH}" -c copy -f rtsp "rtsp://${MEDIAMTX_HOST}:${MEDIAMTX_PORT}/live"
```

### Wait-for-Ready Patterns

Both the init container (waiting for MinIO) and the FFmpeg shell script (waiting for MediaMTX) use polling loops with `nc -z` or `mc alias set` before proceeding. The backend deployment also uses an init container to wait for the video-stream service to become reachable.

```yaml
# deploy/helm/ppe-compliance-monitor/templates/backend-deployment.yaml (lines 26-38)
- name: wait-for-video-stream
  image: "{{ .Values.initUtils.busybox.repository }}:{{ .Values.initUtils.busybox.tag }}"
  command:
    - /bin/sh
    - -c
    - |
      echo "Waiting for video-stream service..."
      until nc -z {{ include "ppe-compliance-monitor.fullname" . }}-video-stream {{ .Values.videoStream.port }}; do
        sleep 2
      done
```

### Compose Two-Service Split

In podman-compose, the pattern splits into two services: `video-stream` runs MediaMTX with tuning env vars, and `video-stream-ffmpeg` builds the custom Alpine+mc image that downloads the MP4 from MinIO and streams it. The FFmpeg service depends on both `video-stream` (MediaMTX) and `minio` being ready.

```yaml
# deploy/local/podman-compose.yaml (lines 94-130)
video-stream:
  image: docker.io/bluenviron/mediamtx@sha256:...
  container_name: video-stream
  environment:
    MTX_WRITEQUEUESIZE: "2048"
    MTX_UDPREADBUFFERSIZE: "4194304"
  ports:
    - "8554:8554"

video-stream-ffmpeg:
  build:
    context: ../../app
    dockerfile: video-stream-image/Dockerfile
  depends_on:
    video-stream:
      condition: service_started
    minio:
      condition: service_healthy
  environment:
    MEDIAMTX_HOST: video-stream
    MEDIAMTX_PORT: "8554"
```

### OpenShift vs Compose RTSP Hostname

The seed script dynamically resolves the in-cluster RTSP URL based on whether it is running on OpenShift (long Helm-generated hostname) or in a compose environment (short service name).

```python
# app/backend/seed_demo_configs.py (lines 155-159)
def _default_rtsp_live_url():
    """In-cluster MediaMTX path used by video-stream; OpenShift vs compose hostnames differ."""
    openshift = os.getenv("OPENSHIFT", "false").lower() == "true"
    if openshift:
        return "rtsp://ppe-compliance-monitor-ppe-compliance-monitor-video-stream:8554/live"
    return "rtsp://video-stream:8554/live"
```

## Configuration
- **Environment variables (FFmpeg publisher / shell script):**
  - `MINIO_ENDPOINT` -- MinIO server URL (default: `http://minio:9000`)
  - `MINIO_ACCESS_KEY` -- MinIO access key (default: `minioadmin`)
  - `MINIO_SECRET_KEY` -- MinIO secret key (default: `minioadmin`)
  - `MINIO_VIDEO_BUCKET` -- bucket containing the source video (default: `data`)
  - `MINIO_VIDEO_KEY` -- object key of the MP4 file (default: `combined-video-no-gap-rooftop.mp4`)
  - `MEDIAMTX_HOST` -- hostname of the MediaMTX server (default: `video-stream`)
  - `MEDIAMTX_PORT` -- RTSP port (default: `8554`)
- **Environment variables (MediaMTX tuning):**
  - `MTX_WRITEQUEUESIZE` -- MediaMTX write queue size (compose default: `2048`, Helm: optional)
  - `MTX_UDPREADBUFFERSIZE` -- UDP read buffer size (compose default: `4194304`, Helm: optional)
- **Helm values:**
  - `videoStream.streamUrl` -- set to real camera URL to skip deploying video-stream entirely
  - `videoStream.image.repository` / `.tag` -- MediaMTX container image (default: `bluenviron/mediamtx:latest`)
  - `videoStream.ffmpegImage.repository` / `.tag` -- init container image for mc download (default: `minio/mc:latest`)
  - `videoStream.port` -- RTSP port (default: `8554`)
  - `videoStream.path` -- RTSP stream path (default: `live`)
  - `videoStream.mediamtx.writeQueueSize` / `.udpReadBufferSize` -- optional MediaMTX tuning
  - `storage.video.bucket` / `.key` -- MinIO bucket and object key for the source MP4

## Known Gotchas
- The Helm deployment uses `docker.io/linuxserver/ffmpeg:latest` for the FFmpeg sidecar container, while the compose build uses a custom Alpine image with `minio/mc` baked in (`app/video-stream-image/Dockerfile`). The Helm deployment separates the mc download into an init container using the `minio/mc` image instead.
- The init container sets `MC_CONFIG_DIR=/tmp/.mc` (line 30 of `video-stream-deployment.yaml`) because the default `~/.mc` path is not writable under OpenShift's restricted SCC.
- The FFmpeg sidecar in the Helm deployment uses a hardcoded `sleep 5` (line 106 of `video-stream-deployment.yaml`) to wait for MediaMTX, while the shell script in the compose image uses a proper `nc -z` polling loop (line 31 of `stream-from-minio.sh`). The sleep-based wait is less reliable if MediaMTX takes longer than 5 seconds to start.
- The init container validates that `/data/video.mp4` is non-empty after download (`if [ ! -s /data/video.mp4 ]`) and the FFmpeg container also checks before streaming, providing defense-in-depth against silent download failures.
- The OpenShift RTSP URL in `seed_demo_configs.py` is hardcoded to `ppe-compliance-monitor-ppe-compliance-monitor-video-stream:8554` (duplicated release name), which will break if the Helm release name or chart name differs from the expected pattern.
- The compose service sets explicit MediaMTX tuning values (`MTX_WRITEQUEUESIZE: "2048"`, `MTX_UDPREADBUFFERSIZE: "4194304"`) while the Helm values default these to empty strings (use MediaMTX defaults). This means compose and cluster deployments may behave differently under load.

## Testing Notes
- Verify MediaMTX is serving: `nc -z <video-stream-host> 8554` or `ffprobe rtsp://<host>:8554/live`
- Check init container logs for download success: `oc logs <pod> -c download-video`
- Check FFmpeg sidecar logs for streaming status: `oc logs <pod> -c ffmpeg`
- To use a real camera instead, set `videoStream.streamUrl` in Helm values and verify the video-stream Deployment and Service are not created
- The backend init container `wait-for-video-stream` should complete within a few seconds once MediaMTX is healthy

## Related Patterns
- Architecture: Multimodal AI pipeline with real-time video input
- Deployment: Multi-container pod with init container for data preparation
- Deployment: Conditional resource creation via Helm value toggles
