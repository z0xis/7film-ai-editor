const assert = require("node:assert/strict");
const { describe, it } = require("node:test");

const {
  appendClipsInBatches,
  buildMusicClipInfo,
  buildVideoClipInfos,
  chunk,
  clampSourceRange,
  musicFrameLimit,
  parseFrameRate,
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
      { startFrame: 10, endFrame: 49, durationFrames: 40 },
    );
  });

  it("trims a range that would run past the media Resolve reports", () => {
    assert.deepEqual(
      clampSourceRange({ startFrame: 240, durationFrames: 40, availableFrames: 250 }),
      { startFrame: 240, endFrame: 249, durationFrames: 10 },
    );
  });

  it("pulls a start beyond the media back onto the last frame", () => {
    assert.deepEqual(
      clampSourceRange({ startFrame: 900, durationFrames: 40, availableFrames: 250 }),
      { startFrame: 249, endFrame: 249, durationFrames: 1 },
    );
  });

  it("leaves the range untouched when the media length is unknown", () => {
    assert.deepEqual(
      clampSourceRange({ startFrame: 240, durationFrames: 40, availableFrames: null }),
      { startFrame: 240, endFrame: 279, durationFrames: 40 },
    );
  });

  it("keeps at least one frame on a single frame source", () => {
    assert.deepEqual(
      clampSourceRange({ startFrame: 0, durationFrames: 40, availableFrames: 1 }),
      { startFrame: 0, endFrame: 0, durationFrames: 1 },
    );
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

  it("clamps a late clip instead of letting Resolve reject the whole batch", () => {
    const { clipInfos } = buildVideoClipInfos([planItem(245, 40)], resolveMedia);
    assert.deepEqual(
      { startFrame: clipInfos[0].startFrame, endFrame: clipInfos[0].endFrame },
      { startFrame: 245, endFrame: 249 },
    );
  });

  it("falls back to the plan's asset frame count when Resolve reports none", () => {
    const { clipInfos } = buildVideoClipInfos(
      [planItem(245, 40)],
      () => ({ mediaPoolItem: VIDEO, frameCount: null }),
    );
    assert.equal(clipInfos[0].endFrame, 249);
  });

  it("reports a label per clip so a rejected batch names the offending file", () => {
    const { labels } = buildVideoClipInfos([planItem(245, 40)], resolveMedia);
    assert.deepEqual(labels, ["/media/A001.mov [245-249]"]);
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
      assert.equal(clipInfos[0].endFrame, 249);
    }
  });

  it("never emits an item Resolve would reject, whatever the plan says", () => {
    const nonsense = [
      { start_frame: -5, duration_frames: 0 },
      { start_frame: 1e9, duration_frames: 1e9 },
      { start_frame: null, duration_frames: null },
    ].map((source_in) => ({ ...planItem(0, 1), source_in }));

    const { clipInfos } = buildVideoClipInfos(nonsense, () => ({ mediaPoolItem: VIDEO, frameCount: 250 }));

    assert.equal(clipInfos.length, 3);
    for (const clipInfo of clipInfos) {
      assert.ok(clipInfo.startFrame >= 0, "startFrame must not be negative");
      assert.ok(clipInfo.endFrame >= clipInfo.startFrame, "endFrame must not precede startFrame");
      assert.ok(clipInfo.endFrame <= 249, "endFrame must stay inside the media");
    }
  });
});

describe("buildMusicClipInfo", () => {
  it("starts at timeline frame 0 on the music track", () => {
    const clipInfo = buildMusicClipInfo({
      mediaPoolItem: MUSIC, timelineFrames: 3000, musicFrames: 3750, trackIndex: 1, recordFrame: 0,
    });
    assert.deepEqual(clipInfo, {
      mediaPoolItem: MUSIC, startFrame: 0, endFrame: 2999, mediaType: 2, trackIndex: 1, recordFrame: 0,
    });
  });

  it("clamps the music to the rough cut when the track is longer", () => {
    assert.equal(
      buildMusicClipInfo({ mediaPoolItem: MUSIC, timelineFrames: 3000, musicFrames: 9000 }).endFrame,
      2999,
    );
  });

  it("clamps the music to the real track length when the rough cut is longer", () => {
    assert.equal(
      buildMusicClipInfo({ mediaPoolItem: MUSIC, timelineFrames: 9000, musicFrames: 3000 }).endFrame,
      2999,
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
        const invalid = clipInfo.startFrame < 0
          || clipInfo.endFrame < clipInfo.startFrame
          || clipInfo.endFrame >= frameCount;
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
    assert.equal(a1[0].endFrame, 2999);
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
