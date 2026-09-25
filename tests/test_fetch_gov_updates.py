#!/usr/bin/env python3
"""
Unit tests for scripts/fetch_gov_updates.py
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fetch_gov_updates import (
    BATCH_TITLE_RE,
    BILL_PATTERN,
    SIGNED_MARKER,
    VETOED_MARKER,
    anchor_href_before,
    extract_msg_url,
    norm,
    parse_bill_items,
    parse_post,
    strip_background_lists,
)


class TestFetchGovUpdates(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(norm("AB 1126"), "ab1126")
        self.assertEqual(norm("AB-1126"), "ab1126")
        self.assertEqual(norm("SB 542"), "sb542")
        self.assertEqual(norm("ABX1 2"), "abx12")
        self.assertEqual(norm("ACA 1"), "aca1")

    def test_batch_title_re(self):
        valid_titles = [
            "Governor Newsom signs legislation 9.14.2026",
            "Governor Newsom signs legislation 8.31.2026",
            "Governor Newsom signs legislation 7.6.26",
            "Acting Governor Monique Limón signs legislation 6.17.26",
            "Governor Newsom issues legislative update 10.13.25",
            "Governor Newsom issues legislative update 6.1.26",
            "Governor Newsom vetoes legislation 10.1.25",
            "Governor Newsom acts on legislation 9.30.26",
            "Governor Newsom takes action on legislation 9.29.26",
        ]
        for title in valid_titles:
            self.assertTrue(bool(BATCH_TITLE_RE.search(title)), f"Failed to match title: {title}")

    def test_parse_september_14_post(self):
        """Test with the September 14, 2026 post format (which had malformed </li>-only lines)."""
        post = {
            "id": 112583,
            "title": {"rendered": "Governor Newsom signs legislation 9.14.2026"},
            "date": "2026-09-14T20:02:03",
            "date_gmt": "2026-09-15T03:02:03",
            "modified": "2026-09-14T20:02:03",
            "modified_gmt": "2026-09-15T03:02:03",
            "slug": "governor-newsom-signs-legislation-9-14-2026",
            "link": "https://www.gov.ca.gov/2026/09/14/governor-newsom-signs-legislation-9-14-2026/",
            "content": {
                "rendered": """
                <p><strong>SACRAMENTO</strong> – Governor Gavin Newsom today announced that he has signed the following bills:</p>
                AB 1126 by Assemblymember Joe Patterson (R-Rocklin) — Medi-Cal managed care plans: enrollees with other health care coverage.</li>
                AB 1153 by Assemblymember Mia Bonta (D-Oakland) — Illegal disposal site abatement.</li>
                AB 1359 by Assemblymember Patrick Ahrens (D-Cupertino) — Jury service exemptions.</li>
                AB 1440 by the Committee on Environmental Safety and Toxic Materials — Pesticide testing.</li>
                AB 1526 by the Committee on Governmental Organization — Horse racing: audits of the horsemen’s organizations: license fee deposits: minisatellite wagering facilities.</li>
                AB 1615 by Assemblymember Stephanie Nguyen (D-Elk Grove) — Firearms: unsafe handguns.</li>
                AB 1617 by Assemblymember Juan Alanis (R-Modesto) — Household hazardous waste: reporting.</li>
                AB 1728 by Assemblymember Juan Alanis (R-Modesto) — Community colleges: common course numbering system: career technical education public safety courses.</li>
                AB 1758 by Assemblymember Stephanie Nguyen (D-Elk Grove) — Sellers of travel.</li>
                AB 1786 by Assemblymember John Harabedian (D-Pasadena) — Public contracts: best value construction contracting for counties, cities, and the San Gabriel Valley Council of Governments.</li>
                AB 1848 by Assemblymember Rhodesia Ransom (D-Tracy) — California Seed Law: annual registration fee: Seed Advisory Board.</li>
                AB 1907 by Assemblymember Dawn Addis (D-Morro Bay) — California Health Benefit Exchange.</li>
                AB 1999 by Assemblymember Ash Kalra (D-San José)  — Veterinary medicine.</li>
                AB 2004 by Assemblymember Juan Alanis (R-Modesto) — Peace officers: deputy sheriffs.</li>
                AB 2015 by Assemblymember Buffy Wicks (D-Oakland) — Department of Transportation: third-party navigation applications: study and report.</li>
                AB 2024 by Assemblymember Stephanie Nguyen (D-Elk Grove) — Outdoor advertising displays: permits: landscaped freeways: relocation agreements.</li>
                AB 2161 by Assemblymember Mia Bonta (D-Oakland) — Medi-Cal eligibility: work or community engagement.</li>
                AB 2168 by Assemblymember Buffy Wicks (D-Oakland) — Active Transportation Program: guidelines.</li>
                AB 2173 by Assemblymember Greg Wallis (R-Bermuda Dunes) — Tribal gaming: compact ratification.</li>
                AB 2471 by the Committee on Emergency Management — Alfred E. Alquist Seismic Safety Commission.</li>
                AB 2539 by Assemblymember James C. Ramos (D-San Bernardino) —  Tribal-state gaming: compact ratification.</li>
                AB 2576 by Assemblymember John Harabedian (D-Pasadena) — Transit-oriented development: exclusions: historic sites.</li>
                AB 2731 by Assemblymember Dawn Addis (D-Morro Bay) — Alcoholic beverage control: neighborhood-restricted on-sale general licenses.</li>
                AB 2766 by Assemblymember Patrick Ahrens (D-Cupertino) — Public postsecondary education: student housing: foster youth and homeless youth.</li>
                AB 2771 by Assemblymember Marc Berman (D-Menlo Park) — California Private Postsecondary Education Act of 2009.</li>
                AB 2773 by the Committee on Business and Professions — California Board of Occupational Therapy: licensing: fees.</li>
                AB 2774 by Assemblymember Marc Berman (D-Menlo Park) — Physical Therapy Board of California.</li>
                AB 2775 by Assemblymember Marc Berman (D-Menlo Park) — Chiropractic Act.</li>
                AB 2780 by the Committee on Public Employment and Retirement — Public employees’ retirement.</li>
                AB 2787 by the Committee on Water, Parks, and Wildlife — Water, parks, and wildlife: omnibus bill.</li>
                AB 2788 by the Committee on Transportation — Transportation: omnibus bill.</li>
                SB 542 by Senator Monique Limón (D-Santa Barbara) — Tribal gaming: compact ratification.</li>
                SB 920 by Senator Bob Archuleta (D-Pico Rivera) — The Gambling Control Act: regulatory fees.</li>
                SB 990 by Senator Shannon Grove (R-Bakersfield)— Highways: exit information.</li>
                SB 1115 by Senator Shannon Grove (R-Bakersfield) — Public cemetery districts: board of trustees: County of Tulare.</li>
                SB 1150 by Senator Brian W. Jones (R-San Diego) — Cancer data: notifications.</li>
                SB 1195 by Senator Susan Rubio (D-Baldwin Park) — Tied-house exceptions: advertising: Counties of Los Angeles, San Bernardino, and San Diego.</li>
                SB 1235 by Senator Susan Rubio (D-Baldwin Park) — Tribal gaming: compact ratification.</li>
                SB 1274 by Senator Bob Archuleta (D-Pico Rivera) — Industrial cities.</li>
                SB 1311 by Senator Aisha Wahab (D-Hayward) — Licensed professions.</li>
                SB 1363 by Senator Aisha Wahab (D-Hayward) — Barbering and cosmetology.</li>
                SB 1368 by Senator Aisha Wahab (D-Hayward) — Speech-language pathologists, audiologists, and hearing aid dispensers.</li>
                SB 1432 by the Committee on Elections and Constitutional Amendments — Political Reform Act of 1974.</li>
                SB 1435 by the Committee on Revenue and Taxation — Personal Income Tax Law and Corporation Tax Law: federal conformity.</li>
                SB 1445 by the Committee on Business, Professions and Economic Development — Healing arts.</li>
                SB 1447 by the Committee on Health — Health omnibus.</li>
                </ul>
                <p>For full text of the bills, visit: <a href="http://leginfo.legislature.ca.gov">leginfo.legislature.ca.gov</a>.</p>
                """
            },
        }
        res = parse_post(post)
        self.assertEqual(len(res), 46, f"Expected 46 bills, got {len(res)}")
        self.assertIn("ab1126", res)
        self.assertEqual(res["ab1126"]["action"], "signed")
        self.assertEqual(res["ab1126"]["date"], "2026-09-14")
        self.assertEqual(res["ab1126"]["url"], "https://www.gov.ca.gov/2026/09/14/governor-newsom-signs-legislation-9-14-2026/")
        self.assertIsNone(res["ab1126"]["msg_url"])

        self.assertIn("sb542", res)
        self.assertEqual(res["sb542"]["action"], "signed")
        self.assertIn("sb1447", res)
        self.assertEqual(res["sb1447"]["action"], "signed")
        # Ensure leginfo URL at bottom wasn't captured as msg_url
        self.assertIsNone(res["sb1447"]["msg_url"])

    def test_acting_governor_post(self):
        """Test Acting Governor post with 'bills signed today' marker."""
        post = {
            "id": 107968,
            "title": {"rendered": "Acting Governor Monique Limón signs legislation 6.17.26"},
            "date": "2026-06-17T14:52:43",
            "slug": "acting-governor-monique-limon-signs-legislation-6-17-26",
            "link": "https://www.gov.ca.gov/2026/06/17/acting-governor-monique-limon-signs-legislation-6-17-26/",
            "content": {
                "rendered": """
                <p>The full list of bills signed today can be found below:</span></p>
                SB 1080 by Senator Suzette Martinez Valladares (R-Santa Clarita): County clerks.</span></li>
                SB 1440 by the Committee on Local Government: Validations.</span></li>
                SB 1441 by the Committee on Local Government: Validations.</span></li>
                SB 1442 by the Committee on Local Government: Validations.</span></li>
                </ul>
                """
            },
        }
        res = parse_post(post)
        self.assertEqual(len(res), 4)
        self.assertIn("sb1080", res)
        self.assertEqual(res["sb1080"]["action"], "signed")
        self.assertEqual(res["sb1080"]["date"], "2026-06-17")

    def test_post_with_signed_and_vetoed(self):
        """Test post containing both signed bills and vetoed bills with message links."""
        post = {
            "id": 103453,
            "title": {"rendered": "Governor Newsom issues legislative update 10.13.25"},
            "date": "2025-10-13T18:32:28",
            "link": "https://www.gov.ca.gov/2025/10/13/governor-newsom-issues-legislative-update-10-13-25/",
            "content": {
                "rendered": """
                <p>SACRAMENTO – Governor Gavin Newsom today announced that he has signed the following bills:</p>
                <ul>
                <li>AB 70 by Assemblymember Cecilia Aguiar-Curry – Solid waste.</li>
                <li>AB 366 by Assemblymember Cottie Petrie-Norris – Full service. A signing message can be found <a href="https://www.gov.ca.gov/wp-content/uploads/2025/10/AB-366-Signing-Message.pdf">here</a>.</li>
                </ul>
                <p>The Governor also announced that he has vetoed the following bills:</p>
                <ul>
                <li>AB 44 by Assemblymember Blanca Pacheco – Open-air markets. A veto message can be found <a href="https://www.gov.ca.gov/wp-content/uploads/2025/10/AB-44-Veto.pdf">here</a>.</li>
                <li>SB 76 by Senator Scott Wiener – Alcoholic beverages. A veto message can be found <a href="https://www.gov.ca.gov/wp-content/uploads/2025/10/SB-76-Veto.pdf">here</a>.</li>
                </ul>
                """
            },
        }
        res = parse_post(post)
        self.assertEqual(len(res), 4)

        # Signed bills
        self.assertEqual(res["ab70"]["action"], "signed")
        self.assertIsNone(res["ab70"]["msg_url"])
        self.assertEqual(res["ab366"]["action"], "signed")
        self.assertEqual(res["ab366"]["msg_url"], "https://www.gov.ca.gov/wp-content/uploads/2025/10/AB-366-Signing-Message.pdf")

        # Vetoed bills
        self.assertEqual(res["ab44"]["action"], "vetoed")
        self.assertEqual(res["ab44"]["msg_url"], "https://www.gov.ca.gov/wp-content/uploads/2025/10/AB-44-Veto.pdf")
        self.assertEqual(res["sb76"]["action"], "vetoed")
        self.assertEqual(res["sb76"]["msg_url"], "https://www.gov.ca.gov/wp-content/uploads/2025/10/SB-76-Veto.pdf")

    def test_unrelated_post_ignored(self):
        """Unrelated press releases with no bill listings must be ignored."""
        post = {
            "id": 99999,
            "title": {"rendered": "California honored for nation-leading efficiency and data-driven improvements"},
            "date": "2026-09-15T10:20:45",
            "link": "https://www.gov.ca.gov/press-release",
            "content": {"rendered": "<p>Governor Newsom today celebrated state efficiency awards.</p>"},
        }
        res = parse_post(post)
        self.assertEqual(res, {})


class TestCrossPostLinkExclusion(unittest.TestCase):
    """Bill codes that are cross-references to other gov.ca.gov posts
    (press-release prose) must not become actions for this post."""

    def test_anchor_href_before_plain_text(self):
        self.assertIsNone(anchor_href_before("plain text SB 53 here", 15))

    def test_anchor_href_before_closed_anchor(self):
        text = 'see <a href="https://www.gov.ca.gov/old/post/">here</a> and then SB 53'
        pos = text.rfind("SB")
        self.assertIsNone(anchor_href_before(text, pos))

    def test_anchor_href_before_open_anchor(self):
        text = 'signed into law <a href="https://www.gov.ca.gov/2025/09/22/ab-238/">AB 238</a>'
        pos = text.rfind("AB")
        self.assertEqual(
            anchor_href_before(text, pos),
            "https://www.gov.ca.gov/2025/09/22/ab-238/",
        )

    def test_cross_post_linked_bill_skipped(self):
        # Gasoline-price press release: bills are links to older signing posts.
        section = (
            "fought for and signed into law: "
            '<a href="https://www.gov.ca.gov/2023-03-28/gas-price-gouging/">SBX1\u20112</a> '
            "and "
            '<a href="https://www.gov.ca.gov/2024-10-14/gas-price-spikes/">ABX2-1</a>, '
            "which created first-in-the-nation transparency requirements."
        )
        self.assertEqual(parse_bill_items(section), [])

    def test_signed_into_law_anchor_text_skipped(self):
        # "signed into law AB 238" is the whole anchor text of a cross-link.
        section = (
            "the Governor "
            '<a href="https://www.gov.ca.gov/2025-09-22/fire-survivor-mortgage-relief/">'
            "signed into law AB 238</a> "
            "(Harabedian), which extended forbearance for up to 12 months."
        )
        self.assertEqual(parse_bill_items(section), [])

    def test_leginfo_linked_bill_kept(self):
        section = (
            "he has signed the following bills:\n"
            '<li><a href="https://leginfo.legislature.ca.gov/faces/billTextClient.php?bill_id=AB113">AB 113</a> '
            "by Assemblymember John Smith (D-Sampleville) \u2014 Sample topic. "
            'A signing message can be found <a href="https://www.gov.ca.gov/wp-content/uploads/2026/09/AB-113-Signing-Message.pdf">here</a>.</li>'
        )
        res = parse_bill_items(section)
        self.assertEqual(res, [("ab113", "AB 113", "https://www.gov.ca.gov/wp-content/uploads/2026/09/AB-113-Signing-Message.pdf")])

    def test_u2011_hyphen_bill_parsed(self):
        res = parse_bill_items("AB\u2011113 by Assemblymember John Smith (D-Sampleville) \u2014 Sample topic.")
        self.assertEqual(res[0][0], "ab113")
        self.assertEqual(res[0][1], "AB 113")

    def test_press_release_post_returns_no_actions(self):
        """The real-world phantom: a press release that merely references
        previously signed bills via cross-post links."""
        post = {
            "id": 105954,
            "title": {"rendered": "Governor Newsom blasts Trump for raising gasoline prices"},
            "date": "2026-03-10T12:00:00",
            "link": "https://www.gov.ca.gov/2026-03-10/gasoline-prices/",
            "content": {
                "rendered": (
                    "<p>SACRAMENTO \u2013 ... These are tools Governor Newsom fought for and "
                    "signed into law: "
                    '<a href="https://www.gov.ca.gov/2023-03-28/gas-price-gouging-law/">SBX1\u20112</a> '
                    "and "
                    '<a href="https://www.gov.ca.gov/2024-10-14/prevent-gas-price-spikes/">ABX2-1</a>, '
                    "which created first-in-the-nation transparency requirements for gas stations.</p>"
                )
            },
        }
        self.assertEqual(parse_post(post), {})


class TestBackgroundRecapLists(unittest.TestCase):
    """Narrative posts recap *earlier* signing rounds with real <li> lists.

    Those bills belong to a previous session; their measure numbers are
    identical, so parsing them as actions of this post fabricates
    "signed 2026-09-19" entries for bills that do not exist in the session —
    which is what made the cross-check fail with "absent from bills.json".
    """

    # Mirrors the structure of
    # https://www.gov.ca.gov/2026-09-19/governor-newsom-signs-new-laws-to-protect-california-elections-from-trump-interference/
    ELECTIONS_POST_HTML = """
        <h1>Governor Newsom signs new laws to protect California elections from Trump interference</h1>
        <p><strong>LOS ANGELES</strong> &mdash; Governor Gavin Newsom today signed a package
        of bills to protect elections in California from interference.</p>
        <h2>The election protection and pro-democracy bill package</h2>
        <ul>
        <li><strong>AB 282 (Pellerin)</strong>&ndash; Makes it a felony to seize ballots.</li>
        <li><strong>SB 259 (Wahab)</strong>&ndash; Makes it a felony to interfere with VBM.</li>
        <li><strong>AB 2103 (Irwin)</strong> &ndash; Establishes the Engaged California Program.</li>
        <li><strong>SB 1420 (Richardson)</strong>&ndash; Requires uniform vote-by-mail procedures.</li>
        </ul>
        <p>This bill package builds on the Governor&rsquo;s continued protection of elections.
        Earlier today, the Governor <a href="https://www.gov.ca.gov/2026-09-19/sovereignty/">signed</a>
        SB 1354 (Archuleta), which preserves California&rsquo;s sovereignty.</p>
        <h2>A record of defending democracy</h2>
        <p>Last year, Governor Newsom <a href="https://us.list-manage.com/a">signed</a>:</p>
        <ul>
        <li><strong>SB 3 (Cervantes)</strong> &mdash; requires that public vote counts are updated.</li>
        <li><strong>AB 16 (Alanis)</strong> &mdash; extended the time to process vote by mail ballots.</li>
        </ul>
        <p>In 2024, Governor Newsom <a href="https://us.list-manage.com/b">signed</a>:</p>
        <ul>
        <li><strong>AB 2655 (Berman)</strong> &mdash; requires large platforms to label content.</li>
        <li><strong>AB 2839 (Pellerin)</strong> &mdash; expands the deceptive-content timeframe.</li>
        <li><strong>AB 2355 (Carrillo)</strong> &mdash; requires an AI disclosure on ads.</li>
        </ul>
        """

    @staticmethod
    def _parse(post):
        """parse_post, with the dropped-recap note swallowed for clean test output."""
        with contextlib.redirect_stdout(io.StringIO()):
            return parse_post(post)

    def _post(self, html, title="Governor Newsom signs new laws to protect California elections"):
        return {
            "id": 112707,
            "title": {"rendered": title},
            "date": "2026-09-19T07:58:25",
            "date_gmt": "2026-09-19T14:58:25",
            "link": "https://www.gov.ca.gov/2026-09-19/elections/",
            "content": {"rendered": html},
        }

    def test_package_bills_are_kept(self):
        res = self._parse(self._post(self.ELECTIONS_POST_HTML))
        for nid in ("ab282", "sb259", "ab2103", "sb1420", "sb1354"):
            self.assertIn(nid, res, f"{nid} is part of today's package")
        self.assertEqual(res["ab282"]["action"], "signed")
        self.assertEqual(res["ab282"]["date"], "2026-09-19")

    def test_recapped_bills_are_not_actions_of_this_post(self):
        res = self._parse(self._post(self.ELECTIONS_POST_HTML))
        for nid in ("sb3", "ab16", "ab2655", "ab2839", "ab2355"):
            self.assertNotIn(nid, res, f"{nid} is background from an earlier session")

    def test_recap_lists_detected_at_the_list_level(self):
        _, dropped = strip_background_lists(self.ELECTIONS_POST_HTML)
        self.assertEqual(dropped, ["AB 16", "AB 2355", "AB 2655", "AB 2839", "SB 3"])

    def test_announcement_line_is_never_recap(self):
        """The official batch format keeps its lists: intro says "signed the
        following", so it must not be treated as background even though the
        post also mentions years."""
        html = (
            "<p>Gov. Newsom today announced that he signed the following bills "
            "in 2026:</p><ul><li>AB 1 by X &mdash; topic.</li>"
            "<li>SB 2 by Y &mdash; topic.</li></ul>"
        )
        self.assertEqual(strip_background_lists(html)[1], [])
        self.assertEqual(len(self._parse(self._post(html))), 2)

    def test_single_bill_post_without_lists_still_parsed(self):
        # gov.ca.gov renders the post title inside the content, which is what
        # lets "signs bill …" press releases be recognised at all.
        html = (
            "<h1>Governor Newsom signs bill to protect California&rsquo;s sovereignty</h1>"
            "<p><strong>SACRAMENTO</strong> &mdash; Today the Governor "
            "<a href=\"https://www.gov.ca.gov/2026-09-19/sovereignty/\">signed</a> "
            "SB 1354 (Archuleta), a bill that protects California sovereignty.</p>"
        )
        res = self._parse(self._post(html, "Governor Newsom signs bill to protect California's sovereignty"))
        self.assertEqual(list(res), ["sb1354"])


if __name__ == "__main__":
    unittest.main()
