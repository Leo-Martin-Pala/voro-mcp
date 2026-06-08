from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


RULES_PATH = Path(__file__).resolve().parent / "rules" / "estonian-leakage-rules.json"
TOKEN_RE = re.compile(r"(?iu)[^\W\d_][^\W\d_'´-]*(?:['´-][^\W\d_]+)*")
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
        inputs = [words] if isinstance(words, str) else list(words)
        cleaned = [str(item).strip() for item in inputs if str(item).strip()]

        results: dict[str, Any] = {}
        window_matches: list[dict[str, Any]] = []
        for original in cleaned:
            tokens = [match.group(0) for match in TOKEN_RE.finditer(original)]
            token_results = {token: self._lint_token(token) for token in tokens}
            results[original] = {
                "tokens": token_results,
                "flagged": any(item["flagged"] for item in token_results.values()),
            }
            if not tokens:
                results[original]["tokens"] = {}

        joined = " ".join(cleaned)
        if joined:
            window_matches = self._lint_window(joined)
            self._attach_window_matches(results, window_matches)

        return {
            "ruleset_id": self.ruleset["ruleset_id"],
            "purpose": self.ruleset["purpose"],
            "checked": len(cleaned),
            "results": results,
            "window_matches": window_matches,
        }

    def _lint_token(self, token: str) -> dict[str, Any]:
        normalized = _normalize(token)
        matches = [
            self._match_payload(rule, token)
            for rule in self.ruleset["rules"]
            if rule.scope == "token"
            and normalized not in rule.allowlist
            and rule.regex.fullmatch(token)
        ]
        matches = self._keep_highest_severity(matches)
        highest = self._highest_severity(matches)
        return {
            "normalized_token": normalized,
            "flagged": bool(matches),
            "highest_severity": highest,
            "matches": matches,
        }

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

    @staticmethod
    def _attach_window_matches(
        results: dict[str, Any],
        window_matches: list[dict[str, Any]],
    ) -> None:
        if not window_matches:
            return
        for result in results.values():
            for token_result in result["tokens"].values():
                token_result.setdefault("window_matches", [])
        for window_match in window_matches:
            normalized_words = {_normalize(token) for token in TOKEN_RE.findall(window_match["text"])}
            for result in results.values():
                attached = False
                for token, token_result in result["tokens"].items():
                    if _normalize(token) in normalized_words:
                        token_result.setdefault("window_matches", []).append(window_match)
                        token_result["flagged"] = True
                        token_result["highest_severity"] = EstonianLeakageLinter._highest_severity(
                            token_result["matches"] + token_result["window_matches"]
                        )
                        attached = True
                result["flagged"] = result["flagged"] or attached
