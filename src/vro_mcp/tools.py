from __future__ import annotations

import sqlite3
from typing import Any

from .config import Settings
from .correction import CorrectionSuggester
from .db import CorpusStore, DictionaryStore, WordBagStore, _text_words
from .estonian_leakage import EstonianLeakageLinter
from .giella import GiellaAdapter
from .neurotolge import NeurotolgeClient

# Per-tool input caps. The dictionary/corpus tools return heavy payloads, so
# they are capped low; the word-bag and analyzer tools return tiny per-item
# results and can take many more inputs in one call.
LOOKUP_CAP = 15
USAGE_CAP = 15
EXISTS_CAP = 100
ANALYZE_CAP = 100
LEAKAGE_CAP = 100
UNRECOGNIZED_LIMIT = 500


def _prepare_batch(value: str | list[str] | None, cap: int) -> tuple[list[str], int]:
    """Normalise a single string or a list into a stripped, de-duplicated,
    order-preserving list capped at ``cap``. Returns (kept, dropped_count)."""
    if value is None:
        items: list[str] = []
    elif isinstance(value, str):
        items = [value]
    else:
        items = list(value)

    seen: set[str] = set()
    cleaned: list[str] = []
    for item in items:
        text = item.strip() if isinstance(item, str) else str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)

    dropped = max(0, len(cleaned) - cap)
    return cleaned[:cap], dropped


def _per_item_limit(limit: int | None, batched: bool) -> int:
    """Per-query result limit: smaller defaults/ceilings when batching to keep
    the combined payload manageable."""
    ceiling = 10 if batched else 50
    if limit is None:
        return 3 if batched else 10
    return max(1, min(int(limit), ceiling))


def _output_limit(limit: int | None, default: int = 50, maximum: int = UNRECOGNIZED_LIMIT) -> int:
    if limit is None:
        return default
    return max(1, min(int(limit), maximum))


class VroTools:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.dictionary = DictionaryStore(settings.dictionary_db)
        self.corpus = CorpusStore(settings.corpus_db)
        self.word_bag = WordBagStore(settings.word_bag_db)
        self.giella = GiellaAdapter(
            settings.analyzer_cmd,
            settings.generator_cmd,
            settings.speller_cmd,
            settings.grammar_cmd,
        )
        self.neurotolge = NeurotolgeClient(settings.neurotolge_base_url)
        self.estonian_leakage = EstonianLeakageLinter()
        self.correction_suggester = CorrectionSuggester(self.dictionary, self.giella)

    def lookup_word(
        self,
        query: str | list[str],
        direction: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        queries, dropped = _prepare_batch(query, LOOKUP_CAP)
        per = _per_item_limit(limit, batched=len(queries) > 1)
        try:
            results = {
                q: self.dictionary.lookup_word(q, direction=direction, limit=per)
                for q in queries
            }
        except sqlite3.Error as exc:
            return self._db_unavailable("dictionary", self.settings.dictionary_db, exc)
        out: dict[str, Any] = {
            "results": results,
            "queries": queries,
            "per_query_limit": per,
        }
        if dropped:
            out["note"] = f"Capped at {LOOKUP_CAP} queries; {dropped} extra dropped."
        return out

    def find_usage_examples(
        self,
        query: str | list[str],
        source_type: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        queries, dropped = _prepare_batch(query, USAGE_CAP)
        per = _per_item_limit(limit, batched=len(queries) > 1)
        try:
            results = {
                q: self.corpus.find_usage_examples(q, source_type=source_type, limit=per)
                for q in queries
            }
        except sqlite3.Error as exc:
            return self._db_unavailable("corpus", self.settings.corpus_db, exc)
        out: dict[str, Any] = {
            "results": results,
            "queries": queries,
            "per_query_limit": per,
        }
        if dropped:
            out["note"] = f"Capped at {USAGE_CAP} queries; {dropped} extra dropped."
        return out

    def word_exists_in_bag(
        self,
        words: str | list[str],
        include_sources: bool = True,
    ) -> dict[str, Any]:
        items, dropped = _prepare_batch(words, EXISTS_CAP)
        try:
            results = self.word_bag.exists_many(items, include_sources=include_sources)
        except sqlite3.Error as exc:
            return self._db_unavailable("word_bag", self.settings.word_bag_db, exc)
        out: dict[str, Any] = {"results": results, "checked": len(items)}
        if dropped:
            out["note"] = f"Capped at {EXISTS_CAP} words; {dropped} extra dropped."
        return out

    def find_unknown_words(self, text: str, limit: int = 50) -> dict[str, Any]:
        try:
            return self.word_bag.find_unknown_words(text, limit=limit)
        except sqlite3.Error as exc:
            return self._db_unavailable("word_bag", self.settings.word_bag_db, exc)

    def find_unrecognized_words(
        self,
        text: str,
        prefilter: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        max_rows = _output_limit(limit)
        tokens = _text_words(text)
        counts: dict[str, int] = {}
        first_seen: dict[str, str] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
            first_seen.setdefault(token, token)

        known: set[str] = set()
        if prefilter and counts:
            try:
                known = self.word_bag._known_words(counts.keys())
            except sqlite3.Error as exc:
                return self._db_unavailable("word_bag", self.settings.word_bag_db, exc)

        candidates = [
            word
            for word in sorted(counts, key=lambda item: (-counts[item], item))
            if word not in known
        ]
        if not candidates:
            out: dict[str, Any] = {
                "available": True,
                "method": "giella_analyzer",
                "prefiltered_with_word_bag": prefilter,
                "token_count": len(tokens),
                "unique_word_count": len(counts),
                "analyzer_candidate_count": 0,
                "unrecognized_count": 0,
                "returned_unrecognized_count": 0,
                "unrecognized_words": [],
                "note": "Unrecognized means the Giella analyzer returned only +? analyses, not proof the form is wrong.",
            }
            if prefilter:
                out["known_unique_count"] = len(known)
                out["prefilter_note"] = (
                    "Words present in the word bag were not analyzer-checked."
                )
            return out

        analysis = self.giella.analyze_words(candidates)
        if not analysis.get("available"):
            analysis.update(
                {
                    "method": "giella_analyzer",
                    "prefiltered_with_word_bag": prefilter,
                    "token_count": len(tokens),
                    "unique_word_count": len(counts),
                    "analyzer_candidate_count": len(candidates),
                    "unrecognized_words": [],
                }
            )
            if prefilter:
                analysis["known_unique_count"] = len(known)
            return analysis

        results = analysis.get("results", {})
        unrecognized = [
            {
                "word": first_seen[word],
                "normalized_word": word,
                "count_in_text": counts[word],
                "lines": results.get(word, {}).get("lines", []),
            }
            for word in candidates
            if not results.get(word, {}).get("recognized", False)
        ]
        out = {
            "available": True,
            "method": "giella_analyzer",
            "prefiltered_with_word_bag": prefilter,
            "token_count": len(tokens),
            "unique_word_count": len(counts),
            "analyzer_candidate_count": len(candidates),
            "unrecognized_count": len(unrecognized),
            "returned_unrecognized_count": min(len(unrecognized), max_rows),
            "unrecognized_words": unrecognized[:max_rows],
            "stderr": analysis.get("stderr", ""),
            "note": "Unrecognized means the Giella analyzer returned only +? analyses, not proof the form is wrong.",
        }
        if prefilter:
            out["known_unique_count"] = len(known)
            out["prefilter_note"] = "Words present in the word bag were not analyzer-checked."
        return out

    def analyze_word(self, words: str | list[str]) -> dict[str, Any]:
        items, dropped = _prepare_batch(words, ANALYZE_CAP)
        out = self.giella.analyze_words(items)
        out["checked"] = len(items)
        if dropped:
            out["note"] = f"Capped at {ANALYZE_CAP} words; {dropped} extra dropped."
        return out

    def lint_estonian_leakage(self, words: str | list[str]) -> dict[str, Any]:
        items, dropped = _prepare_batch(words, LEAKAGE_CAP)
        out = self.estonian_leakage.lint_words(items)
        if dropped:
            out["note"] = f"Capped at {LEAKAGE_CAP} inputs; {dropped} extra dropped."
        return out

    def suggest_correction(self, form: str) -> dict[str, Any]:
        try:
            return self.correction_suggester.suggest_correction(form)
        except sqlite3.Error as exc:
            return self._db_unavailable("dictionary", self.settings.dictionary_db, exc)

    def generate_forms(
        self,
        lemma: str,
        tags: str | None = None,
        part_of_speech: str | None = None,
    ) -> dict[str, Any]:
        return self.giella.generate_forms(lemma, tags=tags, part_of_speech=part_of_speech)

    def spellcheck_vro(self, text: str) -> dict[str, Any]:
        return self.giella.spellcheck_vro(text)

    def grammar_check_vro(self, text: str) -> dict[str, Any]:
        return self.giella.grammar_check_vro(text)

    def translate_vro(
        self,
        text: str,
        source_lang: str | None = None,
        target_lang: str | None = None,
    ) -> dict[str, Any]:
        return self.neurotolge.translate(text, source_lang=source_lang, target_lang=target_lang)

    def check_setup(self) -> dict[str, Any]:
        return {
            "databases": {
                "dictionary": self._db_availability("dictionary", self.settings.dictionary_db, "entries"),
                "corpus": self._db_availability("corpus", self.settings.corpus_db, "segments"),
                "word_bag": self._db_availability("word_bag", self.settings.word_bag_db, "words"),
            },
            "giella": self.giella.availability(),
        }

    @staticmethod
    def _db_unavailable(name: str, path: Any, exc: Exception) -> dict[str, Any]:
        return {
            "available": False,
            "error": f"{name}_db_unavailable",
            "database": name,
            "path": str(path),
            "reason": str(exc),
            "setup_hint": (
                "Populate local data with `make data` and `make giella`, or hydrate "
                "Modal data with `make deploy-release` / `make deploy-local-force`."
            ),
        }

    @classmethod
    def _db_availability(cls, name: str, path: Any, table: str) -> dict[str, Any]:
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                conn.execute(f"select 1 from {table} limit 1").fetchone()
        except sqlite3.Error as exc:
            return cls._db_unavailable(name, path, exc)
        return {"available": True, "path": str(path)}
