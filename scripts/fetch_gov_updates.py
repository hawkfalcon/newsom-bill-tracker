#!/usr/bin/env python3
"""
Fetch Gov. Gavin Newsom's official legislative announcements (signing batches,
vetoes, and legislative updates) from gov.ca.gov (WordPress REST API).

These are the Governor's own office's same-day announcements of which bills
he signed and vetoed — the first public source of the action — and each bill
entry links to the official signing or veto message (usually a PDF).

Output: data/gov_actions.json
  -> { "actions": { <norm_bill_id>: {action, date, url, msg_url, measure, ...} } }

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

# Markers separating signed vs vetoed sections in announcement posts
SIGNED_MARKER = re.compile(
    r"(?:signed\s+the\s+following|signing\s+of\s+the\s+following|bills?\s+signed|signed\s+today|signed\s+into\s+law)",
    re.I,
)
VETOED_MARKER = re.compile(
    r"(?:vetoed?\s+the\s+following|vetoing\s+of\s+the\s+following|bills?\s+vetoed|vetoed\s+today)",
    re.I,
)

# Also match more casual “signs bill” / “signs new laws” phrasing that appears
# in press‑release titles or bodies without the “signed the following” wording.
SIGN_BILL_RE = re.compile(
    r"(?:signs?\s+bill|signs?\s+new\s+laws|signs?\s+legislation)",
    re.I,
)

# Matches batch action titles used by the Governor's press office, e.g.:
# "Governor Newsom signs legislation 9.14.2026"
# "Governor Newsom signs legislation 7.6.26"
# "Acting Governor Monique Limón signs legislation 6.17.26"
# "Governor Newsom issues legislative update 10.13.25"
# "Governor Newsom issues legislative update 6.1.26"
# "Governor Newsom vetoes legislation 10.1.25"
BATCH_TITLE_RE = re.compile(
    r"(?:signs?\s+legislation|legislative\s+update|veto(?:es)?\s+legislation|takes?\s+action\s+on\s+legislation|acts?\s+on\s+legislation|signed\s+legislation|vetoed\s+legislation)",
    re.I,
)

# "AB 70" / "SB 771" / "ABX1 2" / "AB-70" at the start of a bill entry.
# The hyphen class includes U+2011 (non-breaking hyphen), which the Governor's
# site uses inconsistently.
BILL_PATTERN = re.compile(
    r"(?:^|[>\n])\s*(?:[\u2022\u2023\u25E6\u2043\u2219\*\-–—•]\s*)?"
    r"(AB|SB|ACA|SCA|AJR|SJR|ACR|SCR|HR|SR|ABX\d+|SBX\d+)[-\s\u2011]?(\d+)\b",
    re.I,
)


def anchor_href_before(text, pos, lookback=600):
    """If the position is inside an <a> tag, return that anchor's href."""
    seg = text[max(0, pos - lookback):pos]
    open_idx = seg.rfind("<a")
    if open_idx == -1:
        return None
    close_idx = seg.rfind("</a>")
    if close_idx != -1 and close_idx > open_idx:
        return None  # the last anchor was already closed before pos
    tag_end = seg.find(">", open_idx)
    if tag_end == -1:
        return None
    m = re.search(r'href=["\']([^"\']+)["\']', seg[open_idx:tag_end], re.I)
    return m.group(1) if m else None


def norm(measure):
    """'AB 70' / 'AB-70' / 'ABX1 2' -> 'ab70' / 'abx12' (alphanumeric only)."""
    return re.sub(r"[^a-z0-9]", "", measure.lower())


def get_json(url, params, retries=4):
    """Fetch JSON from url with params; return (data, total_pages)."""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=45)
            if r.status_code == 200:
                try:
                    total_pages = int(r.headers.get("X-WP-TotalPages", 1))
                except (ValueError, TypeError):
                    total_pages = 1
                return r.json(), total_pages
            if r.status_code == 400 and "rest_post_invalid_page_number" in r.text:
                return [], 0
            last = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(1 + attempt * 1.5)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def fetch_posts(after_iso):
    """Return (posts, ok) for candidate posts since `after_iso`.

    `ok` is False when any API page failed, i.e. the result set is known to
    be incomplete — callers must not treat it as the full picture.
    """
    queries = [
        {"search": "legislat"},
        {"search": "veto"},
        {"tags": 189},  # Official WordPress "Legislation" tag
    ]
    posts_by_id = {}
    ok = True
    for q_params in queries:
        page = 1
        while True:
            params = {
                **q_params,
                "after": after_iso,
                "per_page": 100,
                "page": page,
                "orderby": "date",
                "order": "desc",
            }
            try:
                data, total_pages = get_json(API, params)
            except Exception as e:  # noqa: BLE001
                print(f"  warning: query {q_params} page {page} failed: {e}")
                ok = False
                break

            if not data:
                break

            for p in data:
                pid = p.get("id")
                if pid:
                    posts_by_id[pid] = p

            if page >= total_pages or len(data) < 100:
                break
            page += 1
            time.sleep(0.3)

    posts = sorted(
        posts_by_id.values(),
        key=lambda p: p.get("date", ""),
        reverse=True,
    )
    return posts, ok


def clean_html(fragment):
    """Strip divi shortcode crud and tags; return readable text."""
    frag = re.sub(r"\[et_pb[^\]]*\]", " ", fragment)
    frag = re.sub(r"<[^>]+>", " ", frag)
    return re.sub(r"\s+", " ", html_mod.unescape(frag)).strip()


def extract_msg_url(chunk):
    """Extract official signing/veto document link from HTML chunk."""
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', chunk)
    for h in hrefs:
        hl = h.lower()
        if any(term in hl for term in ["wp-content", "veto", "signing", "message", ".pdf"]):
            if not any(skip in hl for skip in ["leginfo", "list-manage", "twitter", "facebook", "instagram", "youtube", "linkedin"]):
                return h
    return None


def parse_bill_items(html_section):
    """Parse bill entries from HTML section.

    Handles standard <li> tags, malformed </li>-only lines, <p> tags,
    or newline-delimited lists.
    Returns list of (norm_id, measure_text, msg_url).
    """
    out = []
    seen = set()
    unescaped = html_mod.unescape(html_section)
    matches = list(BILL_PATTERN.finditer(unescaped))
    for i, m in enumerate(matches):
        measure_type = m.group(1).upper()
        num = m.group(2)
        measure = f"{measure_type} {num}"
        nid = norm(measure)
        if nid in seen:
            continue
        seen.add(nid)

        # A bill code inside an anchor that links to another gov.ca.gov page
        # is a cross-reference in press-release prose (e.g. "signed into law
        # AB 238" linking to last year's signing post) — not a bill in this
        # announcement.  Plain-text entries and LegInfo-linked entries keep.
        href = anchor_href_before(unescaped, m.start(1))
        if href and "gov.ca.gov" in href:
            continue

        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(unescaped)
        chunk = unescaped[start:end]

        # If this is the last bill, trim at list/section terminators to avoid capturing footer links
        if i + 1 == len(matches):
            term = re.search(r"(?:</ul>|</ol>|\[/et_pb_text\]|For\s+full\s+text|###)", chunk, re.I)
            if term:
                chunk = chunk[:term.start()]

        msg_url = extract_msg_url(chunk)
        out.append((nid, measure, msg_url))
    return out


def parse_post(post):
    """Return {norm_bill_id: {action, date, url, msg_url, measure}}."""
    title = post.get("title", {}).get("rendered", "")
    title_clean = html_mod.unescape(title)
    content = post.get("content", {}).get("rendered", "")
    date = post.get("date", "")[:10]
    url = post.get("link", "")

    # Post must look like a legislative update / bill action announcement:
    # either by title match or by containing explicit signed/vetoed markers.
    has_title_match = bool(BATCH_TITLE_RE.search(title_clean))
    sm = SIGNED_MARKER.search(content)
    vm = VETOED_MARKER.search(content)

    if not has_title_match and not sm and not vm and not SIGN_BILL_RE.search(content):
        return {}

    signed_html = ""
    vetoed_html = ""

    if sm and vm:
        if sm.start() < vm.start():
            signed_html = content[sm.end():vm.start()]
            vetoed_html = content[vm.end():]
        else:
            vetoed_html = content[vm.end():sm.start()]
            signed_html = content[sm.end():]
    elif sm:
        signed_html = content[sm.end():]
    elif vm:
        vetoed_html = content[vm.end():]
    elif "veto" in title_clean.lower():
        vetoed_html = content
    elif SIGN_BILL_RE.search(content):
        signed_html = content
    else:
        signed_html = content

    out = {}
    common = {
        "post_id": post.get("id"),
        "published_at": post.get("date_gmt") or post.get("date"),
        "modified_at": post.get("modified_gmt") or post.get("modified"),
        "title": title_clean,
    }
    for nid, measure, msg in parse_bill_items(signed_html):
        out[nid] = {**common, "action": "signed", "date": date, "url": url,
                    "msg_url": msg, "measure": measure}
    for nid, measure, msg in parse_bill_items(vetoed_html):
        out[nid] = {**common, "action": "vetoed", "date": date, "url": url,
                    "msg_url": msg, "measure": measure}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--after", default="2024-12-01")
    ap.add_argument("--out", default="data/gov_actions.json")
    args = ap.parse_args()

    # Pre-populate with existing data if present so actions are preserved
    # and enriched even if a single network fetch returns a partial set.
    actions = {}
    if os.path.exists(args.out):
        try:
            with open(args.out, "r", encoding="utf-8") as f:
                prev = json.load(f).get("actions", {})
                if isinstance(prev, dict):
                    actions.update(prev)
                    print(f"Loaded {len(actions)} existing actions from {args.out}")
        except Exception as exc:  # noqa: BLE001
            print(f"Note: could not read existing {args.out}: {exc}")

    after_iso = args.after + "T00:00:00"
    print(f"Fetching gov.ca.gov announcements since {args.after} …")
    posts, fetch_ok = fetch_posts(after_iso)
    print(f"  found {len(posts)} candidate posts (complete={fetch_ok and bool(posts)})")

    # Re-parse all candidate posts oldest -> newest so a later post that
    # corrects an earlier one (bill listed under the wrong batch) wins, and
    # the earliest announcement date / its post link are kept.
    parsed_actions = {}
    parsed_posts = 0
    for p in sorted(posts, key=lambda p: p.get("date", "")):
        parsed = parse_post(p)
        if parsed:
            parsed_posts += 1
        for k, v in parsed.items():
            if k not in parsed_actions:
                parsed_actions[k] = v
                continue
            existing = parsed_actions[k]
            if v["action"] != existing.get("action"):
                print(f"  note: {k} action corrected {existing.get('action')} -> "
                      f"{v['action']} by newer post '{v.get('title', '')}'")
                parsed_actions[k] = v
                continue
            if v["date"] < existing["date"]:
                # Keep the earliest announcement (its post is the canonical link)
                if existing.get("msg_url") and not v.get("msg_url"):
                    v["msg_url"] = existing["msg_url"]
                parsed_actions[k] = v
            elif v.get("msg_url") and not existing.get("msg_url"):
                existing["msg_url"] = v["msg_url"]

    if fetch_ok and posts:
        # Complete re-fetch: rebuild from the posts so stale entries — e.g.
        # phantom actions from old press-release mentions the parser no
        # longer treats as announcements — self-heal on the next run.
        # Carry over message links the current parse didn't find for
        # entries it did still find.
        dropped = sorted(k for k in actions if k not in parsed_actions)
        for k in dropped:
            print(f"  note: dropping stale action {k} ({actions[k].get('measure')})")
        for k, v in parsed_actions.items():
            if not v.get("msg_url") and k in actions and actions[k].get("msg_url"):
                v["msg_url"] = actions[k]["msg_url"]
        actions = parsed_actions
    else:
        # Incomplete fetch: keep the previous file as the source of truth
        # and apply only safe improvements (new entries, missing links).
        print("  note: fetch incomplete; keeping previous actions, adding new ones")
        for k, v in parsed_actions.items():
            if k not in actions:
                actions[k] = v
            elif v.get("msg_url") and not actions[k].get("msg_url"):
                actions[k]["msg_url"] = v["msg_url"]

    print(f"  parsed {parsed_posts} announcement posts -> total {len(actions)} bill actions")

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
