"""Merge one article into the index.html payload. Idempotent.

    python tools/patch_app.py news/2026-10-14.json

The article file carries, besides the article itself (§3.7), two optional
side tables produced by gloss.py: `dict` (new entries) and `names`. They are
merged into the payload-level dict / names and are not stored on the article.

Idempotency rules (spec §4.7):
  - article replaced in place if its id already exists, else appended;
    `seq` (insertion order) is preserved for existing articles
  - dict entries: existing entries keep their hand-edited fields; new ones are
    added; `ls` gets the article id once for every lemma that occurs in it
  - names: added, existing kept
  - known / meta are recomputed from known/known.json + data/bands.json, and
    meta.built is the newest article id, so reruns are byte-identical
The shell (everything outside <script id="data">) is never touched.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from enlib import KNOWN, ROOT, effective_known, load_bands, load_json

INDEX = ROOT / "index.html"
BLOCK = re.compile(r'(<script id="data" type="application/json">)(.*?)(</script>)', re.S)
ARTICLE_KEYS = ("id", "seq", "domain", "title", "level", "source", "coverage", "vocab",
                "blocks", "questions")


def read_payload(html: str) -> dict:
    m = BLOCK.search(html)
    if not m:
        sys.exit("index.html: <script id=\"data\"> block not found")
    return json.loads(m.group(2))


def write_payload(html: str, payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    blob = blob.replace("</", "<\\/")  # never close the script tag early
    return BLOCK.sub(lambda m: m.group(1) + blob + m.group(3), html, count=1)


def lemmas_in(article: dict) -> list[str]:
    seen, out = set(), []
    for b in article["blocks"]:
        for s in b["sents"]:
            for t in s:
                l = t.get("l")
                if l and l not in seen:
                    seen.add(l)
                    out.append(l)
    return out


def known_section() -> tuple[dict, dict]:
    kf = KNOWN / "known.json"
    known = load_json(kf) if kf.exists() else {}
    bands = load_bands()
    eff = effective_known(known)
    size = Counter(bands.values())
    kn = Counter(bands[l] for l in eff if l in bands)
    meta = {
        "known_version": known.get("updated", ""),
        "frontier_band": known.get("frontier_band"),
        "band_size": {str(b): size[b] for b in sorted(size)},
        "band_known": {str(b): kn[b] for b in sorted(size)},
    }
    ks = {k: known[k] for k in ("updated", "source", "threshold_band", "frontier_band", "known",
                                 "known_extra", "unknown_in_known", "app_known", "history")
          if k in known}
    return ks, meta


def patch(article_path: Path) -> None:
    art = load_json(article_path)
    html = INDEX.read_text(encoding="utf-8")
    payload = read_payload(html)
    ARTICLES = payload.setdefault("articles", [])
    DICT = payload.setdefault("dict", {})
    NAMES = payload.setdefault("names", {})
    ID = art["id"]

    new_dict = art.pop("dict", {}) or {}
    new_names = art.pop("names", {}) or {}

    prior = next((x for x in ARTICLES if x["id"] == ID), None)
    seq = prior["seq"] if prior else max((x.get("seq", 0) for x in ARTICLES), default=0) + 1
    record = {k: art[k] for k in ARTICLE_KEYS if k in art and k != "seq"}
    record = {"id": ID, "seq": seq, **{k: v for k, v in record.items() if k != "id"}}
    if prior:
        ARTICLES[ARTICLES.index(prior)] = record
    else:
        ARTICLES.append(record)
    ARTICLES.sort(key=lambda x: x["seq"])

    for lemma, entry in new_dict.items():
        if lemma not in DICT:
            DICT[lemma] = {k: v for k, v in entry.items() if k != "ls"}
            DICT[lemma]["ls"] = []
        else:  # keep hand edits, fill gaps only
            for k, v in entry.items():
                if k != "ls" and not DICT[lemma].get(k):
                    DICT[lemma][k] = v
    for lemma in lemmas_in(record):
        if lemma in DICT:
            ls = DICT[lemma].setdefault("ls", [])
            if ID not in ls:
                ls.append(ID)
                ls.sort()
    for name, entry in new_names.items():
        NAMES.setdefault(name, entry)

    payload["dict"] = dict(sorted(DICT.items()))
    payload["names"] = dict(sorted(NAMES.items()))
    ks, meta = known_section()
    payload["known"] = ks
    payload["meta"] = {"built": max(x["id"] for x in ARTICLES), **meta}
    payload = {k: payload[k] for k in ("meta", "dict", "names", "articles", "known")}

    INDEX.write_text(write_payload(html, payload), encoding="utf-8", newline="\n")
    missing = [l for l in lemmas_in(record) if l not in DICT]
    print(f"patched {ID}: seq {seq}, {len(ARTICLES)} articles, {len(DICT)} dict entries, "
          f"{len(NAMES)} names" + (f"; WARNING {len(missing)} lemmas without dict entry: "
                                   f"{' '.join(missing[:20])}" if missing else ""))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    patch(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
