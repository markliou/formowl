import unittest

import _paths  # noqa: F401
from formowl_records.normalize import normalize


class NormalizeTests(unittest.TestCase):
    def test_full_dates_become_iso_and_partial_dates_stay_unresolved(self) -> None:
        for raw in ("2026/7/3", "2026-07-03", "2026.7.3", "2026年7月3日", "20260703", "2026-07-03T11:49:36+08:00"):
            self.assertEqual(normalize("date", raw)["norm"], "2026-07-03", raw)
        for raw in ("Jul 02, 2025", "2 July 2025", "02-Jul-2025", "JUL.02.2025", "Jul. 2, 2025", "45840"):
            self.assertEqual(normalize("date", raw)["norm"], "2025-07-02", raw)
        self.assertEqual(normalize("date", "18/3/2025")["norm"], "2025-03-18")
        for raw in ("7/3", "TBD", "W23", "26/7/3", "2026/2/30", "", "3/4/2025", "7/2/2025", "11/26/25", "123"):
            self.assertEqual(normalize("date", raw)["status"], "unresolved", raw)

    def test_country_names_codes_and_languages_share_one_code(self) -> None:
        for raw in ("中國", "中国", "China", "china", "CHINA", "CN", "CHN", "Made in China", "中国昆山"):
            self.assertEqual(normalize("country", raw)["norm"], "CN", raw)
        for raw in ("Taiwan", "TW", "台灣", "臺灣", "台灣製"):
            self.assertEqual(normalize("country", raw)["norm"], "TW", raw)
        self.assertEqual(normalize("country", "Korea, Republic of")["norm"], "KR")

    def test_unknown_or_mixed_country_text_is_unresolved(self) -> None:
        for raw in ("tbd", "0.0, 0.0", "China or Taiwan", "Nanjing"):
            self.assertEqual(normalize("country", raw)["status"], "unresolved", raw)

    def test_quantity_drops_separators_and_keeps_unit(self) -> None:
        self.assertEqual(normalize("quantity", "1,300"), {"norm": "1300", "status": "ok", "unit": None})
        self.assertEqual(normalize("quantity", "2,500 Pcs"), {"norm": "2500", "status": "ok", "unit": "Pcs"})
        self.assertEqual(normalize("quantity", "1.50")["norm"], "1.5")
        self.assertEqual(normalize("quantity", "2.4E-2")["norm"], "0.024")
        self.assertEqual(normalize("quantity", "about ten")["status"], "unresolved")

    def test_identifier_folds_case_width_and_spacing_only(self) -> None:
        self.assertEqual(normalize("identifier", " 20.ab12C ")["norm"], "20.ab12c")
        self.assertEqual(normalize("identifier", "ＰＯ　123")["norm"], "po 123")


if __name__ == "__main__":
    unittest.main()
