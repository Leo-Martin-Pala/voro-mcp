from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .tokenization import tokenize


_DIRECTION_ALIASES = {
    "en-vro": "en-vro",
    "vro-en": "en-vro",
    "en_vro": "en-vro",
    "vro_en": "en-vro",
}

_DIRECTION_DESCRIPTIONS = {
    "en-vro": (
        "English-Võro dictionary data. Search English or Võro first; use "
        "direction aliases en-vro or vro-en when you know the side."
    ),
}

_SOURCE_TYPE_DESCRIPTIONS = {
    "wiki_article": "Võro wiki-style encyclopedia text; useful for neutral informational usage.",
    "parallel_corpus_vro_side": "Võro side of a parallel corpus; useful for translated or aligned sentence examples.",
    "tei_literature": "TEI-encoded literature and fiction; useful for literary wording and narrative prose.",
}

def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _limit(value: int | None, default: int = 10, maximum: int = 50) -> int:
    if value is None:
        return default
    return max(1, min(int(value), maximum))


def _normalise_direction(value: str | None) -> str | None:
    if value is None:
        return None
    direction = value.strip().lower()
    if not direction:
        return None
    return _DIRECTION_ALIASES.get(direction, direction)


def _normalise_word(value: str) -> str:
    return value.strip().lower()


def _text_words(text: str) -> list[str]:
    return [_normalise_word(token) for token in tokenize(text)]


def _fts_query(text: str) -> str:
    tokens = _text_words(text)
    if not tokens:
        return '""'
    return " OR ".join(tokens[:5])


class DictionaryStore:
    def __init__(self, path: Path):
        self.path = path

    def lookup_word(
        self,
        query: str,
        direction: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        max_rows = _limit(limit)
        like = f"%{query}%"
        direction = _normalise_direction(direction)

        direction_filter = "and e.direction = ?" if direction else ""
        direction_args: list[Any] = [direction] if direction else []

        sql = f"""
            with candidates as (
                select e.id, 0 as rank
                from entries e
                where e.headword = ? {direction_filter}
                union
                select e.id, 1 as rank
                from entries e join forms f on f.entry_id = e.id
                where f.form = ? {direction_filter}
                union
                select e.id, 2 as rank
                from entries e join translations t on t.entry_id = e.id
                where t.text = ? {direction_filter}
                union
                select e.id, 3 as rank
                from entries e
                where e.headword like ? {direction_filter}
                union
                select e.id, 4 as rank
                from entries e join forms f on f.entry_id = e.id
                where f.form like ? {direction_filter}
                union
                select e.id, 5 as rank
                from entries e join translations t on t.entry_id = e.id
                where t.text like ? {direction_filter}
            )
            select e.*, min(c.rank) as match_rank
            from candidates c
            join entries e on e.id = c.id
            group by e.id
            order by match_rank, length(e.headword), e.headword
            limit ?
        """
        params: list[Any] = []
        for value in (query, query, query, like, like, like):
            params.append(value)
            params.extend(direction_args)
        params.append(max_rows)

        with closing(_connect(self.path)) as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._entry(conn, row) for row in rows]

    def find_correction_entries(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        max_rows = _limit(limit, default=25, maximum=50)
        fts_query = _fts_query(query)
        like = f"%{query}%"

        sql = """
            with candidates as (
                select e.id, 0 as rank
                from entries e
                where e.headword = ?
                union
                select e.id, 1 as rank
                from entries e join forms f on f.entry_id = e.id
                where f.form = ?
                union
                select e.id, 2 as rank
                from entries e join translations t on t.entry_id = e.id
                where t.text = ?
                union
                select e.id, 3 as rank
                from entry_fts f join entries e on e.id = f.entry_id
                where entry_fts match ?
                union
                select e.id, 4 as rank
                from entries e
                where e.headword like ?
                union
                select e.id, 5 as rank
                from entries e join forms f on f.entry_id = e.id
                where f.form like ?
                union
                select e.id, 6 as rank
                from entries e join translations t on t.entry_id = e.id
                where t.text like ?
            )
            select e.*, min(c.rank) as match_rank
            from candidates c
            join entries e on e.id = c.id
            group by e.id
            order by match_rank, length(e.headword), e.headword
            limit ?
        """
        params = [query, query, query, fts_query, like, like, like, max_rows]
        with closing(_connect(self.path)) as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                fallback_sql = """
                    with candidates as (
                        select e.id, 0 as rank
                        from entries e
                        where e.headword = ?
                        union
                        select e.id, 1 as rank
                        from entries e join forms f on f.entry_id = e.id
                        where f.form = ?
                        union
                        select e.id, 2 as rank
                        from entries e join translations t on t.entry_id = e.id
                        where t.text = ?
                        union
                        select e.id, 4 as rank
                        from entries e
                        where e.headword like ?
                        union
                        select e.id, 5 as rank
                        from entries e join forms f on f.entry_id = e.id
                        where f.form like ?
                        union
                        select e.id, 6 as rank
                        from entries e join translations t on t.entry_id = e.id
                        where t.text like ?
                    )
                    select e.*, min(c.rank) as match_rank
                    from candidates c
                    join entries e on e.id = c.id
                    group by e.id
                    order by match_rank, length(e.headword), e.headword
                    limit ?
                """
                rows = conn.execute(
                    fallback_sql,
                    [query, query, query, like, like, like, max_rows],
                ).fetchall()
            return [self._entry(conn, row) for row in rows]

    def _entry(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        entry_id = row["id"]
        raw = _json_loads(row["raw_json"])
        translations = [
            dict(item)
            for item in conn.execute(
                "select language, text from translations where entry_id = ? order by id",
                (entry_id,),
            )
        ]
        forms = [
            dict(item)
            for item in conn.execute(
                "select language, form, form_type from forms where entry_id = ? order by id",
                (entry_id,),
            )
        ]
        examples = [
            dict(item)
            for item in conn.execute(
                "select source_text, target_text from examples where entry_id = ? order by id",
                (entry_id,),
            )
        ]
        notes = [
            item["text"]
            for item in conn.execute(
                "select text from notes where entry_id = ? order by id",
                (entry_id,),
            )
        ]
        return {
            "id": entry_id,
            "headword": row["headword"],
            "direction": row["direction"],
            "direction_description": _DIRECTION_DESCRIPTIONS.get(row["direction"]),
            "source_lang": row["source_lang"],
            "target_lang": row["target_lang"],
            "translations": translations,
            "forms": forms,
            "examples": examples,
            "notes": notes,
            "source_url": row["source_url"],
            "raw": {
                "external_id": row["external_id"],
                "letter": row["letter"],
                "text": raw.get("text"),
            },
        }


class WordBagStore:
    def __init__(self, path: Path):
        self.path = path

    def word_exists_in_bag(self, word: str, include_sources: bool = True) -> dict[str, Any]:
        original = word.strip()
        normalised = _normalise_word(original)
        if not normalised:
            return {"word": original, "normalized_word": normalised, "exists": False}

        with closing(_connect(self.path)) as conn:
            row = conn.execute(
                """
                select word, total_count, corpus_count, dictionary_count, puutri_count
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
                    "note": "Not found as a surface form in the current word bag.",
                }

            result = {
                "word": original,
                "normalized_word": normalised,
                "exists": True,
                "total_count": row["total_count"],
                "corpus_count": row["corpus_count"],
                "dictionary_count": row["dictionary_count"],
                "puutri_count": row["puutri_count"],
                "note": "Found as a surface form in the current word bag; this does not prove it is standard or contextually correct.",
            }
            if include_sources:
                result["sources"] = self._sources(conn, normalised)
            return result

    def exists_many(
        self,
        words: list[str],
        include_sources: bool = True,
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
                    select word, total_count, corpus_count, dictionary_count, puutri_count
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
                        "note": "Not found as a surface form in the current word bag.",
                    }
                    continue
                entry = {
                    "word": original,
                    "normalized_word": norm,
                    "exists": True,
                    "total_count": row["total_count"],
                    "corpus_count": row["corpus_count"],
                    "dictionary_count": row["dictionary_count"],
                    "puutri_count": row["puutri_count"],
                    "note": "Found as a surface form in the current word bag; this does not prove it is standard or contextually correct.",
                }
                if include_sources:
                    entry["sources"] = self._sources(conn, norm)
                results[original] = entry
        return results

    def find_unknown_words(self, text: str, limit: int | None = None) -> dict[str, Any]:
        max_rows = _limit(limit, default=50, maximum=500)
        tokens = _text_words(text)
        if not tokens:
            return {
                "token_count": 0,
                "unique_word_count": 0,
                "unknown_count": 0,
                "unknown_words": [],
            }

        counts: dict[str, int] = {}
        first_seen: dict[str, str] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
            first_seen.setdefault(token, token)

        known = self._known_words(counts.keys())
        unknown = [
            {
                "word": first_seen[word],
                "normalized_word": word,
                "count_in_text": counts[word],
            }
            for word in sorted(counts, key=lambda item: (-counts[item], item))
            if word not in known
        ]
        return {
            "token_count": len(tokens),
            "unique_word_count": len(counts),
            "known_unique_count": len(known),
            "unknown_count": len(unknown),
            "returned_unknown_count": min(len(unknown), max_rows),
            "unknown_words": unknown[:max_rows],
            "note": "Unknown means absent from the surface-form word bag, not necessarily wrong.",
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

    def _sources(self, conn: sqlite3.Connection, word: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            select s.slug, s.name, s.source_group, ws.count
            from word_sources ws
            join sources s on s.id = ws.source_id
            where ws.word = ?
            order by ws.count desc, s.slug
            """,
            (word,),
        ).fetchall()
        return [dict(row) for row in rows]


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
        params: list[Any] = [fts_query]
        if source_type:
            params.append(source_type)
        params.append(limit)
        rows = conn.execute(
            f"""
            select s.id, s.source_type, s.language, s.text, s.metadata_json,
                   d.id as document_id, d.url as document_url
            from segments_fts f
            join segments s on s.id = f.rowid
            join documents d on d.id = s.document_id
            where segments_fts match ? {source_filter}
            order by bm25(segments_fts)
            limit ?
            """,
            params,
        ).fetchall()
        return [self._usage(row) for row in rows]

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
            select s.id, s.source_type, s.language, s.text, s.metadata_json,
                   d.id as document_id, d.url as document_url
            from segments s
            join documents d on d.id = s.document_id
            where s.text like ? {source_filter}
            order by s.id
            limit ?
            """,
            params,
        ).fetchall()
        return [self._usage(row) for row in rows]

    @staticmethod
    def _phrase_query(query: str) -> str:
        escaped = query.replace('"', '""')
        if any(char.isspace() for char in escaped):
            return f'"{escaped}"'
        return escaped

    @staticmethod
    def _usage(row: sqlite3.Row) -> dict[str, Any]:
        metadata = _json_loads(row["metadata_json"])
        return {
            "segment_id": row["id"],
            "text": row["text"],
            "language": row["language"],
            "source_type": row["source_type"],
            "source_description": _SOURCE_TYPE_DESCRIPTIONS.get(row["source_type"]),
            "source": {
                "document_id": row["document_id"],
                "url": metadata.get("url") or row["document_url"],
                "section": metadata.get("section"),
                "published_time": metadata.get("published_time"),
                "issue_date_native": metadata.get("issue_date_native"),
                "raw_path": metadata.get("raw_path"),
            },
        }
