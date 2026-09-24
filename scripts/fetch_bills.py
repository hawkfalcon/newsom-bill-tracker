#!/usr/bin/env python3
"""
Fetch current California legislative session bills that reached Gov. Newsom's
desk (signed / vetoed / pending) from leginfo.legislature.ca.gov and write a
single JSON file used by the static site.

The site deep-links each bill to CalMatters' Digital Democracy:
    https://calmatters.digitaldemocracy.org/bills/<dd_slug>
where <dd_slug> = "ca_" + lowercased leginfo bill_id
(e.g. leginfo 202520260AB302 -> ca_202520260ab302).

LegInfo is the official source of truth for the three states tracked here:
  - signed into law
  - vetoed by the Governor
  - enrolled and on the Governor's desk (pending)

LegInfo's search table labels a bill by where it sits in the Legislature, not by
what the Governor did to it, so a bill whose veto the house has not disposed of
yet reads as "In Senate" again and would silently drop out of the snapshot.
Those bills are re-read from their own LegInfo status/history pages (see section
2b); --gov data/gov_actions.json widens the set to bills the Governor's office
announced but the previous snapshot had already lost.

Usage:
    python scripts/fetch_bills.py [--session 20252026] [--workers 8] [--limit N]
                                  [--gov data/gov_actions.json]
"""

import argparse
import hashlib
import html as html_mod
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

from enrichment import enrich_payload
from plain_english import summarize_bill

BASE = "https://leginfo.legislature.ca.gov/faces"
SEARCH_PATH = "/billSearchClient.xhtml"
STATUS_PATH = "/billStatusClient.xhtml"
HISTORY_PATH = "/billHistoryClient.xhtml"
NAV_PATH = "/billNavClient.xhtml"
TEXT_PATH = "/billTextClient.xhtml"
VOTES_PATH = "/billVotesClient.xhtml"
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
LEGINFO_SIGNED_STATUS = "Chaptered"
LEGINFO_VETOED_STATUS = "Vetoed"
LEGINFO_PENDING_STATUS = "Enrolled"


def classify(status):
    status_map = {
        LEGINFO_SIGNED_STATUS: "signed",
        LEGINFO_VETOED_STATUS: "vetoed",
        LEGINFO_PENDING_STATUS: "pending",
    }
    return status_map.get(status)


STATUS_LABELS = {"signed": "Signed", "vetoed": "Vetoed", "pending": "Awaiting action"}


# --------------------------------------------------------------------------
# 3. Per-bill history (to get the exact Governor-facing action date)
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


def fetch_history_page(bill_id):
    """Full action history (the status page shows only the last five rows)."""
    r = session_for_thread().get(
        BASE + HISTORY_PATH + f"?bill_id={bill_id}", timeout=45
    )
    r.raise_for_status()
    return r.text


def parse_history_rows(html):
    """Parse date/action rows from a LegInfo history table (any length)."""
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
    return history


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
        summary_key = {
            f"{LEGINFO_SIGNED_STATUS} Date": "signed_date",
            f"{LEGINFO_VETOED_STATUS} Date": "vetoed_date",
            f"{LEGINFO_PENDING_STATUS} Date": "pending_date",
        }.get(label, label.lower().replace(" ", "_"))
        summary[summary_key] = parse_date_mmddyy(m.group(2).strip())

    return summary, parse_history_rows(html)


def extract_action(summary, history, kind):
    """Return the Governor-facing action date and plain-language description."""
    if kind == "vetoed":
        for date, text in history:
            if "vetoed by" in text.lower():
                return date, text
        # Same lag protection as the signed path: the status summary may show
        # the veto date before the history table has caught up.
        if summary.get("vetoed_date"):
            return summary["vetoed_date"], "Vetoed by the Governor."
    elif kind == "signed":
        for date, text in history:
            if "approved by the governor" in text.lower():
                return date, "Signed by the Governor."
        # History may lag the newest signing record. The date remains useful,
        # but keep the description focused on the Governor's decision.
        if summary.get("signed_date"):
            return summary["signed_date"], "Signed by the Governor."
    elif kind == "pending":
        for date, text in history:
            if "presented to the governor" in text.lower():
                return date, text
        for date, text in history:
            if "enrolled" in text.lower():
                return date, text
        # parse_status_page stores the "Enrolled Date:" field under
        # "pending_date" (see the summary_key map above).
        if summary.get("pending_date"):
            return summary["pending_date"], "Enrolled."
    return None, None


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
        return {**bill, "action_date": None, "action": None,
                "error": last_err or "empty status page after retries"}

    kind = classify(bill["status"])
    date, text = extract_action(summary, history, kind)
    if date is None and kind in ("signed", "vetoed"):
        # The Governor's action can be missing from the "last 5" window (or
        # the summary can lag).  Fall back to the full action history page —
        # one extra request, only for the rare bill that needs it.
        try:
            time.sleep(random.uniform(0.05, 0.15))  # be polite
            date, text = extract_action(
                {}, parse_history_rows(fetch_history_page(bill_id)), kind
            )
        except Exception:  # noqa: BLE001 - action date is a nice-to-have
            pass

    summary_text = None
    digest_text = None
    try:
        time.sleep(random.uniform(0.05, 0.15))  # be polite
        digest_text = extract_digest_text(fetch_digest(bill_id), bill["title"])
        summary_text = truncate(digest_text) if digest_text else None
    except Exception:  # noqa: BLE001 - summary is a nice-to-have
        summary_text = None
        digest_text = None

    latest_vote = None
    try:
        time.sleep(random.uniform(0.05, 0.15))  # be polite
        latest_vote = parse_latest_vote(fetch_votes(bill_id), bill_id)
    except Exception:  # noqa: BLE001 - vote data is a nice-to-have
        latest_vote = None

    return {**bill, "action_date": date, "action": text,
            "summary": summary_text, "digest_text": digest_text,
            "latest_vote": latest_vote, "error": None}


# --------------------------------------------------------------------------
# 4. Legislative Counsel's Digest (the "little description" of the bill)
# --------------------------------------------------------------------------
DIGEST_RE = re.compile(
    r"DIGEST\s+((?:AB|SB|ACA|SCA|AJR|SJR|ACR|SCR|HR|SR|ABX\d+|SBX\d+)[-\s]?\d+,.+?)Digest Key",
    re.S,
)


def truncate(text, limit=280):
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for punct in (". ", "? ", "! ", "; "):
        idx = cut.rfind(punct)
        if idx > 60:
            return cut[: idx + 1].rstrip() + " …"
    return cut.rsplit(" ", 1)[0].rstrip() + " …"


def fetch_digest(bill_id):
    r = session_for_thread().get(BASE + TEXT_PATH + f"?bill_id={bill_id}", timeout=45)
    r.raise_for_status()
    return r.text


def fetch_votes(bill_id):
    r = session_for_thread().get(BASE + VOTES_PATH + f"?bill_id={bill_id}", timeout=45)
    r.raise_for_status()
    return r.text


def _page_lines(page_html):
    """Turn a LegInfo page into label/value-friendly text lines."""
    text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", page_html,
                  flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:div|p|tr|td|th|li|h[1-6]|label|span)>", "\n", text,
                  flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def _vote_number(value):
    m = re.search(r"\d+", value or "")
    return int(m.group()) if m else None


def parse_latest_vote(votes_html, bill_id=None):
    """Return the newest recorded roll call from a Bill Votes page.

    LegInfo renders each roll call as a sequence of labels and values (Date,
    Result, Location, Ayes Count, Noes Count, NVR Count, Motion).  This keeps
    only the compact result needed by the tracker rather than copying every
    legislator's individual vote into the static site.
    """
    lines = _page_lines(votes_html)
    date_re = re.compile(r"^\d{2}/\d{2}/\d{2}$")
    votes = []

    for i, line in enumerate(lines):
        if line != "Date" or i + 1 >= len(lines) or not date_re.fullmatch(lines[i + 1]):
            continue
        block = lines[i:i + 30]

        def value_after(label):
            try:
                j = block.index(label) + 1
            except ValueError:
                return None
            return block[j] if j < len(block) else None

        ayes = _vote_number(value_after("Ayes Count"))
        noes = _vote_number(value_after("Noes Count"))
        if ayes is None or noes is None:
            continue
        date = parse_date_mmddyy(lines[i + 1])
        if not date:
            continue
        votes.append({
            "date": date,
            "result": value_after("Result"),
            "location": value_after("Location"),
            "ayes": ayes,
            "noes": noes,
            "nvr": _vote_number(value_after("NVR Count")),
            "motion": value_after("Motion"),
            "url": BASE + VOTES_PATH + f"?bill_id={bill_id}" if bill_id else None,
        })

    return max(votes, key=lambda v: v["date"]) if votes else None


def extract_digest_text(digest_html, title):
    """Pull the complete Legislative Counsel digest body as plain text."""
    text = html_mod.unescape(re.sub(r"<[^>]+>", " ", digest_html))
    text = re.sub(r"\s+", " ", text).strip()
    m = DIGEST_RE.search(text)
    if not m:
        return None
    digest = m.group(1).strip()
    # Drop the "AB 123, Author." header.
    digest = re.sub(
        r"^(?:AB|SB|ACA|SCA|AJR|SJR|ACR|SCR|HR|SR|ABX\d+|SBX\d+)[-\s]?\d+,\s*[^.]*\.\s*",
        "", digest,
    ).strip()
    # Drop the short title if it leads the text.
    t = (title or "").strip().rstrip(".")
    if t:
        i = digest.lower().find(t.lower())
        if 0 <= i < 200:
            digest = digest[i + len(t):].lstrip(" .").strip()
    return digest or None


def extract_summary(digest_html, title):
    """Pull a compact source excerpt for the existing list view.

    The full digest is also retained transiently by ``fetch_one`` so the
    deterministic plain-English pass can see the operative provisions even
    when the compact excerpt ends during the background section.
    """
    digest = extract_digest_text(digest_html, title)
    return truncate(digest) if digest else None


# --------------------------------------------------------------------------
# 2b. Bills LegInfo no longer labels as being at the Governor's desk
# --------------------------------------------------------------------------
# LegInfo's search row reports where a bill sits *in the Legislature*, not what
# the Governor did to it.  A bill vetoed late in the session is returned to its
# house of origin, so its row flips from "Vetoed" back to an in-process label
# ("In Senate") while its history gains the line
#     "In Senate. Consideration of Governor's veto pending."
# Classifying from the search row alone would then silently drop a veto this
# tracker had already recorded — the bill disappears from the site and the
# cross-check reports it as absent from bills.json.  Such bills are re-read
# from their own LegInfo record, which still shows the Governor's action.
TRACKED_KINDS = {"signed", "vetoed", "pending"}
FINAL_KINDS = {"signed", "vetoed"}


def kind_from_leginfo_record(summary, history):
    """Classify a bill from its LegInfo status/history rows (not the search row).

    Returns "signed", "vetoed", or None when the record shows no Governor
    action — i.e. the bill genuinely is back in the ordinary floor process.
    The date fields lag a new veto, so the action lines decide.
    """
    text = " | ".join(action.lower() for _, action in history)
    if summary.get("vetoed_date") or "vetoed by" in text:
        return "vetoed"
    if summary.get("signed_date") or "approved by the governor" in text:
        return "signed"
    return None


def norm_measure_label(measure):
    """'SB 632' / 'SB-632' / 'ABX1 2' -> 'sb632' / 'abx12' (cross-check key form)."""
    return re.sub(r"[^a-z0-9]", "", (measure or "").lower())


def announced_measures(path):
    """{normalized measure: action} for every signing/veto the Governor posted.

    Read from data/gov_actions.json, which the refresh job has on disk from the
    previous run.  It is a second, independent statement that a bill reached the
    desk, so a bill this snapshot has *already* lost can still be recovered.
    """
    try:
        with open(path, encoding="utf-8") as f:
            actions = json.load(f).get("actions", {})
    except (OSError, ValueError, TypeError):
        return {}
    out = {}
    for key, action in actions.items():
        if not isinstance(action, dict) or action.get("action") not in FINAL_KINDS:
            continue
        measure = norm_measure_label(action.get("measure") or "") or key
        out[norm_measure_label(measure)] = action["action"]
    return out


def offlisted_desk_bills(bills, previous, announced=None):
    """Search rows that dropped off the desk list but that we still track.

    A row qualifies when its bill_id was signed / vetoed / pending in the last
    snapshot, or the Governor's office announced an action for that measure.
    Every other row the classifier ignores is simply a bill that is not at the
    Governor's desk.
    """
    prior_ids = {
        str(bill_id)
        for bill_id, record in previous.items()
        if isinstance(record, dict) and record.get("status") in TRACKED_KINDS
    }
    announced = announced or {}
    return [
        bill for bill in bills
        if classify(bill["status"]) is None
        and (
            str(bill["bill_id"]) in prior_ids
            or norm_measure_label(bill.get("measure", "")) in announced
        )
    ]


def confirm_offlisted_kind(bill, previous_kind):
    """Recover the status of a bill whose LegInfo search row moved on.

    Returns ``(kind, note)``.  ``kind`` is "signed"/"vetoed" when LegInfo's own
    record still shows the Governor's action, None when it shows none (the bill
    really came back off the desk), and ``previous_kind`` when LegInfo could
    not be read — a failed request is not evidence that the veto did not
    happen, so the last known terminal status is kept and the reason reported.
    """
    bill_id = str(bill["bill_id"])
    try:
        summary, history = parse_status_page(fetch_status_page(bill_id))
    except Exception as exc:  # noqa: BLE001 - fall back to the saved record
        return (
            previous_kind if previous_kind in FINAL_KINDS else None,
            f"status page unreadable ({str(exc)[:90]}); kept {previous_kind}",
        )

    kind = kind_from_leginfo_record(summary, history)
    if kind is not None:
        return kind, None

    # The "last 5" window can miss an older Governor action; read the full
    # action history before giving up on the bill.
    try:
        kind = kind_from_leginfo_record({}, parse_history_rows(fetch_history_page(bill_id)))
    except Exception as exc:  # noqa: BLE001 - fall back to the saved record
        return (
            previous_kind if previous_kind in FINAL_KINDS else None,
            f"history page unreadable ({str(exc)[:90]}); kept {previous_kind}",
        )
    return kind, None


# --------------------------------------------------------------------------
# Incremental cache helpers
# --------------------------------------------------------------------------
def normalize_measure(measure):
    measure = measure or ""
    return measure.replace("-", " ") if re.fullmatch(r"[A-Za-z]+-\d+", measure) else measure


def search_fingerprint(bill):
    """Fields in the LegInfo search result that identify a bill's current row."""
    return json.dumps(
        {
            "bill_id": bill.get("bill_id"),
            "measure": normalize_measure(bill.get("measure")),
            "title": bill.get("title"),
            "author": bill.get("author"),
            "status": bill.get("status"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def can_reuse_final(bill, cached, fallback_record=None):
    """Only reuse terminal records with a matching row and full digest cache.

    The record itself lives in the last ``bills.json`` (``fallback_record``)
    in cache format v2; v1 caches embedded a copy, which is still accepted.
    """
    return (
        classify(bill.get("status")) in FINAL_KINDS
        and cached.get("fingerprint") == search_fingerprint(bill)
        and bool(cached.get("digest_text"))
        and isinstance(cached.get("record") or fallback_record, dict)
    )


CACHE_VERSION = 2
LEGINFO_STATUS_BY_KIND = {
    "signed": LEGINFO_SIGNED_STATUS,
    "vetoed": LEGINFO_VETOED_STATUS,
    "pending": LEGINFO_PENDING_STATUS,
}


def load_cache(path):
    """Load the incremental cache, migrating v1 entries to the v2 shape.

    v1 embedded a full copy of each output record next to its digest, which
    duplicated most of bills.json and bloated every daily commit.  v2 keeps
    only the fingerprint and digest; the record is recovered from the last
    bills.json by the caller.  v1 fingerprints were computed with a broken
    measure normalization, so they are re-derived from the stored record.
    """
    try:
        with open(path, encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
    except (OSError, ValueError, TypeError):
        return {}, None
    if not isinstance(payload, dict):
        return {}, None
    entries = payload.get("bills", {}) or {}
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        record = entry.get("record")
        if isinstance(record, dict):
            kind = record.get("status")
            if payload.get("version") != CACHE_VERSION and kind in LEGINFO_STATUS_BY_KIND:
                entry["fingerprint"] = search_fingerprint({
                    "bill_id": record.get("bill_id"),
                    "measure": normalize_measure(record.get("measure") or ""),
                    "title": record.get("title") or "",
                    "author": record.get("author") or "",
                    "status": LEGINFO_STATUS_BY_KIND[kind],
                })
            entry.pop("record", None)
    return entries, payload.get("session")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
SESSION = "20252026"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="20252026")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="cap status-page fetches (testing)")
    ap.add_argument(
        "--refresh-all",
        action="store_true",
        help="ignore the incremental cache and refetch every tracked bill",
    )
    ap.add_argument(
        "--ai-source",
        default="",
        help="write a transient full-digest cache for optional Gemini enrichment",
    )
    ap.add_argument(
        "--cache",
        default="data/leginfo_cache.json",
        help="persist fetched final-bill records and full digests for incremental refreshes",
    )
    ap.add_argument(
        "--gov",
        default="data/gov_actions.json",
        help="Governor's-office actions from the previous run; measures listed "
             "here are re-read from LegInfo even when the search row dropped them",
    )
    ap.add_argument("--out", default="data/bills.json")
    args = ap.parse_args()

    global SESSION
    SESSION = args.session

    # Preserve accepted offline/AI summaries across refreshes. The source hash
    # below prevents an old explanation from surviving an amended digest.
    previous = {}
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as previous_file:
                previous_payload = json.load(previous_file)
            previous = {
                str(item.get("bill_id")): item
                for item in previous_payload.get("bills", [])
                if item.get("bill_id")
            }
        except (OSError, ValueError, TypeError):
            previous = {}

    cache_bills, cache_session = (
        load_cache(args.cache) if os.path.exists(args.cache) else ({}, None)
    )
    if cache_session and cache_session != SESSION:
        log(f"  note: cache is from session {cache_session}; its records will "
            "not match this session's rows and will be refetched")

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

    # A LegInfo search row can drop a bill whose Governor action this tracker
    # already recorded (a veto returned to its house for consideration, see
    # section 2b).  Re-read those bills' own LegInfo records so the bill stays
    # in the snapshot instead of silently vanishing from the site.  The
    # Governor's announcements select which bills to re-check; LegInfo's record
    # always decides the status, so the two sources stay independent.
    recovered = {}
    offlisted = offlisted_desk_bills(bills, previous, announced_measures(args.gov))
    if offlisted:
        log(f"  {len(offlisted)} bills LegInfo no longer labels as being at the "
            "Governor's desk — rechecking their own LegInfo records …")
        with ThreadPoolExecutor(
            max_workers=min(max(args.workers, 1), len(offlisted))
        ) as ex:
            checks = list(ex.map(lambda bill: confirm_offlisted_kind(
                bill, (previous.get(str(bill["bill_id"])) or {}).get("status")
            ), offlisted))
        for bill, (kind, note) in zip(offlisted, checks):
            if note:
                log(f"  note: {normalize_measure(bill['measure'])}: {note}")
            if kind in TRACKED_KINDS:
                recovered[str(bill["bill_id"])] = kind
        log(f"  {len(recovered)} of them still show a Governor action on LegInfo "
            "and are kept")

    targets = []
    reused = {}
    for bill in bills:
        kind = classify(bill["status"])
        if kind is None:
            kind = recovered.get(str(bill["bill_id"]))
            if kind is None:
                continue
            # Fetch as if the row still read the official status label; the
            # cache keeps the *real* row so the next run rechecks it.
            bill = {**bill, "status": LEGINFO_STATUS_BY_KIND[kind]}
        bid = str(bill["bill_id"])
        cached = cache_bills.get(bid, {})
        # v2 caches no record copy; the last bills.json is the store of
        # record content.  v1 entries may still carry their embedded copy.
        cached_record = cached.get("record") or previous.get(bid)
        # A signed or vetoed bill is terminal for this tracker. Once its search
        # row and full digest are cached, reusing it cannot hide a pending-to-
        # final transition (pending bills are always fetched below).
        if not args.refresh_all and can_reuse_final(bill, cached, previous.get(bid)):
            record = dict(cached_record)
            record.update({
                "bill_id": bid,
                "measure": normalize_measure(bill["measure"]),
                "title": bill["title"],
                "author": bill["author"],
                "status": kind,
                "status_label": STATUS_LABELS[kind],
                "official_digest_excerpt": truncate(cached["digest_text"], 1400),
            })
            reused[bid] = record
        else:
            targets.append(bill)

    governor_count = sum(
        1 for bill in bills
        if classify(bill["status"]) is not None or str(bill["bill_id"]) in recovered
    )
    log(f"  {governor_count} bills reached the Governor "
        f"(signed / vetoed / enrolled); reusing {len(reused)} unchanged final records "
        f"and fetching {len(targets)} bills …")

    if args.limit:
        targets = targets[: args.limit]
        log(f"  (limited to {args.limit} for testing; cached final records remain available)")

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
        digest_text = r.get("digest_text") or ""
        digest_hash = (
            hashlib.sha256(
                re.sub(r"\s+", " ", digest_text).strip().encode("utf-8")
            ).hexdigest()
            if digest_text else None
        )
        explanation = summarize_bill(r["title"], digest_text or r.get("summary"))
        old = previous.get(str(bid), {})
        old_digest_is_current = bool(
            digest_hash and old.get("plain_summary_source_hash") == digest_hash
        )
        # Keep a previously accepted Gemini explanation only when it was based
        # on exactly this digest. The optional batch step can then process only
        # new, changed, or still-unenriched bills.
        old_is_current_ai = (
            old_digest_is_current
            and str(old.get("plain_summary_method", "")).startswith("gemini-")
        )
        out_bills.append({
            "bill_id": bid,
            "measure": measure,
            "title": r["title"],
            "author": r["author"],
            "status": classify(r["status"]),
            "status_label": STATUS_LABELS[classify(r["status"])],
            "action_date": r.get("action_date"),
            "action": r.get("action"),
            "summary": r.get("summary"),
            "official_digest_excerpt": truncate(digest_text, 1400) if digest_text else None,
            "plain_summary": old.get("plain_summary") if old_is_current_ai else explanation["text"],
            "plain_summary_confidence": old.get("plain_summary_confidence") if old_is_current_ai else explanation["confidence"],
            "plain_summary_flags": old.get("plain_summary_flags") if old_is_current_ai else explanation["flags"],
            "plain_summary_method": old.get("plain_summary_method") if old_is_current_ai else explanation["method"],
            "plain_summary_model": old.get("plain_summary_model") if old_is_current_ai else None,
            "plain_summary_source_hash": digest_hash,
            "plain_summary_evidence": old.get("plain_summary_evidence") if old_is_current_ai else None,
            "plain_summary_generated_at": old.get("plain_summary_generated_at") if old_is_current_ai else None,
            "plain_summary_enrichment_hash": old.get("plain_summary_enrichment_hash") if old_digest_is_current else None,
            "plain_summary_enrichment_status": old.get("plain_summary_enrichment_status") if old_digest_is_current else None,
            "plain_summary_enrichment_attempts": old.get("plain_summary_enrichment_attempts") if old_digest_is_current else None,
            "plain_summary_enrichment_version": old.get("plain_summary_enrichment_version") if old_digest_is_current else None,
            "latest_vote": r.get("latest_vote"),
            "dd_url": f"{DD_BASE}/{slug(bid)}",
            "leginfo_url": f"{BASE}{NAV_PATH}?bill_id={bid}",
        })

    # Cached final records were not in the thread-pool result list, but they
    # remain part of the complete static snapshot.
    out_bills.extend(reused.values())
    out_bills.sort(key=lambda bill: (bill.get("action_date") or "", bill.get("measure", "")), reverse=True)

    counts = {}
    for b in out_bills:
        counts[b["status"]] = counts.get(b["status"], 0) + 1

    # A signed or vetoed bill must never vanish quietly: LegInfo re-labels its
    # search row after a late-session veto, a page fetch can fail, or the bill
    # can be pulled back off the desk.  Whatever the reason, say so loudly —
    # the cross-check step turns it red, this makes it diagnosable in the log.
    kept_final = {str(b["bill_id"]) for b in out_bills if b["status"] in FINAL_KINDS}
    lost_final = sorted(
        (record.get("measure") or bill_id)
        for bill_id, record in previous.items()
        if isinstance(record, dict)
        and record.get("status") in FINAL_KINDS
        and bill_id not in kept_final
    )
    if lost_final:
        log(f"  WARNING: {len(lost_final)} previously signed/vetoed bills are "
            f"missing from this snapshot: {', '.join(lost_final[:12])}"
            f"{' …' if len(lost_final) > 12 else ''}")

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": SESSION,
        "session_label": f"{SESSION[:4]}–{SESSION[4:]}",
        "governor": "Gavin Newsom",
        "counts": counts,
        "bills": out_bills,
    }
    enrich_payload(payload)

    # Persist the complete digest outside the public payload so a later run can
    # reuse final bills and still provide full source context to the optional
    # Gemini step without querying LegInfo again.
    out_by_id = {str(bill.get("bill_id")): bill for bill in out_bills}
    fetched_by_id = {str(record.get("bill_id")): record for record in records}
    cache_entries = {}
    for bill in bills:
        bid = str(bill["bill_id"])
        if bid not in out_by_id:
            continue
        if bid in fetched_by_id:
            digest_text = fetched_by_id[bid].get("digest_text") or ""
        else:
            digest_text = cache_bills.get(bid, {}).get("digest_text") or ""
        # v2: no record copy — bills.json already stores the complete record,
        # so keeping a duplicate here only doubled the committed cache size.
        cache_entries[bid] = {
            "fingerprint": search_fingerprint(bill),
            "digest_text": digest_text,
        }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    os.makedirs(os.path.dirname(args.cache) or ".", exist_ok=True)
    with open(args.cache, "w", encoding="utf-8") as f:
        json.dump(
            {"version": CACHE_VERSION, "session": SESSION, "bills": cache_entries},
            f, ensure_ascii=False, separators=(",", ":")
        )
    log(f"  wrote LegInfo cache for {len(cache_entries)} bills")

    if args.ai_source:
        # This file contains full official digests only for the duration of the
        # refresh job. It is ignored and is never embedded in index.html.
        os.makedirs(os.path.dirname(args.ai_source) or ".", exist_ok=True)
        ai_sources = []
        for bid, cached in cache_entries.items():
            digest_text = cached.get("digest_text") or ""
            if not digest_text:
                continue
            record = out_by_id[bid]
            ai_sources.append({
                "bill_id": bid,
                "measure": record.get("measure", ""),
                "title": record.get("title", ""),
                "digest_text": digest_text,
                "source_hash": hashlib.sha256(
                    re.sub(r"\s+", " ", digest_text).strip().encode("utf-8")
                ).hexdigest(),
            })
        with open(args.ai_source, "w", encoding="utf-8") as f:
            json.dump(
                {"generated_at": payload["generated_at"], "bills": ai_sources},
                f, ensure_ascii=False, separators=(",", ":")
            )
        log(f"  wrote transient AI source cache for {len(ai_sources)} bills")

    log(f"DONE — wrote {len(out_bills)} bills to {args.out}")
    log(f"  signed={counts.get('signed', 0)} vetoed={counts.get('vetoed', 0)} "
        f"pending={counts.get('pending', 0)}")


if __name__ == "__main__":
    main()
