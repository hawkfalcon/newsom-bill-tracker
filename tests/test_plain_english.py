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

    # ---- Resolutions and other measures ("This measure would ...") ----

    def test_measure_lead(self):
        result = summarize_bill(
            "The Huuc Atam Highway.",
            "This measure would designate a specified portion of State Route 18 "
            "in the County of San Bernardino as the Huuc Atam Highway.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(result["text"].startswith("Designates a specified portion"))

    def test_resolution_verbs(self):
        for verb, lead in (
            ("proclaim", "Proclaims"),
            ("recognize", "Recognizes"),
            ("urge", "Urges"),
            ("memorialize", "Memorializes"),
        ):
            result = summarize_bill(
                "Test measure.",
                f"This measure would {verb} the specified topic.",
            )
            self.assertEqual(result["confidence"], "high", f"verb: {verb}")
            self.assertTrue(result["text"].startswith(lead), f"verb: {verb}")

    # ---- Lead shapes from real digests ----

    def test_parenthetical_before_would(self):
        result = summarize_bill(
            "Highways: exit information.",
            "Existing law allows signs near exits. This bill, until January 1, "
            "2037, would require the department to allow the placement of "
            "information signs along a highway.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(result["text"].startswith("Requires the department"))

    def test_parenthetical_before_would_with_inner_commas(self):
        result = summarize_bill(
            "Pupil safety.",
            "Existing law requires notices. This bill, commencing with the "
            "2027\u201328 school year, would prohibit a school district, county "
            "office of education, or charter school from requiring a policy.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(result["text"].startswith("Prohibits a school district"))

    # ---- Output quality guards ----

    def test_sentence_length_cap_with_ellipsis(self):
        digest = (
            "This bill would require the department to publish a detailed "
            "report that includes the full financial statements, the names of "
            "each board member, the complete audit findings, and every "
            "contract awarded during the fiscal year, along with the "
            "justification for each expenditure, itemized by program, by "
            "region, and by funding source, as the department determines "
            "necessary for public oversight."
        )
        result = summarize_bill("Test.", digest)
        self.assertEqual(result["confidence"], "high")
        self.assertLessEqual(len(result["text"]), 245)
        self.assertTrue(result["text"].endswith("\u2026"), result["text"])

    def test_total_length_cap_two_sentences(self):
        first = (
            "This bill would require every local agency to prepare and submit "
            "a comprehensive five-year plan that addresses housing needs for "
            "each income group, including low-income and very low-income "
            "households, and that identifies the specific sites proposed for "
            "development within the planning area."
        )
        second = (
            "The bill would prohibit a local agency from denying or delaying "
            "approval of a project that conforms to the comprehensive plan, "
            "and would require the agency to publish the reasons for any "
            "conditions it imposes on the approval."
        )
        result = summarize_bill("Housing elements.", f"{first} {second}")
        self.assertLessEqual(len(result["text"]), 485)
        self.assertIn("Requires every local agency", result["text"])
        self.assertIn("Prohibits a local agency", result["text"])

    def test_anaphoric_those_neutralized(self):
        result = summarize_bill(
            "Court reporting.",
            "Existing law describes the requirements. This bill would repeal "
            "those provisions and establish new requirements for court "
            "reporting services.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertNotIn("those", result["text"].lower())
        self.assertIn("the provisions", result["text"])

    def test_compound_predicate_conjugated(self):
        result = summarize_bill(
            "Behavioral health and arts.",
            "This measure would recognize and affirm the important role of "
            "artists in supporting behavioral health.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertIn("Recognizes and affirms", result["text"])

    def test_initials_not_split_into_sentences(self):
        result = summarize_bill(
            "Tariffs.",
            "This measure urges President Donald J. Trump to veto a specific "
            "provision. The measure would urge the United States Congress to "
            "enact a joint resolution.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(result["text"].startswith("Urges President Donald J. Trump to veto"))

    def test_stray_mid_sentence_period_dropped(self):
        result = summarize_bill(
            "Electricity: program.",
            "This bill would revise the requirements of the customer "
            "subscription program. to promote participation by low-income "
            "customers at levels commensurate with the opportunity provided "
            "to certain customers.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertNotIn("program. to", result["text"])

    def test_mid_sentence_hedge_dropped_without_stray_period(self):
        # ", as provided," in the middle of a sentence must be dropped, not
        # turned into a period ("subscription program. to promote" bug).
        result = summarize_bill(
            "Electricity: subscription program.",
            "This bill would revise the requirements of the customer "
            "subscription program, as provided, among other things, to "
            "promote participation by low-income customers.",
        )
        self.assertEqual(result["confidence"], "high")
        self.assertIn("subscription program to promote", result["text"])
        self.assertNotIn("program. to", result["text"])

    def test_sentence_final_hedge_collapses_to_period(self):
        result = summarize_bill(
            "Reporting.",
            "This bill would require reports to be submitted by October 1 of "
            "the following year, as specified.",
        )
        self.assertEqual(
            result["text"],
            "Requires reports to be submitted by October 1 of the following year.",
        )

    def test_truncated_final_fragment_is_not_a_candidate(self):
        result = summarize_bill(
            "Test.",
            "This bill would require the department to publish reports by "
            "June 1 of each year. The bill would also require each agency to "
            "submit a plan describing the measures \u2026",
        )
        # The digest ends mid-sentence; only the complete first sentence is
        # usable.
        self.assertEqual(result["confidence"], "medium")
        self.assertTrue(result["text"].startswith("Requires the department"))
        self.assertNotIn("submit a plan", result["text"])
        self.assertIn("source_excerpt_truncated", result["flags"])


if __name__ == "__main__":
    unittest.main()
