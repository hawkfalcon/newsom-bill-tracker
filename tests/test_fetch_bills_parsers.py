import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import fetch_bills
from fetch_bills import (
    classify,
    confirm_offlisted_kind,
    extract_action,
    extract_digest_text,
    kind_from_leginfo_record,
    offlisted_desk_bills,
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


class VetoUnderConsiderationTests(unittest.TestCase):
    """A late-session veto flips the LegInfo search row off "Vetoed".

    The bill must stay in bills.json, because dropping it loses a recorded veto
    from the site and makes the gov-vs-LegInfo cross-check fail for good.
    """

    def setUp(self):
        self.summary, self.history = parse_status_page(
            read("leginfo_status_veto_pending.html")
        )

    def test_status_page_shows_no_veto_date_field(self):
        # LegInfo has not stamped the veto yet — that is the whole problem.
        self.assertIsNone(self.summary.get("vetoed_date"))
        self.assertEqual(self.summary.get("pending_date"), "2026-09-01")

    def test_kind_recovered_from_history_rows(self):
        self.assertEqual(kind_from_leginfo_record(self.summary, self.history), "vetoed")

    def test_signed_bill_recovered_from_history_rows(self):
        summary, history = parse_status_page(read("leginfo_status.html"))
        self.assertEqual(kind_from_leginfo_record(summary, history), "signed")

    def test_bill_back_in_floor_process_is_not_recovered(self):
        history = [
            ("2026-09-21", "In Senate. Read and ordered to Third File."),
            ("2026-09-20", "Returned to the Senate."),
        ]
        self.assertIsNone(kind_from_leginfo_record({}, history))

    def test_offlisted_desk_bills_only_returns_tracked_bills(self):
        bills = parse_search_html(read("leginfo_search.html"))
        previous = {"202520260AB7": {"status": "pending", "measure": "AB 7"}}
        offlisted = offlisted_desk_bills(bills, previous)
        self.assertEqual([b["bill_id"] for b in offlisted], ["202520260AB7"])
        # Nothing is rescued when the bill was never on the desk list.
        self.assertEqual(offlisted_desk_bills(bills, {}), [])
        # A bill whose row still classifies is never a rescue candidate.
        self.assertEqual(
            offlisted_desk_bills(bills, {"202520260AB302": {"status": "signed"}}), []
        )

    def test_confirm_offlisted_kind_reads_the_status_page(self):
        html = read("leginfo_status_veto_pending.html")
        calls = []
        with mock.patch.object(
            fetch_bills, "fetch_status_page",
            lambda bill_id: (calls.append(bill_id), html)[1],
        ):
            kind, note = confirm_offlisted_kind({"bill_id": "202520260SB632"}, "pending")
        self.assertEqual(kind, "vetoed")
        self.assertIsNone(note)
        self.assertEqual(calls, ["202520260SB632"])

    def test_confirm_offlisted_kind_gives_up_on_floor_process_bill(self):
        page = (
            '<label class="statusLabel">Enrolled Date:</label>'
            '<span id="lastAction"></span>'
            "<tr><td scope=\"row\">09/21/26</td>"
            "<td>In Senate. Read and ordered to Third File.</td></tr>"
        )
        with mock.patch.object(fetch_bills, "fetch_status_page", lambda bill_id: page), \
             mock.patch.object(fetch_bills, "fetch_history_page", lambda bill_id: page):
            kind, note = confirm_offlisted_kind({"bill_id": "202520260SB1"}, "pending")
        self.assertIsNone(kind)
        self.assertIsNone(note)

    def test_confirm_offlisted_kind_keeps_record_when_leginfo_unreadable(self):
        """A failed request is not evidence that the veto did not happen."""

        def boom(bill_id):
            raise RuntimeError("TLS EOF")

        with mock.patch.object(fetch_bills, "fetch_status_page", boom):
            kind, note = confirm_offlisted_kind({"bill_id": "202520260SB769"}, "vetoed")
        self.assertEqual(kind, "vetoed")
        self.assertIn("status page unreadable", note)

        with mock.patch.object(fetch_bills, "fetch_status_page", boom):
            kind, _ = confirm_offlisted_kind({"bill_id": "202520260SB769"}, "pending")
        self.assertIsNone(kind)


if __name__ == "__main__":
    unittest.main()
