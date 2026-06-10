# Emby

Media server (LinuxServer.io image) running on the `sprigatito` worker
(node label `kubernetes.io/hostname=sprigatito`, NVIDIA GTX 1650, 4 GiB
VRAM, `runtimeClassName: nvidia`). The chart pins the Emby tag to a
known-good LSIO build rather than `beta`/`latest`, applies a runtime
patch to Emby's `encoding.xml` to fix a recurring audio-transcode
crash, and runs a CronJob to clean up `/config/transcoding-temp/`
session directories that Emby itself fails to garbage-collect.

## Why this chart looks the way it does

### 1. Image is pinned, not `beta`

`tag: 4.9.5.0-ls282` rather than `beta`. The `beta` tag follows
Emby's 4.10 pre-releases. 4.10 ships an ffmpeg wrapper change that
narrowed the audio muxer's packet-queue tolerance; combined with
the EAC3→AC3 audio path that the LSIO image defaults to, this
produces the "Too many packets buffered for output stream 1:1"
crash described in (2) below. The 4.9 LTS line does not have this
regression. Bump deliberately after a playback soak test on a
non-primary client.

### 2. Audio transcoder crashes → playback re-buffers

**Symptom:** Emby buffers constantly during playback, regardless of
quality setting.

**Actual cause** (reproduced on 2026-06-10 by inspecting
`/config/logs/ffmpeg-transcode-*.txt` on the running pod):

```
11:13:24.000 Too many packets buffered for output stream 1:1.
11:13:24.259 Conversion failed!
11:13:24.259 EXIT
```

This fires every 5–10 minutes during a 4K HEVC→H.264 transcode
session. EAC3 5.1 audio is being re-encoded to AC3 5.1 at 384 kbps.
AC3 frames are rigid 32 ms packets, but the segment muxer emits on
3-second video boundaries. ffmpeg's default `max_muxing_queue_size`
is 1000 packets; the audio queue grows unbounded waiting for the
next segment boundary, hits the limit, and aborts. Every abort
forces Emby to start a fresh ffmpeg process, which the player
perceives as a stall → re-buffer.

**GPU and NVENC are not the problem.** `nvidia-smi` in the running
pod shows the GPU at 0% utilisation and 1 MiB VRAM used between
sessions; ffmpeg logs show NVDEC → scale_cuda → NVENC with all
"WillDoInHW: True" entries. The pipeline produces 3-second segments
in ~250 ms (12× real-time). The audio muxer aborts, not the
encoder.

**Fix** (see `templates/configmap.yaml`):

- `EnableThrottling=false` removes the BySegmentRequest lockstep
  that synchronises the audio queue with the video segment
  boundary.
- `ThrottleBufferSize=60`, `ThrottleHysteresis=4` (was 120/8) so
  even if throttling is later re-enabled, the queue is smaller.
- `HardwareAccelerationMode=2` (NVENC) explicitly, not the
  "1 = disabled" sentinel that some Emby versions wrote.
- `EnableSoftwareToneMapping=false` — the LSIO image does not
  ship the software tone-map libraries and toggling this on just
  produces a "no path" warning per segment.
- `H264Crf=20` (was 23) — small quality win on NVENC at no
  measurable perf cost.
- `TranscodingTempPath=/config/transcoding-temp` — matches where
  ffmpeg actually writes (Emby ignores the hostPath volume; see 4).

The patch is applied via a `postStart` lifecycle hook that copies
`/config-patch/encoding.xml` (from the `emby-config-patch`
ConfigMap) over `/config/config/encoding.xml` on every pod start.
The file remains owned by Emby post-start, so the user can still
tweak settings in the Web UI and have them persist.

### 3. `/config/transcoding-temp/` accumulates session directories

**Symptom:** the 40 GiB `/config` RWO PVC was at 71% (12 GiB free)
on 2026-06-10 with **17 GiB of leftover transcode session
directories** ranging from 64 MiB to 4.9 GiB each. Emby's built-in
"ffmpeg cleanup" task is unreliable; it only runs on a timer that
frequently misses.

**Fix:**

- `templates/cronjob.yaml` — a `CronJob` that runs every 30 minutes
  on `sprigatito`, mounting the `emby-original-data` PVC
  read-write, and removing session directories whose `.m3u8` was
  last modified more than 30 s ago and whose mtime is older than
  `EMBY_TRANSCODE_TEMP_MAX_AGE_HOURS` (default 2).
- The same cleanup script is also run as a one-shot in the
  pod's `postStart` hook so the first 17 GiB is purged on the
  very first restart after this chart is applied.

The script intentionally does **not** touch the most recent
`.m3u8` modified in the last 30 s, so a long-running transcode
session is not disturbed.

### 4. The unused `hostPath: /emby/transcode` volume is removed

The original chart declared a `hostPath` on
`/emby/transcode` (sprigatito's local SSD, 63 GiB total, 83% used).
Inspection of the running pod showed:

- The directory does not exist on the node (kubelet auto-creates
  it as an empty dir at mount time).
- Emby ignores the volume. ffmpeg writes to
  `/config/transcoding-temp/` (inside the PVC) regardless of the
  `TranscodingTempPath` setting in `encoding.xml`.
- The volume therefore took up no space but was misleadingly
  suggesting transcode work was on local SSD when it was on Ceph
  RBD.

This chart removes the volume. The cleanup CronJob (3) is the
real solution to "transcode temp filling up".

### 5. Health probes use `pgrep`, not TCP

The Emby server listens on 8096 (HTTP) and 8920 (HTTPS), and
internally opens several other ports for the dashboard, plugin
host, and SSDP. A TCP-socket probe on 8096 flaps when a transcode
session pins the .NET thread pool, especially under the audio
crash loop in (2). An `exec` probe matching `EmbyServer\.dll`
is reliable and matches the doplarr chart's pattern.

`startupProbe` failureThreshold is 60 × periodSeconds 5 = 5 min,
which covers the first-boot metadata-library scan on a large
library. `livenessProbe` initialDelaySeconds 120 gives Emby
time to bind its sockets before the kubelet starts killing on
probe failure.

## Upgrading the image

```bash
# 1. Find the latest stable 4.9.x LSIO build:
curl -s https://hub.docker.com/v2/repositories/linuxserver/emby/tags/ \
  | python3 -c "import json,sys; [print(t['name'],t['last_updated'][:10]) for t in json.load(sys.stdin)['results'] if 'beta' not in t['name'] and '4.9' in t['name']]"

# 2. Bump the tag in values.yaml and commit
$EDITOR values.yaml   # change `tag: 4.9.5.0-ls282`

# 3. Commit + push
cd /home/echo/Documents/Github/homelab
git add apps/emby/
git commit -m "chore(emby): bump to 4.9.X.Y-lsNNN"
git push gitea master

# 4. ArgoCD resyncs automatically. Watch for the postStart hook
#    to log "[emby-patch] installed patched encoding.xml":
kubectl logs -n emby -l app.kubernetes.io/name=emby -c main --tail=50

# 5. Confirm the patch took:
kubectl -n emby exec -it deploy/emby -c main -- \
  grep -E '(EnableThrottling|TranscodingTempPath|HardwareAccelerationMode)' \
  /config/config/encoding.xml
```

## Verifying the fix is in place

After `kubectl get pods -n emby` shows the new pod `Ready 1/1`:

```bash
# 1. encoding.xml is patched
kubectl -n emby exec deploy/emby -c main -- \
  grep -E 'EnableThrottling|HardwareAccelerationMode|ThrottleBufferSize' \
  /config/config/encoding.xml
# Expected:
#   <EnableThrottling>false</EnableThrottling>
#   <HardwareAccelerationMode>2</HardwareAccelerationMode>
#   <ThrottleBufferSize>60</ThrottleBufferSize>

# 2. No ffmpeg crash in the last 10 minutes
kubectl -n emby exec deploy/emby -c main -- \
  find /config/logs -name 'ffmpeg-transcode-*.txt' -newer /tmp -mmin -10 \
  -exec grep -l 'Too many packets buffered' {} +
# Expected: no output (no crashes in the last 10 min)

# 3. /config/transcoding-temp stays small
kubectl -n emby exec deploy/emby -c main -- du -sh /config/transcoding-temp
# Expected: under 5 GiB after a normal day of use

# 4. CronJob ran recently
kubectl get jobs -n emby -l app.kubernetes.io/component=transcode-temp-cleanup
```

If (2) still fires, capture the failing `ffmpeg-transcode-*.txt`
and the matching `embyserver.txt` lines around the timestamp; the
audio codec will be in the ffmpeg command line
(`-c:a:0 <codec>`) and the offending audio frame size in the last
"Conversion failed" segment.
