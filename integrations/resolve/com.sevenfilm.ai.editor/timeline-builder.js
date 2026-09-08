// Pure timeline construction helpers for the Resolve Workflow Integration.
// Kept free of Electron and the native bridge so they stay unit testable.

const DEFAULT_BATCH_SIZE = 40;
// A clip shorter than this reads as a freeze frame on the timeline rather than a shot.
const MIN_CLIP_SECONDS = 0.25;

// The engine states every duration as exact rational time, as the blueprint requires, so
// seconds arrive as strings like "1161665306122449/5000000000000". Number() gives NaN for
// those, which silently threw away the music length limit.
function parseRational(raw) {
  const text = String(raw ?? "").trim();
  if (!text) return null;
  const ratio = /^(-?\d+)\s*\/\s*(\d+)$/.exec(text);
  if (ratio) {
    const denominator = Number(ratio[2]);
    return denominator ? Number(ratio[1]) / denominator : null;
  }
  const numeric = Number(text);
  return Number.isFinite(numeric) ? numeric : null;
}

function parseFrameRate(raw, fallback = 25) {
  const value = parseRational(raw);
  return value !== null && value > 0 ? value : fallback;
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
 * endFrame is EXCLUSIVE: verified against Resolve Studio 21.0.2, startFrame 0 with endFrame 50
 * places 50 frames, and startFrame 50 with endFrame 50 places nothing at all. A zero length
 * range is one of the few things Resolve actually rejects ("Invalid items to append",
 * errorCode 2), along with an inverted range and a missing media pool item; a range running
 * past the end of the media it accepts, stretching the clip instead. So the length is what
 * matters here: it is kept whole by sliding the window back into the media, and a range that
 * cannot reach the minimum is dropped rather than sent as a stub.
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
  return { startFrame: start, endFrame: start + duration, durationFrames: duration };
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
 * real music length. endFrame is exclusive here too, so it is the frame count itself.
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
    endFrame: duration,
    mediaType: 2,
    trackIndex,
    recordFrame,
  };
}

/**
 * One clipInfo per song, each laid at its own place on the timeline and starting from the part
 * of the file that was chosen. An edit can open on a slow song and move to a fast one, so the
 * adapter cannot assume a single track starting at zero.
 *
 * Frames are counted at the timeline's rate: Resolve expresses an audio clip's source offset
 * that way, measured on an FCPXML import where a song entering at its own fortieth second came
 * back as source frame 1000 at 25 fps.
 */
function buildMusicClipInfos({ plan, lookup, timelineStart = 0, trackIndex = 1 }) {
  const segments = musicSegments(plan);
  if (!segments.length) return { clipInfos: [], missing: [] };
  const rate = parseFrameRate(plan?.frame_rate);
  const timelineLimit = toFrameCount(timelineFrameCount(plan));
  const clipInfos = [];
  const missing = [];
  for (const segment of segments) {
    const mediaPoolItem = lookup(segment.path);
    if (!mediaPoolItem) {
      missing.push(segment.path);
      continue;
    }
    const offset = secondsToFrames(segment.timelineStartSeconds, rate);
    if (timelineLimit !== null && offset >= timelineLimit) continue;
    let duration = secondsToFrames(segment.durationSeconds, rate);
    if (timelineLimit !== null) duration = Math.min(duration, timelineLimit - offset);
    const total = secondsToFrames(segment.sourceTotalSeconds, rate);
    const start = secondsToFrames(segment.sourceStartSeconds, rate);
    if (total !== null && total > 0) duration = Math.min(duration, total - start);
    if (duration === null || duration < 1) continue;
    clipInfos.push({
      mediaPoolItem,
      startFrame: start ?? 0,
      endFrame: (start ?? 0) + duration,
      mediaType: 2,
      trackIndex,
      recordFrame: timelineStart + offset,
    });
  }
  return { clipInfos, missing };
}

/**
 * The songs a plan carries, newest field first. A plan saved before an edit could hold more
 * than one still has only music_path, and it has to keep working.
 */
function musicSegments(plan) {
  const raw = Array.isArray(plan?.music_segments) ? plan.music_segments : [];
  const segments = raw
    .map((item) => ({
      path: item?.path ? String(item.path) : null,
      timelineStartSeconds: item?.timeline_start_seconds,
      durationSeconds: item?.duration_seconds,
      sourceStartSeconds: item?.source_start_seconds,
      sourceTotalSeconds: item?.source_total_seconds,
    }))
    .filter((item) => item.path);
  if (segments.length) return segments;
  if (!plan?.music_path) return [];
  return [{
    path: String(plan.music_path),
    timelineStartSeconds: "0",
    durationSeconds: plan.music_duration_seconds,
    sourceStartSeconds: "0",
    sourceTotalSeconds: plan.music_duration_seconds,
  }];
}

function secondsToFrames(value, rate) {
  const seconds = parseRational(value);
  if (seconds === null || !(rate > 0)) return null;
  return Math.max(0, Math.floor(seconds * rate));
}

/**
 * Resolve's own spelling of a frame rate, for project.SetSetting("timelineFrameRate").
 * It writes the NTSC rates as the numbers an editor recognises, not as 24000/1001.
 */
function resolveFrameRateSetting(raw) {
  // Read strictly. parseFrameRate falls back to 25 for anything it cannot read, and writing a
  // guessed 25 into the project would put the picture in the wrong place just as surely.
  const rate = parseFrameRate(raw, 0);
  if (!(rate > 0)) return null;
  const ntsc = { 23.976: "23.976", 29.97: "29.97", 47.952: "47.952", 59.94: "59.94", 119.88: "119.88" };
  for (const [value, text] of Object.entries(ntsc)) {
    if (Math.abs(rate - Number(value)) < 0.01) return text;
  }
  return Number.isInteger(rate) ? String(rate) : rate.toFixed(3);
}

/**
 * Whether a timeline running at `current` can hold a plan cut at `wanted`.
 *
 * A plan laid into a timeline of a different rate is not merely retimed: every record frame is
 * a frame number, so a 50 fps plan dropped into a 24 fps timeline puts each clip roughly twice
 * as far along as it belongs. Measured on the user's own project — 114 clips, 113 gaps between
 * them, 3837 frames of black — and the picture simply is not there where the music is.
 */
function frameRatesAgree(current, wanted) {
  const a = parseFrameRate(current, 0);
  const b = parseFrameRate(wanted, 0);
  if (!(a > 0) || !(b > 0)) return false;
  return Math.abs(a - b) < 0.01;
}

function musicFrameLimit(plan, mediaFrameCount) {
  const rate = parseFrameRate(plan?.frame_rate);
  const seconds = parseRational(plan?.music_duration_seconds);
  const fromSeconds = seconds !== null && seconds > 0 ? Math.floor(seconds * rate) : null;
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
 * Append the clips in Resolve sized batches. Resolve drops the invalid items and keeps the
 * rest, so the returned count is checked as well as the call itself: through the Workflow
 * Integration bridge an invalid item surfaces as "Invalid items to append for timeline",
 * errorCode 2, naming the batch it was in rather than the clip. Either way the failure is
 * reported with the clips of that batch spelled out.
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

/**
 * Whether the plan asks for any clip to play at a speed other than its own.
 *
 * The Resolve scripting API cannot express this: TimelineItem.SetProperty offers pan, tilt,
 * zoom, crop and the retime *method*, and no speed at all. Measured against Resolve 21.0.2.
 * So a plan holding a retimed clip has to come in as FCPXML, where an imported timeMap comes
 * back at exactly the speed it asks for.
 *
 * A clip is retimed when it occupies more (or less) of the timeline than the source it plays.
 * Compared in seconds rather than frames, because the two need not share a rate.
 */
// How long the last shot takes to go to black, in frames of the timeline.
//
// Measured on the 18 reference films: 13 end on black, over a median 2.5 seconds. The number
// travels in the exported plan (`closing_fade_seconds`) so the engine stays the one place it
// is decided; this only converts it and keeps it inside the shot.
//
// Until Resolve 21.1 there was no way to apply it: the FCPXML importer drops `adjust-opacity`
// and `<transition>`, and Fusion would not accept a keyframe over the remote proxy. 21.1 adds
// TimelineItem.SetFades, which is measured to work — set 50, reads back 50.
function closingFadeFrames(plan, lastItemDurationFrames) {
  const seconds = Number(parseRational(plan?.closing_fade_seconds));
  if (!Number.isFinite(seconds) || seconds <= 0) return 0;
  const rate = parseFrameRate(plan?.frame_rate, 50);
  const wanted = Math.round(seconds * rate);
  const available = Number(lastItemDurationFrames);
  if (!Number.isFinite(available) || available <= 1) return 0;
  // A fade may not eat the whole shot: a closing that starts black is not a closing.
  return Math.max(1, Math.min(wanted, Math.floor(available - 1)));
}

function hasRetiming(plan) {
  const items = Array.isArray(plan?.items) ? plan.items : [];
  return items.some((item) => {
    const played = parseRational(item?.source_in?.duration_seconds);
    const occupied = parseRational(item?.timeline_in?.duration_seconds);
    if (!Number.isFinite(played) || !Number.isFinite(occupied) || occupied <= 0) return false;
    // A frame of slack: rational seconds round differently on the two clocks.
    return Math.abs(played - occupied) > 1 / parseFrameRate(plan?.frame_rate, 25);
  });
}

/**
 * The monitor format a timeline of this rate should be watched at.
 *
 * Resolve gives a new timeline the project's monitor format, which is not the timeline's rate:
 * measured across nineteen timelines in this project, four 50 fps edits were being played back
 * as "HD 1080p 25" and one as "HD 1080PsF 25". The viewer then judders, which is what the
 * editor saw and what made them go looking for the setting themselves.
 *
 * Only the rate is replaced. The resolution and the scan belong to the editor's monitoring
 * chain and are none of this tool's business — except that a progressive timeline is not
 * watched as segmented frames, so PsF becomes p.
 *
 * Returns null when there is nothing to do or nothing recognisable to change.
 */
function monitorFormatForRate(current, rate) {
  const wanted = Number(rate);
  if (!Number.isFinite(wanted) || wanted <= 0) return null;
  const match = /^(.*?)(p|PsF|i)\s+(\d+(?:\.\d+)?)$/.exec(String(current || "").trim());
  if (!match) return null;
  const [, prefix, scan, present] = match;
  const shown = Number.isInteger(wanted) ? String(wanted) : String(wanted);
  const next = `${prefix}${scan === "PsF" ? "p" : scan} ${shown}`;
  return next === `${prefix}${scan} ${present}` ? null : next;
}

module.exports = {
  closingFadeFrames,
  hasRetiming,
  monitorFormatForRate,
  DEFAULT_BATCH_SIZE,
  MIN_CLIP_SECONDS,
  appendClipsInBatches,
  buildMusicClipInfo,
  buildMusicClipInfos,
  buildVideoClipInfos,
  chunk,
  frameRatesAgree,
  clampSourceRange,
  musicFrameLimit,
  musicSegments,
  parseFrameRate,
  resolveFrameRateSetting,
  parseRational,
  timelineFrameCount,
};
