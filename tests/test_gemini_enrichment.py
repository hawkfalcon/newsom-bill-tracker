import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from gemini_enrichment import (
    build_prompt,
    make_batches,
    needs_enrichment,
    prepare_digest_for_model,
    source_hash,
    validate_item,
)


class GeminiEnrichmentTests(unittest.TestCase):
    def test_preprocessor_keeps_change_and_exception_but_drops_unrelated_background(self):
        background = " ".join(
            f"Existing law contains background provision number {i}."
            for i in range(1, 16)
        )
        digest = (
            "Existing law establishes a board and describes its historical duties. "
            f"{background} "
            "This bill would require the board to publish a report by January 1, 2027. "
            "The requirement would not apply if the board determines that publication would disclose confidential information. "
            "The bill would make other conforming changes."
        )
        prepared = prepare_digest_for_model("Public reporting: board duties.", digest)
        self.assertIn("require the board to publish a report", prepared)
        self.assertIn("would not apply", prepared)
        self.assertLess(len(prepared), len(digest))
        self.assertNotIn("background provision number 12", prepared)

    def test_batches_pack_multiple_bills_under_character_cap(self):
        items = [
            {
                "bill_id": f"id-{i}",
                "measure": f"AB {i}",
                "title": "Housing",
                "prepared_digest": "This bill would require a report. " * 4,
            }
            for i in range(5)
        ]
        batches = make_batches(items, batch_size=3, max_input_chars=1100)
        self.assertEqual([len(batch) for batch in batches], [3, 2])
        prompt = build_prompt(batches[0])
        self.assertIn("id-0", prompt)
        self.assertIn("id-2", prompt)

    def test_validation_requires_exact_source_evidence_and_rejects_new_numbers(self):
        source = "This bill would require reports to be filed by January 1, 2027."
        accepted = validate_item(
            {
                "bill_id": "202520260AB1",
                "plain_summary": "Requires reports to be filed by January 1, 2027.",
                "evidence": ["require reports to be filed by January 1, 2027"],
                "confidence": "high",
            },
            {"bill_id": "202520260AB1"},
            source,
        )
        self.assertIsNotNone(accepted)
        self.assertEqual(accepted["confidence"], "high")

        rejected = validate_item(
            {
                "bill_id": "202520260AB1",
                "plain_summary": "Requires reports to be filed by January 1, 2028.",
                "evidence": ["require reports to be filed by January 1, 2027"],
                "confidence": "high",
            },
            {"bill_id": "202520260AB1"},
            source,
        )
        self.assertIsNone(rejected)

    def test_hash_is_stable_for_whitespace(self):
        self.assertEqual(source_hash("A  bill\nwould require a report."), source_hash("A bill would require a report."))

    def test_unchanged_digest_is_not_sent_again_after_accept_or_rejection(self):
        digest_hash = source_hash("This bill would require a report.")
        self.assertFalse(needs_enrichment({
            "plain_summary_method": "gemini-gemini-3.8-flash",
            "plain_summary_source_hash": digest_hash,
        }, digest_hash))
        self.assertTrue(needs_enrichment({
            "plain_summary_method": "rules-v1",
            "plain_summary_enrichment_hash": digest_hash,
            "plain_summary_enrichment_status": "retry_pending",
            "plain_summary_enrichment_attempts": 1,
        }, digest_hash))
        self.assertFalse(needs_enrichment({
            "plain_summary_method": "rules-v1",
            "plain_summary_enrichment_hash": digest_hash,
            "plain_summary_enrichment_status": "rejected",
            "plain_summary_enrichment_attempts": 2,
        }, digest_hash))
        self.assertTrue(needs_enrichment({
            "plain_summary_method": "rules-v1",
            "plain_summary_source_hash": "different",
        }, digest_hash))


if __name__ == "__main__":
    unittest.main()
