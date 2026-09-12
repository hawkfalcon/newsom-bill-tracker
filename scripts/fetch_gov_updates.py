#!/usr/bin/env python3
"""
Fetch Gov. Gavin Newsom's official "legislative update" announcements from
gov.ca.gov (WordPress REST API). These are the Governor's own office's
same-day announcements of which bills he signed and vetoed — the first public
source of the action — and each includes a link to the official signing or
veto message.

Output: data/gov_actions.json  ->  { "bill_id_normalized": {action, date, url} }

Usage:
    python scripts/fetch_gov_updates.py [--after 2024-12-01] [--out data/gov_actions.json]
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone

import requests

API = "https://www.gov.ca.gov/wp-json/wp/v2/posts"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "application/json"}

SIGNED_MARKER = re.compile(
    r"announced that he (?:has )?signed the following bills|signed the following bills",
    re.I,
)
VETOED_MARKER = re.compile(
    r"vetoed the following bills|has vetoed the following", re.I
)
# "AB 70 by Assemblymember ..." / "SBX1 2 by ..." — captures bill + optional
# split across line breaks, and stops at the author's name.
BILL_RE = re.compile(
    r"\b(AB|SB|ACA|SCA|AJR|SJR|ACR|SCR|HR|SR|ABX\d|SBX\d)[-\s]?(\d+)\s+by\b",
    re.I,
)


def norm(measure):
    """'AB 70' / 'AB-70' / 'ABX1 2' -> 'ab70' / 'abx12' (alphanumeric only)."""
    return re.sub(r"[^a-z0-9]", "", measure.lower())


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s)
    import html as h
    s = h.unescape(s)
    return re.sub(r"\s+", " ", s)


def get_json(url, params, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=45)
            if r.status_code == 200:
                return r.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def fetch_posts(after_iso):
    """Return all 'legislative update' posts since `after_iso`."""
    posts = []
    page = 1
    while True:
        data = get_json(API, {
            "search": "legislative update",
            "after": after_iso,
            "per_page": 100,
            "page": page,
            "orderby": "date",
            "order": "desc",
        })
        if not data:
            break
        posts.extend(data)
        if len(data) < 100:
            break
        page += 1
        time.sleep(0.3)
    return posts


def parse_post(post):
    """Return {norm_bill_id: {'action': 'signed'|'vetoed', 'date': date, 'url': url}}"""
    title = post.get("title", {}).get("rendered", "")
    if "legislative update" not in title.lower():
        return {}
    date = post.get("date", "")[:10]
    url = post.get("link", "")
    text = strip_html(post.get("content", {}).get("rendered", ""))

    # Split into signed / vetoed sections.
    veto_split = VETOED_MARKER.split(text)
    signed_text = veto_split[0]
    vetoed_text = veto_split[1] if len(veto_split) > 1 else ""
    # The signed section begins at the signed-marker if present.
    sm = SIGNED_MARKER.search(signed_text)
    if sm:
        signed_text = signed_text[sm.end():]
    elif vetoed_text:
        signed_text = ""

    out = {}
    for m in BILL_RE.finditer(signed_text):
        out[norm(m.group(1) + m.group(2))] = {
            "action": "signed", "date": date, "url": url}
    for m in BILL_RE.finditer(vetoed_text):
        out[norm(m.group(1) + m.group(2))] = {
            "action": "vetoed", "date": date, "url": url}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--after", default="2024-12-01")
    ap.add_argument("--out", default="data/gov_actions.json")
    args = ap.parse_args()

    after_iso = args.after + "T00:00:00"
    print(f"Fetching gov.ca.gov 'legislative update' posts since {args.after} …")
    posts = fetch_posts(after_iso)
    print(f"  found {len(posts)} posts")

    actions = {}
    seen_titles = 0
    for p in posts:
        parsed = parse_post(p)
        if parsed:
            seen_titles += 1
        for k, v in parsed.items():
            # Keep the earliest announcement if a bill shows up twice.
            if k not in actions or v["date"] < actions[k]["date"]:
                actions[k] = v

    print(f"  parsed {seen_titles} update posts -> {len(actions)} bill actions")

    signed = sum(1 for v in actions.values() if v["action"] == "signed")
    vetoed = sum(1 for v in actions.values() if v["action"] == "vetoed")
    print(f"  signed={signed} vetoed={vetoed}")

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "https://www.gov.ca.gov (Governor's Office legislative updates)",
        "counts": {"signed": signed, "vetoed": vetoed},
        "actions": actions,
    }

    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"DONE — wrote {args.out}")


if __name__ == "__main__":
    main()
