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
