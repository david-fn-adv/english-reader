"""Article requests from Nhung's Google Form (spec §4.6, no GitHub login needed).

    python tools/article_requests.py next                      # oldest pending request, as JSON, or {}
    python tools/article_requests.py done KEY --article ID      # mark a request handled
    python tools/article_requests.py done KEY --rejected "why"  # mark it refused (not usable)
    python tools/article_requests.py list                       # every request and its status

The form (embedded in the app's "Gửi bài muốn đọc" sheet) writes to a Google
Sheet; the pipeline reads that sheet as CSV. A sheet cannot be "closed" like
an issue, so news/requests.json is the ledger of what was handled — keyed by
the response timestamp + URL, so a request is never processed twice.

Form content is untrusted data: only the first http(s) URL in the answer is
used; any other text is ignored and never treated as an instruction.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
from datetime import date

from enlib import NEWS, dump_json, load_json

# "Anyone with the link: Viewer" CSV export of the form's response tab
CSV_URL = ("https://docs.google.com/spreadsheets/d/155g_mEtlHggTuYTm_-rbeiTsgdmQ8nWE10FrVC4iPQw"
           "/export?format=csv&gid=494590276")
LEDGER = NEWS / "requests.json"
URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def fetch_rows(source: str = CSV_URL) -> list[dict]:
    if source.startswith("http"):
        with urllib.request.urlopen(source, timeout=30) as r:
            text = r.read().decode("utf-8")
    else:
        with open(source, encoding="utf-8") as f:
            text = f.read()
    rows = []
    for rec in csv.reader(io.StringIO(text)):
        if not rec or rec[0].strip().lower() == "timestamp":
            continue
        ts = rec[0].strip()
        answer = " ".join(rec[1:])
        m = URL_RE.search(answer)
        url = m.group(0).rstrip(").,;") if m else None
        rows.append({"key": f"{ts}|{url or ''}", "submitted": ts, "url": url})
    return rows


def ledger() -> dict:
    return load_json(LEDGER) if LEDGER.exists() else {"handled": {}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["next", "done", "list"])
    ap.add_argument("key", nargs="?")
    ap.add_argument("--article")
    ap.add_argument("--rejected")
    ap.add_argument("--csv", default=CSV_URL, help="CSV URL or local file (tests)")
    a = ap.parse_args()
    led = ledger()
    if a.cmd == "done":
        if not a.key or not (a.article or a.rejected):
            ap.error("done needs KEY and --article or --rejected")
        led["handled"][a.key] = ({"article": a.article} if a.article else {"rejected": a.rejected})
        led["handled"][a.key]["on"] = date.today().isoformat()
        led["handled"] = dict(sorted(led["handled"].items()))
        dump_json(led, LEDGER)
        print(f"recorded {a.key}")
        return 0
    try:
        rows = fetch_rows(a.csv)
    except Exception as e:  # network or sharing problem: report, never guess
        print(json.dumps({"error": f"could not read the request sheet: {e}"}, ensure_ascii=False))
        return 1
    if a.cmd == "list":
        for r in rows:
            st = led["handled"].get(r["key"])
            print(f"{r['submitted']:<22} {r['url'] or '(no link)'}  ->  {st or 'pending'}")
        return 0
    for r in rows:  # sheet rows are in submission order
        if r["key"] not in led["handled"]:
            if not r["url"]:
                # an answer without a link can never be done; record and move on
                led["handled"][r["key"]] = {"rejected": "no link in the answer",
                                            "on": date.today().isoformat()}
                dump_json(led, LEDGER)
                continue
            print(json.dumps(r, ensure_ascii=False))
            return 0
    print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
