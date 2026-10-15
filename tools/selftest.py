"""End-to-end self-test on a throwaway copy of the repo (spec §4.9). Exit 0/1.

    python tools/selftest.py

Run it once on every new machine before the first real run. It never touches
the real repo: everything happens in a temp copy with an empty app payload.

  good draft  (news/drafts/2026-10-14.json, the sample)
      coverage PASS -> gloss --check PASS -> build_article PASS -> patch_app x3
      (index.html identical each time) -> qa PASS
  bad draft   (same text with an out-of-level word, a number without a source
      row and a 35-word sentence)
      coverage FAIL, build_article FAIL and writes nothing
  broken app  (one dictionary entry removed from the payload)
      qa FAIL
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REAL = Path(__file__).resolve().parent.parent
SAMPLE = "2026-10-14"
BAD = "2026-10-13"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="enreader-selftest-"))
    repo = tmp / "repo"
    shutil.copytree(REAL, repo, ignore=shutil.ignore_patterns(
        ".git", ".venv", "node_modules", "__pycache__"))
    env = {**os.environ, "NODE_PATH": str(REAL / "node_modules"), "PYTHONIOENCODING": "utf-8"}
    py = sys.executable
    results = []

    def run(*args):
        p = subprocess.run([py, *args], cwd=repo, env=env, capture_output=True, text=True,
                           encoding="utf-8")
        return p.returncode, p.stdout + p.stderr

    def expect(name, code, want, out):
        ok = (code == 0) == want
        results.append((name, ok))
        print(f"{'ok ' if ok else 'BAD'}  {name}  (exit {code}, expected {'0' if want else '1'})")
        if not ok:
            print("     " + "\n     ".join(out.strip().splitlines()[-12:]))

    # fresh app: empty payload, no published articles
    sys.path.insert(0, str(repo / "tools"))
    from patch_app import read_payload, write_payload  # noqa: E402
    index = repo / "index.html"
    html = index.read_text(encoding="utf-8")
    index.write_text(write_payload(html, {"meta": {}, "dict": {}, "names": {}, "articles": [],
                                          "known": {}}), encoding="utf-8", newline="\n")
    for p in (repo / "news").glob("*.json"):
        p.unlink()

    d = f"news/drafts/{SAMPLE}.json"
    c, o = run("tools/coverage.py", d); expect("good: coverage", c, True, o)
    c, o = run("tools/gloss.py", d, "--check"); expect("good: gloss --check", c, True, o)
    c, o = run("tools/build_article.py", d); expect("good: build_article", c, True, o)
    hashes = []
    for i in range(3):
        c, o = run("tools/patch_app.py", f"news/{SAMPLE}.json")
        hashes.append(hashlib.sha256(index.read_bytes()).hexdigest())
    expect("good: patch_app x3 identical", 0 if len(set(hashes)) == 1 else 1, True, o)
    c, o = run("tools/qa.py", SAMPLE); expect("good: qa", c, True, o)

    # deliberately bad draft
    draft = json.loads((repo / d).read_text(encoding="utf-8"))
    draft["id"] = BAD
    draft["paragraphs"][0] += (" The garrison counted 99 visitors, and the agency said that the"
                               " numbers for the whole year would be released later in a long"
                               " report about travel between the two countries and their people.")
    bad = repo / f"news/drafts/{BAD}.json"
    bad.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    shutil.copy(repo / f"news/drafts/{SAMPLE}.gloss.tsv", repo / f"news/drafts/{BAD}.gloss.tsv")
    c, o = run("tools/coverage.py", str(bad.relative_to(repo)))
    expect("bad: coverage fails", c, False, o)
    caught = all(s in o for s in ("garrison", "'99'", "longest sentence"))
    expect("bad: all three faults reported", 0 if caught else 1, True, o)
    c, o = run("tools/build_article.py", str(bad.relative_to(repo)))
    expect("bad: build_article fails", c, False, o)
    expect("bad: nothing written", 1 if (repo / f"news/{BAD}.json").exists() else 0, True, "")

    # broken app: remove one dictionary entry
    html = index.read_text(encoding="utf-8")
    P = read_payload(html)
    P["dict"].pop("consecutive")
    index.write_text(write_payload(html, P), encoding="utf-8", newline="\n")
    c, o = run("tools/qa.py", SAMPLE); expect("broken app: qa fails", c, False, o)

    shutil.rmtree(tmp, ignore_errors=True)
    failed = [n for n, ok in results if not ok]
    print(f"\nSELFTEST: {'PASS' if not failed else 'FAIL'} ({len(results) - len(failed)}/{len(results)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
