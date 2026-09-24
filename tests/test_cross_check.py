"""Tests for the gov-vs-LegInfo cross-check that gates the refresh job.

The check has to stay strict about disagreements this pipeline caused (a bill
that vanished from bills.json) while never blocking the normal few-hours lag
between a Governor's announcement and LegInfo catching up.
"""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import cross_check  # noqa: E402


def run(bills, actions, stale_hours=48, age_hours=100):
    """Run cross_check.main() on in-memory data; return (exit code, output)."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    published = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )
    for key, action in actions.items():
        action.setdefault("published_at", published)
    bills_path = tmp / "bills.json"
    gov_path = tmp / "gov.json"
    bills_path.write_text(json.dumps({"bills": bills}))
    gov_path.write_text(json.dumps({"actions": actions}))
    argv = ["cross_check.py", "--bills", str(bills_path), "--gov", str(gov_path),
            "--stale-hours", str(stale_hours)]
    out = io.StringIO()
    old_argv = sys.argv
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(out):
            code = cross_check.main()
    finally:
        sys.argv = old_argv
    return code, out.getvalue()


class CrossCheckTests(unittest.TestCase):
    def test_agreement_is_clean(self):
        code, out = run(
            [{"measure": "SB 769", "status": "vetoed"}],
            {"sb769": {"measure": "SB 769", "action": "vetoed", "date": "2026-09-18"}},
        )
        self.assertEqual(code, 0, out)
        self.assertIn("0 error(s)", out)

    def test_hyphenated_measure_still_matches(self):
        code, _ = run(
            [{"measure": "SB-769", "status": "vetoed"}],
            {"sb769": {"measure": "SB 769", "action": "vetoed", "date": "2026-09-18"}},
        )
        self.assertEqual(code, 0)

    def test_announced_bill_missing_from_snapshot_is_an_error_when_stale(self):
        """The failure mode the veto-consideration bug produced: red CI on purpose."""
        code, out = run(
            [{"measure": "SB 999", "status": "signed"}],
            {"sb769": {"measure": "SB 769", "action": "vetoed", "date": "2026-09-18"}},
        )
        self.assertEqual(code, 1)
        self.assertIn("absent from bills.json", out)
        self.assertIn("fetch_bills log", out)

    def test_fresh_announcement_of_an_unknown_bill_is_only_a_warning(self):
        code, out = run(
            [],
            {"sb769": {"measure": "SB 769", "action": "vetoed", "date": "2026-09-18"}},
            stale_hours=48,
            age_hours=2,
        )
        self.assertEqual(code, 0)
        self.assertIn("1 warning(s)", out)

    def test_leginfo_lag_within_window_is_a_warning(self):
        code, out = run(
            [{"measure": "SB 969", "status": "pending"}],
            {"sb969": {"measure": "SB 969", "action": "signed", "date": "2026-09-20"}},
            age_hours=6,
        )
        self.assertEqual(code, 0)
        self.assertIn("still shows it pending", out)

    def test_leginfo_lag_beyond_window_is_an_error(self):
        code, out = run(
            [{"measure": "SB 969", "status": "pending"}],
            {"sb969": {"measure": "SB 969", "action": "signed", "date": "2026-09-20"}},
            age_hours=60,
        )
        self.assertEqual(code, 1)

    def test_terminal_disagreement_is_always_an_error(self):
        """LegInfo says vetoed, the Governor says signed: never normal lag."""
        code, out = run(
            [{"measure": "AB 100", "status": "vetoed"}],
            {"ab100": {"measure": "AB 100", "action": "signed", "date": "2026-09-19"}},
            age_hours=1,
        )
        self.assertEqual(code, 1)
        self.assertIn("but LegInfo says vetoed", out)


if __name__ == "__main__":
    unittest.main()
