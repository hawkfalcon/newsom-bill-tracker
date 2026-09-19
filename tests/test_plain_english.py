import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from plain_english import summarize_bill


class PlainEnglishTests(unittest.TestCase):
    def test_rewrites_require_sentence(self):
        result = summarize_bill(
            "Household hazardous waste: reporting.",
            "This bill would require reports to be submitted by October 1 of the following year, as specified.",
        )
        self.assertEqual(
            result["text"],
            "Requires reports to be submitted by October 1 of the following year.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["flags"], [])

    def test_finds_change_clause_after_existing_law_background(self):
        result = summarize_bill(
            "Housing.",
            "Existing law regulates housing permits. This bill would prohibit a city from denying the permit.",
        )
        self.assertEqual(result["text"], "Prohibits a city from denying the permit.")

    def test_rewrites_multiple_operating_sentences(self):
        result = summarize_bill(
            "Housing development: transit-oriented development.",
            "This bill would require housing projects near transit stops to meet specified standards. "
            "The bill would allow transit agencies to adopt zoning standards for these projects.",
        )
        self.assertIn("Requires housing projects near transit stops", result["text"])
        self.assertIn("Allows transit agencies to adopt zoning standards", result["text"])

    def test_falls_back_honestly_when_excerpt_is_background_only(self):
        result = summarize_bill(
            "Physical Therapy Board of California.",
            "Existing law establishes the Physical Therapy Board of California within the Department of Consumer Affairs for licensing.",
        )
        self.assertEqual(result["confidence"], "low")
        self.assertIn("Updates California rules", result["text"])
        self.assertIn("no_change_sentence", result["flags"])

    def test_omnibus_fallback_does_not_claim_specific_changes(self):
        result = summarize_bill(
            "Transportation: omnibus bill.",
            "Existing law governs transportation programs. …",
        )
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(
            result["text"],
            "Makes several changes involving Transportation.",
        )
        self.assertIn("source_excerpt_truncated", result["flags"])


if __name__ == "__main__":
    unittest.main()
