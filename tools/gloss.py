"""Phase 3 — dictionary entries for a draft (spec §4.5). Exit 0 pass, 1 fail.

    python tools/gloss.py news/drafts/2026-10-16.json            # write the template
    python tools/gloss.py news/drafts/2026-10-16.json --check    # gate the glosses

Which lemmas need an entry: every lemma or phrase in the draft that is not yet
in the app dictionary (index.html payload). The spec's §4.5 names core words
and phrases, but qa.py (§4.7) requires every tappable token to resolve to a
populated entry, so known words are glossed too — once; the dictionary
accumulates and later articles need fewer new entries.

The glosses live next to the draft in <draft>.gloss.tsv, one per line:
    lemma <TAB> pos <TAB> English (<= 15 words) <TAB> Vietnamese [<TAB> ipa]
Template mode appends a row for every lemma still missing (pos prefilled;
the ipa column says "?" when cmudict has no pronunciation — the agent then
writes the IPA and the PR flags it for review). Existing rows are never touched.

--check fails when a needed lemma has no row or an empty en/vi, when en is
longer than 15 words, when a "?" IPA was not filled in, or when the English
definition itself uses a word she cannot read: every word in it must be
known (or a known word + affix), a loanword, a function word, a grammar
word (METALANG), a capitalised name, the headword, or one of the article's
core / recycled words.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from coverage import analyze
from enlib import _derived_known, ipa_for, load_json, nlp
from patch_app import INDEX, read_payload

COLS = ("lemma", "pos", "en", "vi", "ipa")
# grammar words a definition may need ("used before a noun")
METALANG = {"noun", "verb", "adjective", "adverb", "vowel", "consonant", "plural",
            "sentence", "phrase", "preposition", "pronoun"}


def tsv_path(draft_path: Path) -> Path:
    return draft_path.with_suffix(".gloss.tsv")


def load_tsv(path: Path) -> dict[str, dict]:
    out = {}
    if not path.exists():
        return out
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = [x.strip() for x in line.split("\t")]
        if len(parts) not in (4, 5):
            sys.exit(f"{path}:{n}: expected 4 or 5 tab-separated fields, got {len(parts)}")
        row = dict(zip(COLS, parts))
        out[row["lemma"]] = row
    return out


def needed(draft: dict) -> tuple[list[str], dict, dict]:
    blocks, rep = analyze(draft)
    have = read_payload(INDEX.read_text(encoding="utf-8")).get("dict", {})
    lemmas = []
    for b in blocks:
        for s in b["sents"]:
            for t in s:
                l = t.get("l")
                if l and l not in lemmas and not (have.get(l, {}).get("en") and have[l].get("vi")):
                    lemmas.append(l)
    return lemmas, rep, have


def template(draft_path: Path) -> int:
    draft = load_json(draft_path)
    lemmas, rep, _ = needed(draft)
    path = tsv_path(draft_path)
    rows = load_tsv(path)
    add = []
    for l in lemmas:
        if l in rows:
            continue
        ipa, miss = ipa_for(l)
        add.append("\t".join([l, rep["pos_of"].get(l, ""), "", "", "?" if miss else ""]))
    if add:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if path.exists() and path.stat().st_size and not path.read_text(encoding="utf-8").endswith("\n"):
                f.write("\n")
            f.write("\n".join(add) + "\n")
    print(f"{len(lemmas)} lemmas need an entry; {len(add)} template rows added to {path}")
    return 0


def check(draft_path: Path) -> int:
    from spacy.lang.en.stop_words import STOP_WORDS

    draft = load_json(draft_path)
    lemmas, rep, _ = needed(draft)
    rows = load_tsv(tsv_path(draft_path))
    s = rep["stats"]
    readable = (rep["eff"] | rep["loans"] | set(STOP_WORDS) | set(s["core"]) | set(s["recycled"])
                | METALANG)
    fails = []
    defs = []
    for l in lemmas:
        r = rows.get(l)
        if not r or not r.get("en") or not r.get("vi"):
            fails.append(f"{l}: no English/Vietnamese gloss")
            continue
        if len(r["en"].split()) > 15:
            fails.append(f"{l}: English definition has {len(r['en'].split())} words (> 15)")
        if r.get("ipa", "") == "?":
            fails.append(f"{l}: not in cmudict — write the IPA in column 5")
        defs.append((l, r["en"]))
    for (l, en), doc in zip(defs, nlp().pipe(e for _, e in defs)):
        allowed = readable | set(l.split())
        bad = []
        for t in doc:
            if not any(c.isalpha() for c in t.text) or t.tag_ == "POS":
                continue
            if t.pos_ == "PROPN" and t.text[:1].isupper():   # names: "United States"
                continue
            lem = t.lemma_.lower()
            if lem in allowed or t.text.lower() in allowed or _derived_known(lem, t.text.lower(), rep["eff"]):
                continue
            bad.append(t.text)
        if bad:
            fails.append(f"{l}: definition uses words above her level: {', '.join(bad)}")
    if fails:
        print(f"GLOSS GATE: FAIL ({len(fails)})")
        for f in fails:
            print("  ✗", f)
        return 1
    print(f"GLOSS GATE: PASS — {len(lemmas)} new entries, all definitions readable")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("draft", type=Path)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    return check(a.draft) if a.check else template(a.draft)


if __name__ == "__main__":
    sys.exit(main())
