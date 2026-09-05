const assert = require("node:assert/strict");
const { describe, it } = require("node:test");

const {
  appendClipsInBatches,
  parseRational,
  buildMusicClipInfo,
  buildMusicClipInfos,
  buildVideoClipInfos,
  chunk,
  clampSourceRange,
  frameRatesAgree,
  musicFrameLimit,
  musicSegments,
  parseFrameRate,
  resolveFrameRateSetting,
  timelineFrameCount,
} = require("./timeline-builder");

const VIDEO = { id: "video" };
const MUSIC = { id: "music" };

function planItem(startFrame, durationFrames, sourcePath = "/media/A001.mov") {
  return {
    source_path: sourcePath,
    asset_duration_frames: 250,
    source_in: { start_frame: startFrame, duration_frames: durationFrames },
    timeline_in: { start_frame: 0, duration_frames: durationFrames },
  };
}

describe("clampSourceRange", () => {
  it("keeps an in-bounds range and makes endFrame the last included frame", () => {
    assert.deepEqual(
      clampSourceRange({ startFrame: 10, durationFrames: 40, availableFrames: 250 }),
      { startFrame: 10, endFrame: 50, durationFrames: 40 },
    );
  });

  it("slides a range that would run past the media back inside it, keeping its length", () => {
    // Truncating this to its last ten frames left a stub that Resolve shows as a freeze frame.
    assert.deepEqual(
      clampSourceRange({ startFrame: 240, durationFrames: 40, availableFrames: 250 }),
      { startFrame: 210, endFrame: 250, durationFrames: 40 },
    );
  });

  it("pulls a start beyond the media back to where the whole shot fits", () => {
    assert.deepEqual(
      clampSourceRange({ startFrame: 900, durationFrames: 40, availableFrames: 250 }),
      { startFrame: 210, endFrame: 250, durationFrames: 40 },
    );
  });

  it("shortens the shot only when the media itself is shorter", () => {
    assert.deepEqual(
      clampSourceRange({ startFrame: 10, durationFrames: 40, availableFrames: 25 }),
      { startFrame: 0, endFrame: 25, durationFrames: 25 },
    );
  });

  it("drops a clip that cannot reach the minimum length instead of emitting a freeze frame", () => {
    assert.equal(
      clampSourceRange({ startFrame: 0, durationFrames: 40, availableFrames: 3, minimumFrames: 7 }),
      null,
    );
  });

  it("leaves the range untouched when the media length is unknown", () => {
    assert.deepEqual(
      clampSourceRange({ startFrame: 240, durationFrames: 40, availableFrames: null }),
      { startFrame: 240, endFrame: 280, durationFrames: 40 },
    );
  });

  it("keeps a single frame source only when no minimum is asked for", () => {
    assert.deepEqual(
      clampSourceRange({ startFrame: 0, durationFrames: 40, availableFrames: 1 }),
      { startFrame: 0, endFrame: 1, durationFrames: 1 },
    );
  });
});

describe("clipInfo ranges Resolve actually accepts", () => {
  // Measured against DaVinci Resolve Studio 21.0.2 with a real 252 frame camera file.
  it("treats endFrame as exclusive, so the length is endFrame minus startFrame", () => {
    const range = clampSourceRange({ startFrame: 0, durationFrames: 50, availableFrames: 252 });
    assert.equal(range.endFrame - range.startFrame, 50);
    assert.equal(range.durationFrames, 50);
  });

  it("never emits the zero length range Resolve rejects", () => {
    // A one frame plan item used to arrive as startFrame 50, endFrame 50, which places
    // nothing and fails the batch. Those items cluster late in a plan, which is why the
    // reported failure was on clips 81-120 rather than the first batch.
    const range = clampSourceRange({
      startFrame: 50, durationFrames: 1, availableFrames: 252, minimumFrames: 7,
    });
    assert.equal(range, null);
  });

  it("never emits an inverted range", () => {
    for (const durationFrames of [0, -10, NaN]) {
      const range = clampSourceRange({ startFrame: 100, durationFrames, availableFrames: 252 });
      assert.ok(range === null || range.endFrame > range.startFrame, `duration ${durationFrames}`);
    }
  });

  it("keeps the whole range inside the media so Resolve cannot stretch the clip", () => {
    // Resolve accepts an end past the media and extends the clip: endFrame 452 on a 252
    // frame file placed a 442 frame clip.
    const range = clampSourceRange({ startFrame: 247, durationFrames: 200, availableFrames: 252 });
    assert.ok(range.endFrame <= 252, `endFrame ${range.endFrame} ran past the media`);
  });
});

describe("buildVideoClipInfos", () => {
  const media = { mediaPoolItem: VIDEO, frameCount: 250 };
  const resolveMedia = () => media;

  it("marks every clip as video only so camera audio stays out of the rough cut", () => {
    const { clipInfos } = buildVideoClipInfos([planItem(0, 25), planItem(30, 25)], resolveMedia);
    assert.equal(clipInfos.length, 2);
    assert.ok(clipInfos.every((clipInfo) => clipInfo.mediaType === 1));
  });

  it("sends only the keys Resolve documents for a clipInfo", () => {
    const { clipInfos } = buildVideoClipInfos([planItem(0, 25)], resolveMedia);
    assert.deepEqual(
      Object.keys(clipInfos[0]).sort(),
      ["endFrame", "mediaPoolItem", "mediaType", "startFrame"],
    );
  });

  it("moves a late clip inside the media instead of letting Resolve reject the batch", () => {
    const { clipInfos } = buildVideoClipInfos([planItem(245, 40)], resolveMedia);
    assert.deepEqual(
      { startFrame: clipInfos[0].startFrame, endFrame: clipInfos[0].endFrame },
      { startFrame: 210, endFrame: 250 },
    );
  });

  it("drops a plan item that would land as a one frame freeze rather than a shot", () => {
    const stub = { ...planItem(0, 1), source_in: { start_frame: 0, duration_frames: 1 } };

    const { clipInfos, dropped } = buildVideoClipInfos([stub, planItem(0, 40)], resolveMedia);

    assert.equal(clipInfos.length, 1);
    assert.deepEqual(dropped, ["/media/A001.mov"]);
  });

  it("reads the minimum length from the source's own frame rate", () => {
    // A 50 fps source needs 13 frames for a quarter second, a 25 fps source only 7.
    const fast = { ...planItem(0, 10), source_in: { start_frame: 0, duration_frames: 10, rate: "50/1" } };
    const slow = { ...planItem(0, 10), source_in: { start_frame: 0, duration_frames: 10, rate: "25/1" } };

    assert.equal(buildVideoClipInfos([fast], resolveMedia).clipInfos.length, 0);
    assert.equal(buildVideoClipInfos([slow], resolveMedia).clipInfos.length, 1);
  });

  it("falls back to the plan's asset frame count when Resolve reports none", () => {
    const { clipInfos } = buildVideoClipInfos(
      [planItem(245, 40)],
      () => ({ mediaPoolItem: VIDEO, frameCount: null }),
    );
    assert.equal(clipInfos[0].endFrame, 250);
  });

  it("reports a label per clip so a rejected batch names the offending file", () => {
    const { labels } = buildVideoClipInfos([planItem(245, 40)], resolveMedia);
    assert.deepEqual(labels, ["/media/A001.mov [210-250]"]);
  });

  it("throws with the path when a media pool item is missing", () => {
    assert.throws(
      () => buildVideoClipInfos([planItem(0, 25)], () => null),
      /\/media\/A001\.mov/,
    );
  });

  it("treats an unmeasurable frame count as unknown instead of dropping the clip", () => {
    for (const frameCount of [0, 0.4, null, undefined, NaN, "n/a"]) {
      const { clipInfos } = buildVideoClipInfos(
        [planItem(245, 40)],
        () => ({ mediaPoolItem: VIDEO, frameCount }),
      );
      assert.equal(clipInfos.length, 1, `frameCount ${String(frameCount)} dropped the clip`);
      // Falls back to the plan's own 250 frame asset length.
      assert.equal(clipInfos[0].endFrame, 250);
    }
  });

  it("never emits an item Resolve would reject, whatever the plan says", () => {
    const nonsense = [
      { start_frame: -5, duration_frames: 0 },
      { start_frame: 1e9, duration_frames: 1e9 },
      { start_frame: null, duration_frames: null },
    ].map((source_in) => ({ ...planItem(0, 1), source_in }));

    const { clipInfos } = buildVideoClipInfos(nonsense, () => ({ mediaPoolItem: VIDEO, frameCount: 250 }));

    assert.ok(clipInfos.length >= 1, "a usable range must survive");
    for (const clipInfo of clipInfos) {
      assert.ok(clipInfo.startFrame >= 0, "startFrame must not be negative");
      assert.ok(clipInfo.endFrame > clipInfo.startFrame, "a zero length range is rejected by Resolve");
      assert.ok(clipInfo.endFrame <= 250, "endFrame must stay inside the media");
    }
  });
});

describe("buildMusicClipInfo", () => {
  it("starts at timeline frame 0 on the music track", () => {
    const clipInfo = buildMusicClipInfo({
      mediaPoolItem: MUSIC, timelineFrames: 3000, musicFrames: 3750, trackIndex: 1, recordFrame: 0,
    });
    assert.deepEqual(clipInfo, {
      mediaPoolItem: MUSIC, startFrame: 0, endFrame: 3000, mediaType: 2, trackIndex: 1, recordFrame: 0,
    });
  });

  it("clamps the music to the rough cut when the track is longer", () => {
    assert.equal(
      buildMusicClipInfo({ mediaPoolItem: MUSIC, timelineFrames: 3000, musicFrames: 9000 }).endFrame,
      3000,
    );
  });

  it("clamps the music to the real track length when the rough cut is longer", () => {
    assert.equal(
      buildMusicClipInfo({ mediaPoolItem: MUSIC, timelineFrames: 9000, musicFrames: 3000 }).endFrame,
      3000,
    );
  });

  it("honours a non-zero timeline start frame", () => {
    assert.equal(
      buildMusicClipInfo({
        mediaPoolItem: MUSIC, timelineFrames: 100, musicFrames: 100, recordFrame: 86400,
      }).recordFrame,
      86400,
    );
  });

  it("returns null when no length is known", () => {
    assert.equal(
      buildMusicClipInfo({ mediaPoolItem: MUSIC, timelineFrames: null, musicFrames: null }),
      null,
    );
  });
});

describe("plan measurements", () => {
  it("adds up the timeline duration of every plan item", () => {
    assert.equal(timelineFrameCount({ items: [planItem(0, 25), planItem(0, 50)] }), 75);
  });

  it("returns null for an empty plan", () => {
    assert.equal(timelineFrameCount({ items: [] }), null);
  });

  it("reads the exact rational seconds the engine sends", () => {
    // The engine states time as exact rationals, as the blueprint requires. Number() gives
    // NaN for these, which threw the music length limit away without a word.
    assert.equal(parseRational("1161665306122449/5000000000000"), 232.3330612244898);
    assert.equal(parseRational("150"), 150);
    assert.equal(parseRational("47/25"), 1.88);
    assert.equal(parseRational("232.333"), 232.333);
  });

  it("returns null rather than a wrong number for something unreadable", () => {
    for (const value of ["", "  ", "abc", "1/0", null, undefined, {}]) {
      assert.equal(parseRational(value), null, `parseRational(${JSON.stringify(value)})`);
    }
  });

  it("clamps the music with a rational duration, not just a decimal one", () => {
    const plan = { frame_rate: "50/1", music_duration_seconds: "1161665306122449/5000000000000" };

    assert.equal(musicFrameLimit(plan, null), 11616);
  });

  it("keeps the music inside a track shorter than the rough cut", () => {
    // Resolve stretches an audio item that overruns its media rather than refusing it, so
    // losing this limit lengthens the music instead of stopping it.
    const plan = { frame_rate: "25/1", music_duration_seconds: "601/10" };  // 60.1s
    const clip = buildMusicClipInfo({
      mediaPoolItem: MUSIC, timelineFrames: 3750, musicFrames: musicFrameLimit(plan, null),
    });

    assert.equal(clip.endFrame, 1502, "60.1s at 25fps");
  });

  it("converts the music duration to timeline frames", () => {
    assert.equal(musicFrameLimit({ frame_rate: "25/1", music_duration_seconds: "150.4" }, null), 3760);
  });

  it("prefers whichever music length is shorter", () => {
    assert.equal(musicFrameLimit({ frame_rate: "25/1", music_duration_seconds: "150" }, 3000), 3000);
  });

  it("parses rational and plain frame rates", () => {
    assert.equal(parseFrameRate("25/1"), 25);
    assert.equal(parseFrameRate("30000/1001"), 30000 / 1001);
    assert.equal(parseFrameRate("50"), 50);
    assert.equal(parseFrameRate(undefined), 25);
  });
});

describe("chunk", () => {
  it("splits the clips into Resolve sized batches", () => {
    const batches = chunk([...Array(95).keys()], 40);
    assert.deepEqual(batches.map((batch) => batch.length), [40, 40, 15]);
  });

  it("returns nothing for an empty list", () => {
    assert.deepEqual(chunk([], 40), []);
  });
});

// A stand-in for Resolve's MediaPool that reproduces the behaviour behind the reported bug:
// AppendToTimeline is all or nothing and rejects the entire batch as soon as one item points
// past the media, and the timeline records which media types actually landed on it.
function fakeResolve({ frameCount = 250 } = {}) {
  const timeline = { video: [], audio: new Map() };
  return {
    timeline,
    async AppendToTimeline(clipInfos) {
      for (const clipInfo of clipInfos) {
        // Measured against Resolve Studio 21.0.2: a zero length or inverted range is
        // rejected, and endFrame is exclusive. Running past the media is accepted, so the
        // fake only refuses what the real one refuses, plus the out-of-range case the
        // adapter is expected to have clamped away already.
        const invalid = clipInfo.startFrame < 0
          || clipInfo.endFrame <= clipInfo.startFrame
          || clipInfo.endFrame > frameCount;
        if (invalid) {
          const error = new Error("AppendToTimeline: Error response\nerrorStr: Invalid items to append for timeline\nerrorCode: 2");
          throw error;
        }
      }
      for (const clipInfo of clipInfos) {
        if (clipInfo.mediaType === 2) {
          const track = clipInfo.trackIndex ?? 1;
          timeline.audio.set(track, [...(timeline.audio.get(track) || []), clipInfo]);
        } else {
          timeline.video.push(clipInfo);
        }
      }
      return clipInfos.map((clipInfo) => ({ clipInfo }));
    },
  };
}

describe("Resolve handoff (regression: clips 81-120 rejected as invalid items)", () => {
  // 120 clips whose stored source ranges walk to the very end of the media, and slightly
  // past it: exactly the plan shape that made Resolve reject the third batch.
  const plan = {
    frame_rate: "25/1",
    music_path: "/media/track.wav",
    music_duration_seconds: "150",
    items: Array.from({ length: 120 }, (_, index) => ({
      source_path: "/media/A001.mov",
      asset_duration_frames: 250,
      source_in: { start_frame: index * 2, duration_frames: 40 },
      timeline_in: { start_frame: index * 25, duration_frames: 25 },
    })),
  };
  const media = { mediaPoolItem: VIDEO, frameCount: 250 };

  it("appends all 120 clips without Resolve rejecting a batch", async () => {
    // Before the fix the stored ranges ran to frame 279 while the media holds 250, and the
    // third AppendToTimeline batch came back as "Invalid items to append", errorCode 2.
    const mediaPool = fakeResolve();
    const { clipInfos, labels } = buildVideoClipInfos(plan.items, () => media);

    const appended = await appendClipsInBatches({ mediaPool, clipInfos, labels });

    assert.equal(appended, 120);
    assert.equal(mediaPool.timeline.video.length, 120);
  });

  it("brings no camera audio onto any audio track", async () => {
    const mediaPool = fakeResolve();
    const { clipInfos, labels } = buildVideoClipInfos(plan.items, () => media);

    await appendClipsInBatches({ mediaPool, clipInfos, labels });

    assert.equal(mediaPool.timeline.audio.size, 0);
    assert.ok(mediaPool.timeline.video.every((clipInfo) => clipInfo.mediaType === 1));
  });

  it("puts the chosen music on A1 at frame 0, clamped to the rough cut", async () => {
    const mediaPool = fakeResolve({ frameCount: 3750 });

    const musicClip = buildMusicClipInfo({
      mediaPoolItem: MUSIC,
      timelineFrames: timelineFrameCount(plan),
      musicFrames: musicFrameLimit(plan, 3750),
      trackIndex: 1,
      recordFrame: 0,
    });
    await mediaPool.AppendToTimeline([musicClip]);

    const a1 = mediaPool.timeline.audio.get(1);
    assert.equal(a1.length, 1);
    assert.equal(a1[0].recordFrame, 0, "music must start at timeline frame 0");
    assert.equal(a1[0].startFrame, 0, "music must start at its own frame 0");
    // 120 clips * 25 frames = 3000 frames of rough cut, shorter than the 150s track.
    assert.equal(a1[0].endFrame, 3000);
  });

  it("still reports the offending clips by name when Resolve refuses a batch", async () => {
    // Resolve really holds 199 frames while the plan was clamped against a stale 250, so the
    // third batch is the first to contain an out-of-range item: the reported 81-120 failure.
    const mediaPool = fakeResolve({ frameCount: 199 });
    const { clipInfos, labels } = buildVideoClipInfos(plan.items, () => media);

    await assert.rejects(
      () => appendClipsInBatches({ mediaPool, clipInfos, labels }),
      (error) => {
        assert.match(error.message, /Resolve 81-120\. video kliplerini ekleyemedi/);
        assert.match(error.message, /Invalid items to append for timeline/);
        assert.match(error.message, /\/media\/A001\.mov \[\d+-\d+\]/);
        return true;
      },
    );
  });
});

describe("buildMusicClipInfos", () => {
  const plan = (segments, extra = {}) => ({
    frame_rate: "25/1",
    items: Array.from({ length: 4 }, () => ({ timeline_in: { duration_frames: 750 } })),
    music_segments: segments,
    ...extra,
  });
  const lookup = (name) => ({ id: name });

  it("lays one clip per song, each where the plan put it", () => {
    const { clipInfos } = buildMusicClipInfos({
      plan: plan([
        { path: "/m/yavas.mp3", timeline_start_seconds: "0", duration_seconds: "90",
          source_start_seconds: "0", source_total_seconds: "200" },
        { path: "/m/hareketli.mp3", timeline_start_seconds: "90", duration_seconds: "30",
          source_start_seconds: "40", source_total_seconds: "150" },
      ]),
      lookup,
    });

    assert.equal(clipInfos.length, 2);
    assert.deepEqual(
      clipInfos.map((c) => [c.recordFrame, c.startFrame, c.endFrame]),
      [[0, 0, 2250], [2250, 1000, 1750]],
    );
  });

  it("puts every song on the music track as audio", () => {
    const { clipInfos } = buildMusicClipInfos({
      plan: plan([
        { path: "/m/a.mp3", timeline_start_seconds: "0", duration_seconds: "60",
          source_start_seconds: "0", source_total_seconds: "200" },
        { path: "/m/b.mp3", timeline_start_seconds: "60", duration_seconds: "60",
          source_start_seconds: "0", source_total_seconds: "200" },
      ]),
      lookup,
      trackIndex: 1,
    });

    for (const clip of clipInfos) {
      assert.equal(clip.mediaType, 2);
      assert.equal(clip.trackIndex, 1);
    }
  });

  it("offsets every record frame by where the timeline starts", () => {
    const { clipInfos } = buildMusicClipInfos({
      plan: plan([
        { path: "/m/a.mp3", timeline_start_seconds: "0", duration_seconds: "60",
          source_start_seconds: "0", source_total_seconds: "200" },
        { path: "/m/b.mp3", timeline_start_seconds: "60", duration_seconds: "60",
          source_start_seconds: "0", source_total_seconds: "200" },
      ]),
      lookup,
      timelineStart: 90000,
    });

    assert.deepEqual(clipInfos.map((c) => c.recordFrame), [90000, 91500]);
  });

  it("never runs a song past the end of the picture", () => {
    const { clipInfos } = buildMusicClipInfos({
      plan: plan([
        { path: "/m/a.mp3", timeline_start_seconds: "0", duration_seconds: "500",
          source_start_seconds: "0", source_total_seconds: "900" },
      ]),
      lookup,
    });

    // Four clips of 750 frames is 3000 frames of picture.
    assert.equal(clipInfos[0].endFrame - clipInfos[0].startFrame, 3000);
  });

  it("never runs a song past the end of its own file", () => {
    const { clipInfos } = buildMusicClipInfos({
      plan: plan([
        { path: "/m/a.mp3", timeline_start_seconds: "0", duration_seconds: "90",
          source_start_seconds: "40", source_total_seconds: "60" },
      ]),
      lookup,
    });

    assert.equal(clipInfos[0].startFrame, 1000);
    assert.equal(clipInfos[0].endFrame, 1500);
  });

  it("drops a song that starts after the picture ends", () => {
    const { clipInfos } = buildMusicClipInfos({
      plan: plan([
        { path: "/m/a.mp3", timeline_start_seconds: "0", duration_seconds: "120",
          source_start_seconds: "0", source_total_seconds: "200" },
        { path: "/m/late.mp3", timeline_start_seconds: "500", duration_seconds: "30",
          source_start_seconds: "0", source_total_seconds: "200" },
      ]),
      lookup,
    });

    assert.equal(clipInfos.length, 1);
  });

  it("reports a song the media pool does not hold instead of skipping it", () => {
    const { clipInfos, missing } = buildMusicClipInfos({
      plan: plan([
        { path: "/m/a.mp3", timeline_start_seconds: "0", duration_seconds: "60",
          source_start_seconds: "0", source_total_seconds: "200" },
        { path: "/m/yok.mp3", timeline_start_seconds: "60", duration_seconds: "60",
          source_start_seconds: "0", source_total_seconds: "200" },
      ]),
      lookup: (name) => (name === "/m/yok.mp3" ? null : { id: name }),
    });

    assert.deepEqual(missing, ["/m/yok.mp3"]);
    assert.equal(clipInfos.length, 1);
  });

  it("reads the exact rationals the engine emits", () => {
    const { clipInfos } = buildMusicClipInfos({
      plan: plan([
        { path: "/m/a.mp3", timeline_start_seconds: "0",
          duration_seconds: "1161665306122449/29000000000000",
          source_start_seconds: "0", source_total_seconds: "200" },
      ]),
      lookup,
    });

    // 40.05... seconds at 25 fps.
    assert.equal(clipInfos[0].endFrame, 1001);
  });
});

describe("musicSegments", () => {
  it("reads the songs a plan carries", () => {
    const segments = musicSegments({
      music_segments: [{ path: "/m/a.mp3" }, { path: "/m/b.mp3" }],
    });

    assert.deepEqual(segments.map((s) => s.path), ["/m/a.mp3", "/m/b.mp3"]);
  });

  it("falls back to the single music_path of an older plan", () => {
    const segments = musicSegments({ music_path: "/m/tek.mp3", music_duration_seconds: "150" });

    assert.equal(segments.length, 1);
    assert.equal(segments[0].path, "/m/tek.mp3");
    assert.equal(segments[0].sourceTotalSeconds, "150");
  });

  it("returns nothing for a plan with no music at all", () => {
    assert.deepEqual(musicSegments({}), []);
    assert.deepEqual(musicSegments(null), []);
  });

  it("ignores an entry with no path", () => {
    assert.deepEqual(musicSegments({ music_segments: [{ duration_seconds: "10" }] }), []);
  });
});

describe("frame rate agreement", () => {
  it("accepts the same rate written either way", () => {
    assert.equal(frameRatesAgree("50", "50/1"), true);
    assert.equal(frameRatesAgree("23.976", "24000/1001"), true);
  });

  it("refuses a plan cut at another rate", () => {
    // The user's project was 24 and the plan 50: 114 clips, 113 gaps, 3837 frames of black.
    assert.equal(frameRatesAgree("24", "50/1"), false);
    assert.equal(frameRatesAgree("25", "50/1"), false);
  });

  it("refuses anything it cannot read rather than guessing", () => {
    assert.equal(frameRatesAgree(null, "50/1"), false);
    assert.equal(frameRatesAgree("", "50/1"), false);
    assert.equal(frameRatesAgree("24", "0/0"), false);
  });

  it("writes a rate the way Resolve spells it", () => {
    assert.equal(resolveFrameRateSetting("50/1"), "50");
    assert.equal(resolveFrameRateSetting("25/1"), "25");
    assert.equal(resolveFrameRateSetting("24000/1001"), "23.976");
    assert.equal(resolveFrameRateSetting("30000/1001"), "29.97");
    assert.equal(resolveFrameRateSetting("60000/1001"), "59.94");
  });

  it("has nothing to write for a rate it cannot read", () => {
    assert.equal(resolveFrameRateSetting("0/0"), null);
    assert.equal(resolveFrameRateSetting(undefined), null);
  });
});
