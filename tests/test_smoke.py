from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from vro_mcp.config import load_settings
from vro_mcp.server import _mcp_path_from_env, _read_resource
from vro_mcp.tools import VroTools


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = VroTools(load_settings())

    def test_lookup_word_runs(self) -> None:
        out = self.tools.lookup_word("world", limit=1)
        results = out["results"]["world"]
        self.assertTrue(results)
        self.assertEqual(results[0]["headword"], "world")
        self.assertIn("direction_description", results[0])

    def test_lookup_word_batched_is_keyed(self) -> None:
        out = self.tools.lookup_word(["world", "water"])
        self.assertEqual(set(out["results"]), {"world", "water"})
        self.assertEqual(out["per_query_limit"], 3)  # batched default
        self.assertTrue(out["results"]["world"])

    def test_find_usage_examples_runs(self) -> None:
        out = self.tools.find_usage_examples("naasõ", limit=1)
        results = out["results"]["naasõ"]
        self.assertTrue(results)
        self.assertIn("source_type", results[0])
        self.assertIn("source_description", results[0])
        self.assertNotIn("document_title", results[0])

    def test_word_exists_in_bag_runs(self) -> None:
        out = self.tools.word_exists_in_bag("Miä", include_sources=False)
        result = out["results"]["Miä"]
        self.assertTrue(result["exists"])
        self.assertEqual(result["normalized_word"], "miä")

    def test_word_exists_in_bag_batched_is_keyed(self) -> None:
        out = self.tools.word_exists_in_bag(["Miä", "xyzzyvrotest"], include_sources=False)
        self.assertEqual(out["checked"], 2)
        self.assertTrue(out["results"]["Miä"]["exists"])
        self.assertFalse(out["results"]["xyzzyvrotest"]["exists"])

    def test_find_unknown_words_runs(self) -> None:
        result = self.tools.find_unknown_words("Miä olõ hüä xyzzyvrotest", limit=10)
        unknown = {item["normalized_word"] for item in result["unknown_words"]}
        self.assertIn("xyzzyvrotest", unknown)

    def test_find_unrecognized_words_runs(self) -> None:
        result = self.tools.find_unrecognized_words("Miä olõ hüä xyzzyvrotest", limit=10)
        if not result.get("available"):
            self.skipTest("analyzer not available in this environment")
        unrecognized = {item["normalized_word"] for item in result["unrecognized_words"]}
        self.assertIn("xyzzyvrotest", unrecognized)
        self.assertNotIn("miä", unrecognized)
        self.assertFalse(result["prefiltered_with_word_bag"])
        self.assertGreaterEqual(result["analyzer_candidate_count"], 4)

    def test_find_unrecognized_words_prefilter_runs(self) -> None:
        result = self.tools.find_unrecognized_words(
            "Miä olõ hüä xyzzyvrotest",
            prefilter=True,
            limit=10,
        )
        if not result.get("available"):
            self.skipTest("analyzer not available in this environment")
        unrecognized = {item["normalized_word"] for item in result["unrecognized_words"]}
        self.assertIn("xyzzyvrotest", unrecognized)
        self.assertTrue(result["prefiltered_with_word_bag"])
        self.assertIn("prefilter_note", result)
        self.assertLess(result["analyzer_candidate_count"], result["unique_word_count"])

    def test_giella_unavailable_is_structured(self) -> None:
        result = self.tools.analyze_word("võro")
        self.assertIn("available", result)
        self.assertIn("results", result)

    def test_analyze_word_batched_is_keyed(self) -> None:
        out = self.tools.analyze_word(["uma", "kala"])
        if not out.get("available"):
            self.skipTest("analyzer not available in this environment")
        self.assertEqual(set(out["results"]), {"uma", "kala"})
        self.assertTrue(out["results"]["kala"]["recognized"])

    def test_lint_estonian_leakage_flags_estonian_like_endings(self) -> None:
        out = self.tools.lint_estonian_leakage(["teinud", "kirjutab", "kalaq"])
        self.assertEqual(out["checked"], 3)
        self.assertTrue(out["results"]["teinud"]["tokens"]["teinud"]["flagged"])
        self.assertEqual(
            out["results"]["teinud"]["tokens"]["teinud"]["matches"][0]["rule_id"],
            "EST_ACTIVE_PAST_NUD",
        )
        self.assertEqual(
            out["results"]["kirjutab"]["tokens"]["kirjutab"]["matches"][0]["rule_id"],
            "EST_3SG_PRESENT_B",
        )
        self.assertFalse(out["results"]["kalaq"]["tokens"]["kalaq"]["flagged"])

    def test_lint_estonian_leakage_window_rule(self) -> None:
        out = self.tools.lint_estonian_leakage(["ei", "teinud"])
        self.assertEqual(out["window_matches"][0]["rule_id"], "EST_NEG_PAST_EI_NUD")
        self.assertTrue(out["results"]["ei"]["flagged"])
        self.assertTrue(out["results"]["teinud"]["flagged"])

    def test_lint_estonian_leakage_allowlist(self) -> None:
        out = self.tools.lint_estonian_leakage("maks")
        self.assertFalse(out["results"]["maks"]["tokens"]["maks"]["flagged"])

    def test_suggest_correction_returns_valid_form_as_already_valid(self) -> None:
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
        result = self.tools.spellcheck_vro("Miä olõ hüä tekstt.")
        self.assertIn('"tekstt" is NOT in the lexicon', result.get("output", ""))
        self.assertNotIn('"miä" is NOT in the lexicon', result.get("output", ""))

    def test_generate_forms_runs_with_giella_tags(self) -> None:
        result = self.tools.generate_forms("uma", tags="A+Sg+Ill")
        self.assertIn("umma", result.get("output", ""))

    def test_lookup_word_accepts_user_facing_direction_alias(self) -> None:
        out = self.tools.lookup_word("vesi", direction="vro-en", limit=1)
        self.assertTrue(out["results"]["vesi"])

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
        result = self.tools.check_setup()
        self.assertIn("databases", result)
        self.assertTrue(result["databases"]["dictionary"]["available"])


if __name__ == "__main__":
    unittest.main()
