"""Assemble news/<id>.json from a draft that passed coverage.py and gloss.py.

    python tools/build_article.py news/drafts/2026-10-16.json [--preview]

Draft format (written by the agent, see tools/daily-news.md):
  { "id": "YYYY-MM-DD", "domain": "business|travel|fashion", "title": "...",
    "source": { "url", "outlet", "author", "title", "date", "accessed",
                "figures": [ {"id": "f1", "text": "6.8% rise in September",
                              "quote": "verbatim snippet from the source"} ] },
    "paragraphs": [ "plain text", ... ],
    "names": { "Statistics Canada": {"vi": "..."} },      # multiword allowed
    "questions"?: [ {"q": "...", "a": ["...", "...", "..."], "correct": 1} ] }
Glosses: <draft>.gloss.tsv (see gloss.py).

Runs the coverage gate and the gloss gate again (so a stale draft can never
be assembled), then writes the article with blocks, coverage, vocab, and the
side tables `dict` (new entries only: ipa from cmudict or the TSV, pos, band,
en, vi) and `names`, which patch_app.py moves into the payload.
Exit 1 and write nothing if a gate fails; --preview writes anyway (for
looking at a draft in the reader) but still exits 1.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from coverage import analyze, print_report
from enlib import NEWS, dump_json, ipa_for, load_json, nlp, phrase_band
from gloss import check as gloss_check, load_tsv, needed, tsv_path


def assemble(draft_path: Path):
    from spacy.lang.en.stop_words import STOP_WORDS

    draft = load_json(draft_path)
    blocks, rep = analyze(draft)
    lemmas, _, _ = needed(draft)
    rows = load_tsv(tsv_path(draft_path))
    bands, known = rep["bands"], rep["known"]

    dict_out = {}
    for l in lemmas:
        r = rows.get(l, {})
        ipa, _ = ipa_for(l)
        if r.get("ipa") and r["ipa"] != "?":
            ipa = r["ipa"]
        entry = {"ipa": ipa or "", "pos": r.get("pos") or rep["pos_of"].get(l, ""),
                 "en": r.get("en", ""), "vi": r.get("vi", "")}
        band = phrase_band(l, bands, STOP_WORDS) if " " in l else bands.get(l)
        if band:
            entry["band"] = band
        dict_out[l] = entry

    order = []
    for b in blocks:
        for s in b["sents"]:
            for t in s:
                if t.get("l") and t["l"] not in order:
                    order.append(t["l"])
    core = rep["stats"]["core"]
    vocab = [l for l in order if l in core] + [l for l in order if " " in l and l not in core]

    names_out = {}
    for full, entry in draft.get("names", {}).items():
        toks = [t.text for t in nlp().tokenizer(full) if any(c.isalpha() for c in t.text)
                and not t.text.startswith("'")]
        for w in toks:   # keyed by token text, as the reader looks them up
            names_out.setdefault(w, {**entry, **({"full": full} if len(toks) > 1 else {})})

    article = {
        "id": draft["id"], "domain": draft["domain"], "title": draft["title"],
        "level": {"known_version": known.get("updated", ""), "frontier_band": rep["frontier"]},
        "source": draft["source"], "coverage": rep["coverage"], "vocab": vocab, "blocks": blocks,
    }
    if draft.get("questions"):
        article["questions"] = draft["questions"]
    article["dict"] = dict_out
    article["names"] = names_out
    return article, rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("draft", type=Path)
    ap.add_argument("--preview", action="store_true", help="write even if a gate fails")
    a = ap.parse_args()
    article, rep = assemble(a.draft)
    print_report(rep)
    ok = not rep["fails"]
    if rep["fails"]:
        print("\nCOVERAGE GATE: FAIL")
        for f in rep["fails"]:
            print("  ✗", f)
    print()
    ok = (gloss_check(a.draft) == 0) and ok
    if ok or a.preview:
        out = NEWS / f"{article['id']}.json"
        dump_json(article, out)
        print(f"wrote {out}" + ("" if ok else "  (PREVIEW — gates failed, do not publish)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
