"""Draft -> article file (news/<id>.json), with the coverage report.

    python tools/build_article.py news/drafts/2026-10-14.json [--strict]

Draft format (hand- or agent-written):
  { "id", "domain", "title",
    "source": { "url", "outlet", "author", "title", "date",
                "figures": [ {"id": "f1", "text": "6.8%", "quote": "verbatim snippet"} ] },
    "paragraphs": [ "plain text", ... ],
    "names":  { "Statistics Canada": {"vi": "..."} },      # multiword allowed
    "gloss":  { "lemma or phrase": {"en": "...", "vi": "...", "pos"?: "...", "ipa"?: "..."} },
    "questions"?: [...] }
Glosses may also live next to the draft in <draft>.gloss.tsv, one per line:
  lemma <TAB> pos <TAB> English definition (<= 15 words) <TAB> Vietnamese

What it does:
  tokenize (spaCy) -> phrases -> classify against known/known.json
  -> tag every number with its figure id (a number without a figure row is an error)
  -> dict entries for every lemma: ipa from cmudict, pos from spaCy, band from
     bands.json, en/vi from the draft's gloss
  -> coverage report + gate (the Phase 3 coverage.py gate, same thresholds)
Exit 1 if any gate fails or a gloss / figure is missing. --strict is the
default for the pipeline; without it the article is still written so the
reader can be previewed, but the exit code still reports failure.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from enlib import (KNOWN, NEWS, dump_json, effective_known, ipa_for, load_bands, load_json,
                   load_loanwords, load_phrases, phrase_band, tokenize_text, classify)

POS = {"NOUN": "n", "PROPN": "name", "VERB": "v", "AUX": "aux", "ADJ": "adj", "ADV": "adv",
       "ADP": "prep", "PRON": "pron", "DET": "det", "CCONJ": "conj", "SCONJ": "conj",
       "NUM": "num", "PART": "part", "INTJ": "intj"}
NUMBER = re.compile(r"\d")
NUM_IN = re.compile(r"\d+(?:[.,]\d+)*")

GATE = {"effective_min": 0.95, "core_min": 8, "core_max": 12, "core_reps": 2,
        "words_min": 350, "words_max": 500, "avg_sent_max": 18, "sent_max": 30}


def build(draft: dict):
    from spacy.lang.en.stop_words import STOP_WORDS

    known = load_json(KNOWN / "known.json")
    eff = effective_known(known)
    bands = load_bands()
    frontier = int(known["frontier_band"])
    loans = load_loanwords()
    phrases = load_phrases()
    name_words = set()
    for n in draft.get("names", {}):
        name_words.update(n.split())

    blocks, pos_of = [], {}
    texts = [("h", draft["title"])] + [("p", p) for p in draft["paragraphs"]]
    for typ, text in texts:
        sents = tokenize_text(text, phrases, name_words, bands)
        for s in sents:
            for t in s:
                if t.get("l") and t["l"] not in pos_of:
                    pos_of[t["l"]] = "phr" if " " in t["l"] else POS.get(t.get("_pos", ""), "")
        blocks.append({"type": typ, "sents": sents})

    # classify body and title together; title counts toward nothing in the gate
    stats = classify([s for b in blocks for s in b["sents"]], eff, bands, frontier, loans)
    body = [s for b in blocks if b["type"] == "p" for s in b["sents"]]
    body_stats = _body_stats(body)

    # figures
    errors = []
    figs = draft["source"].get("figures", [])
    for b in blocks:
        for s in b["sents"]:
            for t in s:
                if NUMBER.search(t["w"]):
                    # exact match against the numbers in each figure row ("6" ≠ "6.8%")
                    fid = next((f["id"] for f in figs
                                if t["w"] in NUM_IN.findall(f["text"])), None)
                    if fid:
                        t["fig"] = fid
                    else:
                        errors.append(f"number '{t['w']}' has no row in source.figures")

    # dict entries for every lemma in the article
    gloss = draft.get("gloss", {})
    dict_out, missing_gloss, flagged_ipa = {}, [], []
    lemmas = []
    for b in blocks:
        for s in b["sents"]:
            for t in s:
                if t.get("l") and t["l"] not in lemmas:
                    lemmas.append(t["l"])
    for l in lemmas:
        g = gloss.get(l, {})
        ipa, miss = ipa_for(l)
        if g.get("ipa"):
            ipa = g["ipa"]
        elif miss:
            flagged_ipa.append(l)
        band = phrase_band(l, bands, STOP_WORDS) if " " in l else bands.get(l)
        entry = {"ipa": ipa or "", "pos": g.get("pos") or pos_of.get(l, ""),
                 "en": g.get("en", ""), "vi": g.get("vi", "")}
        if band:
            entry["band"] = band
        if not entry["en"] or not entry["vi"]:
            missing_gloss.append(l)
        dict_out[l] = entry

    core = stats["core"]
    vocab = [l for l in lemmas if l in core] + [l for l in lemmas if " " in l and l not in core]
    lexical = stats["lexical"]
    coverage = {
        "strict": round(stats["known"] / lexical, 3) if lexical else 0,
        "effective": round((stats["known"] + stats["derived"]) / lexical, 3) if lexical else 0,
        "tokens": body_stats["words"],
        "new_core": len(core),
    }
    names_out = {}
    for full, entry in draft.get("names", {}).items():
        for w in full.split():
            names_out.setdefault(w, {**entry, **({"full": full} if " " in full else {})})

    article = {
        "id": draft["id"], "domain": draft["domain"], "title": draft["title"],
        "level": {"known_version": known.get("updated", ""), "frontier_band": frontier},
        "source": draft["source"], "coverage": coverage, "vocab": vocab, "blocks": blocks,
    }
    if draft.get("questions"):
        article["questions"] = draft["questions"]
    article["dict"] = dict_out
    article["names"] = names_out

    # gate
    g = GATE
    fails = list(errors)
    if coverage["effective"] < g["effective_min"]:
        fails.append(f"effective coverage {coverage['effective']:.3f} < {g['effective_min']}")
    if not g["core_min"] <= len(core) <= g["core_max"]:
        fails.append(f"distinct core words {len(core)} not in {g['core_min']}–{g['core_max']}")
    thin = [l for l, n in core.items() if n < g["core_reps"]]
    if thin:
        fails.append(f"core words used < {g['core_reps']}×: {', '.join(thin)}")
    if stats["offenders"]:
        fails.append("out-of-level: " + ", ".join(f"{l}({n})" for l, n in stats["offenders"].items()))
    if not g["words_min"] <= body_stats["words"] <= g["words_max"]:
        fails.append(f"length {body_stats['words']} words not in {g['words_min']}–{g['words_max']}")
    if body_stats["avg"] > g["avg_sent_max"]:
        fails.append(f"average sentence {body_stats['avg']:.1f} words > {g['avg_sent_max']}")
    if body_stats["max"] > g["sent_max"]:
        fails.append(f"longest sentence {body_stats['max']} words > {g['sent_max']}: "
                     f"“{body_stats['max_text'][:80]}…”")
    if missing_gloss:
        fails.append(f"{len(missing_gloss)} lemmas without en/vi gloss")
    # spaCy does not end a sentence after "U.S." — "a visit to the U.S. September was"
    # becomes one sentence, which breaks TTS highlighting and example sentences
    for s_ in body:
        for i in range(len(s_) - 1):
            w, nxt = s_[i]["w"], s_[i + 1]["w"]
            if len(w) > 2 and w.endswith(".") and "." in w[:-1] and nxt[:1].isupper():
                fails.append(f"possible missed sentence break after '{w}' before '{nxt}' — "
                             f"rephrase so the abbreviation does not end a sentence")
    report = {"stats": stats, "body": body_stats, "coverage": coverage, "fails": fails,
              "missing_gloss": missing_gloss, "flagged_ipa": flagged_ipa}
    return article, report


def _body_stats(sents):
    lens = []
    for s in sents:
        n = sum(1 for t in s if any(c.isalnum() for c in t["w"]))
        lens.append((n, " ".join(t["w"] for t in s)))
    words = sum(n for n, _ in lens)
    mx = max(lens) if lens else (0, "")
    return {"words": words, "sentences": len(lens),
            "avg": words / len(lens) if lens else 0, "max": mx[0], "max_text": mx[1]}


def load_tsv_gloss(path: Path) -> dict:
    out = {}
    if path.exists():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split("	")
            if len(parts) != 4:
                sys.exit(f"{path}:{n}: expected 4 tab-separated fields")
            lemma, pos, en, vi = (x.strip() for x in parts)
            if len(en.split()) > 15:
                sys.exit(f"{path}:{n}: English definition longer than 15 words")
            out[lemma] = {"pos": pos, "en": en, "vi": vi}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("draft", type=Path)
    ap.add_argument("--strict", action="store_true", help="do not write the article on failure")
    a = ap.parse_args()
    draft = load_json(a.draft)
    tsv = load_tsv_gloss(a.draft.with_suffix(".gloss.tsv"))
    draft["gloss"] = {**tsv, **draft.get("gloss", {})}
    article, rep = build(draft)
    s, b, c = rep["stats"], rep["body"], rep["coverage"]
    print(f"words {b['words']}  sentences {b['sentences']}  avg {b['avg']:.1f}  max {b['max']}")
    print(f"coverage strict {c['strict']:.3f}  effective {c['effective']:.3f}  "
          f"lexical tokens {s['lexical']}")
    print("core words:")
    for l, n in sorted(s["core"].items(), key=lambda x: -x[1]):
        flag = "  (below frontier, marked unknown)" if l in s["below_unknown"] else ""
        print(f"  {n:>2}×  {l}{flag}")
    if s["offenders"]:
        print("OUT-OF-LEVEL:", ", ".join(f"{l}({n})" for l, n in s["offenders"].items()))
    if rep["missing_gloss"]:
        print("missing gloss:", ", ".join(rep["missing_gloss"]))
    if rep["flagged_ipa"]:
        print("IPA not in cmudict (supply in gloss, review in PR):", ", ".join(rep["flagged_ipa"]))
    if rep["fails"]:
        print("\nGATE: FAIL")
        for f in rep["fails"]:
            print("  ✗", f)
    else:
        print("\nGATE: PASS")
    if not (rep["fails"] and a.strict):
        out = NEWS / f"{article['id']}.json"
        dump_json(article, out)
        print(f"wrote {out}")
    return 1 if rep["fails"] else 0


if __name__ == "__main__":
    sys.exit(main())
