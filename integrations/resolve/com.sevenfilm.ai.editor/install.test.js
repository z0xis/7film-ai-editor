const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { describe, it } = require("node:test");

const PLUGIN_DIR = __dirname;
const INSTALLER = path.join(PLUGIN_DIR, "..", "..", "..", "scripts", "install_resolve_plugin.sh");

function localRequires(file) {
  const source = fs.readFileSync(path.join(PLUGIN_DIR, file), "utf8");
  return [...source.matchAll(/require\("\.\/([^"]+)"\)/g)]
    .map((match) => match[1])
    .filter((name) => !name.endsWith(".node"));
}

describe("the installer ships everything the plugin loads", () => {
  // The plugin is copied file by file into Resolve's plugin folder. A module left out of
  // that list only fails once Resolve tries to load it, by quietly not appearing in the menu.
  const installer = fs.readFileSync(INSTALLER, "utf8");

  it("copies every local module main.js requires", () => {
    for (const required of localRequires("main.js")) {
      const candidates = [required, `${required}.js`];
      assert.ok(
        candidates.some((name) => installer.includes(name)),
        `install_resolve_plugin.sh does not copy ${required}`,
      );
    }
  });

  it("copies the entry points Resolve itself needs", () => {
    for (const file of ["manifest.xml", "package.json", "main.js", "preload.js", "index.html"]) {
      assert.ok(installer.includes(file), `install_resolve_plugin.sh does not copy ${file}`);
    }
  });

  it("names main.js as the entry point package.json declares", () => {
    const manifest = JSON.parse(fs.readFileSync(path.join(PLUGIN_DIR, "package.json"), "utf8"));
    assert.ok(fs.existsSync(path.join(PLUGIN_DIR, manifest.main)), `${manifest.main} is missing`);
  });

  it("has every module it requires present in the source folder", () => {
    for (const required of localRequires("main.js")) {
      const resolved = path.join(PLUGIN_DIR, required.endsWith(".js") ? required : `${required}.js`);
      assert.ok(fs.existsSync(resolved), `${required} is missing from the plugin folder`);
    }
  });
});

describe("the import path the plugin leads with", () => {
  const source = fs.readFileSync(path.join(PLUGIN_DIR, "main.js"), "utf8");
  const flow = source.slice(source.indexOf("async function importTimeline"));

  it("builds the plan through the Resolve API before trying the FCPXML file", () => {
    // Only the API path can say picture-only, place the music on A1 and add the markers, and
    // it is the one verified against real Resolve.
    const api = flow.indexOf("createTimelineFromPlan(");
    const fcpxml = flow.indexOf("ImportTimelineFromFile(");
    assert.ok(api > -1 && fcpxml > -1, "both paths should still be present");
    assert.ok(api < fcpxml, "the verified Resolve API path must be attempted first");
  });

  it("takes the retimed plan through the API too, and keeps FCPXML underneath it", () => {
    // Until 21.1 a retimed plan had to go through FCPXML: AppendToTimeline laid a clip down at
    // its own speed and SetProperty offered pan, tilt, zoom, crop and the retime method, no
    // speed. 21.1 adds SetSpeed, measured against the FCPXML path on this footage — rendered
    // frame for frame the two are identical, and SetSpeed additionally leaves the item
    // reporting its real source position instead of 0.
    //
    // So the API path is tried for every plan, and FCPXML catches an older Resolve, a clip
    // with too little source, or a speed that does not read back.
    assert.match(source, /async function applySpeeds\(/);
    assert.match(source, /applySpeeds\(timeline, clipInfos\)/);
    // The speed has to be read back, and so does the length: SetSpeed kept a mid-timeline
    // clip at 100 frames but took the first clip of a real edit from 126 to 252, overwriting
    // the two after it.
    assert.match(source, /GetSpeed\(\)/);
    assert.match(source, /GetDuration\(\)/);
    const api = flow.indexOf("createTimelineFromPlan(");
    const fcpxml = flow.indexOf("ImportTimelineFromFile(");
    assert.ok(api < fcpxml, "FCPXML is the fallback, not the first choice");
    assert.match(flow, /catch \(error\)/, "the fallback has to be reachable on failure");
  });

  it("still downloads the FCPXML, which the fallback needs", () => {
    assert.match(flow, /downloadExport\(/);
  });

  it("reports which path built the timeline", () => {
    assert.match(flow, /importMethod/);
    assert.match(flow, /"Resolve API"/);
    assert.match(flow, /FCPXML/);
  });
});

describe("the plugin and the engine agree on a version", () => {
  const API = path.join(PLUGIN_DIR, "..", "..", "..", "apps", "api", "sevenfilm", "api.py");

  it("main.js declares the same ENGINE_VERSION as api.py", () => {
    // The installed copy lives under Resolve's plugin folder and does not move when the
    // repository does. When they disagree the plugin refuses the engine it just started,
    // waits twenty seconds and dies — which is how the window stopped opening at all.
    const plugin = fs.readFileSync(path.join(PLUGIN_DIR, "main.js"), "utf8")
      .match(/const ENGINE_VERSION = "([^"]+)"/);
    const engine = fs.readFileSync(API, "utf8").match(/^ENGINE_VERSION = "([^"]+)"/m);

    assert.ok(plugin, "main.js has no ENGINE_VERSION");
    assert.ok(engine, "api.py has no ENGINE_VERSION");
    assert.equal(plugin[1], engine[1]);
  });

  it("says which versions disagree instead of reporting a backend that never started", () => {
    const source = fs.readFileSync(path.join(PLUGIN_DIR, "main.js"), "utf8");

    assert.match(source, /install_resolve_plugin\.sh/);
    assert.match(source, /bildiriyor/);
  });
});
