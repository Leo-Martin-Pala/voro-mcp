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

    def lint_words(self, words: str | list[str]) -> dict[str, Any]:
        """In-depth leakage check for discrete words or short phrases.

        Inputs are treated as whole units (one word/phrase each); no tokenization
        happens here, mirroring ``word_exists_in_bag`` / ``analyze_word``. Use
        ``find_in_text`` to locate suspects in a larger passage, then pass them
        here for rule IDs, severities, messages, and hints.
        """
        inputs = [words] if isinstance(words, str) else list(words)
        cleaned = [str(item).strip() for item in inputs if str(item).strip()]
        results = {original: self._lint_unit(original) for original in cleaned}
        return {
            "ruleset_id": self.ruleset["ruleset_id"],
            "purpose": self.ruleset["purpose"],
            "checked": len(cleaned),
            "results": results,
        }

    def find_in_text(self, text: str, limit: int = 200) -> dict[str, Any]:
        """Slim leakage scan over a larger text: deduped flagged surface forms
        plus phrase-level (window) hits, without per-rule detail. The model can
        re-check any item via ``lint_words`` for the full explanation.
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

        phrases: list[str] = []
        seen_phrases: set[str] = set()
        for match in self._lint_window(text):
            key = _normalize(match["text"])
            if key not in seen_phrases:
                seen_phrases.add(key)
                phrases.append(match["text"])

        return {
            "ruleset_id": self.ruleset["ruleset_id"],
            "purpose": self.ruleset["purpose"],
            "token_count": len(tokens),
            "unique_word_count": len(counts),
            "flagged_count": len(flagged_words),
            "returned_flagged_count": min(len(flagged_words), limit),
            "flagged_words": flagged_words[:limit],
            "flagged_phrases": phrases[:limit],
            "note": (
                "Slim triage: surface forms with an Estonian-looking ending, plus "
                "phrase-level hits. Pass any of these to lint_estonian_leakage for "
                "rule IDs, severities, messages, and hints."
            ),
        }

    def _lint_unit(self, unit: str) -> dict[str, Any]:
        normalized = _normalize(unit)
        matches: list[dict[str, Any]] = []
        for rule in self.ruleset["rules"]:
            if normalized in rule.allowlist:
                continue
            if rule.scope == "token":
                if rule.regex.fullmatch(unit):
                    matches.append(self._match_payload(rule, unit))
            else:
                for match in rule.regex.finditer(unit):
                    matches.append(
                        {
                            **self._match_payload(rule, match.group(0)),
                            "span": [match.start(), match.end()],
                        }
                    )
        matches = self._keep_highest_severity(matches)
        return {
            "normalized_token": normalized,
            "flagged": bool(matches),
            "highest_severity": self._highest_severity(matches),
            "matches": matches,
        }

    def _token_is_flagged(self, token: str, normalized: str) -> bool:
        return any(
            rule.scope == "token"
            and normalized not in rule.allowlist
            and rule.regex.fullmatch(token)
            for rule in self.ruleset["rules"]
        )

    def _lint_window(self, text: str) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for rule in self.ruleset["rules"]:
            if rule.scope != "window":
                continue
            for match in rule.regex.finditer(text):
                matches.append(
                    {
                        **self._match_payload(rule, match.group(0)),
                        "span": [match.start(), match.end()],
                    }
                )
        return matches

    @staticmethod
    def _match_payload(rule: LeakageRule, text: str) -> dict[str, Any]:
        return {
            "text": text,
            "rule_id": rule.id,
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
