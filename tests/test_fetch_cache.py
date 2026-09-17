import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from fetch_bills import can_reuse_final, search_fingerprint


class FetchCacheTests(unittest.TestCase):
    def setUp(self):
        self.bill = {
            "bill_id": "202520260AB1",
            "measure": "AB 1",
            "title": "Public reporting.",
            "author": "Example",
            "status": "Chaptered",
        }
        self.cached = {
            "fingerprint": search_fingerprint(self.bill),
            "digest_text": "This bill would require a report.",
            "record": {"bill_id": self.bill["bill_id"], "status": "signed"},
        }

    def test_reuses_unchanged_terminal_bill_with_full_digest(self):
        self.assertTrue(can_reuse_final(self.bill, self.cached))

    def test_pending_bill_is_always_checked(self):
        pending = {**self.bill, "status": "Enrolled"}
        pending_cache = {**self.cached, "fingerprint": search_fingerprint(pending)}
        self.assertFalse(can_reuse_final(pending, pending_cache))

    def test_changed_search_row_is_not_reused(self):
        changed = {**self.bill, "title": "Public reporting: amended."}
        self.assertFalse(can_reuse_final(changed, self.cached))

    def test_missing_full_digest_is_not_reused(self):
        self.assertFalse(can_reuse_final(self.bill, {**self.cached, "digest_text": ""}))


if __name__ == "__main__":
    unittest.main()
