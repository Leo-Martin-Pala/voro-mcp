from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from vro_mcp.config import load_settings
from vro_mcp.server import _mcp_path_from_env, _read_resource
from vro_mcp.tools import VroTools


DATA_HINT = "run `make data` (or `make setup`) to download the datasets"
GIELLA_HINT = "run `make giella` (or `make setup`) to install the Giella tools"


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = VroTools(load_settings())
        status = cls.tools.check_setup()
        cls.db_available = {
            name: bool(info.get("available")) for name, info in status["databases"].items()
        }
        cls.giella_available = {
            key: bool(info.get("available")) for key, info in status["giella"].items()
        }

    def _require_db(self, *names: str) -> None:
        missing = [name for name in names if not self.db_available.get(name)]
        if missing:
            self.skipTest(f"{', '.join(missing)} database not installed — {DATA_HINT}")

    def _require_giella(self, *keys: str) -> None:
        missing = [key for key in keys if not self.giella_available.get(key)]
        if missing:
            self.skipTest(f"Giella {', '.join(missing)} not installed — {GIELLA_HINT}")

    def test_lookup_word_runs(self) -> None:
        self._require_db("dictionary")
        out = self.tools.lookup_word("world", limit=1)
        results = out["world"]
        self.assertTrue(results)
        self.assertEqual(results[0]["en"], ["world"])
        self.assertIn("maailm", results[0]["vro"])

    def test_lookup_word_batched_is_keyed(self) -> None:
        self._require_db("dictionary")
        out = self.tools.lookup_word(["world", "water"])
        self.assertEqual(set(out), {"world", "water"})
        self.assertTrue(out["world"])

    def test_find_usage_examples_runs(self) -> None:
        self._require_db("corpus")
        out = self.tools.find_usage_examples("naasõ", limit=1)
        results = out["naasõ"]
        self.assertTrue(results)
        self.assertIsInstance(results[0], str)
        self.assertLessEqual(len(results[0]), 266)
        self.assertNotIn("public_id", results[0])

    def test_word_exists_in_bag_runs(self) -> None:
        self._require_db("word_bag")
        out = self.tools.word_exists_in_bag("Miä", include_sources=False)
        self.assertGreater(out["Miä"], 0)

    def test_word_exists_in_bag_batched_is_keyed(self) -> None:
        self._require_db("word_bag")
        out = self.tools.word_exists_in_bag(["Miä", "xyzzyvrotest"], include_sources=False)
        self.assertGreater(out["Miä"], 0)
        self.assertEqual(out["xyzzyvrotest"], 0)

    def test_find_unknown_words_runs(self) -> None:
        self._require_db("word_bag")
        result = self.tools.find_unknown_words("Miä olõ hüä xyzzyvrotest", limit=10)
        self.assertIn("xyzzyvrotest", result["unknown"])
        self.assertEqual(result["checked"], 4)

    def test_find_unrecognized_words_runs(self) -> None:
        result = self.tools.find_unrecognized_words("Miä olõ hüä xyzzyvrotest", limit=10)
        if result.get("available") is False:
            self.skipTest("analyzer not available in this environment")
        self.assertIn("xyzzyvrotest", result["unrecognized"])
        self.assertNotIn("miä", result["unrecognized"])
        self.assertFalse(result["prefiltered"])
        self.assertGreaterEqual(result["checked"], 4)

    def test_find_unrecognized_words_prefilter_runs(self) -> None:
        result = self.tools.find_unrecognized_words(
            "Miä olõ hüä xyzzyvrotest",
            prefilter=True,
            limit=10,
        )
        if result.get("available") is False:
            self.skipTest("analyzer not available in this environment")
        self.assertIn("xyzzyvrotest", result["unrecognized"])
        self.assertTrue(result["prefiltered"])
        self.assertLess(result["checked"], 4)

    def test_giella_unavailable_is_structured(self) -> None:
        tools = VroTools(replace(load_settings(), analyzer_cmd="/tmp/no-such-analyzer"))
        result = tools.analyze_word("võro")
        self.assertIn("available", result)
        self.assertIn("setup", result)

    def test_analyze_word_batched_is_keyed(self) -> None:
        out = self.tools.analyze_word(["uma", "kala"])
        if out.get("available") is False:
            self.skipTest("analyzer not available in this environment")
        self.assertEqual(set(out), {"uma", "kala"})
        self.assertTrue(out["kala"])

    def test_lint_estonian_leakage_flags_estonian_like_endings(self) -> None:
        out = self.tools.lint_estonian_leakage(["teinud", "kirjutab", "kalaq"])
        self.assertEqual(out["checked"], 3)
        self.assertTrue(out["results"]["teinud"]["flagged"])
        self.assertEqual(
            out["results"]["teinud"]["matches"][0]["rule_id"],
            "EST_ACTIVE_PAST_NUD",
        )
        self.assertEqual(
            out["results"]["kirjutab"]["matches"][0]["rule_id"],
            "EST_3SG_PRESENT_B",
        )
        self.assertFalse(out["results"]["kalaq"]["flagged"])

    def test_lint_estonian_leakage_does_not_tokenize_inputs(self) -> None:
        # A whole phrase is treated as one unit; the window rule fires via search.
        out = self.tools.lint_estonian_leakage("ei teinud")
        self.assertEqual(out["checked"], 1)
        self.assertEqual(set(out["results"]), {"ei teinud"})
        self.assertEqual(out["results"]["ei teinud"]["matches"][0]["rule_id"], "EST_NEG_PAST_EI_NUD")

    def test_lint_estonian_leakage_allowlist(self) -> None:
        out = self.tools.lint_estonian_leakage("maks")
        self.assertFalse(out["results"]["maks"]["flagged"])

    def test_find_estonian_leakage_slim_scan(self) -> None:
        text = "Tä läheb kodo. Üts asi om tehtud. Timä ei teinud taad. Tehtud sai tehtud."
        out = self.tools.find_estonian_leakage(text)
        # Slim: surface strings only, deduped and frequency-sorted.
        self.assertEqual(out["flagged_words"][0], "tehtud")  # most frequent
        self.assertIn("läheb", out["flagged_words"])
        self.assertIn("ei teinud", out["flagged_phrases"])
        self.assertNotIn("tokens", out)
        self.assertNotIn("matches", out)

    def test_find_estonian_leakage_keeps_voro_words(self) -> None:
        out = self.tools.find_estonian_leakage("Ma olõ-i tennüq taad tüüd mõistaq.")
        self.assertEqual(out["flagged_words"], [])
        self.assertEqual(out["flagged_phrases"], [])

    def test_suggest_correction_returns_valid_form_as_already_valid(self) -> None:
        self._require_giella("analyzer")
        result = self.tools.suggest_correction("köüdet")
        self.assertEqual(result["status"], "already_valid")
        self.assertEqual(result["best"]["form"], "köüdet")

    def test_suggest_correction_combines_dictionary_generation_and_analyzer(self) -> None:
        result = self.tools.suggest_correction("seotud")
        if result.get("best", {}).get("form") != "köüdet":
            self.skipTest("public dictionary does not contain the expected köütmä correction path")
        self.assertEqual(result["status"], "suggested")
        self.assertEqual(result["best"]["form"], "köüdet")
        self.assertTrue(any(line.endswith("\t0") for line in result["best"]["analyses"]))

    def test_spellcheck_tokenizes_sentence_input(self) -> None:
        self._require_giella("speller")
        result = self.tools.spellcheck_vro("Miä olõ hüä tekstt.")
        output = "\n".join(result.get("lines", []))
        self.assertIn('"tekstt" is NOT in the lexicon', output)
        self.assertNotIn('"miä" is NOT in the lexicon', output)

    def test_generate_forms_runs_with_giella_tags(self) -> None:
        self._require_giella("generator")
        result = self.tools.generate_forms("uma", tags="A+Sg+Ill")
        self.assertIn("umma", result.get("forms", []))

    def test_lookup_word_accepts_standard_direction(self) -> None:
        self._require_db("dictionary")
        out = self.tools.lookup_word("vesi", direction="vro-en", limit=1)
        self.assertEqual(out["vesi"][0]["direction"], "vro-en")
        self.assertTrue(out["vesi"][0]["en"])
        self.assertTrue(out["vesi"][0]["vro"])

    def test_lookup_word_supports_standard_directions(self) -> None:
        self._require_db("dictionary")
        cases = {
            "en-vro": ("world", "en", "vro"),
            "et-vro": ("maailm", "et", "vro"),
            "vro-en": ("vesi", "vro", "en"),
            "vro-et": ("vesi", "vro", "et"),
        }
        for direction, (query, source_lang, target_lang) in cases.items():
            with self.subTest(direction=direction):
                out = self.tools.lookup_word(query, direction=direction, limit=1)
                self.assertTrue(out[query])
                result = out[query][0]
                self.assertEqual(result["direction"], direction)
                self.assertTrue(result[source_lang])
                self.assertTrue(result[target_lang])

    def test_grammar_resources_are_readable(self) -> None:
        self.assertIn("Võro noun declension", _read_resource("resources/noun-cases.md"))
        self.assertIn("Võro verb conjugation", _read_resource("resources/verb-conjugation.md"))
        self.assertIn(
            "Võro orthography and standard language",
            _read_resource("resources/orthography-and-standard.md"),
        )
        self.assertIn(
            "Võro-language translator",
            _read_resource("resources/vro-translator-prompt.md"),
        )

    def test_mcp_path_from_env_adds_missing_leading_slash(self) -> None:
        with patch.dict("os.environ", {"MCP_PATH": "secret"}):
            self.assertEqual(_mcp_path_from_env(), "/secret/mcp")

    def test_translate_rejects_unsupported_pair_locally(self) -> None:
        result = self.tools.translate_vro("Tere", source_lang="deu", target_lang="vro")
        self.assertEqual(result["error"], "unsupported_translation_pair")
        self.assertNotIn("ger", result["supported_to_vro"])

    def test_missing_dictionary_db_is_structured(self) -> None:
        tools = VroTools(replace(load_settings(), dictionary_db=Path("/tmp/no-such-dict.sqlite")))
        result = tools.lookup_word("world")
        self.assertFalse(result["available"])
        self.assertEqual(result["error"], "dictionary_db_unavailable")
        self.assertEqual(result["database"], "dictionary")
        self.assertIn("setup_hint", result)

    def test_missing_corpus_db_is_structured(self) -> None:
        tools = VroTools(replace(load_settings(), corpus_db=Path("/tmp/no-such-corpus.sqlite")))
        result = tools.find_usage_examples("naasõ")
        self.assertFalse(result["available"])
        self.assertEqual(result["error"], "corpus_db_unavailable")
        self.assertEqual(result["database"], "corpus")
        self.assertIn("setup_hint", result)

    def test_missing_word_bag_db_is_structured(self) -> None:
        tools = VroTools(replace(load_settings(), word_bag_db=Path("/tmp/no-such-bag.sqlite")))
        result = tools.word_exists_in_bag("Miä")
        self.assertFalse(result["available"])
        self.assertEqual(result["error"], "word_bag_db_unavailable")
        self.assertEqual(result["database"], "word_bag")
        self.assertIn("setup_hint", result)

    def test_find_unrecognized_words_prefilter_missing_word_bag_is_structured(self) -> None:
        tools = VroTools(replace(load_settings(), word_bag_db=Path("/tmp/no-such-bag.sqlite")))
        result = tools.find_unrecognized_words("Miä olõ hüä", prefilter=True)
        self.assertFalse(result["available"])
        self.assertEqual(result["error"], "word_bag_db_unavailable")
        self.assertEqual(result["database"], "word_bag")
        self.assertIn("setup_hint", result)

    def test_check_setup_reports_databases(self) -> None:
        self._require_db("dictionary")
        result = self.tools.check_setup()
        self.assertIn("databases", result)
        self.assertTrue(result["databases"]["dictionary"]["available"])


if __name__ == "__main__":
    unittest.main()
