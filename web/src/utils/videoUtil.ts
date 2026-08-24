import { Recording } from "@/types/record";

/** the HLS endpoint returns the vod segments with the first
 * segment of the hour trimmed, meaning it will start at
 * the beginning of the hour, cutting off any difference
 * that the segment has.
 */
export function calculateInpointOffset(
  timeRangeStart: number | undefined,
  firstRecordingSegment: Recording | undefined,
): number {
  if (!timeRangeStart || !firstRecordingSegment) {
    return 0;
  }

  // if the first recording segment does not cross over
  // the beginning of the time range then there is no offset
  if (
    firstRecordingSegment.start_time < timeRangeStart &&
    firstRecordingSegment.end_time > timeRangeStart
  ) {
    return timeRangeStart - firstRecordingSegment.start_time;
  }

  return 0;
}

/**
 * Calculates the video player time (in seconds) for a given timestamp
 * by iterating through recording segments and summing their durations.
 * This accounts for the fact that the video is a concatenation of segments,
 * not a single continuous stream.
 *
 * @param timestamp - The target timestamp to seek to
 * @param recordings - Array of recording segments
 * @param inpointOffset - HLS inpoint offset to subtract from the result
 * @returns The calculated seek position in seconds, or undefined if timestamp is out of range
 */
export function calculateSeekPosition(
  timestamp: number,
  recordings: Recording[],
  inpointOffset: number = 0,
): number | undefined {
  if (!recordings || recordings.length === 0) {
    return undefined;
  }

  // Check if timestamp is within the recordings range
  if (
    timestamp < recordings[0].start_time ||
    timestamp > recordings[recordings.length - 1].end_time
  ) {
    return undefined;
  }

  let seekSeconds = 0;

  for (const segment of recordings) {
    if (timestamp < segment.start_time) {
      // The requested wall-clock time falls into a recording gap. The VOD
      // playlist is a concatenation of media segments, so treating the gap as
      // media duration would incorrectly seek to the next clip.
      return undefined;
    }

    if (timestamp <= segment.end_time) {
      seekSeconds += timestamp - segment.start_time;
      seekSeconds -= inpointOffset;
      return seekSeconds >= 0 ? seekSeconds : undefined;
    }

    seekSeconds += segment.end_time - segment.start_time;
  }

  return undefined;
}
