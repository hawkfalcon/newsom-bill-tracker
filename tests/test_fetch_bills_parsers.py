import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from fetch_bills import (
    classify,
    extract_action,
    extract_digest_text,
    parse_history_rows,
    parse_latest_vote,
    parse_search_html,
    parse_status_page,
)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class SearchParseTests(unittest.TestCase):
    def setUp(self):
        self.bills = parse_search_html(read("leginfo_search.html"))

    def test_parses_all_bill_rows(self):
        self.assertEqual(len(self.bills), 5)
        first = self.bills[0]
        self.assertEqual(first["bill_id"], "202520260AB302")
        self.assertEqual(first["measure"], "AB 302")
        self.assertEqual(first["title"], "Transit-oriented development: exclusions.")
        self.assertEqual(first["author"], "Berman")
        self.assertEqual(first["status"], "Chaptered")

    def test_keeps_leginfo_display_form_verbatim(self):
        # LegInfo displays hyphenated measures; normalization happens later.
        by_id = {b["bill_id"]: b for b in self.bills}
        self.assertEqual(by_id["202520260SB1392"]["measure"], "SB-1392")

    def test_classify_maps_leginfo_statuses(self):
        by_id = {b["bill_id"]: b for b in self.bills}
        self.assertEqual(classify(by_id["202520260AB302"]["status"]), "signed")
        self.assertEqual(classify(by_id["202520260AB101"]["status"]), "vetoed")
        self.assertEqual(classify(by_id["202520260SB95"]["status"]), "pending")
        self.assertIsNone(classify(by_id["202520260AB7"]["status"]))

    def test_rows_without_bill_link_are_skipped(self):
        self.assertTrue(all(b["bill_id"].startswith("20252026") for b in self.bills))


class StatusParseTests(unittest.TestCase):
    def setUp(self):
        self.summary, self.history = parse_status_page(read("leginfo_status.html"))

    def test_summary_dates(self):
        self.assertEqual(self.summary.get("signed_date"), "2026-09-15")
        # "Enrolled Date:" is stored under "pending_date" (the pending kind).
        self.assertEqual(self.summary.get("pending_date"), "2026-09-02")
        self.assertEqual(self.summary.get("last_amended_date"), "2026-08-18")
        # Empty value -> None, key still present.
        self.assertIsNone(self.summary.get("vetoed_date"))

    def test_extract_action_pending_falls_back_to_summary_date(self):
        date, text = extract_action({"pending_date": "2026-09-02"}, [], "pending")
        self.assertEqual(date, "2026-09-02")
        self.assertEqual(text, "Enrolled.")

    def test_history_rows(self):
        self.assertEqual(len(self.history), 5)
        self.assertEqual(self.history[0][0], "2026-09-15")
        self.assertIn("Approved by the Governor", self.history[0][1])

    def test_extract_action_signed_from_history(self):
        date, text = extract_action(self.summary, self.history, "signed")
        self.assertEqual(date, "2026-09-15")
        self.assertEqual(text, "Signed by the Governor.")

    def test_extract_action_pending_prefers_presentation(self):
        date, text = extract_action(self.summary, self.history, "pending")
        self.assertEqual(date, "2026-09-02")
        self.assertIn("presented to the Governor", text)

    def test_extract_action_vetoed_from_history(self):
        summary, history = {}, [("2026-09-18", "Vetoed by the Governor.")]
        date, text = extract_action(summary, history, "vetoed")
        self.assertEqual(date, "2026-09-18")
        self.assertIn("Vetoed by the Governor", text)

    def test_extract_action_vetoed_falls_back_to_summary_date(self):
        # The history table can lag the summary fields; the summary date is
        # still the Governor's decision date.
        date, text = extract_action(
            {"vetoed_date": "2026-09-18"}, [], "vetoed"
        )
        self.assertEqual(date, "2026-09-18")
        self.assertEqual(text, "Vetoed by the Governor.")

    def test_extract_action_missing_everywhere(self):
        date, text = extract_action({}, [], "signed")
        self.assertIsNone(date)
        self.assertIsNone(text)


class FullHistoryTests(unittest.TestCase):
    def test_parses_more_than_five_rows(self):
        history = parse_history_rows(read("leginfo_history.html"))
        self.assertEqual(len(history), 6)
        vetoed = [row for row in history if "Vetoed by the Governor" in row[1]]
        self.assertEqual(len(vetoed), 1)
        self.assertEqual(vetoed[0][0], "2026-09-18")
        date, text = extract_action({}, history, "vetoed")
        self.assertEqual(date, "2026-09-18")


class DigestTests(unittest.TestCase):
    def test_extract_digest_text_strips_header_and_title(self):
        digest = extract_digest_text(
            read("leginfo_digest.html"),
            "Transit-oriented development: exclusions.",
        )
        self.assertTrue(digest.startswith("Existing law specifies exclusions"))
        self.assertIn("This bill would also exclude", digest)
        self.assertNotIn("Digest Key", digest)
        self.assertNotIn("AB 302, Berman", digest)

    def test_missing_digest_returns_none(self):
        self.assertIsNone(extract_digest_text("<html><body>No digest here</body></html>", "X."))


class VoteTests(unittest.TestCase):
    def test_latest_vote_wins(self):
        vote = parse_latest_vote(read("leginfo_votes.html"), "202520260AB302")
        self.assertEqual(vote["date"], "2026-09-10")
        self.assertEqual(vote["ayes"], 64)
        self.assertEqual(vote["noes"], 0)
        self.assertEqual(vote["nvr"], 0)
        self.assertEqual(vote["location"], "Sacramento")
        self.assertIn("Reconsidered", vote["motion"])
        self.assertIn("bill_id=202520260AB302", vote["url"])

    def test_no_votes_returns_none(self):
        self.assertIsNone(parse_latest_vote("<html><body>none</body></html>", "x"))


if __name__ == "__main__":
    unittest.main()
