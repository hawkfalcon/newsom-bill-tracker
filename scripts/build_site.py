#!/usr/bin/env python3
"""
Build the static site: inject data/bills.json into site/template.html and
write index.html. The result is a single self-contained HTML file that works
on GitHub Pages (and anywhere else) with no server-side code.

Usage:
    python scripts/build_site.py --data data/bills.json \
        --template site/template.html --out index.html
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/bills.json")
    ap.add_argument("--gov", default="data/gov_actions.json")
    ap.add_argument("--template", default="site/template.html")
    ap.add_argument("--out", default="index.html")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    with open(args.template, encoding="utf-8") as f:
        tpl = f.read()

    # Merge the Governor's official announcements (gov.ca.gov) into each bill
    # as the "first to know" link. Kept independent from the LegInfo fetcher so
    # either source can refresh on its own.
    def norm(m):
        return re.sub(r"[^a-z0-9]", "", m.lower())

    gov = {}
    if os.path.exists(args.gov):
        with open(args.gov, encoding="utf-8") as f:
            gov = json.load(f).get("actions", {})

    for b in data.get("bills", []):
        k = norm(b.get("measure", ""))
        if k in gov and gov[k]["action"] == b.get("status"):
            b["gov_url"] = gov[k]["url"]
            b["gov_date"] = gov[k]["date"]
        else:
            b["gov_url"] = None
            b["gov_date"] = None

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Escape "<" so no "</script>" sequence can appear inside the inline JSON.
    payload = payload.replace("<", "\\u003c")
    # Inject the JSON object literal in place of the placeholder.
    html = tpl.replace("__DATA_JSON__", payload)
    html = html.replace("__BUILD_TIME__",
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)

    counts = data.get("counts", {})
    print(f"Built {args.out} — signed={counts.get('signed', 0)} "
          f"vetoed={counts.get('vetoed', 0)} pending={counts.get('pending', 0)} "
          f"({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
