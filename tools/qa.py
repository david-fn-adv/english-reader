"""Phase 3 — render QA (spec §4.7). Exit 0 pass, 1 fail.

    python tools/qa.py 2026-10-16

Renders index.html in jsdom (runScripts 'dangerously', pretendToBeVisual,
url https://x.test/) via tools/qa_render.js and asserts:
  - every token with a lemma resolves to a populated dict entry (en, vi, ipa)
  - every `fig` id exists in source.figures, and every number has one
  - the article list shows the new card
  - opening the article and tapping every token shows a populated sheet
  - no console errors
Needs Node and `npm install` (jsdom) once in the repo root.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from enlib import ROOT


def node_exe() -> str:
    exe = shutil.which("node")
    if exe:
        return exe
    for p in (Path("C:/Program Files/nodejs/node.exe"), Path("/usr/local/bin/node"),
              Path("/opt/homebrew/bin/node")):
        if p.exists():
            return str(p)
    sys.exit("node not found — install Node.js LTS, then run `npm install` in the repo root")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    import os
    extra = os.environ.get("NODE_PATH", "")
    if not (ROOT / "node_modules" / "jsdom").exists() and not (Path(extra) / "jsdom").exists():
        sys.exit("jsdom missing — run `npm install` in the repo root")
    proc = subprocess.run([node_exe(), str(ROOT / "tools" / "qa_render.js"),
                           str(ROOT / "index.html"), sys.argv[1]],
                          capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    try:
        rep = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(proc.stdout, proc.stderr)
        print("QA: FAIL (no report)")
        return 1
    print(f"tokens {rep.get('tokens')}  sheets {rep.get('sheets_opened')}  "
          f"paragraphs {rep.get('paragraphs')}  card {rep.get('card')}  "
          f"console errors {len(rep.get('console_errors', []))}")
    for e in rep.get("console_errors", [])[:10]:
        print("  console:", e)
    if rep["pass"]:
        print("QA: PASS")
        return 0
    print("QA: FAIL")
    for f in rep["fails"]:
        print("  ✗", f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
