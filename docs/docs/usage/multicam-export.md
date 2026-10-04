---
id: multicam-export
title: Multicamera export
---

Open recording history, select up to four cameras and a time range, then choose
**MultiCam export**. The editor produces one MP4 with synchronized camera views.
Keep several cameras on screen, switch to one camera, or change views per shot.

## Edit and preview

Edit each shot's start/end, split shots and toggle cameras. Choose the recording
stream, output resolution and a fixed audio camera (or silence).
**Auto** resolves available main/sub recordings. An explicitly chosen stream
uses that stream. Missing recordings remain visible as labeled gaps.

Validate the plan to check recording coverage, then play its synchronized preview.
The preview is muted; exported audio comes from the selected camera, including
when off screen. Browser decoding and server FFmpeg codec support can differ.

Per-camera clock offsets correct timestamp errors: a positive offset reads later
source timestamps for the same output time. Check against a visible shared event.
Camera and UTC labels identify shots; the label is the shot's start time.

Save/import plans as JSON. A local draft is associated with the signed-in username
and can be restored explicitly.

## Follow a person or animal

Expand the assisted journey editor, search the chosen cameras/time range and
select an initial observation. Confirm which other observations belong to the
same person or animal. Optional directional camera transitions narrow proposals.

Choose **Follow** for cuts between confirmed observations or **Grid** for cameras
with concurrent confirmed observations. Padding and minimum shot duration help
avoid abrupt cuts. Review the generated plan, adjust shots and export directly.

Tracking IDs are local to each camera. This feature relies on your confirmation;
it does not automatically establish identity across cameras. Similar subjects,
occlusion and poor light need attention. Supported animals are built-in common
animal classes; custom labels outside that list are not proposed. No license-plate
recognition is required. Periods without confirmation appear as an explicit gap.

## Limits and operation

Plans support four source cameras (including audio), 64 shots and up to one hour
of output. Defaults are 720p at 15 fps; 1080p is available. Bounded CPU workers
encode outside capture, with up to four admitted jobs. Large grids add CPU/disk
load. Queue capacity and available disk space are checked.

Private hard links pin source recordings while queued or rendering. Recordings
and exports must reside on the same filesystem. Retention can remove the original
directory entry without destroying pinned data. Cancel from the editor to release
private files. A restart discards unfinished composites rather than publishing
partial output.

List, detail, progress, thumbnails and downloads require access to every source
camera, including audio-only cameras. Plans are stored with exports and embedded
in MP4 metadata. Existing exports remain usable after migration.

## Deployment acceptance

Back up the database before deploying recording/export migrations. Then check:

- Short two/four-camera grids, cuts and fixed-camera audio.
- Main/sub handoffs, retention gaps and corrected camera clock offsets.
- Confirmed person/animal journeys, overlap and lost observations.
- Similar subjects and night footage: review proposals before export.
- Cancellation, restart recovery and constrained disk space.
- Restricted users: inaccessible cameras block preview and downloads.
- Existing synchronized playback, OIDC and proxy authentication.

Unit and real-media tests do not replace browser and camera acceptance.
