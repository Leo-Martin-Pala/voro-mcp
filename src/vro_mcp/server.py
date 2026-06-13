from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import load_settings
from .tools import VroTools


settings = load_settings()
tools = VroTools(settings)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_resource(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _mcp_path_from_env() -> str:
    path = os.getenv("MCP_PATH", "/mcp").strip()
    if not path:
        return "/mcp"
    if not path.startswith("/"):
        path = f"/{path}"
    return path if path.endswith("/mcp") else f"{path.rstrip('/')}/mcp"


def create_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "Python package 'mcp' is required. Install this project with `pip install -e .`."
        ) from exc

    # stateless_http lets the server run on serverless platforms where each
    # request may land on a fresh container. MCP_PATH (e.g. "/<random>/mcp")
    # keeps the public URL unguessable when hosted; it defaults to "/mcp" for
    # local use and is ignored entirely by the default stdio transport.
    mcp = FastMCP(
        "vro-mcp-server",
        host="0.0.0.0",
        stateless_http=True,
        streamable_http_path=_mcp_path_from_env(),
    )

    @mcp.resource(
        "vro://grammar/noun-cases",
        name="Võro Noun Cases",
        description=(
            "Markdown reference for Võro noun/adjective/numeral/pronoun "
            "declension, case endings, number formation, and orthography notes."
        ),
        mime_type="text/markdown",
    )
    def noun_cases() -> str:
        return _read_resource("resources/noun-cases.md")

    @mcp.resource(
        "vro://grammar/verb-conjugation",
        name="Võro Verb Conjugation",
        description=(
            "Markdown reference for Võro verb conjugation, moods, tenses, "
            "person/number endings, voice, negation, and non-finite forms."
        ),
        mime_type="text/markdown",
    )
    def verb_conjugation() -> str:
        return _read_resource("resources/verb-conjugation.md")

    @mcp.resource(
        "vro://grammar/orthography-and-standard",
        name="Võro Orthography and Standard Language",
        description=(
            "Markdown reference for the Võro writing system (alphabet, glottal "
            "stop q, palatalization, high õ, length spelling, negation spelling) "
            "and Võro Institute standard-language orientation, with a "
            "distinctive-vocabulary list versus Estonian."
        ),
        mime_type="text/markdown",
    )
    def orthography_and_standard() -> str:
        return _read_resource("resources/orthography-and-standard.md")

    @mcp.resource(
        "vro://guide/translator-prompt",
        name="Võro Translator Prompt",
        description=(
            "Markdown translator/post-editor prompt and workflow for producing "
            "Võro text: constraints, quality goals, the reference resources, and "
            "a step-by-step workflow that uses these MCP tools."
        ),
        mime_type="text/markdown",
    )
    def translator_prompt() -> str:
        return _read_resource("resources/vro-translator-prompt.md")

    @mcp.tool()
    def lookup_word(
        query: str | list[str], direction: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        """
        Look up one or more words. Pass a single string, or a list of up to 15
        strings to look up many in one call. Output is keyed by input query;
        each result is a compact concept object with language keys such as en,
        et, and vro. Direction accepts the standard values en-vro, et-vro,
        vro-en, and vro-et; directed results include a direction field and only
        that source/target language pair. Leave direction unset when unsure.
        """
        return tools.lookup_word(query, direction=direction, limit=limit)

    @mcp.tool()
    def find_usage_examples(
        query: str | list[str], source_type: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        """
        Find real usage snippets from the local Võro corpus. Pass a single
        string, or a list of up to 15 strings to search many terms at once.
        Output is keyed by input query and contains short text snippets only.
        Optional source_type filters: wiki_article for encyclopedia text,
        parallel_corpus_vro_side for translated/aligned text, and
        tei_literature for fiction/literature.
        """
        return tools.find_usage_examples(query, source_type=source_type, limit=limit)

    @mcp.tool()
    def word_exists_in_bag(words: str | list[str], include_sources: bool = True) -> dict[str, Any]:
        """
        Check whether word surface forms exist in the Võro word bag. Pass a
        single string, or a list of up to 100 words. Output is keyed by input
        word; the integer value is the stored count, with 0 meaning absent.
        Existence does not prove the form is standard or correct in context.
        """
        return tools.word_exists_in_bag(words, include_sources=include_sources)

    @mcp.tool()
    def find_unknown_words(text: str, limit: int = 50) -> dict[str, Any]:
        """
        Tokenize a larger Võro text/article and return unique word forms absent
        from the surface-form word bag. Use before or after translation to find
        forms that have not appeared in the current corpus/dictionary bag.
        Output is compact: unknown forms plus the number of checked tokens.
        """
        return tools.find_unknown_words(text, limit=limit)

    @mcp.tool()
    def find_unrecognized_words(
        text: str,
        prefilter: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Tokenize larger Võro text and return only unique word forms that the
        GiellaLT analyzer marks as unrecognized (+?). By default every unique
        token is analyzer-checked. Set prefilter=true to first skip forms already
        present in the word bag; this is faster for long text, but words in the
        bag are not analyzer-checked. Output contains only unrecognized forms,
        checked candidate count, and whether prefiltering was used.
        """
        return tools.find_unrecognized_words(text, prefilter=prefilter, limit=limit)

    @mcp.tool()
    def analyze_word(words: str | list[str]) -> dict[str, Any]:
        """
        Analyze one or more Võro words with GiellaLT. Pass a single string, or a
        list of up to 100 words analyzed in one pass; the response is keyed by
        input form. Each value is a compact list of analysis strings; an empty
        list means no recognized analysis. Treat output as guidance.
        """
        return tools.analyze_word(words)

    @mcp.tool()
    def lint_estonian_leakage(words: str | list[str]) -> dict[str, Any]:
        """
        In-depth Standard Estonian leakage linter for discrete Võro words. Pass a
        single word/short phrase, or a list of up to 100 inputs; each input is
        checked as a whole unit with no tokenization (mirrors word_exists_in_bag
        and analyze_word). For a larger passage, scan it with find_estonian_leakage
        first, then pass the flagged words/phrases here. It flags Estonian-looking
        inflectional endings such as -nud, -tud/-dud, -b, -vad, -sse, and -sid,
        returning rule IDs, severities, messages, and hints. Findings mean "this
        ending is Estonian-looking", not proof that the whole word is Estonian.
        """
        return tools.lint_estonian_leakage(words)

    @mcp.tool()
    def find_estonian_leakage(text: str, limit: int = 200) -> dict[str, Any]:
        """
        Tokenize a larger intended-Võro text and return a slim list of surface
        word forms whose ending looks like Standard Estonian (e.g. -nud, -tud/-dud,
        -b, -vad, -sse, -sid), plus any phrase-level hits such as "ei tehtud" past
        negation. Output is deduplicated and frequency-sorted, with no per-rule
        detail, so it stays small for long text. Pass any flagged word or phrase to
        lint_estonian_leakage for rule IDs, severities, messages, and hints.
        Flagged means "ending looks Estonian", not proof the word is wrong.
        """
        return tools.find_estonian_leakage(text, limit=limit)

    @mcp.tool()
    def suggest_correction(form: str) -> dict[str, Any]:
        """
        Suggest the best Võro correction for one bad or unknown form by combining
        speller suggestions, compact dictionary concepts, generated forms, and
        analyzer confirmation. The best result is only promoted when the
        candidate analyzes at weight 0.
        """
        return tools.suggest_correction(form)

    @mcp.tool()
    def generate_forms(
        lemma: str,
        tags: str | None = None,
        part_of_speech: str | None = None,
    ) -> dict[str, Any]:
        """Generate compact form list for one exact Giella analysis, e.g. lemma=uma and tags=A+Sg+Ill. This is not a full paradigm generator."""
        return tools.generate_forms(lemma, tags=tags, part_of_speech=part_of_speech)

    @mcp.tool()
    def spellcheck_vro(text: str) -> dict[str, Any]:
        """
        Token-level Võro spellcheck with GiellaLT/Divvun. Checks each word form
        against the speller lexicon and returns unknown words plus suggestions.
        It does not judge sentence grammar; suggestions are capped to keep MCP
        output compact and may be incomplete or wrong.
        """
        return tools.spellcheck_vro(text)

    @mcp.tool()
    def grammar_check_vro(text: str) -> dict[str, Any]:
        """
        Sentence-level Võro grammar check with GiellaLT/Divvun. Returns
        structured error spans when the grammar checker detects issues, including
        some typos. Use as a weak warning signal, not a final authority.
        """
        return tools.grammar_check_vro(text)

    @mcp.tool()
    def translate_vro(text: str, source_lang: str | None = None, target_lang: str | None = None) -> dict[str, Any]:
        """
        Translate text to or from Võro with Neurotõlge/TartuNLP. Use 3-letter
        API language codes. From Võro supports target_lang eng, est, fin, rus,
        hun, lav, nor. To Võro supports source_lang eng, est, fin, rus, lav,
        hun, nor. Successful output omits raw API payloads.
        """
        return tools.translate_vro(text, source_lang=source_lang, target_lang=target_lang)

    @mcp.tool()
    def check_setup() -> dict[str, Any]:
        """Report configured external-tool availability."""
        return tools.check_setup()

    return mcp


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
