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
        out: dict[str, Any] = results
        if dropped:
            out["_dropped"] = dropped
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
        out: dict[str, Any] = results
        if dropped:
            out["_dropped"] = dropped
        return out

    def word_exists_in_bag(
        self,
        words: str | list[str],
        include_sources: bool = True,
    ) -> dict[str, Any]:
        items, dropped = _prepare_batch(words, EXISTS_CAP)
        try:
            rows = self.word_bag.exists_many(items, include_sources=include_sources)
        except sqlite3.Error as exc:
            return self._db_unavailable("word_bag", self.settings.word_bag_db, exc)
        out: dict[str, Any] = {
            original: int(result.get("total_count", 0))
            for original, result in rows.items()
        }
        if dropped:
            out["_dropped"] = dropped
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
            return {"unrecognized": [], "checked": 0, "prefiltered": prefilter}

        analysis = self.giella.analyze_words(candidates)
        if not analysis.get("available"):
            analysis.update(
                {
                    "checked": len(candidates),
                    "unrecognized": [],
                    "prefiltered": prefilter,
                }
            )
            return analysis

        results = analysis.get("results", {})
        unrecognized = [
            first_seen[word]
            for word in candidates
            if not results.get(word, {}).get("recognized", False)
        ]
        return {
            "unrecognized": unrecognized[:max_rows],
            "checked": len(candidates),
            "prefiltered": prefilter,
        }

    def analyze_word(self, words: str | list[str]) -> dict[str, Any]:
        items, dropped = _prepare_batch(words, ANALYZE_CAP)
        result = self.giella.analyze_words(items)
        if not result.get("available"):
            return result
        raw_results = result.get("results", {})
        out: dict[str, Any] = {}
        for item in items:
            lines = raw_results.get(item, {}).get("lines", [])
            out[item] = [
                parts[1]
                for line in lines
                if not line.rstrip().endswith("+?")
                if len(parts := line.split("\t")) >= 2
            ]
        if dropped:
            out["_dropped"] = dropped
        return out

    def lint_estonian_leakage(self, words: str | list[str]) -> dict[str, Any]:
        items, dropped = _prepare_batch(words, LEAKAGE_CAP)
        out = self.estonian_leakage.lint_words(items)
        if dropped:
            out["note"] = f"Capped at {LEAKAGE_CAP} inputs; {dropped} extra dropped."
        return out

    def find_estonian_leakage(self, text: str, limit: int = 200) -> dict[str, Any]:
        max_rows = _output_limit(limit, default=200, maximum=500)
        return self.estonian_leakage.find_in_text(text, limit=max_rows)

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
        result = self.giella.generate_forms(lemma, tags=tags, part_of_speech=part_of_speech)
        if not result.get("available"):
            return result
        forms = []
        for line in result.get("lines", []):
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1].strip():
                forms.append(parts[1].strip())
        return {"forms": forms}

    def spellcheck_vro(self, text: str) -> dict[str, Any]:
        result = self.giella.spellcheck_vro(text)
        if not result.get("available"):
            return result
        return {"lines": result.get("lines", [])}

    def grammar_check_vro(self, text: str) -> dict[str, Any]:
        result = self.giella.grammar_check_vro(text)
        if not result.get("available"):
            return result
        return {"lines": result.get("lines", [])}

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
                "dictionary": self._db_availability(
                    "dictionary",
                    self.settings.dictionary_db,
                    {"entries": {"entry_id", "source", "language", "word", "info"}},
                ),
                "corpus": self._db_availability(
                    "corpus",
                    self.settings.corpus_db,
                    {
                        "segments": {
                            "id",
                            "public_id",
                            "source_slug",
                            "source_type",
                            "document_id",
                            "segment_index",
                            "text",
                        },
                        "segments_fts": {"text"},
                    },
                ),
                "word_bag": self._db_availability(
                    "word_bag",
                    self.settings.word_bag_db,
                    {"words": {"word", "total_count"}},
                ),
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
    def _db_availability(
        cls,
        name: str,
        path: Any,
        required_schema: dict[str, set[str]],
    ) -> dict[str, Any]:
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                for table, required_columns in required_schema.items():
                    row = conn.execute(
                        "select 1 from sqlite_master where name = ? limit 1",
                        (table,),
                    ).fetchone()
                    if row is None:
                        raise sqlite3.OperationalError(f"missing required table: {table}")
                    columns = {
                        item[1]
                        for item in conn.execute(f"pragma table_info({table})")
                    }
                    missing = sorted(required_columns - columns)
                    if missing:
                        raise sqlite3.OperationalError(
                            f"{table} missing required column(s): {', '.join(missing)}"
                        )
                first_table = next(iter(required_schema))
                conn.execute(f"select 1 from {first_table} limit 1").fetchone()
        except sqlite3.Error as exc:
            return cls._db_unavailable(name, path, exc)
        return {"available": True, "path": str(path)}
