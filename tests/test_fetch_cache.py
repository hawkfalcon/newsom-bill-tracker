import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from fetch_bills import (
    CACHE_VERSION,
    can_reuse_final,
    load_cache,
    normalize_measure,
    search_fingerprint,
)


class NormalizeMeasureTests(unittest.TestCase):
    def test_hyphenated_measure_is_normalized(self):
        self.assertEqual(normalize_measure("SB-1392"), "SB 1392")
        self.assertEqual(normalize_measure("AB-302"), "AB 302")

    def test_space_measure_unchanged(self):
        self.assertEqual(normalize_measure("AB 302"), "AB 302")

    def test_empty_unchanged(self):
        self.assertEqual(normalize_measure(""), "")
        self.assertEqual(normalize_measure(None), "")


class FetchCacheTests(unittest.TestCase):
    def setUp(self):
        self.bill = {
            "bill_id": "202520260AB1",
            "measure": "AB 1",
            "title": "Public reporting.",
            "author": "Example",
            "status": "Chaptered",
        }
        self.record = {
            "bill_id": self.bill["bill_id"],
            "measure": "AB 1",
            "title": "Public reporting.",
            "author": "Example",
            "status": "signed",
            "action_date": "2026-09-10",
        }
        self.cached = {
            "fingerprint": search_fingerprint(self.bill),
            "digest_text": "This bill would require a report.",
        }

    def test_reuses_unchanged_terminal_bill_with_record_from_previous(self):
        self.assertTrue(can_reuse_final(self.bill, self.cached, self.record))

    def test_reuses_v1_entry_with_embedded_record(self):
        v1 = {**self.cached, "record": self.record}
        self.assertTrue(can_reuse_final(self.bill, v1))

    def test_no_record_anywhere_is_not_reused(self):
        self.assertFalse(can_reuse_final(self.bill, self.cached))

    def test_pending_bill_is_always_checked(self):
        pending = {**self.bill, "status": "Enrolled"}
        pending_cache = {**self.cached, "fingerprint": search_fingerprint(pending)}
        self.assertFalse(can_reuse_final(pending, pending_cache, self.record))

    def test_changed_search_row_is_not_reused(self):
        changed = {**self.bill, "title": "Public reporting: amended."}
        self.assertFalse(can_reuse_final(changed, self.cached, self.record))

    def test_missing_full_digest_is_not_reused(self):
        self.assertFalse(
            can_reuse_final(self.bill, {**self.cached, "digest_text": ""}, self.record)
        )


class LoadCacheMigrationTests(unittest.TestCase):
    def _write(self, payload):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(payload, f)
        f.close()
        return f.name

    def test_v1_cache_migrates_fingerprint_from_record_and_drops_record(self):
        # v1 fingerprints were computed with the broken normalization, so a
        # hyphen-form measure ("SB-1392") was stored verbatim.  The migrated
        # fingerprint must equal what the fixed code computes for the live
        # search row.
        record = {
            "bill_id": "202520260SB1392",
            "measure": "SB-1392",
            "title": "Water.",
            "author": "Example",
            "status": "signed",
        }
        path = self._write({
            "version": 1,
            "session": "20252026",
            "bills": {
                "202520260SB1392": {
                    "fingerprint": "stale-v1-fingerprint",
                    "digest_text": "This bill would require a report.",
                    "record": record,
                }
            },
        })
        entries, session = load_cache(path)
        entry = entries["202520260SB1392"]
        self.assertEqual(session, "20252026")
        self.assertNotIn("record", entry)
        live_row = {
            "bill_id": "202520260SB1392",
            "measure": "SB-1392",  # LegInfo displays the hyphen form
            "title": "Water.",
            "author": "Example",
            "status": "Chaptered",
        }
        self.assertEqual(entry["fingerprint"], search_fingerprint(live_row))

    def test_v2_cache_is_left_untouched(self):
        fingerprint = search_fingerprint({
            "bill_id": "202520260AB1", "measure": "AB 1",
            "title": "T.", "author": "A", "status": "Chaptered",
        })
        path = self._write({
            "version": CACHE_VERSION,
            "session": "20252026",
            "bills": {"202520260AB1": {
                "fingerprint": fingerprint,
                "digest_text": "digest",
            }},
        })
        entries, _ = load_cache(path)
        self.assertEqual(entries["202520260AB1"]["fingerprint"], fingerprint)

    def test_missing_or_corrupt_cache_returns_empty(self):
        self.assertEqual(load_cache("/nonexistent/path.json"), ({}, None))
        path = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        path.write("{not json")
        path.close()
        self.assertEqual(load_cache(path.name), ({}, None))


if __name__ == "__main__":
    unittest.main()
