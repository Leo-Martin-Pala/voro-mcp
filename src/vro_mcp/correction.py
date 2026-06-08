from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .db import DictionaryStore
from .giella import GiellaAdapter


TOKEN_RE = re.compile(r"(?iu)[^\W\d_][^\W\d_'´-]*(?:['´-][^\W\d_]+)*")
SPELLING_SUGGESTION_RE = re.compile(r"^(.+?)\s+([0-9]+(?:\.[0-9]+)?)$")
VERB_INF_TAGS = ("+V+Inf/mA", "+V+Inf")


@dataclass
class Candidate:
    form: str
    source: str
    source_rank: int
    score: float
    details: list[dict[str, Any]] = field(default_factory=list)
    analyses: list[str] = field(default_factory=list)

    def add(self, source: str, source_rank: int, score: float, detail: dict[str, Any]) -> None:
        self.source_rank = min(self.source_rank, source_rank)
        self.score = min(self.score, score)
        self.details.append({"source": source, **detail})


class CorrectionSuggester:
    def __init__(self, dictionary: DictionaryStore, giella: GiellaAdapter) -> None:
        self.dictionary = dictionary
        self.giella = giella

    def suggest_correction(self, form: str) -> dict[str, Any]:
        original = form.strip()
        if not original:
            return {"form": original, "status": "empty", "best": None, "candidates": []}

        original_analysis = self.giella.analyze_words([original])
        if self._is_weight_zero(original_analysis, original):
            return {
                "form": original,
                "status": "already_valid",
                "best": {
                    "form": original,
                    "source": "analyzer",
                    "confidence": "confirmed",
                    "analyses": original_analysis["results"][original]["lines"],
                },
                "candidates": [],
                "evidence": {"analyzer": original_analysis},
            }

        candidates: dict[str, Candidate] = {}
        evidence: dict[str, Any] = {"analyzer": original_analysis}

        spelling = self.giella.spellcheck_vro(original)
        evidence["speller"] = spelling
        for rank, item in enumerate(self._parse_speller_suggestions(spelling), start=1):
            self._add_candidate(
                candidates,
                item["form"],
                "speller",
                20 + rank,
                item["weight"],
                {"weight": item["weight"], "rank": rank},
            )

        dictionary_entries = self.dictionary.find_correction_entries(original, limit=40)
        evidence["dictionary_entries"] = self._compact_entries(dictionary_entries)
        for entry_rank, entry in enumerate(dictionary_entries, start=1):
            for token in self._vro_tokens_from_entry(entry):
                self._add_candidate(
                    candidates,
                    token,
                    "dictionary",
                    10 + entry_rank,
                    float(entry_rank),
                    {"entry_id": entry["id"], "headword": entry["headword"]},
                )

        analyzed = self._analyze_candidates(candidates)
        generated = self._generate_inflection_candidates(original, analyzed)
        for item in generated:
            self._add_candidate(
                candidates,
                item["form"],
                "dictionary_generated",
                1,
                item["score"],
                item,
            )

        analyzed = self._analyze_candidates(candidates)
        confirmed = [candidate for candidate in analyzed.values() if candidate.analyses]
        confirmed.sort(key=self._ranking_key)

        best = self._candidate_payload(confirmed[0]) if confirmed else None
        return {
            "form": original,
            "status": "suggested" if best else "no_confirmed_candidate",
            "best": best,
            "candidates": [self._candidate_payload(candidate) for candidate in confirmed[:10]],
            "evidence": evidence,
        }

    def _generate_inflection_candidates(
        self,
        original: str,
        candidates: dict[str, Candidate],
    ) -> list[dict[str, Any]]:
        tags = self._target_generation_tags(original)
        if not tags:
            return []

        generated: list[dict[str, Any]] = []
        seen_lemmas: set[str] = set()
        for candidate in candidates.values():
            for line in candidate.analyses:
                lemma = self._verb_lemma_from_analysis(line)
                if lemma is None or lemma in seen_lemmas:
                    continue
                seen_lemmas.add(lemma)
                for tag in tags:
                    result = self.giella.generate_forms(lemma, tags=tag)
                    for form in self._parse_generated_forms(result):
                        generated.append(
                            {
                                "form": form,
                                "lemma": lemma,
                                "tags": tag,
                                "from_candidate": candidate.form,
                                "score": candidate.score,
                            }
                        )
        return generated

    def _analyze_candidates(self, candidates: dict[str, Candidate]) -> dict[str, Candidate]:
        unanalyzed = [candidate.form for candidate in candidates.values() if not candidate.analyses]
        if not unanalyzed:
            return candidates
        result = self.giella.analyze_words(unanalyzed)
        if not result.get("available"):
            return candidates
        for form, analysis in result.get("results", {}).items():
            weight_zero = [line for line in analysis.get("lines", []) if _line_has_weight_zero(line)]
            if form in candidates and weight_zero:
                candidates[form].analyses = weight_zero
        return candidates

    @staticmethod
    def _parse_speller_suggestions(spelling: dict[str, Any]) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []
        for line in spelling.get("lines", []):
            match = SPELLING_SUGGESTION_RE.match(line.strip())
            if not match:
                continue
            suggestions.append({"form": match.group(1).strip(), "weight": float(match.group(2))})
        return suggestions

    @staticmethod
    def _parse_generated_forms(result: dict[str, Any]) -> list[str]:
        forms: list[str] = []
        if not result.get("available"):
            return forms
        for line in result.get("lines", []):
            parts = line.split("\t")
            if len(parts) >= 3 and parts[-1] == "0" and parts[1].strip():
                forms.append(parts[1].strip())
        return forms

    @staticmethod
    def _target_generation_tags(original: str) -> list[str]:
        lower = original.casefold()
        if lower.endswith(("tud", "dud")):
            return ["V+Pss+PrfPrc", "V+Pss+PrfPrc+Sg+Nom"]
        if lower.endswith("nud"):
            return ["V+Act+PrfPrc", "V+Act+PrfPrc+Sg+Nom"]
        return []

    @staticmethod
    def _verb_lemma_from_analysis(line: str) -> str | None:
        parts = line.split("\t")
        if len(parts) < 2 or not _line_has_weight_zero(line):
            return None
        analysis = parts[1]
        if not any(tag in analysis for tag in VERB_INF_TAGS):
            return None
        lemma = analysis.split("+", 1)[0].strip()
        return lemma or None

    @staticmethod
    def _is_weight_zero(analysis: dict[str, Any], form: str) -> bool:
        result = analysis.get("results", {}).get(form, {})
        return any(_line_has_weight_zero(line) for line in result.get("lines", []))

    @staticmethod
    def _vro_tokens_from_entry(entry: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for translation in entry.get("translations", []):
            if translation.get("language") == "vro":
                values.append(translation.get("text", ""))
        for form in entry.get("forms", []):
            if form.get("language") == "vro":
                values.append(form.get("form", ""))
        for example in entry.get("examples", []):
            values.append(example.get("target_text", ""))

        tokens: list[str] = []
        for value in values:
            for token in TOKEN_RE.findall(value.replace("|", "")):
                cleaned = token.strip(".-()[]{}:;\"'")
                if len(cleaned) >= 2:
                    tokens.append(cleaned)
        return tokens

    @staticmethod
    def _compact_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": entry["id"],
                "headword": entry["headword"],
                "translations": entry.get("translations", [])[:3],
                "forms": entry.get("forms", [])[:5],
            }
            for entry in entries[:10]
        ]

    @staticmethod
    def _add_candidate(
        candidates: dict[str, Candidate],
        form: str,
        source: str,
        source_rank: int,
        score: float,
        detail: dict[str, Any],
    ) -> None:
        cleaned = form.strip()
        if not cleaned or len(cleaned) < 2:
            return
        candidate = candidates.get(cleaned)
        if candidate is None:
            candidate = Candidate(cleaned, source, source_rank, score, [])
            candidates[cleaned] = candidate
        candidate.add(source, source_rank, score, detail)

    @staticmethod
    def _candidate_payload(candidate: Candidate) -> dict[str, Any]:
        sources = {detail.get("source") for detail in candidate.details}
        source = (
            "combined"
            if len(sources) > 1
            else candidate.details[0]["source"]
            if candidate.details
            else candidate.source
        )
        return {
            "form": candidate.form,
            "source": source,
            "confidence": "confirmed",
            "analyses": candidate.analyses,
            "details": candidate.details,
        }

    @staticmethod
    def _ranking_key(candidate: Candidate) -> tuple[int, int, float, int, str]:
        sources = {detail.get("source") for detail in candidate.details}
        if "dictionary_generated" in sources and "dictionary" in sources:
            evidence_rank = 0
        elif "dictionary_generated" in sources:
            evidence_rank = 1
        elif "dictionary" in sources:
            evidence_rank = 2
        elif "speller" in sources:
            evidence_rank = 3
        else:
            evidence_rank = 4
        return (evidence_rank, candidate.source_rank, candidate.score, len(candidate.form), candidate.form)


def _line_has_weight_zero(line: str) -> bool:
    return line.rstrip().endswith("\t0")
