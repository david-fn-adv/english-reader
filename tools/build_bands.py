"""Phase 1 — build data/bands.json: lemma -> frequency band (1..10).

Run once:  python tools/build_bands.py      (~6 min, spaCy tags every word)

Source: wordfreq top_n_list('en', 30000), walked in rank order until 10,000
lemmas are collected (the spec's 20,000 is not enough once inflections are
collapsed and names removed).

Filtering rules
  1. alphabetic, lowercase, length >= 2 — plus "a" and "i", which are words.
     Two-letter forms survive only if they are spaCy stop words or in TWO_OK
     (drops "ev", "uv", "th", "nd"...).
  2. must contain a vowel letter and be in cmudict (drops web junk; every
     banded lemma is guaranteed an IPA).
  3. lemmatize: spaCy's rule lemmatizer is run with the POS forced to VERB,
     then NOUN, then ADJ; the first lemma that differs from the word and is
     itself a cmudict word wins (wore -> wear, children -> child,
     warmer -> warm). LEMMA_FIX (in enlib) overrides a few bad lemmas
     (data -> datum). Inflections collapse onto the lemma, keeping its best rank.
  4. proper nouns. wordfreq has no case information, so "Paris" vs "paris"
     counts cannot be compared. Three signals instead, computed on the word
     when it is its own lemma:
       A = in how many of 5 lowercase carrier sentences spaCy tags it PROPN
       B = in how many of 2 Title-case carrier sentences NER marks it as
           PERSON/GPE/LOC/NORP/ORG/FAC
       X = in how many of 9 other languages (fr es it pt pl tr id nl de) its
           wordfreq Zipf is within 1.5 of the English one — names are spelled
           the same everywhere and are about as frequent everywhere
     drop if (A >= 4 and B >= 1 and X >= 5) or (A == 3 and B == 2 and X >= 8),
     unless in KEEP (months, days, nationalities, a few false hits).
     Tuned on hand-labelled samples: precision over recall, because a name
     left in a band costs one slot while a real word dropped from the bands
     later reads as "out of level" to the coverage gate.
Then re-rank lemmas, band = ceil(rank / 1000), keep the first 10,000.
"""
from __future__ import annotations

import math
import random
import re
import sys
from collections import Counter

from enlib import DATA, LEMMA_FIX, dump_json, nlp

SOURCE_N = 30000
SCAN_N = 24000          # words to tag; enough to reach 10k lemmas
N_LEMMAS = 10000
VOWEL = re.compile(r"[aeiouy]")
TWO_OK = {"ok", "oh", "hi", "ox", "ax", "ad", "ah", "uh", "pi"}
LANGS = ("fr", "es", "it", "pt", "pl", "tr", "id", "nl", "de")
CARRIER_LO = ("i think {w} is here .", "we talked about {w} today .",
              "the {w} was there .", "there are many {w} .", "it is very {w} .")
CARRIER_TI = ("Yesterday I read about {W} in the paper .", "{W} said it was fine .")
ENT = {"PERSON", "GPE", "LOC", "NORP", "ORG", "FAC"}

KEEP = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "american", "british", "english", "french", "german", "spanish", "italian",
    "chinese", "japanese", "korean", "indian", "european", "african", "asian",
    "russian", "canadian", "australian", "mexican", "vietnamese", "thai",
    "christian", "christmas", "muslim", "jewish", "catholic", "islamic",
    "god", "lord", "united", "congress", "senate", "parliament", "republican",
    "democrat", "democratic", "federal", "national", "western", "eastern",
    "northern", "southern", "pacific", "atlantic", "arctic", "mediterranean",
    "noun", "mosquito", "glacier", "denim", "cucumber", "mango", "taco",
    "graffiti", "tram", "lotus", "venus", "jupiter", "iris", "marsh",
}


# Function words are never run through the forced-POS lemmatizer (it turns
# "his" into "hi", "this" into "thi", "less" into "little"). They keep
# themselves, except these inflections, which spaCy also collapses in context.
STOP_LEMMA = {
    **{w: "be" for w in ("am", "is", "are", "was", "were", "been", "being")},
    **{w: "do" for w in ("does", "did", "doing", "done")},
    **{w: "have" for w in ("has", "had", "having")},
    **{w: "become" for w in ("becomes", "became", "becoming")},
    **{w: "seem" for w in ("seems", "seemed", "seeming")},
    "made": "make", "used": "use", "him": "he", "me": "i", "us": "we", "them": "they",
}


def lemma_candidates(words: list[str], cmu) -> dict[str, str]:
    """Context-free lemma for each word.

    A verb base form is its own lemma, and so is an -ing word that spaCy's
    index lists as a noun (evening, morning, building — not running).
    Otherwise, for POS in VERB, NOUN, ADJ, the first rule
    lemma that is itself one of the candidate words (a real, frequent word)
    wins. The second condition rejects rule artefacts like need -> "nee",
    glasses -> "glas", industries -> "industrie".
    """
    from spacy.lang.en.stop_words import STOP_WORDS
    from spacy.tokens import Doc

    lemmatizer = nlp().get_pipe("lemmatizer")
    index = lemmatizer.lookups.get_table("lemma_index")
    pool = set(words)
    out = {}
    for w in words:
        if w in LEMMA_FIX:
            out[w] = LEMMA_FIX[w]
            continue
        if w in STOP_WORDS:
            out[w] = STOP_LEMMA.get(w, w)
            continue
        lem = w
        if w in index.get("verb", ()) or (w.endswith("ing") and w in index.get("noun", ())):
            out[w] = w
            continue
        for pos in ("VERB", "NOUN", "ADJ"):
            doc = Doc(nlp().vocab, words=[w])
            doc[0].pos_ = pos
            cands = [c.lower() for c in lemmatizer.rule_lemmatize(doc[0])]
            c = next((c for c in cands if c != w and c in pool), None)
            if c:
                lem = LEMMA_FIX.get(c, c)
                break
        out[w] = lem
    return out


def name_signals(words: list[str]) -> dict[str, tuple[int, int, int]]:
    from wordfreq import zipf_frequency

    n = nlp()
    lo = list(n.pipe((c.format(w=w) for w in words for c in CARRIER_LO), batch_size=512))
    ti = list(n.pipe((c.format(W=w.capitalize()) for w in words for c in CARRIER_TI),
                     batch_size=512))
    k1, k2 = len(CARRIER_LO), len(CARRIER_TI)
    sig = {}
    for i, w in enumerate(words):
        a = sum(any(t.text == w and t.pos_ == "PROPN" for t in lo[i * k1 + k]) for k in range(k1))
        b = sum(any(e.text.lower() == w and e.label_ in ENT for e in ti[i * k2 + k].ents)
                for k in range(k2))
        ez = zipf_frequency(w, "en")
        x = sum(zipf_frequency(w, l) >= ez - 1.5 for l in LANGS)
        sig[w] = (a, b, x)
    return sig


def is_name(sig) -> bool:
    a, b, x = sig
    return (a >= 4 and b >= 1 and x >= 5) or (a == 3 and b == 2 and x >= 8)


def main() -> int:
    from spacy.lang.en.stop_words import STOP_WORDS
    from wordfreq import top_n_list
    import cmudict

    cmu = cmudict.dict()
    dropped = Counter()
    cand = []
    for w in top_n_list("en", SOURCE_N)[:SCAN_N]:
        if not w.isalpha() or w != w.lower():
            dropped["non-alpha"] += 1
        elif len(w) == 1 and w not in ("a", "i"):
            dropped["short"] += 1
        elif len(w) == 2 and w not in STOP_WORDS and w not in TWO_OK:
            dropped["short"] += 1
        elif not VOWEL.search(w):
            dropped["no vowel"] += 1
        elif w not in cmu:
            dropped["not in cmudict"] += 1
        else:
            cand.append(w)

    lemma = lemma_candidates(cand, cmu)
    roots = [w for w in cand if lemma[w] == w and w not in KEEP]
    sig = name_signals(roots)
    names = [w for w in roots if is_name(sig[w])]
    name_set = set(names)
    dropped["proper noun"] = len(names)

    best: dict[str, int] = {}
    for rank, w in enumerate(cand, 1):
        lem = lemma[w]
        if lem in name_set or w in name_set:
            continue
        if lem not in best or rank < best[lem]:
            best[lem] = rank

    ordered = sorted(best, key=lambda l: (best[l], l))[:N_LEMMAS]
    if len(ordered) < N_LEMMAS:
        print(f"ERROR: only {len(ordered)} lemmas; raise SCAN_N", file=sys.stderr)
        return 1
    bands = {lem: math.ceil(i / 1000) for i, lem in enumerate(ordered, 1)}
    dump_json(dict(sorted(bands.items())), DATA / "bands.json", compact=True)

    print("dropped:", dict(dropped))
    print("proper-noun drops (first 80):", " ".join(names[:80]))
    counts = Counter(bands.values())
    rnd = random.Random(1)
    for b in range(1, 11):
        words = [l for l in ordered if bands[l] == b]
        print(f"band {b:>2}  n={counts[b]:>4}  {' '.join(rnd.sample(words, 20))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
