from __future__ import annotations

import unittest

from vro_mcp.tokenization import tokenize


class TokenizationTests(unittest.TestCase):
    def test_hyphenated_negatives_stay_whole(self) -> None:
        self.assertEqual(tokenize("olõ-i saa-i tunnõ-i"), ["olõ-i", "saa-i", "tunnõ-i"])

    def test_apostrophe_marks_stay_attached(self) -> None:
        self.assertEqual(
            tokenize("Claude'ile Codexile ChatGPT-le"),
            ["Claude'ile", "Codexile", "ChatGPT-le"],
        )
        self.assertEqual(tokenize("tä' kal' näʼe"), ["tä'", "kal'", "näʼe"])

    def test_final_q_is_kept(self) -> None:
        self.assertEqual(tokenize("tetäq mõistaq luvvaq"), ["tetäq", "mõistaq", "luvvaq"])

    def test_numbers_dates_times_drop_out(self) -> None:
        self.assertEqual(tokenize("hind 1 043,88 eurot"), ["hind", "eurot"])
        self.assertEqual(tokenize("aastal 1 000 000"), ["aastal"])
        self.assertEqual(tokenize("kell 14:30 kuupäiv 08.06.2026"), ["kell", "kuupäiv"])

    def test_urls_and_emails_are_skipped(self) -> None:
        self.assertEqual(
            tokenize("Kae https://wikipedia.org/wiki/Võro lehte"),
            ["Kae", "lehte"],
        )
        self.assertEqual(tokenize("var www.vro.ee man"), ["var", "man"])
        self.assertEqual(tokenize("saadaq a.b@näide.ee pääle"), ["saadaq", "pääle"])


if __name__ == "__main__":
    unittest.main()
