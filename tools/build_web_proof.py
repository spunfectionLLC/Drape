"""Build the in-browser speed test: out/web_proof/ with the page, the GPU solver
(live_springs.js) and drape_bundle.zip (drape's Python code, the body model and the
example measurements). Serve the folder over http(s) and open index.html."""
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "web_proof"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copy(ROOT / "web" / "proof.html", OUT / "index.html")
    shutil.copy(ROOT / "drape" / "studio" / "static" / "live_springs.js", OUT / "live_springs.js")
    shutil.copy(ROOT / "web" / "HOW_TO_RUN.txt", OUT / "HOW_TO_RUN.txt")
    # the footer's placeholder pages (Cloudflare Pages serves /terms from terms.html)
    sys.path.insert(0, str(ROOT))
    from drape import brand
    for path in brand.PAGES:
        (OUT / f"{path.strip('/')}.html").write_bytes(brand.placeholder_page(path))
    with zipfile.ZipFile(OUT / "drape_bundle.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "drape").rglob("*")):
            rel = f.relative_to(ROOT)
            if f.is_dir() or "__pycache__" in rel.parts or "static" in rel.parts:
                continue
            if f.suffix in (".py", ".npz", ".md", ".json"):
                z.write(f, rel.as_posix())
        for f in sorted((ROOT / "measurements").glob("*.json")):
            z.write(f, f.relative_to(ROOT).as_posix())
    size = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"built {OUT} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
