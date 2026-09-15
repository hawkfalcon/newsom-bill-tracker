#!/usr/bin/env python3
"""
Unit tests for scripts/fetch_gov_updates.py
"""

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
    extract_msg_url,
    norm,
    parse_bill_items,
    parse_post,
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


if __name__ == "__main__":
    unittest.main()
