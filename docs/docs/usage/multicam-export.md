---
id: multicam-export
title: Multicamera export
---

Open recording history, select **MultiCam export**, and choose cameras and a
start/end time. Enter a name and select **Prepare ZIP export**. The selected
history range and cameras are filled in automatically.

Frigate prepares one MP4 per camera using the existing recording export pipeline.
Each video keeps its own audio, when available. Available main recordings are
preferred, with sub recordings used where main recordings have expired. Recording
gaps are omitted; the resulting videos are not guaranteed to stay synchronized.

The dialog shows the status of each camera. Once preparation finishes, select
**Download ZIP** to download all completed videos in one archive. If a camera has
no recordings or its export fails, the dialog identifies it and explicitly offers
a ZIP containing only the successful videos.

Videos are also saved together in a named case under **Exports**. You can close
the dialog while exports run and reopen it to check their status. After navigating
away or reloading, open the saved case under **Exports**, select its completed
videos and choose **Download ZIP**.

Up to 50 cameras can be selected per batch, subject to export queue capacity.
ZIP creation uses temporary server disk space and does not recompress the MP4s.
Downloads require access to every source camera and reject unfinished, missing,
or inaccessible exports. The archive is generated on demand and discarded after
the download.

The MVP does not expose the earlier composite editor, synchronized preview,
cut plans, clock corrections, or assisted person/animal journeys. Existing
composite exports remain available.
