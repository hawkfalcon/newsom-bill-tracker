"""Tests for the plain-English veto reason layer (scripts/veto_messages.py)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from veto_messages import (  # noqa: E402
    EXTRACTED,
    REVIEWED,
    attach_veto_reasons,
    extract_reason,
    fill_missing,
    norm_measure,
)

MESSAGE = """OFFICE OF THE GOVERNOR

SEP 30 2026

To the Members of the California State Senate:

I am returning Senate Bill 1130 without my signature.

This bill would make it a misdemeanor to operate a wearable recording device
to capture sound or video of any other person in a place of business.

Wearable technology is rapidly advancing. These devices can record audio and
video and livestream to an audience.

While I support the author's attempt to meet that demand, this measure defines
several terms too broadly or imprecisely.

For these reasons, I cannot sign this bill.

Sincerely,

Gavin Newsom

GOVERNOR GAVIN NEWSOM - SACRAMENTO, CA 95814 - (916) 445-2841
"""


class ExtractReasonTests(unittest.TestCase):
    def test_drops_letter_furniture_and_bill_description(self):
        reason, quote = extract_reason(MESSAGE)
        self.assertIsNotNone(reason)
        for boilerplate in (
            "OFFICE OF THE GOVERNOR", "SEP 30 2026", "To the Members",
            "without my signature", "Sincerely", "Gavin Newsom", "SACRAMENTO",
        ):
            self.assertNotIn(boilerplate, reason)
        # The "This bill would ..." description is not the reason.
        self.assertFalse(reason.startswith("This bill would"))
        # The actual reasoning survives, and the quote is its first sentence.
        self.assertIn("defines\nseveral terms", MESSAGE)  # source is wrapped
        self.assertIn("too broadly or imprecisely", reason)
        self.assertTrue(reason.startswith(quote))

    def test_drops_closing_formula(self):
        reason, _ = extract_reason(MESSAGE)
        self.assertNotIn("For these reasons", reason)
        self.assertNotIn("I cannot sign this bill", reason)

    def test_markdown_headers_are_ignored(self):
        reason, _ = extract_reason(
            "# OFFICE OF THE GOVERNOR\n## OCT 3 2025\n"
            "To the Members of the California State Senate:\n"
            "I am returning Senate Bill 224 without my signature.\n"
            "This bill would require new forecasting models.\n"
            "DWR has already implemented the recommendations.\n"
            "For this reason, I cannot sign this bill.\nSincerely,\nGavin Newsom"
        )
        self.assertEqual(reason, "DWR has already implemented the recommendations.")

    def test_joint_veto_message_keeps_the_reasoning(self):
        reason, _ = extract_reason(
            "OFFICE OF THE GOVERNOR\nOCT 13 2025\n"
            "To the Members of the California State Senate:\n"
            "I am returning Senate Bills 877 and 878 without my signature.\n"
            "These two bills codify existing technical regulations.\n"
            "These bills, however, seek to codify unrelated existing regulations.\n"
            "For this reason, I am unable to sign these bills.\nSincerely,\nGavin Newsom"
        )
        self.assertIn("unrelated existing regulations", reason)
        self.assertNotIn("unable to sign", reason)

    def test_empty_text_returns_none(self):
        self.assertEqual(extract_reason(""), (None, None))
        self.assertEqual(
            extract_reason("OFFICE OF THE GOVERNOR\nSincerely,\nGavin Newsom"),
            (None, None),
        )


class AttachTests(unittest.TestCase):
    def _bills(self):
        return [
            {"measure": "AB 44", "status": "vetoed"},
            {"measure": "SB 996", "status": "signed"},
            {"measure": "AB 1387", "status": "vetoed"},
        ]

    def test_reviewed_reasons_win_and_signed_bills_get_none(self):
        messages = {
            "ab44": {"reason": "Costs outside the budget.", "quote": "q",
                     "method": REVIEWED},
            "ab1387": {"reason": "Auto text.", "quote": "aq",
                       "method": EXTRACTED},
        }
        counts = attach_veto_reasons(self._bills(), messages)
        bills = self._bills()
        attach_veto_reasons(bills, messages)
        self.assertEqual(bills[0]["veto_reason"], "Costs outside the budget.")
        self.assertEqual(bills[0]["veto_reason_method"], REVIEWED)
        self.assertIsNone(bills[1]["veto_reason"])
        self.assertEqual(bills[2]["veto_reason_method"], EXTRACTED)
        self.assertEqual(counts[REVIEWED], 1)
        self.assertEqual(counts[EXTRACTED], 1)
        self.assertEqual(counts["missing"], 0)
        self.assertEqual(counts["not_vetoed"], 1)

    def test_missing_message_is_left_empty_not_invented(self):
        bills = self._bills()
        counts = attach_veto_reasons(bills, {"ab44": {"reason": "x"}})
        self.assertIsNone(bills[2]["veto_reason"])
        self.assertEqual(counts["missing"], 1)

    def test_measure_keys_are_normalised(self):
        self.assertEqual(norm_measure("AB 1116-1"), "ab11161")
        self.assertEqual(norm_measure("SBX1 2"), "sbx12")
        bills = [{"measure": "AB 1116", "status": "vetoed"}]
        attach_veto_reasons(bills, {"ab1116": {"reason": "matched"}})
        self.assertEqual(bills[0]["veto_reason"], "matched")


class FillMissingTests(unittest.TestCase):
    def test_only_vetoed_bills_without_a_reason_are_listed(self):
        gov = {
            "actions": {
                "ab44": {"measure": "AB 44", "action": "vetoed",
                         "msg_url": "http://example.invalid/AB-44.pdf"},
                "ab45": {"measure": "AB 45", "action": "vetoed",
                         "msg_url": "http://example.invalid/AB-45.pdf"},
                "sb1": {"measure": "SB 1", "action": "signed",
                        "msg_url": "http://example.invalid/SB-1.pdf"},
                "ab46": {"measure": "AB 46", "action": "vetoed",
                         "msg_url": None},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gov.json")
            with open(path, "w", encoding="utf-8") as f:
                import json
                json.dump(gov, f)
            doc = {"messages": {"AB 44": {"reason": "already reviewed"}}}
            todo, failed = fill_missing(path, doc, fetch=False)
            self.assertEqual(todo, ["AB 45"])  # signed + no-URL bills skipped
            self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
