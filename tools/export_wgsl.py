"""Export the GPU solver's shaders for drape.gpu (the drape button on the GPU).

studio/static/live_springs.js is the one source of the springs solver's WGSL. This runs
it in node, takes the shader text it builds (SPR_SOLVE_WGSL, SPR_BODY_WGSL, SPR_SELF_WGSL)
and the constants the host needs, and writes drape/data/springs_wgsl.json. Run it after
any change to live_springs.js; tests/test_v22_gpu_drape.py fails while the two differ.

    python tools/export_wgsl.py          (needs node on PATH)
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "drape" / "studio" / "static" / "live_springs.js"
OUT = ROOT / "drape" / "data" / "springs_wgsl.json"

NODE_SCRIPT = r"""
const fs = require("fs"), vm = require("vm");
const ctx = {window: {}, navigator: {}, console, Math, performance: {now: () => 0}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8") + `
;globalThis.__out = {solve: SPR_SOLVE_WGSL, body: SPR_BODY_WGSL, self: SPR_SELF_WGSL,
  fields: SPR_FIELDS, ubytes: SPR_UBYTES, vb: VB, vb_count: VB_COUNT, cg_budget: SPR_CG_BUDGET,
  cand: SPR_CAND, ecand: SPR_ECAND, wg: SPR_WG, grab_k: SPR_GRAB_K,
  speed_safety: SPEED_SAFETY, speed_headroom: SPEED_HEADROOM, nsub_cap: NSUB_CAP_LIVE};`, ctx);
process.stdout.write(JSON.stringify(ctx.__out));
"""


def export() -> dict:
    """The shaders and constants as live_springs.js builds them (runs node)."""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node is not on PATH")
    out = subprocess.run([node, "-e", NODE_SCRIPT, str(SRC)], capture_output=True, text=True,
                         encoding="utf-8", check=True)
    d = json.loads(out.stdout)
    d["source"] = "drape/studio/static/live_springs.js (tools/export_wgsl.py)"
    return d


def main():
    d = export()
    OUT.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: " + ", ".join(f"{k} {len(d[k])} chars" for k in ("solve", "body", "self")))


if __name__ == "__main__":
    sys.exit(main())
