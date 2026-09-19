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

    # ---- Shapes the original matcher missed (found in real digests) ----

    def test_adverb_between_would_and_verb(self):
        result = summarize_bill(
            "Transit-oriented development: exclusions.",
            "Existing law specifies exclusions. "
            "This bill would also exclude a contributing site within a historic "
            "district from the provisions described above.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(result["text"].startswith("Excludes a contributing site"))

    def test_adverbs_further_additionally_instead(self):
        for adverb, verb in (
            ("further", "update"),
            ("additionally", "require"),
            ("instead", "require"),
        ):
            result = summarize_bill(
                "Test bill.",
                f"This bill would {adverb} {verb} the applicable provisions "
                "as provided.",
            )
            self.assertEqual(result["confidence"], "high", f"adverb: {adverb}")
            self.assertNotIn("no_change_sentence", result["flags"])

    def test_parenthetical_between_would_and_verb(self):
        result = summarize_bill(
            "Active Transportation Program: guidelines.",
            "This bill would, on and after January 1, 2028, instead require the "
            "guidelines with regard to project eligibility to include specified "
            "criteria.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(result["text"].startswith("Requires the guidelines"))

    def test_parenthetical_with_inner_comma(self):
        result = summarize_bill(
            "Multifamily Housing Program: Homekey.",
            "This bill would, for Homekey awards made on or after July 1, 2026, "
            "require the department to consider allowing the local agency to use "
            "the funds.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(result["text"].startswith("Requires the department"))

    def test_newer_operative_verbs(self):
        for verb in ("lower", "incorporate", "define", "codify"):
            result = summarize_bill(
                "Test bill.",
                f"This bill would {verb} the threshold specified in existing law.",
            )
            self.assertEqual(result["confidence"], "high", f"verb: {verb}")

    def test_existing_law_would_parenthetical_is_not_a_change(self):
        # "Existing law would, on or after ..., require ..." describes the
        # current law; the matcher may select the sentence, but the rewriter
        # must not turn it into a claimed change.
        result = summarize_bill(
            "Reporting.",
            "Existing law would, on or after January 1, 2027, require reports "
            "from agencies.",
        )
        self.assertEqual(result["confidence"], "low")
        self.assertIn("no_change_sentence", result["flags"])


if __name__ == "__main__":
    unittest.main()
