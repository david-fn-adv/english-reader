"""Phase 1 — build test/items.v1.json and bake it into test/index.html.

    python tools/make_test_items.py

- bands 1–8, 16 real words per band, 4 from each quarter of the band
- excluded: function words outside band 1, loanwords / Vietnamese cognates
  (data/loanwords.json), offensive words, slang, words shorter than 3 letters
  (4 letters from band 3 up — short rare forms are mostly abbreviations), and
  anything with even a weak proper-noun signal (spaCy PROPN in >= 2 of 5
  carriers, or NER hit on the Title-case form). The bands keep borderline
  names to protect coverage; the test cannot afford them, because "jeremy"
  or "lisbon" measures nothing. Rejected draws are replaced from the same
  quarter, so the stratification holds.
- also excluded: transparent derivations of a banded word with the affixes
  the coverage gate already treats as known (-ly, -ness, -er, -ing, un-, re-):
  "instantly" measures nothing that "instant" does not.
- 32 pseudowords from data/pseudowords.json, each verified absent from
  wordfreq top 50k and from cmudict
- fixed seed; shuffled order is baked in, so every retake sees the same list

The test page must work offline from file://, so the item list is also
embedded in test/index.html between the ITEMS markers (idempotent replace).
Bump VERSION if the list ever changes.
"""
from __future__ import annotations

import json
import random
import re
import sys

from build_bands import name_signals
from enlib import DATA, ROOT, _derived_known, dump_json, load_json

VERSION = "v1"
SEED = 20261014
BANDS = range(1, 9)
PER_BAND = 16
N_PSEUDO = 32

# keep the test free of slurs/profanity and of words that are awkward to show
BLOCK = {
    "fuck", "fucking", "shit", "bitch", "damn", "dick", "cock", "pussy", "ass", "porn",
    "sex", "sexy", "nigger", "nigga", "fag", "faggot", "slut", "whore", "cunt", "bastard",
    "rape", "penis", "vagina", "boob", "tit", "horny", "nude", "naked", "cum", "piss",
    "crap", "hell", "suck", "dildo", "anal", "orgasm", "erotic", "jerk", "retard",
    "homosexual", "gay", "lesbian", "poop", "drug", "pornography", "prostitute", "abortion",
    "intimacy", "stimulation",
}
SLANG = {
    "gonna", "wanna", "gotta", "kinda", "sorta", "yeah", "yep", "nope", "buddy", "gee",
    "dude", "guy", "uh", "um", "hey", "lol", "omg", "ya", "yo", "bro", "cool", "awesome",
    "gal", "pal", "doo", "heh", "ohh", "yay", "nah", "huh", "wow", "dang", "mate",
}
# hand review of the drawn list (brands, abbreviations, archaic/childish forms)
MANUAL = {"playstation", "comp", "writ", "daddy", "barack", "salvador", "funk", "woody", "santo", "torres",
          "dying", "fourteen", "seventy", "thirteen", "fifteen", "sixty", "eighty", "ninety"}


def main() -> int:
    from spacy.lang.en.stop_words import STOP_WORDS
    from wordfreq import top_n_list, zipf_frequency
    import cmudict

    bands = load_json(DATA / "bands.json")
    loans = set(load_json(DATA / "loanwords.json")["words"])
    rnd = random.Random(SEED)
    lemma_set = set(bands)

    items = []
    for b in BANDS:
        # band members by frequency (bands.json is alphabetical); quarters of
        # the band are then quarters of this frequency-ordered list
        members = sorted((w for w, bb in bands.items() if bb == b),
                         key=lambda w: (-zipf_frequency(w, "en"), w))
        pool = [w for w in members
                if len(w) >= (3 if b <= 2 else 4) and w not in loans and w not in BLOCK
                and w not in SLANG and w not in MANUAL and not (b > 1 and w in STOP_WORDS)
                and not _derived_known(w, w, lemma_set - {w})]
        q = len(pool) // 4
        for k in range(4):
            quarter = pool[k * q:(k + 1) * q] if k < 3 else pool[3 * q:]
            order = rnd.sample(quarter, len(quarter))
            got = 0
            for w in order:
                a, nb, _ = name_signals([w])[w]
                if a >= 2 or nb >= 1:
                    continue
                items.append({"w": w, "band": b, "real": True})
                got += 1
                if got == PER_BAND // 4:
                    break

    top50k = set(top_n_list("en", 50000))
    cmu = cmudict.dict()
    pseudo = load_json(DATA / "pseudowords.json")["words"]
    bad = [w for w in pseudo if w in top50k or w in cmu or w in bands]
    clean = [w for w in pseudo if w not in bad]
    if bad:
        print("pseudowords rejected (real words):", " ".join(bad))
    if len(clean) < N_PSEUDO:
        print(f"ERROR: only {len(clean)} clean pseudowords, need {N_PSEUDO}", file=sys.stderr)
        return 1
    for w in rnd.sample(clean, N_PSEUDO):
        items.append({"w": w, "band": 0, "real": False})

    rnd.shuffle(items)
    items = [{"id": i, **it} for i, it in enumerate(items, 1)]
    out = {"version": VERSION, "items": items}
    dump_json(out, ROOT / "test" / f"items.{VERSION}.json")

    page = ROOT / "test" / "index.html"
    html = page.read_text(encoding="utf-8")
    blob = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    new, n = re.subn(
        r'(<script id="items" type="application/json">).*?(</script>)',
        lambda m: m.group(1) + blob + m.group(2), html, flags=re.S)
    if n != 1:
        print("ERROR: items <script> block not found in test/index.html", file=sys.stderr)
        return 1
    page.write_text(new, encoding="utf-8", newline="\n")

    for b in BANDS:
        print(f"band {b}: " + " ".join(i["w"] for i in items if i["band"] == b))
    print("pseudo: " + " ".join(i["w"] for i in items if not i["real"]))
    print(f"{len(items)} items -> test/items.{VERSION}.json + test/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
