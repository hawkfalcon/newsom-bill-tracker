#!/usr/bin/env python3
"""
Plain-English veto reasons for every vetoed bill.

Every veto the Governor issues comes with a signed veto message (a PDF on
gov.ca.gov, linked from data/gov_actions.json as `msg_url`). This module turns
those messages into a short plain-English explanation of *why* the bill was
vetoed, which the site shows on each vetoed card.

Two layers, in priority order:

1. **Reviewed reasons** (`data/veto_messages.json`, method `reviewed-v1`).
   Written by reading the Governor's message; each entry keeps a verbatim
   `quote` so the summary can be checked against the source. This file is
   committed and is the authoritative layer.

2. **Automatic extraction** (method `extract-v1`). For any vetoed bill that
   has no reviewed reason yet, `--fetch` downloads the veto message and
   distills the Governor's own reasoning paragraphs, dropping the letter's
   boilerplate. This keeps coverage complete between refreshes: a new veto
   always gets *some* plain-English reason on the next run, and a reviewer can
   replace it with a curated entry at any time.

Usage:
    python scripts/veto_messages.py --gov data/gov_actions.json \
        --out data/veto_messages.json --fetch        # fill gaps automatically
    python scripts/veto_messages.py --gov data/gov_actions.json \
        --out data/veto_messages.json --report       # just list what is missing
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

REVIEWED = "reviewed-v1"
EXTRACTED = "extract-v1"

# Letter furniture that carries no policy content.
_BOILERPLATE_PATTERNS = (
    r"^office of the governor$",
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\s*,?\s*\d{4}$",
    r"^to the members of the california state (assembly|senate)[:.]?$",
    r"^dear members of the california state (assembly|senate)[:.]?$",
    r"^i am returning .*without my signature\.?$",
    r"^i am returning (senate|assembly) bills? .*$",
    r"^(sincerely|singerely|sincrely)[,.]?$",
    r"^gavin news?om$",
    r"^governor gavin newsom\b",
    r"^-+$",
    r"^\s*$",
)
_BOILERPLATE = [re.compile(p, re.I) for p in _BOILERPLATE_PATTERNS]

# The closing formula and the signature are never part of the reason.
_CLOSING = re.compile(
    r"^for (these|this|that) reasons?,? i (cannot|can not|am unable( to)?|"
    r"am returning|will not)",
    re.I,
)

# A first paragraph of this shape describes the bill rather than the veto.
_DESCRIPTION = re.compile(
    r"^(this (bill|measure|act)|these (bills|measures|two bills)|"
    r"(ab|sb|acrx?|sjsx?|ajrx?)\s*\d)",
    re.I,
)

MAX_REASON_CHARS = 700


def norm_measure(measure):
    """`AB 1234` -> `ab1234` so measures match across data files."""
    return re.sub(r"[^a-z0-9]", "", (measure or "").lower())


def _split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _clean_pdf_text(raw):
    """Normalise PDF-extracted text: fix line wrapping and stray page marks."""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)  # markdown headers from parsers
    text = re.sub(r"[ \t]+", " ", text)
    # Rejoin lines that were hard-wrapped mid-sentence.
    text = re.sub(r"([a-z,;”\)\]])\n([a-z“\(])", r"\1 \2", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def _paragraphs(text):
    """Group the letter's lines into paragraphs, dropping boilerplate lines.

    PDF text arrives one visual line at a time, so boilerplate has to be
    removed line by line; a boilerplate line (the office header, the date, the
    salutation, the signature block) also ends the paragraph around it.
    """
    out, cur = [], []
    for raw in _clean_pdf_text(text).split("\n"):
        line = raw.strip()
        if not line or any(p.match(line) for p in _BOILERPLATE):
            if cur:
                out.append(" ".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        out.append(" ".join(cur))
    return [p for p in out if p]


def extract_reason(text):
    """
    Distil a veto message into the Governor's stated reasoning.

    Returns ``(reason, quote)`` — ``reason`` is the Governor's own words,
    trimmed to whole sentences, with the letter's furniture, the bill
    description, and the closing formula removed; ``quote`` is the single
    sentence the reason opens with. Returns ``(None, None)`` when nothing
    usable is left.
    """
    sentences = []
    for para in _paragraphs(text):
        sentences.extend(_split_sentences(para))

    def select(drop_descriptions):
        """Keep everything but the closing formula (and optionally the lead)."""
        out, saw_reasoning = [], False
        for sentence in sentences:
            if _CLOSING.match(sentence):
                continue
            # Drop only the *leading* "This bill would ..." description; later
            # sentences that mention the bill are part of the argument.
            if drop_descriptions and not saw_reasoning \
                    and _DESCRIPTION.match(sentence):
                continue
            saw_reasoning = True
            out.append(sentence)
        return out

    kept = select(drop_descriptions=True)
    if not kept:
        # A joint or very short message may describe the bill in every
        # sentence; keep those rather than returning nothing at all.
        kept = select(drop_descriptions=False)

    reason, quote = "", None
    for sentence in kept:
        candidate = (reason + " " + sentence).strip()
        if len(candidate) > MAX_REASON_CHARS and reason:
            break
        if quote is None:
            quote = sentence
        reason = candidate
    reason = reason.strip()
    if not reason:
        return None, None
    return reason, quote


def load_messages(path):
    if not path or not os.path.exists(path):
        return {"messages": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def attach_veto_reasons(bills, messages):
    """
    Add `veto_reason` (and provenance) to every vetoed bill in place.

    Reviewed entries win over extracted ones. Bills whose veto message has not
    been reviewed or extracted yet get ``veto_reason = None``; the site then
    falls back to the veto-letter link rather than inventing a reason.
    Returns a dict of counts for logging.
    """
    by_measure = {norm_measure(k): v for k, v in (messages or {}).items()}
    counts = {REVIEWED: 0, EXTRACTED: 0, "missing": 0, "not_vetoed": 0}
    for b in bills:
        if b.get("status") != "vetoed":
            counts["not_vetoed"] += 1
            b["veto_reason"] = None
            b["veto_reason_quote"] = None
            b["veto_reason_method"] = None
            continue
        entry = by_measure.get(norm_measure(b.get("measure", "")))
        reason = (entry or {}).get("reason")
        if reason:
            b["veto_reason"] = reason
            b["veto_reason_quote"] = (entry or {}).get("quote")
            b["veto_reason_method"] = (entry or {}).get("method") or REVIEWED
            counts[b["veto_reason_method"]] = counts.get(
                b["veto_reason_method"], 0) + 1
        else:
            b["veto_reason"] = None
            b["veto_reason_quote"] = None
            b["veto_reason_method"] = None
            counts["missing"] += 1
    return counts


# ---------------------------------------------------------------- fetching --

def _pdf_text(data):
    """Extract text from veto-message PDF bytes (pypdf, installed on demand)."""
    import io

    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency guard
        from PyPDF2 import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def fetch_message_text(url, timeout=30):
    import requests

    resp = requests.get(url, timeout=timeout, headers={
        "User-Agent": "newsom-bill-tracker (veto message reader)"})
    resp.raise_for_status()
    return _pdf_text(resp.content)


def fill_missing(gov_path, doc, fetch=True, limit=None, sleep=0.4):
    """
    Add automatically extracted reasons for vetoed bills with no reviewed one.

    Returns ``(added, failed)`` lists of measures.
    """
    with open(gov_path, encoding="utf-8") as f:
        actions = json.load(f).get("actions", {})
    known = {norm_measure(k) for k, v in doc.get("messages", {}).items()
             if v.get("reason")}
    todo = []
    for key, a in sorted(actions.items()):
        if a.get("action") != "vetoed" or norm_measure(a.get("measure", key)) in known:
            continue
        if a.get("msg_url"):
            todo.append((a["measure"], a["msg_url"]))
    if limit:
        todo = todo[:limit]

    added, failed = [], []
    if not fetch:
        return [m for m, _ in todo], failed

    import time

    for measure, url in todo:
        try:
            reason, quote = extract_reason(fetch_message_text(url))
        except Exception as exc:  # noqa: BLE001 - keep refreshing other bills
            print(f"  ! {measure}: {exc}", file=sys.stderr)
            failed.append(measure)
            continue
        if not reason:
            failed.append(measure)
            continue
        doc["messages"][measure] = {
            "reason": reason,
            "quote": quote,
            "method": EXTRACTED,
            "url": url,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        added.append(measure)
        time.sleep(sleep)
    return added, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gov", default="data/gov_actions.json")
    ap.add_argument("--out", "--veto", dest="out",
                    default="data/veto_messages.json")
    ap.add_argument("--fetch", action="store_true",
                    help="download veto messages and auto-extract missing reasons")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--report", action="store_true",
                    help="list vetoed bills that still lack a reason")
    args = ap.parse_args()

    doc = load_messages(args.out)
    doc.setdefault("messages", {})
    doc.setdefault("source", "Governor's veto messages (gov.ca.gov PDFs)")
    doc.setdefault(
        "notes",
        "Plain-English veto reasons. 'reviewed-v1' entries were written by "
        "reading the Governor's veto message and keep a verbatim 'quote'; "
        "'extract-v1' entries are the Governor's own reasoning paragraphs, "
        "distilled automatically from the same message.")

    if args.fetch:
        added, failed = fill_missing(args.gov, doc, fetch=True, limit=args.limit)
        print(f"auto-extracted {len(added)} veto reason(s); {len(failed)} failed")
        doc["generated_at"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, ensure_ascii=False, sort_keys=True)

    if args.report or not args.fetch:
        with open(args.gov, encoding="utf-8") as f:
            actions = json.load(f).get("actions", {})
        have = {norm_measure(k) for k, v in doc["messages"].items()
                if v.get("reason")}
        missing = sorted(a["measure"] for a in actions.values()
                         if a.get("action") == "vetoed"
                         and norm_measure(a.get("measure", "")) not in have)
        reviewed = sum(1 for v in doc["messages"].values()
                       if v.get("reason") and (v.get("method") or REVIEWED) == REVIEWED)
        extracted = sum(1 for v in doc["messages"].values()
                        if v.get("method") == EXTRACTED)
        print(f"veto reasons: {reviewed} reviewed, {extracted} auto-extracted, "
              f"{len(missing)} missing")
        if missing:
            print("missing: " + ", ".join(missing))
        return 1 if missing and not args.fetch else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
