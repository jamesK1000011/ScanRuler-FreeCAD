# SPDX-License-Identifier: AGPL-3.0-only
# Release readiness without FreeCAD: package.xml, scanrulerfc.VERSION and
# the changelog's newest version agree; package.xml is dated as that
# version; the changelog keeps an Unreleased section on top; the README's
# install ways and links are there, and the credit to Stefan Hermann (CNC
# Kitchen) wherever his work is described.
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scanrulerfc  # noqa: E402

REPO = "https://github.com/jamesK1000011/ScanRuler-FreeCAD"


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


class Versions(unittest.TestCase):
    def setUp(self):
        self.xml = read("package.xml")
        self.log = read("CHANGELOG.md")

    def newest(self):
        m = re.search(r"(?m)^## (\d+\.\d+\.\d+) — (\d{4}-\d{2}-\d{2})$", self.log)
        self.assertIsNotNone(m, "no dated version in CHANGELOG.md")
        return m.group(1), m.group(2)

    def test_versions_agree(self):
        ver, _ = self.newest()
        pkg = re.search(r"<version>([^<]+)</version>", self.xml).group(1)
        self.assertRegex(scanrulerfc.VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(pkg, scanrulerfc.VERSION, "package.xml and scanrulerfc.VERSION")
        self.assertEqual(ver, scanrulerfc.VERSION, "the changelog's newest version and scanrulerfc.VERSION")

    def test_package_dated_as_the_release(self):
        _, day = self.newest()
        self.assertEqual(re.search(r"<date>([^<]+)</date>", self.xml).group(1), day)

    def test_unreleased_on_top(self):
        heads = re.findall(r"(?m)^## (.+)$", self.log)
        self.assertEqual(heads[0], "[Unreleased]")
        self.assertRegex(heads[1], r"^\d+\.\d+\.\d+ — ")

    def test_package_points_at_the_repository(self):
        self.assertIn(f'<url type="repository" branch="main">{REPO}</url>', self.xml)
        self.assertIn(f'<url type="readme">{REPO}/blob/main/README.md</url>', self.xml)
        self.assertIn("Stefan Hermann (CNC Kitchen)", self.xml)


class Readme(unittest.TestCase):
    def setUp(self):
        self.text = read("README.md")

    def test_install_ways_and_links(self):
        self.assertIn("Addon Manager", self.text)
        self.assertIn(f"`{REPO}`, branch `main`", self.text)
        self.assertIn(f"({REPO}/releases)", self.text)
        self.assertIn(f"({REPO}/archive/refs/heads/main.zip)", self.text)

    def test_credit(self):
        self.assertIn("**ScanRuler by Stefan Hermann (CNC Kitchen)**", self.text)
        self.assertIn("https://github.com/CNCKitchen/ScanRuler", self.text)
        self.assertIn("Stefan Hermann", read("NOTICE.md"))
        self.assertIn("Stefan Hermann (CNC Kitchen)", scanrulerfc.CREDIT)


if __name__ == "__main__":
    unittest.main()
