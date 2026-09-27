const assert = require("node:assert/strict");
const path = require("node:path");
const { describe, it } = require("node:test");

const {
  allMediaPoolFolders,
  canonicalMediaKey,
  ensurePoolMedia,
  planMediaImport,
} = require("./timeline-builder");

const NFD = "/Volumes/T7/17 EYLÜL/CLIP/K2S0387.MP4";
const NFC = NFD.normalize("NFC");
const keyOf = (p) => canonicalMediaKey(p, { resolvePath: path.resolve });

// A Media Pool the way Resolve reports it: nested bins, File Path composed (NFC), and
// ImportMedia adding a new item for every path it is given -- which is what made duplicates.
function fakePool(tree) {
  const imports = [];
  const make = (filePath) => ({
    GetClipProperty: async () => ({ "File Path": filePath.normalize("NFC") }),
  });
  const build = (node) => ({
    name: node.name,
    clips: (node.clips || []).map(make),
    subs: (node.subs || []).map(build),
    async GetClipList() { return this.clips; },
    async GetSubFolderList() { return this.subs; },
  });
  const root = build(tree);
  const all = () => {
    const out = [];
    const walk = (f) => { out.push(...f.clips); f.subs.forEach(walk); };
    walk(root);
    return out;
  };
  return {
    imports,
    count: () => all().length,
    async GetRootFolder() { return root; },
    async ImportMedia(paths) {
      imports.push(...paths);
      const created = paths.map(make);
      root.clips.push(...created);
      return created;
    },
  };
}

describe("canonical media identity", () => {
  it("treats NFC and NFD spellings of one file as one file", () => {
    assert.equal(keyOf(NFD), keyOf(NFC));
  });

  it("does not merge same basename in different folders", () => {
    assert.notEqual(keyOf("/a/CLIP/C7620.MP4"), keyOf("/b/CLIP/C7620.MP4"));
  });

  it("does not merge paths differing only in case", () => {
    assert.notEqual(keyOf("/a/C7620.MP4"), keyOf("/a/c7620.mp4"));
  });

  it("collapses redundant separators and dot segments", () => {
    assert.equal(keyOf("/a//b/./C7620.MP4"), keyOf("/a/b/C7620.MP4"));
  });

  it("collapses a symlink or volume alias when a realpath is given", () => {
    const realpath = (p) => p.replace("/Volumes/alias", "/Volumes/T7");
    const key = (p) => canonicalMediaKey(p, { resolvePath: path.resolve, realpath });
    assert.equal(key("/Volumes/alias/x.MP4"), key("/Volumes/T7/x.MP4"));
  });

  it("keeps a textual identity when the file cannot be reached", () => {
    const realpath = () => { throw new Error("ENOENT"); };
    assert.equal(canonicalMediaKey(NFD, { resolvePath: path.resolve, realpath }), NFC);
  });

  it("asks once for a path the plan names twice", () => {
    const { missing } = planMediaImport([], [NFD, NFC], keyOf);
    assert.deepEqual(missing, [NFD]);
  });

  it("reports existing duplicates without dropping either", () => {
    const a = { id: "a" };
    const b = { id: "b" };
    const { itemByKey, duplicateGroups } = planMediaImport(
      [{ item: a, filePath: NFC }, { item: b, filePath: NFC }], [NFD], keyOf);
    assert.equal(itemByKey.get(keyOf(NFC)), a);
    assert.deepEqual(duplicateGroups.get(keyOf(NFC)), [a, b]);
  });
});

describe("Media Pool import is idempotent", () => {
  it("finds a clip that sits in a nested bin rather than importing it again", async () => {
    const pool = fakePool({ name: "Master", subs: [{ name: "clip", subs: [{ name: "CLIP", clips: [NFC] }] }] });
    const { imported } = await ensurePoolMedia(pool, [NFD], { keyOf });
    assert.equal(imported, 0);
    assert.equal(pool.count(), 1);
  });

  it("imports a missing file once, and nothing on the next run", async () => {
    const pool = fakePool({ name: "Master" });
    await ensurePoolMedia(pool, [NFD, "/x/music.mp3"], { keyOf });
    assert.equal(pool.count(), 2);
    for (let run = 0; run < 5; run += 1) {
      const { imported } = await ensurePoolMedia(pool, [NFD, "/x/music.mp3"], { keyOf });
      assert.equal(imported, 0);
    }
    assert.equal(pool.count(), 2);
  });

  it("keeps two different files with the same basename apart", async () => {
    const pool = fakePool({ name: "Master", clips: ["/a/C7620.MP4"] });
    await ensurePoolMedia(pool, ["/a/C7620.MP4", "/b/C7620.MP4"], { keyOf });
    assert.deepEqual(pool.imports, ["/b/C7620.MP4"]);
    assert.equal(pool.count(), 2);
  });

  it("leaves existing duplicates in place", async () => {
    const pool = fakePool({ name: "Master", clips: [NFC], subs: [{ name: "old", clips: [NFC] }] });
    const { duplicateGroups, imported } = await ensurePoolMedia(pool, [NFD], { keyOf });
    assert.equal(imported, 0);
    assert.equal(duplicateGroups.size, 1);
    assert.equal(pool.count(), 2);
  });

  it("lists every folder so FCPXML links to what is already there", async () => {
    const pool = fakePool({ name: "Master", subs: [{ name: "a", subs: [{ name: "b" }] }] });
    const names = (await allMediaPoolFolders(pool)).map((f) => f.name);
    assert.deepEqual(names, ["Master", "a", "b"]);
  });
});

describe("plugin wiring", () => {
  const fs = require("node:fs");
  const source = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");

  it("never asks FCPXML import to bring its own source clips", () => {
    assert.ok(!/importSourceClips:\s*true/.test(source));
    assert.match(source, /importSourceClips:\s*false/);
  });

  it("has exactly one ImportMedia call site, inside the shared idempotent helper", () => {
    assert.equal((source.match(/ImportMedia\(/g) || []).length, 0);
    const lib = fs.readFileSync(path.join(__dirname, "timeline-builder.js"), "utf8");
    assert.equal((lib.match(/\.ImportMedia\(/g) || []).length, 1);
  });
});
