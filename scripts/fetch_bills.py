#!/usr/bin/env python3
"""
Fetch current California legislative session bills that reached Gov. Newsom's
desk (signed / vetoed / pending) from leginfo.legislature.ca.gov and write a
single JSON file used by the static site.

The site deep-links each bill to CalMatters' Digital Democracy:
    https://calmatters.digitaldemocracy.org/bills/<dd_slug>
where <dd_slug> = "ca_" + lowercased leginfo bill_id
(e.g. leginfo 202520260AB302 -> ca_202520260ab302).

Status source of truth is LegInfo (the official record):
  - "Chaptered"                -> signed into law
  - "Vetoed"                   -> vetoed by the Governor
  - "Enrolled"                 -> enrolled, on the Governor's desk (pending)

Usage:
    python scripts/fetch_bills.py [--session 20252026] [--workers 8] [--limit N]
"""

import argparse
import html as html_mod
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

BASE = "https://leginfo.legislature.ca.gov/faces"
SEARCH_PATH = "/billSearchClient.xhtml"
STATUS_PATH = "/billStatusClient.xhtml"
NAV_PATH = "/billNavClient.xhtml"
DD_BASE = "https://calmatters.digitaldemocracy.org/bills"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; NewsomBillTracker/1.0; "
        "automated public-records check once daily)"
    ),
}

# Local TLS so requests are isolated per worker thread.
_tls = threading.local()


def session_for_thread():
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update(HEADERS)
        _tls.session = s
    return s


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------
# 1. Full bill list + current status via the LegInfo search form (single POST)
# --------------------------------------------------------------------------
def get_viewstate(session):
    r = session.get(BASE + SEARCH_PATH + f"?session_year={SESSION}&house=Both&author=All&lawCode=All",
                    timeout=45)
    r.raise_for_status()
    m = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("Could not find JSF ViewState on the search page")
    return m.group(1)


def run_search(session, viewstate):
    data = {
        "billSearchForm": "billSearchForm",
        "session_year": SESSION,
        "house": "Both",
        "author": "All",
        "keyword": "",
        "bill_number": "",
        "law_code": "All",
        "law_section_num": "",
        "statuteYear": "",
        "chapter_number": "",
        "search_keywords": "",
        "hiddenSessionYr": SESSION,
        "hiddenHouse": "Both",
        "hidden_author": "All",
        "hidden_keyword": "",
        "hidden_bill_nbr": "",
        "hidden_sess_yr": SESSION,
        "attrSearch": "Search",
        "javax.faces.ViewState": viewstate,
    }
    r = session.post(BASE + SEARCH_PATH, data=data, timeout=90)
    r.raise_for_status()
    return r.text


def parse_search_html(html):
    rows = re.findall(r"<tr>\s*<td>(.*?)</tr>", html, re.S)
    bills = []
    for row in rows:
        m = re.search(r'bill_id=([^"&]+)"[^>]*>\s*(.*?)\s*</a>', row, re.S)
        if not m:
            continue
        bill_id = m.group(1)
        measure = html_mod.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        measure = re.sub(r"\s+", " ", measure).strip()
        tds = [html_mod.unescape(re.sub(r"<[^>]+>", "", x)) for x in re.findall(r"<td>(.*?)</td>", row, re.S)]
        tds = [re.sub(r"\s+", " ", x).strip() for x in tds]
        # The measure's own <td> was consumed by the outer row regex, so the
        # remaining cells are [title, author, status].
        if len(tds) < 3:
            continue
        bills.append({
            "bill_id": bill_id,
            "measure": measure,
            "title": tds[0],
            "author": tds[1],
            "status": tds[2],
        })
    return bills


# --------------------------------------------------------------------------
# 2. Classification
# --------------------------------------------------------------------------
def classify(status):
    if status == "Chaptered":
        return "signed"
    if status == "Vetoed":
        return "vetoed"
    if status == "Enrolled":
        return "pending"
    return None


STATUS_LABELS = {"signed": "Signed", "vetoed": "Vetoed", "pending": "Awaiting action"}


# --------------------------------------------------------------------------
# 3. Per-bill history (to get the exact action date + chapter number)
# --------------------------------------------------------------------------
def parse_date_mmddyy(d):
    """'09/10/26' -> '2026-09-10'"""
    m = re.match(r"(\d{2})/(\d{2})/(\d{2})", d)
    if not m:
        return None
    mo, dy, yr = m.groups()
    return f"20{yr}-{mo}-{dy}"


def fetch_status_page(bill_id):
    r = session_for_thread().get(
        BASE + STATUS_PATH + f"?bill_id={bill_id}", timeout=45
    )
    r.raise_for_status()
    return r.text


def parse_status_page(html):
    """Return (summary_dates, history).

    summary_dates: {label: 'YYYY-MM-DD'} from the "…Date:" fields near the top
    (always current, even when the history table lags a day).
    history: list of (date, action) from the "Last 5 History Actions" table.
    """
    summary = {}
    for m in re.finditer(
        r'class="statusLabel">([^<]*Date:)</label>.*?<span id="lastAction"[^>]*>([^<]*)</span>',
        html, re.S,
    ):
        label = m.group(1).strip().rstrip(":")
        summary[label] = parse_date_mmddyy(m.group(2).strip())

    rows = re.findall(
        r'<tr>\s*<td scope="row">(\d{2}/\d{2}/\d{2})</td>\s*<td>(.*?)</td>',
        html, re.S,
    )
    history = []
    for d, a in rows:
        a = html_mod.unescape(re.sub(r"<[^>]+>", " ", a))
        a = re.sub(r"\s+", " ", a).strip()
        date = parse_date_mmddyy(d)
        if date:
            history.append((date, a))
    return summary, history


def extract_action(summary, history, kind):
    """Return (action_date, action_text, chapter_number)."""
    if kind == "vetoed":
        for date, text in history:
            if "vetoed by" in text.lower():
                return date, text, None
    elif kind == "signed":
        for date, text in history:
            low = text.lower()
            if "chaptered by secretary of state" in low:
                ch = re.search(r"chapter\s+(\d+)", low)
                return date, text, ch.group(1) if ch else None
        # History may lag the summary (chaptering just recorded); fall back to
        # the "Chaptered Date:" summary field without a chapter number.
        if summary.get("Chaptered Date"):
            return summary["Chaptered Date"], "Chaptered by Secretary of State.", None
        for date, text in history:
            if "approved by the governor" in text.lower():
                return date, text, None
    elif kind == "pending":
        for date, text in history:
            if "presented to the governor" in text.lower():
                return date, text, None
        for date, text in history:
            if "enrolled" in text.lower():
                return date, text, None
        if summary.get("Enrolled Date"):
            return summary["Enrolled Date"], "Enrolled.", None
    return None, None, None


def fetch_one(bill):
    """Fetch history for one bill and return the enriched record (or None)."""
    bill_id = bill["bill_id"]
    summary, history = {}, []
    last_err = None
    for _ in range(3):  # retry transient redirects / empty responses
        try:
            time.sleep(random.uniform(0.05, 0.15))  # be polite
            summary, history = parse_status_page(fetch_status_page(bill_id))
            if summary or history:  # got real data
                break
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)[:120]
            time.sleep(0.5)
    else:
        return {**bill, "action_date": None, "action": None, "chapter": None,
                "error": last_err or "empty status page after retries"}

    kind = classify(bill["status"])
    date, text, chapter = extract_action(summary, history, kind)
    return {**bill, "action_date": date, "action": text, "chapter": chapter,
            "error": None}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
SESSION = "20252026"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="20252026")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="cap status-page fetches (testing)")
    ap.add_argument("--out", default="data/bills.json")
    args = ap.parse_args()

    global SESSION
    SESSION = args.session

    log(f"Fetching bill list for session {SESSION} …")
    s = requests.Session()
    s.headers.update(HEADERS)

    html = None
    last_err = None
    for attempt in range(1, 4):
        try:
            vs = get_viewstate(s)
            html = run_search(s, vs)
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log(f"  search attempt {attempt} failed: {exc}")
            time.sleep(3 * attempt)
    if html is None:
        log(f"FATAL: could not run search: {last_err}")
        sys.exit(1)

    bills = parse_search_html(html)
    log(f"  parsed {len(bills)} bills")
    if len(bills) < 1000:
        log(f"FATAL: expected ~5000 bills, only got {len(bills)} — aborting to "
            "avoid writing incomplete data.")
        sys.exit(1)

    targets = [b for b in bills if classify(b["status"]) is not None]
    log(f"  {len(targets)} bills reached the Governor "
        f"(signed / vetoed / enrolled) — fetching action details …")

    if args.limit:
        targets = targets[: args.limit]
        log(f"  (limited to {args.limit} for testing)")

    records = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(fetch_one, b) for b in targets]
        for fut in as_completed(futs):
            rec = fut.result()
            records.append(rec)
            done += 1
            if done % 200 == 0:
                log(f"  …{done}/{len(targets)}")

    # Build final structure.
    def sort_key(r):
        return (r["action_date"] or "", r["measure"])

    records.sort(key=sort_key, reverse=True)

    def slug(bill_id):
        return "ca_" + bill_id.lower()

    out_bills = []
    for r in records:
        bid = r["bill_id"]
        measure = r["measure"]
        # Normalize "AB-302" -> "AB 302", keep "ABX1-2" style intact.
        if re.fullmatch(r"[A-Za-z]+-\d+", measure):
            measure = measure.replace("-", " ")
        out_bills.append({
            "measure": measure,
            "title": r["title"],
            "author": r["author"],
            "status": classify(r["status"]),
            "status_label": STATUS_LABELS[classify(r["status"])],
            "action_date": r.get("action_date"),
            "action": r.get("action"),
            "chapter": r.get("chapter"),
            "dd_url": f"{DD_BASE}/{slug(bid)}",
            "leginfo_url": f"{BASE}{NAV_PATH}?bill_id={bid}",
        })

    counts = {}
    for b in out_bills:
        counts[b["status"]] = counts.get(b["status"], 0) + 1

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": SESSION,
        "session_label": f"{SESSION[:4]}–{SESSION[4:]}",
        "governor": "Gavin Newsom",
        "counts": counts,
        "bills": out_bills,
    }

    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    log(f"DONE — wrote {len(out_bills)} bills to {args.out}")
    log(f"  signed={counts.get('signed', 0)} vetoed={counts.get('vetoed', 0)} "
        f"pending={counts.get('pending', 0)}")


if __name__ == "__main__":
    main()
