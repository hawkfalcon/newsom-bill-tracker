#!/usr/bin/env python3
"""Cross-check the Governor's gov.ca.gov announcements against the LegInfo
bill list, and report disagreements.

The two sources are independently authoritative, so they are expected to
disagree briefly: gov.ca.gov announces an action the day it happens, while
LegInfo's search rows can lag by hours (most visible during the September
signing window).  That brief window is reported as warnings only.

When a disagreement is still present long after the announcement
(default: more than 48 hours), something is wrong (a missed parse, a LegInfo
status that never flipped, or a misclassified bill), and this script exits
non-zero so the GitHub Actions run goes red for a human to look at it.

Two disagreements showed up during the September 2026 signing window and are
fixed at the source, not here:

  * LegInfo re-labels a vetoed bill's search row once the house takes the bill
    back ("In Senate. Consideration of Governor's veto pending."), which used
    to drop the bill from bills.json — fetch_bills now re-reads such bills' own
    LegInfo records.
  * A press release that recaps earlier signing rounds lists those bills with
    the same markup as its own package, so prior-session measure numbers became
    phantom actions — fetch_gov_updates now skips recap lists.

Usage:
    python scripts/cross_check.py [--bills data/bills.json] \
        [--gov data/gov_actions.json] [--stale-hours 48]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone


def norm(m):
    return re.sub(r"[^a-z0-9]", "", (m or "").lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bills", default="data/bills.json")
    ap.add_argument("--gov", default="data/gov_actions.json")
    ap.add_argument(
        "--stale-hours", type=int, default=48,
        help="announce-age beyond which a disagreement becomes an error "
             "(the normal gov/LegInfo lag is a few hours)",
    )
    args = ap.parse_args()

    with open(args.bills, encoding="utf-8") as f:
        bills = json.load(f).get("bills", [])
    with open(args.gov, encoding="utf-8") as f:
        gov = json.load(f).get("actions", {})

    by_measure = {}
    for b in bills:
        by_measure.setdefault(norm(b.get("measure")), b)

    now = datetime.now(timezone.utc)
    warnings, errors = [], []

    for nid, act in gov.items():
        bill = by_measure.get(nid)
        label = act.get("measure") or nid

        age_hours = None
        published = act.get("published_at") or ""
        if published:
            try:
                pub = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if pub.tzinfo is None:  # WordPress GMT dates carry no offset
                    pub = pub.replace(tzinfo=timezone.utc)
                age_hours = (now - pub).total_seconds() / 3600
            except ValueError:
                age_hours = None
        stale = age_hours is not None and age_hours > args.stale_hours

        if bill is None:
            # Two very different things can cause this, and both are worth a
            # human look: LegInfo has a row for the bill but this snapshot
            # dropped it, or the measure is not part of the session at all
            # (a gov.ca.gov post that recapped an earlier session's bills).
            msg = (f"{label}: gov says {act.get('action')} {act.get('date')}, "
                   f"but the bill is absent from bills.json — check the "
                   f"'rechecking their own LegInfo records' / 'WARNING' lines "
                   f"in the fetch_bills log, then the gov.ca.gov post parse")
            (errors if stale else warnings).append(msg)
            continue

        if bill.get("status") == "pending" and act.get("action") in ("signed", "vetoed"):
            msg = (f"{bill.get('measure')}: gov says {act.get('action')} "
                   f"{act.get('date')}, but LegInfo still shows it pending")
            (errors if stale else warnings).append(msg)
        elif bill.get("status") != "pending" and bill.get("status") != act.get("action"):
            # A terminal disagreement: LegInfo says one thing, the Governor's
            # office announced another.  This is never normal lag.
            errors.append(
                f"{bill.get('measure')}: gov says {act.get('action')} "
                f"{act.get('date')}, but LegInfo says {bill.get('status')}"
            )

    print(f"Cross-check: {len(gov)} gov actions vs {len(bills)} bills")
    for w in warnings:
        print(f"  warn : {w}")
    for e in errors:
        print(f"  ERROR: {e}")
    print(f"  {len(warnings)} warning(s), {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
