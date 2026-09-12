#!/usr/bin/env python3
"""
Fetch Gov. Gavin Newsom's official "legislative update" announcements from
gov.ca.gov (WordPress REST API). These are the Governor's own office's
same-day announcements of which bills he signed and vetoed — the first public
source of the action — and each bill entry links to the official signing or
veto message (usually a PDF).

Output: data/gov_actions.json
  -> { "actions": { <norm_bill_id>: {action, date, url, msg_url} } }

Usage:
    python scripts/fetch_gov_updates.py [--after 2024-12-01] [--out data/gov_actions.json]
"""

import argparse
import html as html_mod
import json
import os
import re
import time
from datetime import datetime, timezone

import requests

API = "https://www.gov.ca.gov/wp-json/wp/v2/posts"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "application/json"}

SIGNED_MARKER = re.compile(r"signed the following", re.I)
VETOED_MARKER = re.compile(r"vetoed the following", re.I)
# "AB 70" / "SB 771" / "ABX1 2" / "AB-70" at the start of a bill line.
BILL_AT_START = re.compile(
    r"^\s*(AB|SB|ACA|SCA|AJR|SJR|ACR|SCR|HR|SR|ABX\d+|SBX\d+)[-\s]?(\d+)\b",
    re.I,
)


def norm(measure):
    """'AB 70' / 'AB-70' / 'ABX1 2' -> 'ab70' / 'abx12' (alphanumeric only)."""
    return re.sub(r"[^a-z0-9]", "", measure.lower())


def get_json(url, params, retries=3):
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=45)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
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


def clean_html(fragment):
    """Strip divi shortcode crud and tags; return readable text."""
    frag = re.sub(r"\[et_pb[^\]]*\]", " ", fragment)
    frag = re.sub(r"<[^>]+>", " ", frag)
    return re.sub(r"\s+", " ", html_mod.unescape(frag)).strip()


def parse_bill_items(html_section):
    """Parse an HTML list of '<li>BILL… <a href>…</a></li>' items.

    Returns list of (norm_id, measure_text, msg_url).
    """
    out = []
    for li in re.findall(r"<li[^>]*>(.*?)</li>", html_section, re.S):
        hrefs = re.findall(r'href="([^"]+)"', li)
        text = clean_html(li)
        m = BILL_AT_START.match(text)
        if not m:
            continue
        measure = m.group(1) + " " + m.group(2)
        msg_url = hrefs[0] if hrefs else None
        # Only keep message links that look like the official docs, not
        # navigation or generic gov.ca.gov links.
        if msg_url and ("wp-content" not in msg_url and "veto" not in msg_url.lower()
                        and "signing" not in msg_url.lower() and "message" not in msg_url.lower()):
            msg_url = None
        out.append((norm(measure), measure, msg_url))
    return out


def parse_post(post):
    """Return {norm_bill_id: {action, date, url, msg_url, measure}}."""
    title = post.get("title", {}).get("rendered", "")
    if "legislative update" not in title.lower():
        return {}
    date = post.get("date", "")[:10]
    url = post.get("link", "")
    content = post.get("content", {}).get("rendered", "")

    veto_split = VETOED_MARKER.split(content)
    signed_html = veto_split[0]
    vetoed_html = veto_split[1] if len(veto_split) > 1 else ""

    sm = SIGNED_MARKER.search(signed_html)
    if sm:
        signed_html = signed_html[sm.end():]
    elif vetoed_html:
        signed_html = ""

    out = {}
    for nid, measure, msg in parse_bill_items(signed_html):
        out[nid] = {"action": "signed", "date": date, "url": url,
                    "msg_url": msg, "measure": measure}
    for nid, measure, msg in parse_bill_items(vetoed_html):
        out[nid] = {"action": "vetoed", "date": date, "url": url,
                    "msg_url": msg, "measure": measure}
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
    parsed_posts = 0
    for p in posts:
        parsed = parse_post(p)
        if parsed:
            parsed_posts += 1
        for k, v in parsed.items():
            if k not in actions or v["date"] < actions[k]["date"]:
                actions[k] = v

    print(f"  parsed {parsed_posts} update posts -> {len(actions)} bill actions")

    signed = sum(1 for v in actions.values() if v["action"] == "signed")
    vetoed = sum(1 for v in actions.values() if v["action"] == "vetoed")
    with_msg = sum(1 for v in actions.values() if v.get("msg_url"))
    print(f"  signed={signed} vetoed={vetoed} (with message links: {with_msg})")

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "https://www.gov.ca.gov (Governor's Office legislative updates)",
        "counts": {"signed": signed, "vetoed": vetoed},
        "actions": actions,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"DONE — wrote {args.out}")


if __name__ == "__main__":
    main()
