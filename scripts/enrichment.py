#!/usr/bin/env python3
"""Deterministic enrichment shared by the fetcher and static-site builder.

Topics are intentionally explainable: they are inferred from each bill's
official title and Legislative Counsel digest, not from a partisan source or a
black-box model. Lead-author names and districts come from the checked-in
2025-26 Assembly and Senate roster.
"""

import json
import re
from pathlib import Path

try:
    from plain_english import summarize_bill
except ImportError:  # Allows importing this module from the repository root in tests.
    from scripts.plain_english import summarize_bill


ROOT = Path(__file__).resolve().parent.parent
LEGISLATORS_PATH = ROOT / "data" / "legislators.json"

TOPIC_ORDER = [
    "Agriculture",
    "Budget",
    "Economy",
    "Education",
    "Energy",
    "Entertainment",
    "Environment",
    "Government",
    "Health",
    "Higher Education",
    "Housing",
    "Justice",
    "Labor",
    "Politics",
    "Poverty",
    "Technology",
    "Transportation",
    "Other",
]

# A title hit is weighted more heavily than a digest hit. This keeps generic
# legal language in a digest from overwhelming the bill's actual subject.
TOPIC_RULES = {
    "Agriculture": [
        r"agricultur\w*", r"farm(?:er|worker|ing|s)?\b", r"food\b",
        r"livestock", r"crop\w*", r"pesticide", r"seed\b", r"dairy",
        r"wine\b", r"fisher(?:y|ies)", r"cannabis", r"nursery",
    ],
    "Budget": [
        r"\bbudget\w*", r"appropriat\w*", r"bond\s+act", r"\btax(?:es|ation)?\b",
        r"revenue", r"fiscal", r"funding", r"finance", r"treasury", r"debt\b",
        r"general fund", r"expenditure", r"\bfees?\b",
    ],
    "Economy": [
        r"business", r"commerce", r"corporat\w*", r"consumer", r"economic",
        r"bank(?:ing)?", r"credit", r"trade", r"commercial", r"industry",
        r"antitrust", r"price gouging", r"insurance", r"professional\s+(?:license|regulation)",
        r"licens(?:e|ing|ure)", r"franchise", r"securities",
    ],
    "Education": [
        r"\bschool\w*", r"pupil\w*", r"student\w*", r"teacher\w*",
        r"instruction", r"curriculum", r"kindergarten", r"child(?:ren)?\s+care",
        r"early learning", r"education\b", r"school district",
    ],
    "Energy": [
        r"\benerg\w*", r"electric(?:ity|al)?", r"\butility|utilities\b",
        r"solar", r"renewable", r"natural gas", r"petroleum", r"\boil\b",
        r"power grid", r"battery", r"charging station", r"hydrogen",
    ],
    "Entertainment": [
        r"film\w*", r"motion picture", r"music\w*", r"theater\w*", r"arts?\b",
        r"artist\w*", r"sport\w*", r"athletic", r"casino", r"gaming", r"amusement",
    ],
    "Environment": [
        r"environment\w*", r"climate", r"emission\w*", r"greenhouse",
        r"pollution", r"recycl\w*", r"waste\b", r"\bwater\b", r"wildfire",
        r"forest\w*", r"coastal", r"air quality", r"natural resources",
        r"drought", r"conservation", r"endangered species", r"carbon",
    ],
    "Government": [
        r"government", r"local government", r"county\b", r"city\b", r"municipal",
        r"public entit\w*", r"public agenc\w*", r"state agenc\w*", r"public records",
        r"open meetings", r"board of supervisors", r"public contract", r"county of",
        r"city of", r"department of", r"secretary of state", r"governmental",
    ],
    "Health": [
        r"\bhealth\w*", r"medical", r"medicine", r"hospital\w*", r"physician\w*",
        r"nurse\w*", r"patient\w*", r"prescription", r"pharmacy", r"mental health",
        r"disease", r"health care", r"medicaid|medi-cal", r"public health",
        r"sexual health", r"dental",
    ],
    "Higher Education": [
        r"college\w*", r"universit\w*", r"postsecondary", r"community college",
        r"california state university", r"university of california", r"student loan",
        r"higher education",
    ],
    "Housing": [
        r"housing", r"homeless\w*", r"\brent\w*", r"tenant\w*", r"landlord\w*",
        r"shelter", r"dwelling\w*", r"accessory dwelling", r"zoning", r"building standards",
        r"real estate", r"mobilehome", r"manufactured housing",
    ],
    "Justice": [
        r"\bcrime\w*", r"criminal", r"\bcourt\w*", r"judicial", r"justice",
        r"attorney", r"legal", r"law enforcement", r"inmate\w*", r"prison\w*",
        r"correction\w*", r"parole", r"sentenc\w*", r"victim\w*", r"firearm\w*",
        r"\bgun\w*", r"civil penalty", r"liability", r"sexual exploitation",
        r"child abuse", r"public safety", r"restraining order",
    ],
    "Labor": [
        r"labor", r"worker\w*", r"employment", r"employee\w*", r"employer\w*",
        r"wage\w*", r"workplace", r"retirement", r"pension", r"unemployment",
        r"apprenticeship", r"prevailing wage", r"paid leave", r"meal period",
        r"farmworker",
    ],
    "Politics": [
        r"\belection\w*", r"voting\b", r"ballot\w*", r"campaign\w*", r"redistrict\w*",
        r"political", r"officeholder", r"legislative ethics", r"conflict of interest",
    ],
    "Poverty": [
        r"poverty", r"low-income", r"public assistance", r"welfare", r"calworks",
        r"calfresh", r"food benefits", r"social services", r"human services",
        r"basic needs", r"income support",
    ],
    "Technology": [
        r"artificial intelligence", r"\bAI\b", r"chatbot\w*", r"digital",
        r"software", r"internet", r"data privacy", r"data broker", r"cyber",
        r"technology", r"platform\w*", r"social media", r"computer\w*",
        r"online service", r"electronic device",
    ],
    "Transportation": [
        r"transportation", r"transit", r"\bvehicle\w*", r"traffic", r"highway\w*",
        r"\broad\w*", r"rail(?:road)?", r"airport", r"automobile", r"\bdmv\b",
        r"driver\w*", r"bicycle\w*", r"pedestrian\w*", r"parking", r"motor\w*",
    ],
}


def _load_authors():
    try:
        with LEGISLATORS_PATH.open(encoding="utf-8") as f:
            return json.load(f).get("authors", {})
    except FileNotFoundError:
        return {}


AUTHORS = _load_authors()


def _score_topic(title, summary, patterns):
    score = 0
    for pattern in patterns:
        if re.search(pattern, title, flags=re.I):
            score += 4
        if summary and re.search(pattern, summary, flags=re.I):
            score += 1
    return score


def classify_topics(title, summary=None):
    """Return one to three broad, nonpartisan topic labels."""
    title = title or ""
    summary = summary or ""
    scored = [
        (topic, _score_topic(title, summary, patterns), index)
        for index, (topic, patterns) in enumerate(TOPIC_RULES.items())
    ]
    scored = [item for item in scored if item[1] > 0]
    if not scored:
        return ["Other"]

    scored.sort(key=lambda item: (-item[1], item[2]))
    best = scored[0][1]
    # A secondary label must have a real signal, and cannot be merely a weak
    # generic digest hit next to a strong title match.
    selected = [item[0] for item in scored if item[1] >= 2 and item[1] >= best * 0.32][:3]
    return selected or [scored[0][0]]


def enrich_bill(bill, authors=None):
    """Add stable topic, author, and plain-English fields.

    The plain-English text is intentionally generated from the official digest
    already present in the payload.  It never replaces that source text.
    """
    authors = AUTHORS if authors is None else authors
    author = bill.get("author") or ""
    info = authors.get(author)
    # Score against the longest stored digest text (the 1400-char excerpt when
    # present), not just the 280-char list summary, so topic signals later in
    # the digest are not silently ignored.
    bill["topics"] = classify_topics(
        bill.get("title"),
        bill.get("official_digest_excerpt") or bill.get("summary"),
    )
    bill["author_info"] = dict(info) if info else None

    if not bill.get("plain_summary"):
        explanation = summarize_bill(bill.get("title"), bill.get("summary"))
        bill["plain_summary"] = explanation["text"]
        bill["plain_summary_confidence"] = explanation["confidence"]
        bill["plain_summary_flags"] = explanation["flags"]
        bill["plain_summary_method"] = explanation["method"]
    else:
        bill.setdefault("plain_summary_confidence", "medium")
        bill.setdefault("plain_summary_flags", [])
        bill.setdefault("plain_summary_method", "rules-v1")
    return bill


def enrich_payload(payload):
    authors = AUTHORS
    for bill in payload.get("bills", []):
        enrich_bill(bill, authors)
    payload["topic_options"] = TOPIC_ORDER
    payload["topic_method"] = (
        "Deterministic labels inferred from the official bill title and "
        "Legislative Counsel digest; bills may have multiple labels and "
        "unmatched bills use Other."
    )
    payload["author_method"] = (
        "Lead-author labels matched to the checked-in 2025-26 California "
        "Assembly and Senate roster; committee authors remain as reported."
    )
    return payload
