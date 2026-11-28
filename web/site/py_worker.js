// Spunfection Studio on the web: the Python side (Pyodide) in a Web Worker, so the page
// stays responsive while it builds avatars and patterns. It loads drape's Python code
// (drape_bundle.zip) and answers the studio's /api requests with drape/webapi.py.
// A module worker (new Worker(..., {type: "module"})): Pyodide is an ES module.
// Messages in: {id, method, path, body}. Out: {id, res} or {id, error}; and {status} while loading.
"use strict";
const PYODIDE = "314.0.8";   // as the speed test (web/proof.html)
let py = null;
const ready = (async () => {
  const say = s => postMessage({status: s});
  say("Loading Python (first visit: about a minute, then it's cached)…");
  const {loadPyodide} = await import(`https://cdn.jsdelivr.net/pyodide/v${PYODIDE}/full/pyodide.mjs`);
  py = await loadPyodide();
  say("Loading numpy, SciPy, Shapely, matplotlib…");
  await py.loadPackage(["micropip"]);
  await py.pyimport("micropip").install(["numpy", "scipy", "shapely", "matplotlib", "pillow", "scikit-image", "ezdxf"]);
  say("Loading Spunfection Studio…");
  const buf = await (await fetch("drape_bundle.zip")).arrayBuffer();
  py.unpackArchive(buf, "zip", {extractDir: "/app"});
  await py.runPythonAsync(`
import os, sys
os.environ.update(DRAPE_SDF_CACHE="/tmp/sdf", DRAPE_CACHE_ROOT="/tmp/nc", MPLBACKEND="Agg", DRAPE_GRID_H="0.008")
os.chdir("/app"); sys.path.insert(0, "/app")
from drape import webapi
`);
  say("ready");
})();
ready.catch(err => postMessage({status: "Couldn't start Python: " + (err && err.message || err), failed: true}));

onmessage = async e => {
  const {id, method, path, body} = e.data;
  try {
    await ready;
    const handle = py.globals.get("webapi").handle;
    const r = handle(method, path, body == null ? null : body);
    const res = r.toJs({dict_converter: Object.fromEntries}); r.destroy();
    postMessage({id, res});
  } catch (err) {
    postMessage({id, error: String(err && err.message || err)});
  }
};
