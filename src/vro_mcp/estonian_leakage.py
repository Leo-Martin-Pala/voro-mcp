from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .tokenization import tokenize


RULES_PATH = Path(__file__).resolve().parent / "rules" / "estonian-leakage-rules.json"
SEVERITY_RANK = {"info": 1, "warning": 2, "error": 3}


@dataclass(frozen=True)
class LeakageRule:
    id: str
    severity: str
    scope: str
    regex: re.Pattern[str]
    message: str
    hint: str
    allowlist: frozenset[str]


def _normalize(text: str) -> str:
    return text.casefold().strip()


@lru_cache(maxsize=1)
def load_leakage_rules() -> dict[str, Any]:
    """Load the YAML-compatible JSON ruleset without a third-party dependency."""
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    rules: list[LeakageRule] = []
    for raw in data.get("rules", []):
        rules.append(
            LeakageRule(
                id=raw["id"],
                severity=raw["severity"],
                scope=raw["scope"],
                regex=re.compile(raw["regex"]),
                message=raw["message"],
                hint=raw["hint"],
                allowlist=frozenset(_normalize(item) for item in raw.get("allowlist", [])),
            )
        )
    return {
        "ruleset_id": data["ruleset_id"],
        "purpose": data["purpose"],
        "rules": tuple(rules),
    }


class EstonianLeakageLinter:
    def __init__(self) -> None:
        self.ruleset = load_leakage_rules()

    def lint_words(self, words: str | list[str]) -> dict[str, list[dict[str, Any]]]:
        """In-depth leakage check for discrete words or short phrases.

        Inputs are treated as whole units (one word/phrase each); no tokenization
        happens here, mirroring ``word_exists_in_bag`` / ``analyze_word``. Use
        ``find_in_text`` to locate suspects in a larger passage, then pass them
        here for severities, messages, and hints.
        """
        inputs = [words] if isinstance(words, str) else list(words)
        cleaned = [str(item).strip() for item in inputs if str(item).strip()]
        results = {original: self._lint_unit(original) for original in cleaned}
        return results

    def find_in_text(self, text: str, limit: int = 200) -> dict[str, Any]:
        """Slim leakage scan over a larger text: deduped flagged surface forms
        without phrase-level (window) hits or per-rule detail.
        """
        tokens = tokenize(text)
        counts: dict[str, int] = {}
        first_seen: dict[str, str] = {}
        flagged: set[str] = set()
        for token in tokens:
            norm = _normalize(token)
            counts[norm] = counts.get(norm, 0) + 1
            if norm not in first_seen:
                first_seen[norm] = token
                if self._token_is_flagged(token, norm):
                    flagged.add(norm)

        ordered = sorted(flagged, key=lambda norm: (-counts[norm], norm))
        flagged_words = [first_seen[norm] for norm in ordered]

        return {
            "token_count": len(tokens),
            "unique_word_count": len(counts),
            "flagged_count": len(flagged_words),
            "flagged_words": flagged_words[:limit],
        }

    def _lint_unit(self, unit: str) -> list[dict[str, Any]]:
        normalized = _normalize(unit)
        matches: list[dict[str, Any]] = []
        for rule in self.ruleset["rules"]:
            if normalized in rule.allowlist:
                continue
            if rule.scope == "token":
                if rule.regex.fullmatch(unit):
                    matches.append(self._match_payload(rule))
            else:
                for match in rule.regex.finditer(unit):
                    matches.append(
                        {
                            **self._match_payload(rule),
                            "span": [match.start(), match.end()],
                        }
                    )
        matches = self._keep_highest_severity(matches)
        return matches

    def _token_is_flagged(self, token: str, normalized: str) -> bool:
        return any(
            rule.scope == "token"
            and normalized not in rule.allowlist
            and rule.regex.fullmatch(token)
            for rule in self.ruleset["rules"]
        )

    @staticmethod
    def _match_payload(rule: LeakageRule) -> dict[str, Any]:
        return {
            "severity": rule.severity,
            "message": rule.message,
            "hint": rule.hint,
        }

    @staticmethod
    def _highest_severity(matches: list[dict[str, Any]]) -> str | None:
        if not matches:
            return None
        return max(matches, key=lambda item: SEVERITY_RANK.get(item["severity"], 0))["severity"]

    @staticmethod
    def _keep_highest_severity(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not matches:
            return matches
        highest_rank = max(SEVERITY_RANK.get(item["severity"], 0) for item in matches)
        return [item for item in matches if SEVERITY_RANK.get(item["severity"], 0) == highest_rank]
