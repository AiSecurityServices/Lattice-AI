"""Package the built web UI into the wheel: copies web/dist → src/lattice_ai/web_dist.

Run after `cd web && npm run build`, before `python -m build` / `pip wheel .`.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIST = ROOT / "web" / "dist"
DEST = ROOT / "src" / "lattice_ai" / "web_dist"

if not SRC_DIST.is_dir():
    print(f"build output missing: {SRC_DIST} — run `cd web && npm run build` first", file=sys.stderr)
    sys.exit(1)

if DEST.exists():
    shutil.rmtree(DEST)
shutil.copytree(SRC_DIST, DEST, ignore=shutil.ignore_patterns("*.map"))
print(f"packed web UI: {SRC_DIST} -> {DEST}")
