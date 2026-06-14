from __future__ import annotations

import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Any

from .tokenization import tokenize


_DIRECTION_ALIASES = {
    "en-vro": "en-vro",
    "en_vro": "en-vro",
    "vro-en": "vro-en",
    "vro_en": "vro-en",
    "et-vro": "et-vro",
    "et_vro": "et-vro",
    "vro-et": "vro-et",
    "vro_et": "vro-et",
}

_DIRECTION_PAIRS = {
    "en-vro": ("en", "vro"),
    "et-vro": ("et", "vro"),
    "vro-en": ("vro", "en"),
    "vro-et": ("vro", "et"),
}

COMMON_TERM_MATCH_THRESHOLD = 5000
_APOSTROPHE_VARIANTS = str.maketrans({
    "´": "'",
    "ʼ": "'",
    "’": "'",
    "‘": "'",
    "`": "'",
})
_COMBINING_ACUTE = "\u0301"
_PALATALIZABLE = set("bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _limit(value: int | None, default: int = 10, maximum: int = 50) -> int:
    if value is None:
        return default
    return max(1, min(int(value), maximum))


def _parse_direction(value: str | None) -> tuple[str | None, str | None, str | None]:
    if value is None:
        return None, None, None
    direction = value.strip().lower().replace(" ", "")
    if not direction:
        return None, None, None
    canonical = _DIRECTION_ALIASES.get(direction)
    if canonical:
        source_lang, target_lang = _DIRECTION_PAIRS[canonical]
        return canonical, source_lang, target_lang
    if direction in {"en", "et", "vro"}:
        return None, direction, None
    return None, None, None


def _available_directions(languages: set[str]) -> list[str]:
    return [
        direction
        for direction, (source_lang, target_lang) in _DIRECTION_PAIRS.items()
        if source_lang in languages and target_lang in languages
    ]


def normalize_db_text(value: str) -> str:
    """Normalize text the same way the SQLite lookup keys are stored."""
    text = unicodedata.normalize("NFD", value.strip().translate(_APOSTROPHE_VARIANTS))
    parts: list[str] = []
    for char in text:
        if char == _COMBINING_ACUTE and parts and parts[-1] in _PALATALIZABLE:
            parts.append("'")
            continue
        parts.append(char)
    return unicodedata.normalize("NFC", "".join(parts)).lower()


def _normalise_word(value: str) -> str:
    return normalize_db_text(value)


def _text_words(text: str) -> list[str]:
    return [_normalise_word(token) for token in tokenize(text)]


class DictionaryStore:
    def __init__(self, path: Path):
        self.path = path

    def lookup_word(
        self,
        query: str,
        direction: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        word = _normalise_word(query)
        if not word:
            return []
        max_rows = _limit(limit)
        canonical_direction, source_lang, target_lang = _parse_direction(direction)
        language_filter = "and language = ?" if source_lang else ""
        target_filter = (
            "and exists (select 1 from entries target "
            "where target.entry_id = entries.entry_id and target.language = ?)"
            if target_lang
            else ""
        )
        params: list[Any] = [word]
        if source_lang:
            params.append(source_lang)
        if target_lang:
            params.append(target_lang)
        params.append(max_rows)

        with closing(_connect(self.path)) as conn:
            entry_ids = self._matching_entry_ids(
                conn,
                word,
                max_rows,
                language_filter,
                target_filter,
                params,
            )
            return [
                self._concept(conn, entry_id, canonical_direction)
                for entry_id in entry_ids
            ]

    def find_correction_entries(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        return self.lookup_word(query, direction="vro", limit=limit)

    @staticmethod
    def _matching_entry_ids(
        conn: sqlite3.Connection,
        word: str,
        max_rows: int,
        language_filter: str,
        target_filter: str,
        exact_params: list[Any],
    ) -> list[str]:
        entry_ids = [
            row["entry_id"]
            for row in conn.execute(
                f"""
                select distinct entry_id
                from entries
                where word = ? {language_filter} {target_filter}
                order by entry_id
                limit ?
                """,
                exact_params,
            )
        ]
        if entry_ids:
            return entry_ids

        substring_params = list(exact_params)
        substring_params[0] = f"%{word}%"
        return [
            row["entry_id"]
            for row in conn.execute(
                f"""
                select distinct entry_id
                from entries
                where word like ? {language_filter} {target_filter}
                order by length(word), entry_id
                limit ?
                """,
                substring_params,
            )
        ]

    @staticmethod
    def _format_term(row: sqlite3.Row) -> str:
        word = row["word"]
        info = row["info"]
        return f"{word} ({info})" if info else word

    def _concept(
        self,
        conn: sqlite3.Connection,
        entry_id: str,
        direction: str | None = None,
    ) -> dict[str, Any]:
        concept: dict[str, Any] = {}
        if direction:
            concept["direction"] = direction
        rows = conn.execute(
            """
            select language, word, info
            from entries
            where entry_id = ?
            order by language, word
            """,
            (entry_id,),
        )
        allowed_languages = set(_DIRECTION_PAIRS[direction]) if direction else None
        for row in rows:
            if allowed_languages is not None and row["language"] not in allowed_languages:
                continue
            concept.setdefault(row["language"], []).append(self._format_term(row))
        if not direction:
            languages = {key for key in concept if key in {"en", "et", "vro"}}
            concept["available_directions"] = _available_directions(languages)
        return concept


class WordBagStore:
    def __init__(self, path: Path):
        self.path = path

    def word_exists_in_bag(self, word: str) -> dict[str, Any]:
        original = word.strip()
        normalised = _normalise_word(original)
        if not normalised:
            return {"word": original, "normalized_word": normalised, "exists": False}

        with closing(_connect(self.path)) as conn:
            row = conn.execute(
                """
                select word, total_count
                from words
                where word = ?
                """,
                (normalised,),
            ).fetchone()
            if row is None:
                return {
                    "word": original,
                    "normalized_word": normalised,
                    "exists": False,
                    "total_count": 0,
                }

            result = {
                "word": original,
                "normalized_word": normalised,
                "exists": True,
                "total_count": row["total_count"],
            }
            return result

    def exists_many(
        self,
        words: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Batched word_exists_in_bag. Returns a map keyed by the ORIGINAL input
        string. Existence is checked with a single IN query per 500-word chunk."""
        pairs = [(original, _normalise_word(original)) for original in words]
        norms = [norm for _, norm in pairs if norm]
        results: dict[str, dict[str, Any]] = {}
        if not norms:
            for original, norm in pairs:
                results[original] = {"word": original, "normalized_word": norm, "exists": False}
            return results

        with closing(_connect(self.path)) as conn:
            rows: dict[str, sqlite3.Row] = {}
            for index in range(0, len(norms), 500):
                chunk = norms[index:index + 500]
                placeholders = ",".join("?" for _ in chunk)
                for row in conn.execute(
                    f"""
                    select word, total_count
                    from words where word in ({placeholders})
                    """,
                    chunk,
                ):
                    rows[row["word"]] = row

            for original, norm in pairs:
                if not norm:
                    results[original] = {"word": original, "normalized_word": norm, "exists": False}
                    continue
                row = rows.get(norm)
                if row is None:
                    results[original] = {
                        "word": original,
                        "normalized_word": norm,
                        "exists": False,
                        "total_count": 0,
                    }
                    continue
                entry = {
                    "word": original,
                    "normalized_word": norm,
                    "exists": True,
                    "total_count": row["total_count"],
                }
                results[original] = entry
        return results

    def find_unknown_words(self, text: str, limit: int | None = None) -> dict[str, Any]:
        max_rows = _limit(limit, default=50, maximum=500)
        tokens = _text_words(text)
        if not tokens:
            return {
                "unknown": [],
                "checked": 0,
            }

        counts: dict[str, int] = {}
        first_seen: dict[str, str] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
            first_seen.setdefault(token, token)

        known = self._known_words(counts.keys())
        unknown = [
            first_seen[word]
            for word in sorted(counts, key=lambda item: (-counts[item], item))
            if word not in known
        ]
        return {
            "unknown": unknown[:max_rows],
            "checked": len(tokens),
        }

    def _known_words(self, words: Any) -> set[str]:
        word_list = list(words)
        if not word_list:
            return set()
        known: set[str] = set()
        with closing(_connect(self.path)) as conn:
            for index in range(0, len(word_list), 500):
                chunk = word_list[index:index + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"select word from words where word in ({placeholders})",
                    chunk,
                ).fetchall()
                known.update(row["word"] for row in rows)
        return known

class CorpusStore:
    def __init__(self, path: Path):
        self.path = path

    def find_usage_examples(
        self,
        query: str,
        source_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        max_rows = _limit(limit)

        with closing(_connect(self.path)) as conn:
            try:
                return self._fts_search(conn, query, source_type, max_rows)
            except sqlite3.OperationalError:
                return self._like_search(conn, query, source_type, max_rows)

    def _fts_search(
        self,
        conn: sqlite3.Connection,
        query: str,
        source_type: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        fts_query = self._phrase_query(query)
        source_filter = "and s.source_type = ?" if source_type else ""
        count_params: list[Any] = [fts_query]
        if source_type:
            count_params.append(source_type)
        match_count = conn.execute(
            f"""
            select count(*) as total
            from segments_fts f
            join segments s on s.id = f.rowid
            where segments_fts match ? {source_filter}
            """,
            count_params,
        ).fetchone()["total"]

        params = [*count_params, limit]
        order_clause = (
            ""
            if match_count > COMMON_TERM_MATCH_THRESHOLD
            else "order by bm25(segments_fts)"
        )
        rows = conn.execute(
            f"""
            select s.text
            from segments_fts f
            join segments s on s.id = f.rowid
            where segments_fts match ? {source_filter}
            {order_clause}
            limit ?
            """,
            params,
        ).fetchall()
        return [self._snippet(row["text"], query) for row in rows]

    def _like_search(
        self,
        conn: sqlite3.Connection,
        query: str,
        source_type: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        source_filter = "and s.source_type = ?" if source_type else ""
        params: list[Any] = [f"%{query}%"]
        if source_type:
            params.append(source_type)
        params.append(limit)
        rows = conn.execute(
            f"""
            select s.text
            from segments s
            where s.text like ? {source_filter}
            order by s.id
            limit ?
            """,
            params,
        ).fetchall()
        return [self._snippet(row["text"], query) for row in rows]

    @staticmethod
    def _phrase_query(query: str) -> str:
        escaped = query.replace('"', '""')
        if any(char.isspace() for char in escaped):
            return f'"{escaped}"'
        return escaped

    @staticmethod
    def _snippet(text: str, query: str, max_chars: int = 260) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= max_chars:
            return normalized

        folded = normalized.casefold()
        needles = [query.casefold(), *_text_words(query)]
        match_at = -1
        match_len = 0
        for needle in needles:
            if not needle:
                continue
            match_at = folded.find(needle.casefold())
            if match_at >= 0:
                match_len = len(needle)
                break

        if match_at < 0:
            return f"{normalized[:max_chars].rstrip()} ..."

        before = 90
        start = max(0, match_at - before)
        end = min(len(normalized), start + max_chars)
        start = max(0, end - max_chars)
        snippet = normalized[start:end].strip()
        if start:
            snippet = f"... {snippet}"
        if end < len(normalized):
            snippet = f"{snippet} ..."
        return snippet
