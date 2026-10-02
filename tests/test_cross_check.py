"""Tests for the gov-vs-LegInfo cross-check the refresh job runs.

In CI the check runs --warn-only: every disagreement, including a bill that
vanished from bills.json, is reported and never blocks the refresh.  The
strict mode is still the default (and still tested) so a human can run it as a
gate, and the report itself has to stay accurate either way: real findings in
the log, capped annotations on Actions.
"""
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import cross_check  # noqa: E402


def run(bills, actions, stale_hours=48, age_hours=100, warn_only=False,
        on_github=False):
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
    if warn_only:
        argv.append("--warn-only")
    out = io.StringIO()
    old_argv = sys.argv
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(out):
            # Pin the runner env either way, so the annotation expectations do
            # not shift when these tests themselves run on GitHub Actions.
            with mock.patch.dict(os.environ,
                                 {"GITHUB_ACTIONS": "true" if on_github else ""}):
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


class WarnOnlyTests(unittest.TestCase):
    """The mode the refresh job uses: report, never block."""

    def test_stale_disagreement_does_not_block_with_warn_only(self):
        code, out = run(
            [{"measure": "SB 969", "status": "pending"}],
            {"sb969": {"measure": "SB 969", "action": "signed", "date": "2026-09-20"}},
            age_hours=60,
            warn_only=True,
        )
        self.assertEqual(code, 0, out)
        # Downgrading the exit code must not lose the finding itself.
        self.assertIn("ERROR: SB 969: gov says signed", out)
        self.assertIn("1 error(s)", out)

    def test_vanished_bill_does_not_block_with_warn_only(self):
        """Even the class of disagreement this pipeline could have caused."""
        code, out = run(
            [{"measure": "SB 999", "status": "signed"}],
            {"sb769": {"measure": "SB 769", "action": "vetoed", "date": "2026-09-18"}},
            warn_only=True,
        )
        self.assertEqual(code, 0, out)
        self.assertIn("absent from bills.json", out)

    def test_clean_data_is_unremarkable_in_both_modes(self):
        bills = [{"measure": "SB 769", "status": "vetoed"}]
        actions = {"sb769": {"measure": "SB 769", "action": "vetoed",
                             "date": "2026-09-18"}}
        for warn_only in (False, True):
            code, out = run(bills, dict(actions), warn_only=warn_only,
                            on_github=True)
            self.assertEqual(code, 0, out)
            self.assertNotIn("::warning::", out)
            self.assertNotIn("::notice::", out)

    def test_annotations_only_on_github_actions(self):
        bills = [{"measure": "SB 969", "status": "pending"}]
        actions = {"sb969": {"measure": "SB 969", "action": "signed",
                            "date": "2026-09-20"}}

        code, local = run(bills, dict(actions), age_hours=60, warn_only=True)
        self.assertEqual(code, 0)
        self.assertNotIn("::warning::", local,
                         "a plain terminal run gets no workflow commands")

        code, ci = run(bills, dict(actions), age_hours=60, warn_only=True,
                       on_github=True)
        self.assertEqual(code, 0)
        self.assertIn("::warning::SB 969: gov says signed", ci)
        self.assertIn("::notice::cross-check found 1 gov/LegInfo", ci)

    def test_annotations_are_capped_and_counted(self):
        """Hundreds of stale rows must not bury the run in annotations.

        The finding count is fixed rather than derived from MAX_ANNOTATIONS, so
        raising the cap stops the assertions instead of moving them along.
        """
        n = 40
        cap = cross_check.MAX_ANNOTATIONS
        self.assertLess(cap, n, "test needs the cap below the finding count")
        self.assertLessEqual(cap, 50,
                             "GitHub only surfaces a limited number of "
                             "annotations per check run")
        bills = [{"measure": f"AB {i}", "status": "pending"} for i in range(n)]
        actions = {f"ab{i}": {"measure": f"AB {i}", "action": "signed",
                              "date": "2026-09-20"} for i in range(n)}
        code, out = run(bills, actions, age_hours=60, warn_only=True,
                        on_github=True)
        self.assertEqual(code, 0, out)
        # The cap of findings, plus one line counting the rest.
        self.assertEqual(out.count("::warning::"), cap + 1, out)
        self.assertIn(f"{n - cap} further disagreement(s), listed in the "
                      "step log", out)
        # The log still carries every single one.
        self.assertEqual(out.count("ERROR: AB "), n)

    def test_annotation_payload_is_escaped(self):
        """Reserved characters must not break the workflow command."""
        actions = {"ab5": {"measure": "AB%5", "action": "signed",
                           "date": "2026-09-20"}}
        code, out = run([], actions, age_hours=60, warn_only=True,
                        on_github=True)
        self.assertEqual(code, 0, out)
        line = next(l for l in out.splitlines() if l.startswith("::warning::"))
        # "%" is reserved in workflow commands: an unescaped one would truncate
        # the payload instead of reaching the UI, so nothing but our own escape
        # sequences may survive in the line.
        self.assertIn("AB%255", line, out)
        residue = (line.replace("%25", "").replace("%0D", "").replace("%0A", ""))
        self.assertNotIn("%", residue, f"unescaped % in annotation: {residue}")


if __name__ == "__main__":
    unittest.main()
