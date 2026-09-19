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

Resolutions and other measures (ACR/SCR/SJR/AJR) say "This measure would ..."
instead of "This bill would ..."; both leads are matched.

Output stays skimmable: at most two operative sentences, each capped in
length (the full digest remains one click below the card), and demonstrative
back-references ("those provisions") are neutralized, since the provisions of
the existing law they point at are not in front of the reader.
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
    # Resolution-style measures (ACR/SCR/SJR/AJR) and other common leads:
    "recognize", "affirm", "acknowledge", "encourage", "urge", "commend",
    "proclaim", "call", "memorialize", "name", "recast", "excuse",
)

# Adverbs that commonly sit between "would" and the operative verb.
ADVERBS = (
    "also", "further", "additionally", "instead", "similarly",
    "explicitly", "specifically", "separately", "indefinitely",
)

_VERBS = "|".join(ACTION_WORDS)
_ADVERBS = "|".join(ADVERBS)
_PAREN = r"(?:,\s*[^.;]{0,80},\s*)?"

# Bills say "This bill would ..."; resolutions and other measures (ACR, SCR,
# SJR, AJR, ...) say "This measure would ...".  Both leads are matched.
_LEAD_SUBJECT = r"(?:this|the)\s+(?:bill|measure)"

# The lead may carry a comma parenthetical before "would" ("This bill,
# until January 1, 2037, would require ...").  When a parenthetical is
# present, "would" is mandatory: an optional "would" would let a greedy
# parenthetical swallow the real "would" and strand the verb in the gap.
# (No parenthetical: "would" stays optional for "This bill requires ..."
# shapes.)
_LEAD_AFTER_SUBJECT = (
    r"(?:,\s*[^.;]{0,80},\s*would\b\s*"
    r"|(?:would\b\s*)?)"
)

# Matches "This bill/measure would [adverb] [ , parenthetical , ] [adverb]
# <verb>", or a bare "would ..." sentence (an operative continuation of the
# previous sentence).  "would" may be followed directly by the comma of a
# parenthetical ("would, on and after ...") — keep the comma for _PAREN
# to handle.
_WOULD = r"(?:would\b\s*)?"
_ADVB = r"(?:(?:" + _ADVERBS + r")\s+)?"
_ACTION_VERB = r"(?:" + _VERBS + r")s?\b"
ACTION_RE = re.compile(
    r"\b" + _LEAD_SUBJECT + r"\s*" + _LEAD_AFTER_SUBJECT
    + _ADVB + _PAREN + _ADVB + _ACTION_VERB
    + r"|\bwould\b\s*" + _ADVB + _PAREN + _ADVB + _ACTION_VERB,
    re.I,
)

LEAD_RE = re.compile(r"^(?:" + _LEAD_SUBJECT + r")\s*" + _LEAD_AFTER_SUBJECT, re.I)
OPERATIVE_VERB_RE = re.compile(r"\b(?P<verb>" + _VERBS + r")s?\b", re.I)
WOULD_RE = re.compile(r"^would\b\s*", re.I)

# Card summaries stay skimmable: one provision sentence is capped in length,
# and at most two sentences are kept per bill.  The full official digest
# remains one click below the card, so an ellipsis here is safe.
MAX_SENTENCE_CHARS = 240
MAX_TOTAL_CHARS = 480


def _trim(text, limit):
    """Cut text to at most `limit` characters on a word boundary.

    Returns the text unchanged when it already fits; otherwise it ends with
    an ellipsis so the cut is visible.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:\u2014-\u2013") + " \u2026"


# Boilerplate that adds legal hedging without changing the reader's
# understanding.  We do not remove conditions, dates, amounts, or exceptions.
BOILERPLATE_REPLACEMENTS = (
    (r"\s*,\s*among other things,?", ""),
    # Mid-sentence hedges are dropped; sentence-final ones collapse to a period.
    (r"\s*,\s*as provided\b,?", ""),
    (r"\s*,\s*as specified\b,?", ""),
    (r"\s*,\s*as applicable\b,?", ""),
    (r"\s*as provided\b\?.", "."),
    (r"\s*as specified\b\?.", "."),
    (r"\s*as applicable\b\?.", "."),
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
    # Do not split after a single capital letter followed by a
    # period (initials, as in "President Donald J. Trump").
    parts = re.split(r"(?<=[.!?])(?<![A-Z]\.)\s+(?=(?:\(\d+\)\s*)?[A-Z])", text)
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
    lead_match = re.search(
        r"\b(?:this|the)\s+(?:bill|measure)\s*(?:,\s*[^.;]{0,80},\s*would\b|would\b)",
        original,
        flags=re.I,
    )
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

    verb = vm.group("verb").lower().removesuffix("s")
    rest = tail[vm.end():].strip(" ,")

    verb_leads = {
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
        "recognize": "Recognizes",
        "affirm": "Affirms",
        "acknowledge": "Acknowledges",
        "encourage": "Encourages",
        "urge": "Urges",
        "commend": "Commends",
        "proclaim": "Proclaims",
        "call": "Calls",
        "memorialize": "Memorializes",
        "name": "Names",
        "recast": "Recasts",
        "excuse": "Excuses",
    }
    lead = verb_leads.get(verb)

    # Compound predicates ("would recognize and affirm ...", "would require
    # X and allow Y") conjugate the joined verbs as well, or the sentence
    # reads "Recognizes and affirm ...".
    if rest:
        def _conj(m3):
            return "and " + verb_leads.get(m3.group(1).lower(), m3.group(1)).lower()

        rest = re.sub(r"\band\s+(" + _VERBS + r")\b", _conj, rest, flags=re.I)

    if not lead or not rest:
        return None

    output = f"{lead} {rest}"
    for pattern, replacement in BOILERPLATE_REPLACEMENTS:
        output = re.sub(pattern, replacement, output, flags=re.I)
    output = re.sub(r"\s+", " ", output).strip()
    # Source typos: a period after a long word followed by a lowercase word
    # is not a real sentence break in the one-line rendering ("program. to
    # promote").  Long-word filter spares short abbreviations (U.S., Inc.).
    output = re.sub(r"\b[A-Za-z]{5,}\.(?=\s+[a-z])", "", output)
    # Digests point back at provisions of the existing law ("those
    # provisions"), which the reader does not have in front of them.
    # Neutralize the demonstrative so the sentence stands on its own.
    output = re.sub(r"\bthose\b", "the", output, flags=re.I)
    output = re.sub(r"\s+", " ", output).strip()
    if len(output) > MAX_SENTENCE_CHARS:
        output = _trim(output, MAX_SENTENCE_CHARS)
    else:
        output = output.rstrip(" .,;") + "."
    if not output:
        return None
    return output[0].upper() + output[1:]


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
    # If the stored digest cuts off mid-sentence, the final "sentence" is a
    # fragment: it may look like an operative clause but has no ending, so it
    # is not a candidate.
    last_sentence_complete = bool(re.search(r"[.!?]$", digest))
    sentences = _sentences(digest)
    candidates = []
    for i, sentence in enumerate(sentences):
        if i == len(sentences) - 1 and not last_sentence_complete:
            continue
        if ACTION_RE.search(sentence):
            rewritten = _rewrite(sentence)
            if rewritten:
                candidates.append(rewritten)
        if len(candidates) >= 2:
            break

    if candidates:
        # Two operative sentences are useful; a second sentence is only
        # included when it adds a distinct provision, starts cleanly, and
        # fits the total length budget (it may be trimmed, not bloated).
        text = candidates[0]
        if len(candidates) > 1 and candidates[1].lower() != text.lower() \
                and candidates[1][0].isupper():
            budget = MAX_TOTAL_CHARS - len(text) - 1
            if budget >= 80:
                text = f"{text} {_trim(candidates[1], budget)}"
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
