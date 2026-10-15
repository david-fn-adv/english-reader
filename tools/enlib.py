"""Shared helpers for the English reader tools.

Kept deliberately small: paths, JSON I/O, the spaCy loader, ARPAbet -> IPA,
the effective known set, and draft tokenization (text -> blocks of tokens).
coverage.py / gloss.py (Phase 3) build on these; nothing here writes files.
"""
from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

# Windows consoles default to cp1252; the tools print Vietnamese and ✓/✗
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KNOWN = ROOT / "known"
NEWS = ROOT / "news"


def load_json(path: Path | str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump_json(obj, path: Path | str, compact: bool = False) -> None:
    """Write JSON deterministically (same input -> same bytes)."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


@lru_cache(maxsize=1)
def nlp():
    import spacy

    return spacy.load("en_core_web_sm")


# ── ARPAbet -> IPA (General American) ────────────────────────────────────────
# Vowels carry a stress digit in cmudict: 0 none, 1 primary, 2 secondary.
VOWELS = {
    "AA": "ɑ", "AE": "æ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ",
    "EY": "eɪ", "IH": "ɪ", "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ",
    "UW": "u",
    # stress-dependent
    "AH": ("ʌ", "ə"), "ER": ("ɝ", "ɚ"),
}
CONSONANTS = {
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p",
    "R": "r", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}
# Legal English onsets (ARPAbet), used to place the stress mark at the start
# of the stressed syllable (maximal onset principle).
ONSETS = {
    (), ("B",), ("CH",), ("D",), ("DH",), ("F",), ("G",), ("HH",), ("JH",),
    ("K",), ("L",), ("M",), ("N",), ("P",), ("R",), ("S",), ("SH",), ("T",),
    ("TH",), ("V",), ("W",), ("Y",), ("Z",), ("ZH",),
    ("B", "L"), ("B", "R"), ("D", "R"), ("D", "W"), ("F", "L"), ("F", "R"),
    ("F", "Y"), ("G", "L"), ("G", "R"), ("G", "W"), ("HH", "Y"), ("K", "L"),
    ("K", "R"), ("K", "W"), ("K", "Y"), ("M", "Y"), ("P", "L"), ("P", "R"),
    ("P", "Y"), ("S", "K"), ("S", "L"), ("S", "M"), ("S", "N"), ("S", "P"),
    ("S", "T"), ("S", "W"), ("SH", "R"), ("T", "R"), ("T", "W"), ("TH", "R"),
    ("V", "Y"), ("B", "Y"),
    ("S", "K", "R"), ("S", "K", "W"), ("S", "K", "Y"), ("S", "P", "L"),
    ("S", "P", "R"), ("S", "T", "R"), ("S", "P", "Y"),
}


def arpabet_to_ipa(phones: list[str]) -> str:
    """['G','AE1','R','AH0','S','AH0','N'] -> 'ˈɡærəsən'.

    Stress marks are kept; a one-syllable word gets no mark.
    """
    base = [re.sub(r"\d", "", p) for p in phones]
    stress = [int(p[-1]) if p[-1].isdigit() else None for p in phones]
    vowel_idx = [i for i, s in enumerate(stress) if s is not None]
    marks: dict[int, str] = {}
    if len(vowel_idx) > 1:
        prev_v = -1
        for vi in vowel_idx:
            s = stress[vi]
            if s in (1, 2):
                # consonants between previous vowel and this one
                start = prev_v + 1
                cluster = base[start:vi]
                # longest legal onset at the end of the cluster
                k = len(cluster)
                while k > 0 and tuple(cluster[len(cluster) - k:]) not in ONSETS:
                    k -= 1
                if prev_v < 0:
                    k = len(cluster)  # word-initial: whole cluster is the onset
                marks[vi - k] = "ˈ" if s == 1 else "ˌ"
            prev_v = vi
    out = []
    for i, (b, s) in enumerate(zip(base, stress)):
        if i in marks:
            out.append(marks[i])
        if s is None:
            out.append(CONSONANTS[b])
        else:
            v = VOWELS[b]
            if isinstance(v, tuple):
                v = v[0] if s in (1, 2) else v[1]
            out.append(v)
    return "".join(out)


@lru_cache(maxsize=1)
def _cmu():
    import cmudict

    return cmudict.dict()


def ipa_for_word(word: str) -> str | None:
    prons = _cmu().get(word.lower())
    if not prons:
        return None
    return arpabet_to_ipa(prons[0])


def ipa_for(headword: str) -> tuple[str | None, list[str]]:
    """IPA for a word or a phrase (concatenated per word). Returns (ipa, missing)."""
    parts, missing = [], []
    for w in headword.split():
        ipa = ipa_for_word(w)
        if ipa is None:
            missing.append(w)
            parts.append("?")
        else:
            parts.append(ipa)
    return (None if missing else " ".join(parts)), missing


# ── Known set ────────────────────────────────────────────────────────────────
def effective_known(known: dict) -> set[str]:
    """known ∪ known_extra − unknown_in_known (spec §2.5)."""
    return (set(known.get("known", [])) | set(known.get("known_extra", []))) - set(
        known.get("unknown_in_known", [])
    )


def load_bands() -> dict[str, int]:
    return load_json(DATA / "bands.json")


def load_phrases() -> list[dict]:
    """Curated phrases. Each gets `seqs`: the listed lemma sequence plus the one
    spaCy produces for the headword itself (according to -> accord to), so the
    list can be written in plain dictionary form."""
    phrases = load_json(DATA / "phrases.json")["phrases"]
    heads = [p["head"] for p in phrases]
    for p, doc in zip(phrases, nlp().pipe(heads)):
        auto = [fix_lemma(t.lemma_.lower(), t.text) for t in doc]
        p["seqs"] = [p["lemmas"]] + ([auto] if auto != p["lemmas"] else [])
    return phrases


def load_loanwords() -> set[str]:
    return set(load_json(DATA / "loanwords.json")["words"])


def phrase_band(headword: str, bands: dict[str, int], stop: set[str]) -> int | None:
    """A phrase takes the band of its rarest content word."""
    content = [w for w in headword.split() if w not in stop] or headword.split()
    bs = [bands.get(w) for w in content]
    bs = [b for b in bs if b is not None]
    return max(bs) if bs else None


# spaCy lemmas that are wrong or unhelpful for a learner. Applied both when
# building bands and when tokenizing drafts, so the two always agree.
LEMMA_FIX = {
    "data": "data", "datum": "data", "media": "media", "medium": "medium",
    "news": "news", "politics": "politics", "physics": "physics",
    "economics": "economics", "species": "species", "series": "series",
    "clothes": "clothes", "glasses": "glasses",
    "headquarters": "headquarters", "us": "we", "people": "people",
    "better": "good", "best": "good", "worse": "bad", "worst": "bad",
}


def fix_lemma(lemma: str, surface: str) -> str:
    s = surface.lower()
    if s in LEMMA_FIX:
        return LEMMA_FIX[s]
    return LEMMA_FIX.get(lemma, lemma)


# ── Draft tokenization ──────────────────────────────────────────────────────
NUM_RE = re.compile(r"^[\d.,%$€£]+$|^\d")


def _is_lexical(tok) -> bool:
    """Words are tappable; punctuation, numbers and the possessive 's are not.
    Abbreviations like "U.S." and clitics like "n't" (lemma "not") are words."""
    if tok.tag_ == "POS":
        return False
    return any(c.isalpha() for c in tok.text)


def tokenize_text(text: str, phrases: list[dict], names, wordlist=None):
    """Tokenize one paragraph of draft text.

    Returns a list of sentences; each sentence is a list of token dicts with
    the schema fields w / l / k-candidate / ph / nsp. `k` is filled later by
    classify() because it needs the known set.

    A token is a name if it is part of a name listed in the draft — matched as
    a whole token sequence, so "for" in "Ross Dress for Less" is a name but
    every other "for" is not — or if spaCy tags it PROPN, it is capitalised,
    and its lowercase form is not an ordinary banded word (so "September" and
    "Northern" stay words, "Leger" is a name).
    """
    # dotted names from the draft ("e.l.f.") stay one token; otherwise spaCy
    # splits off the final "." and ends the sentence there
    from spacy.attrs import ORTH
    for n in names or ():
        for part in n.split():
            if "." in part.rstrip("."):
                nlp().tokenizer.add_special_case(part, [{ORTH: part}])
    doc = nlp()(text)
    # merge hyphenated compounds (well-known, year-over-year) into one token
    with doc.retokenize() as rt:
        i = 0
        while i < len(doc):
            j = i
            while j + 2 < len(doc) and doc[j + 1].text == "-" and not doc[j].whitespace_ \
                    and not doc[j + 1].whitespace_ and doc[j + 2].is_alpha and doc[j].is_alpha:
                j += 2
            if j > i:
                rt.merge(doc[i:j + 1])
                i = j + 1
            else:
                i += 1

    name_seqs = _name_sequences(names)
    sents = []
    for sent in doc.sents:
        toks = [t for t in sent]
        in_name = _mark_names([t.text for t in toks], name_seqs)
        out = []
        for idx, t in enumerate(toks):
            d = {"w": t.text}
            if not t.whitespace_ and t.i != sent.end - 1:
                d["nsp"] = 1
            if _is_lexical(t):
                if in_name[idx] or (t.pos_ == "PROPN" and t.text[0].isupper()
                                    and (wordlist is None or t.text.lower() not in wordlist)):
                    d["_name"] = True
                else:
                    d["l"] = (fix_lemma(t.lemma_.lower(), t.text) if "-" not in t.text
                              else t.text.lower())
                    d["_pos"] = t.pos_
                    d["_dep"] = t.dep_
                    d["_head"] = t.head.i - sent.start
            out.append(d)
        _tag_phrases(out, phrases)
        sents.append(out)
    return sents


def _name_sequences(names) -> list[list[str]]:
    """Token sequences of the draft's names, longest first ("dd's Discounts" ->
    ["dd", "'s", "Discounts"], tokenized exactly as the text will be)."""
    seqs = {tuple(t.text for t in nlp().tokenizer(n)) for n in names if n.strip()}
    return sorted((list(s) for s in seqs), key=len, reverse=True)


def _mark_names(words: list[str], seqs: list[list[str]]) -> list[bool]:
    marked = [False] * len(words)
    for seq in seqs:
        n = len(seq)
        for i in range(len(words) - n + 1):
            if words[i:i + n] == seq and not any(marked[i:i + n]):
                for k in range(i, i + n):
                    marked[k] = True
    return marked


def _tag_phrases(sent: list[dict], phrases: list[dict]) -> None:
    """Curated phrases (contiguous lemma sequences) + phrasal verbs via the prt dependency."""
    ph_id = 0
    lemmas = [t.get("l") for t in sent]
    # 1. curated multiword expressions, longest first
    for p in sorted(phrases, key=lambda p: -len(p["lemmas"])):
        for seq in p.get("seqs", [p["lemmas"]]):
            n = len(seq)
            i = 0
            while i + n <= len(sent):
                window = lemmas[i:i + n]
                if window == seq and all("ph" not in sent[i + k] for k in range(n)):
                    ph_id += 1
                    for k in range(n):
                        sent[i + k]["ph"] = ph_id
                        sent[i + k]["l"] = p["head"]
                        sent[i + k]["_parts"] = list(seq)
                    i += n
                else:
                    i += 1
    # 2. phrasal verbs: particle (dep=prt) attached to a verb, adjacent only
    for idx, t in enumerate(sent):
        if t.get("_dep") == "prt" and "ph" not in t and idx > 0:
            h = t.get("_head")
            if h is not None and h == idx - 1 and "ph" not in sent[h] and sent[h].get("l"):
                ph_id += 1
                parts = [sent[h]["l"], t["l"]]
                head = " ".join(parts)
                for k in (h, idx):
                    sent[k]["ph"] = ph_id
                    sent[k]["l"] = head
                    sent[k]["_parts"] = parts


def classify(sents, eff_known: set[str], bands: dict[str, int], frontier: int,
             loanwords: set[str], taught: set[str] = frozenset()):
    """Fill `k` on every token. Returns stats used by the coverage report.

    known  — lemma/phrase in effective known set (phrases: all content parts known
             counts as known, per spec "allowed when their parts are known")
    core   — lemma in the frontier band and not known
    recycled — a core word of an earlier article, used again (spec §4.3). Shown
             as core (still highlighted) but counted as familiar for coverage and
             not counted among the 8–12 new core words.
    name / plain
    offenders — lemmas above the frontier band, not known, not loanwords
    """
    stats = {"lexical": 0, "known": 0, "derived": 0, "core": {}, "offenders": {},
             "below_unknown": {}, "recycled": {}}
    for sent in sents:
        for t in sent:
            if t.pop("_name", False):
                t["k"] = "name"
                _strip(t)
                continue
            lem = t.get("l")
            if not lem:
                t["k"] = "plain"
                _strip(t)
                continue
            stats["lexical"] += 1
            if lem in eff_known or lem in loanwords:
                t["k"] = "known"
                stats["known"] += 1
            elif " " in lem and all(w in eff_known or w in loanwords
                                    for w in t.get("_parts", lem.split())):
                t["k"] = "known"
                stats["known"] += 1
            elif _derived_known(lem, t["w"].lower(), eff_known):
                t["k"] = "known"
                stats["derived"] += 1
            elif "-" in lem and all(_part_known(p, eff_known, loanwords)
                                    for p in lem.split("-") if p):
                # transparent compound of known words: brand-name, off-price
                t["k"] = "known"
                stats["derived"] += 1
            elif lem in taught:
                t["k"] = "core"
                stats["recycled"][lem] = stats["recycled"].get(lem, 0) + 1
            else:
                b = bands.get(lem)
                if " " in lem:
                    parts = t.get("_parts", lem.split())
                    b = max([bands.get(w, 99) for w in parts if w not in eff_known] or [0])
                elif "-" in lem:
                    parts = [p for p in lem.split("-") if p]
                    b = max([bands.get(w, 99) for w in parts
                             if not _part_known(w, eff_known, loanwords)] or [0])
                if b == frontier:
                    t["k"] = "core"
                    stats["core"][lem] = stats["core"].get(lem, 0) + 1
                elif b is not None and b < frontier:
                    # below frontier but marked unknown (unknown_in_known): treat as core
                    t["k"] = "core"
                    stats["core"][lem] = stats["core"].get(lem, 0) + 1
                    stats["below_unknown"][lem] = b
                else:
                    t["k"] = "core"
                    stats["offenders"][lem] = stats["offenders"].get(lem, 0) + 1
            _strip(t)
    return stats


def _part_known(w: str, eff: set[str], loanwords: set[str]) -> bool:
    return w in eff or w in loanwords or _derived_known(w, w, eff)


AFFIXES_SUFFIX = ("ly", "ness", "er", "ing")
AFFIXES_PREFIX = ("un", "re")


def _derived_known(lemma: str, surface: str, eff: set[str]) -> bool:
    """Effective coverage: known lemma + known affix (-ly, -ness, -er, -ing, un-, re-)."""
    for w in {lemma, surface}:
        for suf in AFFIXES_SUFFIX:
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                stem = w[: -len(suf)]
                cands = {stem, stem + "e"}
                if stem.endswith("i"):
                    cands.add(stem[:-1] + "y")
                if len(stem) > 3 and stem[-1] == stem[-2]:
                    cands.add(stem[:-1])
                if cands & eff:
                    return True
        for pre in AFFIXES_PREFIX:
            if w.startswith(pre) and w[len(pre):] in eff and len(w) - len(pre) >= 3:
                return True
    return False


def _strip(t: dict) -> None:
    for k in ("_pos", "_dep", "_head", "_name", "_parts"):
        t.pop(k, None)
