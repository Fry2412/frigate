---
id: record
title: Recording
---

import ConfigTabs from "@site/src/components/ConfigTabs";
import TabItem from "@theme/TabItem";
import NavPath from "@site/src/components/NavPath";

Recordings can be enabled and are stored at `/media/frigate/recordings`. The folder structure for the recordings is `YYYY-MM-DD/HH/<camera_name>/MM.SS.mp4` in **UTC time**. These recordings are written directly from your camera stream without re-encoding. Each camera supports a configurable retention policy. Frigate chooses the largest matching retention value between the recording retention and the tracked object retention when determining if a recording should be removed.

New recording segments are written from the camera stream to cache, they are only moved to disk if they match the setup recording retention policy.

H265 recordings can be viewed in Chrome 108+, Edge and Safari only. All other browsers require recordings to be encoded with H264.

## Common recording configurations

### Most conservative: Ensure all video is saved

For users deploying Frigate in environments where it is important to have contiguous video stored even if there was no detectable motion, the following configuration will store all video for 3 days. After 3 days, only video containing motion will be saved for 7 days. After 7 days, only video containing motion and overlapping with alerts or detections will be retained until 30 days have passed.

<ConfigTabs>
<TabItem value="ui">

Navigate to <NavPath path="Settings > Global configuration > Recording" />.

- Set **Enable recording** to on
- Set **Continuous retention > Retention days** to `3`
- Set **Motion retention > Retention days** to `7`
- Set **Alert retention > Event retention > Retention days** to `30`
- Set **Alert retention > Event retention > Retention mode** to `all`
- Set **Detection retention > Event retention > Retention days** to `30`
- Set **Detection retention > Event retention > Retention mode** to `all`

</TabItem>
<TabItem value="yaml">

```yaml
record:
  enabled: True
  continuous:
    days: 3
  motion:
    days: 7
  alerts:
    retain:
      days: 30
      mode: all
  detections:
    retain:
      days: 30
      mode: all
```

</TabItem>
</ConfigTabs>

### Reduced storage: Only saving video when motion is detected

To reduce storage requirements, configure recording to only retain video where motion or activity was detected.

<ConfigTabs>
<TabItem value="ui">

Navigate to <NavPath path="Settings > Global configuration > Recording" />.

- Set **Enable recording** to on
- Set **Motion retention > Retention days** to `3`
- Set **Alert retention > Event retention > Retention days** to `30`
- Set **Alert retention > Event retention > Retention mode** to `motion`
- Set **Detection retention > Event retention > Retention days** to `30`
- Set **Detection retention > Event retention > Retention mode** to `motion`

</TabItem>
<TabItem value="yaml">

```yaml
record:
  enabled: True
  motion:
    days: 3
  alerts:
    retain:
      days: 30
      mode: motion
  detections:
    retain:
      days: 30
      mode: motion
```

</TabItem>
</ConfigTabs>

### Minimum: Alerts only

If you only want to retain video that occurs during activity caused by tracked object(s), this configuration will discard video unless an alert is ongoing.

<ConfigTabs>
<TabItem value="ui">

Navigate to <NavPath path="Settings > Global configuration > Recording" />.

- Set **Enable recording** to on
- Set **Continuous retention > Retention days** to `0`
- Set **Alert retention > Event retention > Retention days** to `30`
- Set **Alert retention > Event retention > Retention mode** to `motion`

</TabItem>
<TabItem value="yaml">

```yaml
record:
  enabled: True
  continuous:
    days: 0
  alerts:
    retain:
      days: 30
      mode: motion
```

</TabItem>
</ConfigTabs>

## Will Frigate delete old recordings if my storage runs out?

As of Frigate 0.12 if there is less than an hour left of storage, the oldest 2 hours of recordings will be deleted.

## Configuring Recording Retention

Frigate supports both continuous and tracked object based recordings with separate retention modes and retention periods.

:::tip

Retention configs support decimals meaning they can be configured to retain `0.5` days, for example.

:::

### Continuous and Motion Recording

The number of days to retain continuous and motion recordings can be configured. By default, continuous recording is disabled.

<ConfigTabs>
<TabItem value="ui">

Navigate to <NavPath path="Settings > Global configuration > Recording" />.

| Field                                     | Description                                  |
| ----------------------------------------- | -------------------------------------------- |
| **Enable recording**                      | Enable or disable recording for all cameras  |
| **Continuous retention > Retention days** | Number of days to keep continuous recordings |
| **Motion retention > Retention days**     | Number of days to keep motion recordings     |

</TabItem>
<TabItem value="yaml">

```yaml
record:
  enabled: True
  continuous:
    days: 1 # <- number of days to keep continuous recordings
  motion:
    days: 2 # <- number of days to keep motion recordings
```

</TabItem>
</ConfigTabs>

Continuous recording supports different retention modes [which are described below](#configuring-recording-retention).

### Object Recording

The number of days to retain recordings for review items can be specified for items classified as alerts as well as tracked objects.

<ConfigTabs>
<TabItem value="ui">

Navigate to <NavPath path="Settings > Global configuration > Recording" />.

| Field                                                      | Description                                 |
| ---------------------------------------------------------- | ------------------------------------------- |
| **Enable recording**                                       | Enable or disable recording for all cameras |
| **Alert retention > Event retention > Retention days**     | Number of days to keep alert recordings     |
| **Detection retention > Event retention > Retention days** | Number of days to keep detection recordings |

</TabItem>
<TabItem value="yaml">

```yaml
record:
  enabled: True
  alerts:
    retain:
      days: 10 # <- number of days to keep alert recordings
  detections:
    retain:
      days: 10 # <- number of days to keep detections recordings
```

</TabItem>
</ConfigTabs>

This configuration will retain recording segments that overlap with alerts and detections for 10 days. Because multiple tracked objects can reference the same recording segments, this avoids storing duplicate footage for overlapping tracked objects and reduces overall storage needs.

## Sub Stream Recording

In addition to the main recording stream, Frigate can record a second, lower quality stream for each camera. This serves two purposes:

- **Quality selection during playback**: A quality selector (`Auto`, `Original`, or `Low`) appears in History view for cameras with sub stream recording enabled. `Original` and `Low` play only that stream's recordings. Time ranges where the selected stream has no footage are skipped during playback, and the selector notes when the selected stream has no recordings at all in the viewed time range. With `Auto` (the default), playback prefers the original quality and automatically falls back to the low quality stream when the connection cannot keep up, or for time ranges where the original recordings have expired. The selector shows each stream's video codec and audio details beneath the options; footage recorded by older Frigate versions shows no details.
- **Extended retention**: Sub stream recordings have their own retention settings, fully independent of the main recordings. By giving the low quality recordings a longer retention period, you can keep weeks or months of low quality history using a fraction of the storage, and that history remains playable after the main recordings expire. Playback falls back to the low quality recordings automatically, and the timeline shows a muted treatment for time ranges where only low quality footage remains. Timeline previews are kept for as long as either stream still has recordings, so scrubbing works across the whole retained history.

### Configuring sub stream recording

Sub stream recording uses the `record_sub` input role. This role can be assigned to the same input as `detect`, so in the common case where detect already uses the camera's sub stream, no additional camera connection is needed. Like the main recording stream, sub stream segments are copied directly from the camera stream without re-encoding, so the recording quality is determined by the source stream.

The following examples keep 7 days of full quality continuous recordings and 60 days of low quality continuous recordings:

<ConfigTabs>
<TabItem value="ui">

Navigate to <NavPath path="Settings > Camera configuration > Streams (FFmpeg)" /> and select the camera.

- In **Camera inputs**, enable the **Record (Sub Stream)** role on the stream you want to record at low quality, commonly the same stream that has the **Detect** role. Only one stream may have this role, and it cannot be assigned to the same stream as the **Record** role.

Navigate to <NavPath path="Settings > Camera configuration > Recording" /> and select the camera.

- Set **Enable recording** to on
- Set **Continuous retention > Retention days** to `7`
- Set **Sub stream recording > Enable sub stream recording** to on
- Set **Sub stream recording > Sub stream continuous retention > Retention days** to `60`

The camera setup wizard also offers the **Record (Sub Stream)** role when assigning stream roles for a newly added camera.

</TabItem>
<TabItem value="yaml">

```yaml
cameras:
  front_door:
    ffmpeg:
      inputs:
        - path: rtsp://camera/main
          roles:
            - record
        - path: rtsp://camera/sub
          roles:
            - detect
            - record_sub
    record:
      enabled: true
      continuous:
        days: 7
      sub:
        enabled: true
        continuous:
          days: 60
```

If your camera does not provide a suitable sub stream (or the sub stream is already used at a resolution you don't want to record), you can use a go2rtc transcode as the source for `record_sub` instead:

```yaml
go2rtc:
  streams:
    front_door: rtsp://camera/main
    front_door_lq: ffmpeg:front_door#video=h264#width=854#hardware

cameras:
  front_door:
    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/front_door
          input_args: preset-rtsp-restream
          roles:
            - detect
            - record
        - path: rtsp://127.0.0.1:8554/front_door_lq
          input_args: preset-rtsp-restream
          roles:
            - record_sub
    record:
      enabled: true
      continuous:
        days: 7
      sub:
        enabled: true
        continuous:
          days: 60
```

</TabItem>
</ConfigTabs>

The `record.sub` config supports the same retention structure as the main recording config: `continuous`, `motion`, `alerts`, and `detections` each with their own `days` (and `mode` for alerts and detections). The pre-capture and post-capture windows for alerts and detections are taken from the main `record.alerts` and `record.detections` config. Extending `sub.alerts.days` or `sub.detections.days` beyond the main values also keeps those review items visible in the review timeline for the longer window, with playback falling back to the low quality stream once the main recordings expire.

:::note

Recording must be enabled (`record.enabled`) for sub stream recording to run, and Frigate will fail to start if `record.sub.enabled` is set without a `record_sub` role assigned to one of the camera's inputs.

:::

### How Auto picks a quality

`Auto` measures throughput on every segment download and compares it against the original stream's bitrate (computed from the recorded footage itself). Playback drops to the low quality stream when any of these happen:

- A freeze lasts 4 seconds (10 seconds when it starts within 2 seconds of a seek, since the seek target is rarely buffered), or freezes total 7 seconds within the last minute.
- 3 downloads in a row measure below the original bitrate plus 10%, dropping quality before a stall ever becomes visible.
- No first frame appears within 10 seconds, or loading fails outright.

Playback returns to full quality only when measured throughput exceeds the original bitrate by 50%, checked continuously while playing the low quality stream and again at each new hour. The asymmetric thresholds (1.1x to drop, 1.5x to return) keep a borderline connection from switching back and forth.

The most recent measurement is remembered on the device: a connection last measured below the original bitrate (or below 3 Mbps when the bitrate is not yet known) starts playback on the low quality stream so a first frame appears immediately, then upgrades within a few segments if the speed allows.

The quality selector shows which stream Auto is currently playing and why. A browser with Data Saver enabled stays on the low quality stream, a browser that cannot decode the original stream's codec (for example H.265 without HEVC support) plays the low quality stream for that camera, and pinning `Original` or `Low` bypasses Auto entirely.

### Sub stream output args

By default the sub stream is recorded with the same [output args](/configuration/ffmpeg_presets#output-args-presets) as the main recording stream, so it inherits any customization made to `ffmpeg.output_args.record`. Setting `ffmpeg.output_args.record_sub` gives the sub stream its own args instead. Like all `ffmpeg` config, this can be set globally or per camera.

The most common reason to set this is a pair of streams whose audio differs. Many cameras send AAC on the main stream but PCM on the sub stream, and PCM cannot be copied into an mp4 recording. Copying the main stream's audio avoids re-encoding audio that is already AAC, while the sub stream still needs to be transcoded:

```yaml
ffmpeg:
  output_args:
    # main stream audio is already AAC, so copy it
    record: preset-record-generic-audio-copy
    # sub stream audio is PCM, so transcode it to AAC
    record_sub: preset-record-generic-audio-aac
```

Other reasons to set this are recording a sub stream whose codec needs a different preset than the main stream, such as `preset-record-mjpeg`, or forcing a matching audio sample rate across the two streams with manual args ending in `-c:a aac -ar 16000`.

:::warning

Avoid removing audio from only one of the two streams (for example with `-an`). When one stream has audio and the other does not, playback of time ranges that combine both qualities is silent, so stripping audio from the sub stream also silences the merged timeline.

:::

### Which stream do features use?

As a general rule, features that read recordings prefer the main stream and fall back to the sub stream for time ranges where the main recordings have expired. Analytics features use only the main stream.

| Feature                                                                                  | Stream used                                                                                                   |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Recording playback (History and Review)                                                  | Both (main preferred with sub fallback by default), or exactly one stream when a quality is selected manually |
| Tracking details and Explore clip playback                                               | Main, falling back to sub where the main recordings have expired                                              |
| Exports and clip downloads                                                               | Main; sub is used when no main recordings remain in the range (streams are never mixed in one file)           |
| Frames grabbed from a recording in History (download snapshot, submit frame to Frigate+) | Main preferred, sub fallback                                                                                  |
| Audio extraction (e.g., transcription)                                                   | Main preferred, sub fallback                                                                                  |
| Motion search                                                                            | Main only                                                                                                     |
| Review timeline motion data                                                              | Main only                                                                                                     |
| Storage usage statistics                                                                 | Both streams counted                                                                                          |

This table covers only features that read recordings from disk. Tracked object snapshots and thumbnails (the images shown in Explore and sent with notifications, and the images submitted to Frigate+ from a tracked object) are captured live from the `detect` stream as the object is tracked, never from recordings, so sub stream recording does not affect them.

### Trade-offs

- Recording a second stream increases overall storage use. The increase is typically small relative to the main recordings, since the low quality stream is much smaller. Both streams are cached before being written to disk, so cache use goes up as well. See [the `/tmp/cache` area is separate](#the-tmpcache-area-is-separate) if you start seeing `No space left on device` errors after enabling it.
- The go2rtc transcode approach continuously encodes the low quality stream, which uses CPU or GPU resources. This cost only applies to the transcode path; recording the camera's native sub stream does not re-encode. See the [go2rtc hardware acceleration documentation](https://github.com/AlexxIT/go2rtc?tab=readme-ov-file#source-ffmpeg) for accelerating the transcode.
- Many camera sub streams do not include audio. If the source stream has no audio, the low quality recordings will not have audio.
- **Matching video codecs and audio settings between the two streams gives the smoothest playback.** When playback combines both qualities on one timeline (the default `Auto` behavior: for example original quality during events with low quality in between, or low quality history after the original recordings expire) and the streams use different video codecs or audio settings, for example H.265 on the main stream and H.264 on the sub stream, or 16 kHz audio on one and 8 kHz on the other, playback still works: Frigate inserts a decoder reset at each quality transition, which can cause a barely-perceptible pause there. Configuring both streams in the camera's firmware to use the same video codec, audio codec, and sample rate makes transitions fully seamless, and a mismatched audio sample rate can also be corrected with [sub stream output args](#sub-stream-output-args). If one stream has audio and the other does not, combined time ranges play **without audio**; selecting a single quality with the playback selector always keeps that stream's audio.

## Can I have "continuous" recordings, but only at certain times?

Using Frigate UI, Home Assistant, or MQTT, cameras can be automated to only record in certain situations or at certain times.

## How do I export recordings?

Footage can be exported from Frigate by right-clicking (desktop) or long pressing (mobile) on a review item in the Review pane or by clicking the Export button in the History view. Exported footage is then organized and searchable through the Export view, accessible from the main navigation bar.

### Time-lapse export

Time lapse exporting is available only via the [HTTP API](../integrations/api/export-recording-export-camera-name-start-start-time-end-end-time-post.api.mdx).

When exporting a time-lapse the default speed-up is 25x with 30 FPS. This means that every 25 seconds of (real-time) recording is condensed into 1 second of time-lapse video (always without audio) with a smoothness of 30 FPS.

To configure the speed-up factor, the frame rate and further custom settings, use the `timelapse_args` parameter. The below configuration example would change the time-lapse speed to 60x (for fitting 1 hour of recording into 1 minute of time-lapse) with 25 FPS:

```yaml {3-4}
record:
  enabled: True
  export:
    timelapse_args: "-vf setpts=PTS/60 -r 25"
```

:::tip

When using `hwaccel_args`, hardware encoding is used for timelapse generation. This setting can be overridden for a specific camera (e.g., when camera resolution exceeds hardware encoder limits); set the camera-level export hwaccel_args with the appropriate settings. Using an unrecognized value or empty string will fall back to software encoding (libx264).

:::

:::tip

The encoder determines its own behavior so the resulting file size may be undesirably large.
To reduce the output file size the ffmpeg parameter `-qp n` can be utilized (where `n` stands for the value of the quantisation parameter). The value can be adjusted to get an acceptable tradeoff between quality and file size for the given scenario.

:::

## Apple Compatibility with H.265 Streams

Apple devices running the Safari browser may fail to playback h.265 recordings. The [apple compatibility option](../configuration/camera_specific.md#h265-cameras-via-safari) should be used to ensure seamless playback on Apple devices.

## Syncing Media Files With Disk

Media files (event snapshots, event thumbnails, review thumbnails, previews, exports, and recordings) can become orphaned when database entries are deleted but the corresponding files remain on disk.

Normal operation may leave small numbers of orphaned files until Frigate's scheduled cleanup, but crashes, configuration changes, or upgrades may cause more orphaned files that Frigate does not clean up. This feature checks the file system for media files and removes any that are not referenced in the database.

The Maintenance pane in the Frigate UI or an API endpoint `POST /api/media/sync` can be used to trigger a media sync. When using the API, a job ID is returned and the operation continues on the server. Status can be checked with the `/api/media/sync/status/{job_id}` endpoint.

Setting `verbose: true` writes a detailed report of every orphaned file and database entry to `/config/media_sync/<job_id>.txt`. For recordings, the report separates orphaned database entries (DB records whose files are missing from disk) from orphaned files (files on disk with no corresponding database record).

:::warning

This operation uses considerable CPU resources and includes a safety threshold that aborts if more than 50% of files would be deleted. Only run when necessary. If you set `force: true` the safety threshold will be bypassed; do not use `force` unless you are certain the deletions are intended.

:::
