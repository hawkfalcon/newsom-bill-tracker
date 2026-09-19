#!/usr/bin/env python3
"""Small, deterministic plain-English bill explainer.

This is deliberately not a pretend legal oracle.  It rewrites the change
sentences in the Legislative Counsel digest when one is available and falls
back to a clearly-labeled topic-level description when the stored excerpt only
contains background about existing law.  No network, model, or API is needed.

Legislative Counsel digests frequently put material between "would" and the
operative verb — adverbs ("would also require", "would instead require") and
comma parentheticals ("would, on and after January 1, 2028, require").  The
matchers below tolerate both so the operative clause is still found.
"""

import re

METHOD = "rules-v1"

# Operative verbs that usually introduce the change part of a digest.  The
# list is intentionally conservative: a false generic summary is worse than
# admitting that the source excerpt is incomplete.
ACTION_WORDS = (
    "require", "authorize", "prohibit", "establish", "create", "expand",
    "extend", "revise", "amend", "repeal", "delete", "eliminate", "increase",
    "decrease", "reduce", "allow", "permit", "provide", "direct", "exempt",
    "impose", "modify", "change", "specify", "clarify", "make", "remove",
    "appropriate", "fund", "designate", "rename", "declare", "transfer",
    "consolidate", "continue", "restore", "limit", "ban", "add",
    "exclude", "include", "update", "incorporate", "lower", "define",
    "codify", "state", "request",
)

# Adverbs that commonly sit between "would" and the operative verb.
ADVERBS = (
    "also", "further", "additionally", "instead", "similarly",
    "explicitly", "specifically", "separately", "indefinitely",
)

_VERBS = "|".join(ACTION_WORDS)
_ADVERBS = "|".join(ADVERBS)
_PAREN = r"(?:,\s*[^.;]{0,80}?,\s*)?"

# Matches "This bill would [adverb] [ , parenthetical , ] [adverb] <verb>".
# "would" may be followed directly by a comma ("would, on and after ...").
# "would" may be followed directly by the comma of a parenthetical
# ("would, on and after ...") — keep the comma for _PAREN to handle.
_WOULD = r"(?:would\b\s*)?"
_ADVB = r"(?:(?:" + _ADVERBS + r")\s+)?"
_ACTION_VERB = r"(?:" + _VERBS + r")\b"
ACTION_RE = re.compile(
    (r"\b(?:this|the)\s+bill\s+" + _WOULD + _ADVB + _PAREN + _ADVB + _ACTION_VERB)
    + ("|\\bwould\\b\\s*" + _ADVB + _PAREN + _ADVB + _ACTION_VERB),
    re.I,
)

OPERATIVE_VERB_RE = re.compile(r"\b(?P<verb>" + _VERBS + r")\b", re.I)
LEAD_RE = re.compile(r"^(?:this|the)\s+bill\s+" + _WOULD, re.I)
WOULD_RE = re.compile(r"^would\b\s*", re.I)

# Boilerplate that adds legal hedging without changing the reader's
# understanding.  We do not remove conditions, dates, amounts, or exceptions.
BOILERPLATE_REPLACEMENTS = (
    (r"\s*,?\s*among other things,?", ""),
    (r"\s*,?\s*as provided\.?", "."),
    (r"\s*,?\s*as specified\.?", "."),
    (r"\s*,?\s*as applicable\.?", "."),
    (r"including,\s+but not limited to,", "including"),
    (r"\bOn or before\b", "By"),
    (r"\bcommencing\b", "starting"),
)


def _clean(value):
    value = value or ""
    value = value.replace("\u2026", " ")
    value = re.sub(r"\s+", " ", value).strip()
    # The extractor may leave numbered digest paragraphs at the front.
    value = re.sub(r"^(?:\(\d+\)|\d+\.)\s*", "", value)
    return value


def _sentences(text):
    """Split digest prose without requiring a heavyweight NLP dependency."""
    text = _clean(text)
    if not text:
        return []
    # Digest paragraphs are generally sentence-oriented.  Keep abbreviations
    # such as "U.S." together well enough for the short snippets we use.
    parts = re.split(r"(?<=[.!?])\s+(?=(?:\(\d+\)\s*)?[A-Z])", text)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def _gap_ok(gap):
    """The gap between the lead ("This bill would") and the operative verb
    may be empty, adverbs, or one comma parenthetical (optionally followed
    by adverbs).  Anything else means this is not the operative clause."""
    if not gap:
        return True
    if re.fullmatch(r"(?:" + _ADVERBS + r")\s+", gap, flags=re.I):
        return True
    if re.fullmatch(r",\s*[^.;]{0,80}?,\s*", gap, flags=re.I):
        return True
    if re.fullmatch(r",\s*[^.;]{0,80}?,\s+(?:" + _ADVERBS + r")\s+", gap, flags=re.I):
        return True
    return False


def _rewrite(sentence):
    """Turn common Legislative Counsel constructions into a lead sentence."""
    original = _clean(sentence)
    if not original:
        return None
    # Digests often place the operative clause after a long description of
    # existing law in the same paragraph. Start at the bill's change clause so
    # the background does not prevent the simple rewrite from matching.
    lead_match = re.search(r"\b(?:this|the)\s+bill\s+would\b", original, flags=re.I)
    if lead_match:
        original = original[lead_match.start():]

    # Remove the standard lead, then locate the operative verb.  It may be
    # separated from "would" by adverbs and/or a comma parenthetical.
    m = LEAD_RE.match(original)
    if not m:
        m = WOULD_RE.match(original)
    if not m:
        return None
    tail = original[m.end():]
    vm = OPERATIVE_VERB_RE.search(tail)
    if not vm or not _gap_ok(tail[:vm.start()]):
        return None

    verb = vm.group("verb").lower()
    rest = tail[vm.end():].strip(" ,")
    lead = {
        "require": "Requires",
        "authorize": "Allows",
        "allow": "Allows",
        "permit": "Allows",
        "prohibit": "Prohibits",
        "ban": "Bans",
        "establish": "Establishes",
        "create": "Creates",
        "expand": "Expands",
        "extend": "Extends",
        "revise": "Revises",
        "amend": "Changes",
        "repeal": "Repeals",
        "delete": "Removes",
        "eliminate": "Eliminates",
        "increase": "Increases",
        "decrease": "Decreases",
        "reduce": "Reduces",
        "provide": "Provides",
        "direct": "Directs",
        "exempt": "Exempts",
        "impose": "Imposes",
        "modify": "Modifies",
        "change": "Changes",
        "specify": "Specifies",
        "clarify": "Clarifies",
        "make": "Makes",
        "remove": "Removes",
        "appropriate": "Provides funding for",
        "fund": "Funds",
        "designate": "Designates",
        "rename": "Renames",
        "declare": "Declares",
        "transfer": "Transfers",
        "consolidate": "Consolidates",
        "continue": "Continues",
        "restore": "Restores",
        "limit": "Limits",
        "add": "Adds",
        "exclude": "Excludes",
        "include": "Includes",
        "update": "Updates",
        "incorporate": "Incorporates",
        "lower": "Lowers",
        "define": "Defines",
        "codify": "Codifies",
        "state": "States",
        "request": "Requests",
    }.get(verb)
    if not lead or not rest:
        return None

    output = f"{lead} {rest}"
    for pattern, replacement in BOILERPLATE_REPLACEMENTS:
        output = re.sub(pattern, replacement, output, flags=re.I)
    output = re.sub(r"\s+", " ", output).strip(" .")
    if not output:
        return None
    return output[0].upper() + output[1:] + "."


def _subject(title):
    title = _clean(title).rstrip(".")
    if not title:
        return "the subject described in the official digest"
    title = re.sub(r"\s*:\s*", " — ", title)
    if re.search(r"\bomnibus\s+bill\b", title, flags=re.I):
        title = re.sub(r"\s*—\s*omnibus\s+bill", "", title, flags=re.I).strip(" —")
    return title


def summarize_bill(title, digest=None):
    """Return a stable explanation record for one bill.

    The returned text is intentionally modest.  It says what the source lets
    us say, rather than inventing affected groups or fiscal impacts that are
    absent from the digest excerpt.
    """
    title = _clean(title)
    raw_digest = digest or ""
    truncated = "\u2026" in raw_digest
    digest = _clean(digest)
    candidates = []
    for sentence in _sentences(digest):
        if ACTION_RE.search(sentence):
            rewritten = _rewrite(sentence)
            if rewritten:
                candidates.append(rewritten)
        if len(candidates) >= 2:
            break

    if candidates:
        # Two short operative sentences are useful; a second sentence is only
        # included when it adds a distinct provision rather than repeating the
        # same opening verb.
        text = candidates[0]
        if len(candidates) > 1 and candidates[1].lower() != text.lower():
            text = f"{text} {candidates[1]}"
        confidence = "medium" if truncated else "high"
        flags = ["source_excerpt_truncated"] if truncated else []
        return {
            "text": text,
            "confidence": confidence,
            "flags": flags,
            "method": METHOD,
        }

    subject = _subject(title)
    if re.search(r"omnibus", title, flags=re.I):
        text = f"Makes several changes involving {subject}."
    elif re.search(r"\b(?:fees?|licensing|license|regulation|reporting|standards?)\b", title, flags=re.I):
        text = f"Updates California rules for {subject}."
    else:
        text = f"Updates California rules for {subject}."
    flags = ["no_change_sentence"]
    if truncated:
        flags.append("source_excerpt_truncated")
    return {
        "text": text,
        "confidence": "low",
        "flags": flags,
        "method": METHOD,
    }


if __name__ == "__main__":
    examples = [
        ("Household hazardous waste: reporting.",
         "This bill would require reports to be submitted by October 1 of the following year, as specified."),
        ("Housing development: transit-oriented development.",
         "This bill would require housing projects near transit stops to meet specified standards and would allow transit agencies to adopt zoning standards."),
        ("Transit-oriented development: exclusions.",
         "Existing law specifies exclusions from the provisions described above. This bill would also exclude a contributing site within a historic district from the provisions described above."),
        ("Active Transportation Program.",
         "This bill would, on and after January 1, 2028, instead require the guidelines with regard to project eligibility to include specified criteria."),
    ]
    for title, digest in examples:
        print(title)
        print(summarize_bill(title, digest))
