"""Seed or grow known/known.json.

    python tools/seed_known.py path/to/vocab-test-YYYY-MM-DD.json     # seed from a test
    python tools/seed_known.py --merge path/to/known-export.json      # merge an app export

Seed (spec §2.5):
  known            = every lemma in bands <= threshold_band
  known_extra      = test items she knew above the threshold
  unknown_in_known = test items she missed inside the threshold bands
  The result file is copied into known/history/ (idempotent). On a retake,
  earlier known_extra entries that came from the app (marked "Đã biết") and
  are still above the new threshold are kept — the test does not unlearn them.

Merge (app "Export known.json"):
  The export is a full known.json plus `changes` = the reader's explicit marks
  {"known": [...], "learning": [...], "unknown": [...]}. Changes are applied on
  top of the current known/known.json:
    marked known    -> removed from unknown_in_known, or added to known_extra
    learning/unknown-> removed from known_extra, added to unknown_in_known if
                       the lemma is in a known band
  Lists are de-duplicated and sorted, so merging the same export twice gives
  the same file.

Both modes append to `history` ([{date, size, source}], one row per source),
which the Tiến độ tab draws.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from enlib import KNOWN, dump_json, effective_known, load_bands, load_json

KNOWN_FILE = KNOWN / "known.json"


def _history(prev: dict | None, date: str, size: int, source: str) -> list[dict]:
    rows = [r for r in (prev or {}).get("history", []) if r.get("source") != source]
    rows.append({"date": date, "size": size, "source": source})
    return sorted(rows, key=lambda r: (r["date"], r["source"]))


def _finish(obj: dict) -> dict:
    for k in ("known", "known_extra", "unknown_in_known"):
        obj[k] = sorted(set(obj.get(k, [])))
    return obj


def seed(result_path: Path) -> dict:
    res = load_json(result_path)
    bands = load_bands()
    items = {it["id"]: it for it in load_json(
        KNOWN.parent / "test" / f"items.{res['version']}.json")["items"]}
    thr = int(res["threshold_band"])
    known = [l for l, b in bands.items() if b <= thr]
    extra, unk = set(), set()
    for r in res["responses"]:
        it = items.get(r["id"])
        if not it or not it["real"]:
            continue
        w, b = it["w"], it["band"]
        if b > thr and r["known"]:
            extra.add(w)
        elif b <= thr and not r["known"]:
            unk.add(w)

    prev = load_json(KNOWN_FILE) if KNOWN_FILE.exists() else None
    if prev:
        # keep words the reader marked known in the app, if still above threshold
        app_extra = set(prev.get("app_known", []))
        extra |= {l for l in app_extra if bands.get(l, 99) > thr}

    name = f"vocab-test-{res['date']}.json"
    hist_dir = KNOWN / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    dest = hist_dir / name
    if result_path.resolve() != dest.resolve():
        shutil.copyfile(result_path, dest)

    out = _finish({
        "updated": res["date"],
        "source": name,
        "threshold_band": thr,
        "frontier_band": int(res["frontier_band"]),
        "known": known,
        "known_extra": list(extra),
        "unknown_in_known": list(unk),
        "app_known": sorted(set((prev or {}).get("app_known", []))),
    })
    out["history"] = _history(prev, res["date"], len(effective_known(out)), name)
    return out


def merge(export_path: Path) -> dict:
    exp = load_json(export_path)
    if not KNOWN_FILE.exists():
        sys.exit("known/known.json does not exist — seed from a test result first")
    base = load_json(KNOWN_FILE)
    ch = exp.get("changes") or {}
    known_base = set(base["known"])
    extra = set(base.get("known_extra", []))
    unk = set(base.get("unknown_in_known", []))
    app_known = set(base.get("app_known", []))
    for l in ch.get("known", []):
        app_known.add(l)
        if l in known_base:
            unk.discard(l)
        else:
            extra.add(l)
    for l in ch.get("learning", []) + ch.get("unknown", []):
        app_known.discard(l)
        extra.discard(l)
        if l in known_base:
            unk.add(l)
    source = exp.get("source") or export_path.name
    out = _finish({
        **{k: v for k, v in base.items() if k != "history"},
        "updated": max(base.get("updated", ""), exp.get("updated", "")),
        "known_extra": list(extra),
        "unknown_in_known": list(unk),
        "app_known": sorted(app_known),
    })
    out["history"] = _history(base, exp.get("updated", base.get("updated", "")),
                              len(effective_known(out)), source)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--merge", action="store_true", help="merge an app export")
    ap.add_argument("--out", type=Path, default=KNOWN_FILE)
    a = ap.parse_args()
    out = merge(a.path) if a.merge else seed(a.path)
    dump_json(out, a.out)
    eff = effective_known(out)
    print(f"{a.out}: threshold {out['threshold_band']}, frontier {out['frontier_band']}, "
          f"known {len(out['known'])}, extra {len(out['known_extra'])}, "
          f"unknown_in_known {len(out['unknown_in_known'])}, effective {len(eff)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
