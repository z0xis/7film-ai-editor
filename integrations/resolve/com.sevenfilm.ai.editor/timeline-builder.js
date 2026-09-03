// Pure timeline construction helpers for the Resolve Workflow Integration.
// Kept free of Electron and the native bridge so they stay unit testable.

const DEFAULT_BATCH_SIZE = 40;
// A clip shorter than this reads as a freeze frame on the timeline rather than a shot.
const MIN_CLIP_SECONDS = 0.25;

function parseFrameRate(raw, fallback = 25) {
  const text = String(raw ?? "").trim();
  const match = /^(\d+)(?:\s*\/\s*(\d+))?$/.exec(text);
  if (!match) {
    const numeric = Number(text);
    return Number.isFinite(numeric) && numeric > 0 ? numeric : fallback;
  }
  const numerator = Number(match[1]);
  const denominator = match[2] === undefined ? 1 : Number(match[2]);
  if (!numerator || !denominator) return fallback;
  return numerator / denominator;
}

// A media pool item Resolve cannot measure reports 0 (or nothing) for "Frames". That is
// "unknown", not "empty": clamping against it would drop every clip of the file, so anything
// below a single frame is reported back as unknown and the caller falls back to the plan.
function toFrameCount(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 1) return null;
  return Math.floor(numeric);
}

/**
 * Resolve treats endFrame as the LAST included source frame, and rejects the whole
 * AppendToTimeline batch ("Invalid items to append", errorCode 2) as soon as one item
 * points past the media pool item's real frame count. ffprobe/PySceneDetect frame counts
 * routinely run a frame or two long on VFR and long-GOP camera files, so every range is
 * clamped against what Resolve itself reports before it is sent.
 */
function clampSourceRange({ startFrame, durationFrames, availableFrames, minimumFrames = 1 }) {
  const available = toFrameCount(availableFrames);
  const rawStart = Number(startFrame);
  const rawDuration = Number(durationFrames);
  let start = Number.isFinite(rawStart) ? Math.max(0, Math.floor(rawStart)) : 0;
  let duration = Number.isFinite(rawDuration) ? Math.floor(rawDuration) : 0;
  const minimum = Math.max(1, Math.floor(minimumFrames));
  if (duration < 1) duration = 1;
  if (available !== null) {
    duration = Math.min(duration, available);
    // Slide the window back into the media instead of truncating it. Cutting the tail off a
    // clip whose start sits near the end of the file leaves a one frame stub, which Resolve
    // shows as a freeze frame; the same shot a few frames earlier is the shot that was meant.
    start = Math.max(0, Math.min(start, available - duration));
  }
  if (duration < minimum) return null;
  return { startFrame: start, endFrame: start + duration - 1, durationFrames: duration };
}

/**
 * Build video-only clipInfos. mediaType 1 keeps the camera audio of the source clips out
 * of the rough cut so the user's chosen music owns the audio tracks. Only the keys Resolve
 * documents are placed on a clipInfo; human readable labels are kept alongside so a rejected
 * batch can be reported precisely. Every range is clamped rather than dropped, so the payload
 * that reaches Resolve can no longer contain an item it will reject.
 */
function buildVideoClipInfos(items, resolveMedia) {
  const clipInfos = [];
  const labels = [];
  const dropped = [];
  for (const item of items || []) {
    const sourcePath = String(item?.source_path ?? "");
    const media = resolveMedia(sourcePath);
    if (!media || !media.mediaPoolItem) {
      throw new Error(`Media Pool öğesi bulunamadı: ${sourcePath}`);
    }
    const reported = toFrameCount(media.frameCount);
    const range = clampSourceRange({
      startFrame: item?.source_in?.start_frame,
      durationFrames: item?.source_in?.duration_frames,
      availableFrames: reported === null ? item?.asset_duration_frames : reported,
      minimumFrames: Math.ceil(MIN_CLIP_SECONDS * parseFrameRate(item?.source_in?.rate)),
    });
    if (range === null) {
      dropped.push(sourcePath);
      continue;
    }
    clipInfos.push({
      mediaPoolItem: media.mediaPoolItem,
      startFrame: range.startFrame,
      endFrame: range.endFrame,
      mediaType: 1,
    });
    labels.push(`${sourcePath} [${range.startFrame}-${range.endFrame}]`);
  }
  return { clipInfos, labels, dropped };
}

/**
 * The music starts at timeline frame 0 and is clamped by both the rough cut length and the
 * real music length, so Resolve never gets an out-of-range audio item either.
 */
function buildMusicClipInfo({
  mediaPoolItem,
  timelineFrames,
  musicFrames,
  trackIndex = 1,
  recordFrame = 0,
}) {
  if (!mediaPoolItem) return null;
  const timelineLimit = toFrameCount(timelineFrames);
  const musicLimit = toFrameCount(musicFrames);
  const limits = [timelineLimit, musicLimit].filter((value) => value !== null);
  if (!limits.length) return null;
  const duration = Math.min(...limits);
  if (duration < 1) return null;
  return {
    mediaPoolItem,
    startFrame: 0,
    endFrame: duration - 1,
    mediaType: 2,
    trackIndex,
    recordFrame,
  };
}

function musicFrameLimit(plan, mediaFrameCount) {
  const rate = parseFrameRate(plan?.frame_rate);
  const seconds = Number(plan?.music_duration_seconds);
  const fromSeconds = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds * rate) : null;
  const fromMedia = toFrameCount(mediaFrameCount);
  const limits = [fromSeconds, fromMedia].filter((value) => value !== null);
  return limits.length ? Math.min(...limits) : null;
}

function timelineFrameCount(plan) {
  const total = (plan?.items || []).reduce(
    (sum, item) => sum + Math.max(0, Math.floor(Number(item?.timeline_in?.duration_frames) || 0)),
    0,
  );
  return total > 0 ? total : null;
}

/**
 * Append the clips in Resolve sized batches. AppendToTimeline is all or nothing: one bad item
 * rejects its whole batch, which is how a single out-of-range clip used to surface as
 * "Resolve could not add clips 81-120". The ranges are already clamped by the time they get
 * here, and a failure now names the exact clips in the rejected batch.
 */
async function appendClipsInBatches({ mediaPool, clipInfos, labels = [], batchSize = DEFAULT_BATCH_SIZE }) {
  let appendedCount = 0;
  for (const batch of chunk(clipInfos, batchSize)) {
    const first = appendedCount + 1;
    const last = appendedCount + batch.length;
    const batchLabels = labels.slice(appendedCount, last).join(", ");
    let appended = null;
    try {
      appended = await mediaPool.AppendToTimeline(batch);
    } catch (error) {
      throw new Error(
        `Resolve ${first}-${last}. video kliplerini ekleyemedi: ${error.message || error} (${batchLabels})`,
      );
    }
    if (!appended || appended.length !== batch.length) {
      throw new Error(`Resolve ${first}-${last}. video grubunu eksik ekledi (${batchLabels}).`);
    }
    appendedCount += batch.length;
  }
  return appendedCount;
}

function chunk(values, size = DEFAULT_BATCH_SIZE) {
  const step = Math.max(1, Math.floor(size));
  const batches = [];
  for (let start = 0; start < values.length; start += step) {
    batches.push(values.slice(start, start + step));
  }
  return batches;
}

module.exports = {
  DEFAULT_BATCH_SIZE,
  MIN_CLIP_SECONDS,
  appendClipsInBatches,
  buildMusicClipInfo,
  buildVideoClipInfos,
  chunk,
  clampSourceRange,
  musicFrameLimit,
  parseFrameRate,
  timelineFrameCount,
};
