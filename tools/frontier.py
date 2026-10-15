"""Word lists for drafting (helper; changes nothing).

    python tools/frontier.py                 # frontier-band words she does not know yet
    python tools/frontier.py --grep travel   # ... filtered by substring
    python tools/frontier.py --recycle       # core words of the last three articles
    python tools/frontier.py --check WORD …  # band and status of words you plan to use

Use it while drafting: pick 8–12 target words from the frontier list that fit
the story, 3–5 words from --recycle, and --check any word you are unsure of
(status "out-of-level" means coverage.py will fail the draft).
"""
from __future__ import annotations

import argparse
import sys

from coverage import core_of, previous_articles
from enlib import KNOWN, _derived_known, effective_known, load_bands, load_json, load_loanwords


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grep")
    ap.add_argument("--recycle", action="store_true")
    ap.add_argument("--check", nargs="+")
    a = ap.parse_args()
    known = load_json(KNOWN / "known.json")
    eff = effective_known(known)
    bands = load_bands()
    fr = int(known["frontier_band"])
    if a.recycle:
        for art in previous_articles("9999")[:3]:
            words = sorted(core_of(art) - eff)
            print(f"{art['id']} ({art['domain']}): {', '.join(words)}")
        return 0
    if a.check:
        loans = load_loanwords()
        taught = set().union(*(core_of(x) for x in previous_articles("9999"))) if \
            previous_articles("9999") else set()
        from enlib import fix_lemma, nlp
        for raw in a.check:
            t = nlp()(raw.lower())[0]
            w = raw.lower() if raw.lower() in bands else fix_lemma(t.lemma_.lower(), raw)
            b = bands.get(w)
            if w in eff or w in loans or _derived_known(w, w, eff):
                st = "known"
            elif w in taught:
                st = "recycled (taught earlier)"
            elif b == fr or (b is not None and b < fr):
                st = "core (new word)"
            else:
                st = "OUT-OF-LEVEL — replace it"
            shown = raw if w == raw.lower() else f"{raw} ({w})"
            print(f"{shown:<24} band {b if b else '—':<3} {st}")
        return 0
    words = sorted(l for l, b in bands.items() if b == fr and l not in eff)
    if a.grep:
        words = [w for w in words if a.grep.lower() in w]
    print(f"frontier band {fr}: {len(words)} words not yet known")
    print(", ".join(words))
    return 0


if __name__ == "__main__":
    sys.exit(main())
