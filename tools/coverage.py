"""Phase 3 — the coverage gate (spec §4.4). Exit 0 pass, 1 fail.

    python tools/coverage.py news/drafts/2026-10-16.json
    python tools/coverage.py draft.txt --names names.json        # plain text + names

Input: a draft (see build_article.py for the format) or plain text where
paragraphs are separated by blank lines and the first line is the title.

Steps
  1. spaCy tokenize + lemmatize; phrases from data/phrases.json and phrasal
     verbs via the `prt` dependency
  2. classify every lexical token: known / core / name / plain, plus
       recycled  — a core word of an earlier article (news/*.json), used again;
                   highlighted like core, counted as familiar for coverage
       out-of-level — above the frontier band, not known, not a loanword
  3. strict = known / lexical;  effective = (known + derived + recycled) / lexical
     derived = known lemma + known affix (-ly -ness -er -ing un- re-)
  4. gate: effective >= 0.95; 8 <= new core <= 12; each new core >= 2x;
     0 out-of-level; 350–500 words; average sentence <= 18, none > 30;
     every number has a source.figures row; 3–5 core words recycled from the
     previous three articles (when they exist); no missed sentence break
  5. prints the core table and the offenders
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from enlib import (KNOWN, NEWS, classify, effective_known, load_bands, load_json,
                   load_loanwords, load_phrases, tokenize_text)

POS = {"NOUN": "n", "PROPN": "name", "VERB": "v", "AUX": "aux", "ADJ": "adj", "ADV": "adv",
       "ADP": "prep", "PRON": "pron", "DET": "det", "CCONJ": "conj", "SCONJ": "conj",
       "NUM": "num", "PART": "part", "INTJ": "intj"}
NUMBER = re.compile(r"\d")
NUM_IN = re.compile(r"\d+(?:[.,]\d+)*")

GATE = {"effective_min": 0.95, "core_min": 8, "core_max": 12, "core_reps": 2,
        "words_min": 350, "words_max": 500, "avg_sent_max": 18, "sent_max": 30,
        "recycle_min": 3, "recycle_max": 5}


def previous_articles(before_id: str) -> list[dict]:
    """Published articles older than `before_id`, newest first."""
    arts = []
    for p in sorted(NEWS.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json")):
        if p.stem < before_id:
            arts.append(load_json(p))
    return sorted(arts, key=lambda a: a["id"], reverse=True)


def core_of(article: dict) -> set[str]:
    return {t["l"] for b in article["blocks"] for s in b["sents"] for t in s
            if t.get("k") == "core" and t.get("l")}


def analyze(draft: dict) -> tuple[list, dict]:
    """Tokenize + classify + figures + gate. Returns (blocks, report)."""
    known = load_json(KNOWN / "known.json")
    eff = effective_known(known)
    bands = load_bands()
    frontier = int(known["frontier_band"])
    loans = load_loanwords()
    phrases = load_phrases()
    name_words = set()
    for n in draft.get("names", {}):
        name_words.update(n.split())

    prev = previous_articles(draft["id"])
    taught = set().union(*(core_of(a) for a in prev)) - eff if prev else set()
    recent = set().union(*(core_of(a) for a in prev[:3])) - eff if prev else set()

    blocks, pos_of = [], {}
    texts = [("h", draft["title"])] + [("p", p) for p in draft["paragraphs"]]
    for typ, text in texts:
        sents = tokenize_text(text, phrases, name_words, bands)
        for s in sents:
            for t in s:
                if t.get("l") and t["l"] not in pos_of:
                    pos_of[t["l"]] = "phr" if " " in t["l"] else POS.get(t.get("_pos", ""), "")
        blocks.append({"type": typ, "sents": sents})

    stats = classify([s for b in blocks for s in b["sents"]], eff, bands, frontier, loans, taught)
    body = [s for b in blocks if b["type"] == "p" for s in b["sents"]]
    body_stats = _body_stats(body)

    fails = []
    figs = draft.get("source", {}).get("figures", [])
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
                        fails.append(f"number '{t['w']}' has no row in source.figures")

    core = stats["core"]
    lexical = stats["lexical"]
    familiar = stats["known"] + stats["derived"] + sum(stats["recycled"].values())
    coverage = {
        "strict": round(stats["known"] / lexical, 3) if lexical else 0,
        "effective": round(familiar / lexical, 3) if lexical else 0,
        "tokens": body_stats["words"],
        "new_core": len(core),
    }
    recycled_recent = sorted(l for l in stats["recycled"] if l in recent)

    g = GATE
    if coverage["effective"] < g["effective_min"]:
        fails.append(f"effective coverage {coverage['effective']:.3f} < {g['effective_min']}")
    if not g["core_min"] <= len(core) <= g["core_max"]:
        fails.append(f"distinct new core words {len(core)} not in {g['core_min']}–{g['core_max']}")
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
    need = min(g["recycle_min"], len(recent))
    if recent and not need <= len(recycled_recent) <= g["recycle_max"]:
        fails.append(f"recycled core words from the previous three articles: "
                     f"{len(recycled_recent)} (need {need}–{g['recycle_max']}); "
                     f"candidates: {', '.join(sorted(recent))}")
    # spaCy does not end a sentence after "U.S." — "a visit to the U.S. September was"
    # becomes one sentence, which breaks TTS highlighting and example sentences
    for s_ in body:
        for i in range(len(s_) - 1):
            w, nxt = s_[i]["w"], s_[i + 1]["w"]
            if len(w) > 2 and w.endswith(".") and "." in w[:-1] and nxt[:1].isupper():
                fails.append(f"possible missed sentence break after '{w}' before '{nxt}' — "
                             f"rephrase so the abbreviation does not end a sentence")

    report = {"stats": stats, "body": body_stats, "coverage": coverage, "fails": fails,
              "pos_of": pos_of, "recycled_recent": recycled_recent, "recent": sorted(recent),
              "known": known, "bands": bands, "eff": eff, "loans": loans, "frontier": frontier}
    return blocks, report


def _body_stats(sents):
    lens = []
    for s in sents:
        n = sum(1 for t in s if any(c.isalnum() for c in t["w"]))
        lens.append((n, " ".join(t["w"] for t in s)))
    words = sum(n for n, _ in lens)
    mx = max(lens) if lens else (0, "")
    return {"words": words, "sentences": len(lens),
            "avg": words / len(lens) if lens else 0, "max": mx[0], "max_text": mx[1]}


def print_report(rep: dict) -> None:
    s, b, c = rep["stats"], rep["body"], rep["coverage"]
    print(f"words {b['words']}  sentences {b['sentences']}  avg {b['avg']:.1f}  max {b['max']}")
    print(f"coverage strict {c['strict']:.3f}  effective {c['effective']:.3f}  "
          f"lexical tokens {s['lexical']}")
    print(f"new core words ({len(s['core'])}):")
    for l, n in sorted(s["core"].items(), key=lambda x: -x[1]):
        flag = "  (below frontier, marked unknown)" if l in s["below_unknown"] else ""
        print(f"  {n:>2}×  {l}{flag}")
    if s["recycled"]:
        print("recycled: " + ", ".join(f"{l}({n})" for l, n in s["recycled"].items()))
    if s["offenders"]:
        print("OUT-OF-LEVEL: " + ", ".join(f"{l}({n})" for l, n in s["offenders"].items()))


def load_draft(path: Path, names: Path | None) -> dict:
    if path.suffix == ".json":
        return load_json(path)
    paras = [p.strip() for p in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")) if p.strip()]
    title, *body = paras
    return {"id": "9999-99-99", "title": title, "paragraphs": body,
            "names": load_json(names) if names else {}, "source": {"figures": []}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("draft", type=Path)
    ap.add_argument("--names", type=Path, help="names JSON for a plain-text draft")
    a = ap.parse_args()
    _, rep = analyze(load_draft(a.draft, a.names))
    print_report(rep)
    if rep["fails"]:
        print("\nCOVERAGE GATE: FAIL")
        for f in rep["fails"]:
            print("  ✗", f)
        return 1
    print("\nCOVERAGE GATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
