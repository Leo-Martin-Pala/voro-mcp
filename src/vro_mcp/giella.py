from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandSpec:
    name: str
    command: str
    env_var: str
    setup_hint: str


class GiellaAdapter:
    def __init__(
        self,
        analyzer_cmd: str,
        generator_cmd: str,
        speller_cmd: str,
        grammar_cmd: str,
    ):
        self.commands = {
            "analyzer": CommandSpec(
                "analyzer",
                analyzer_cmd,
                "VRO_ANALYZER_CMD",
                "Create a repo-local analyzer wrapper, for example tools/giella/bin/analyze-vro.",
            ),
            "generator": CommandSpec(
                "generator",
                generator_cmd,
                "VRO_GENERATOR_CMD",
                "Create a repo-local generator wrapper, for example tools/giella/bin/generate-vro.",
            ),
            "speller": CommandSpec(
                "speller",
                speller_cmd,
                "VRO_SPELLER_CMD",
                "Create a repo-local speller wrapper, for example tools/giella/bin/spellcheck-vro.",
            ),
            "grammar": CommandSpec(
                "grammar",
                grammar_cmd,
                "VRO_GRAMMAR_CMD",
                "Create a repo-local grammar wrapper, for example tools/giella/bin/grammar-check-vro.",
            ),
        }

    def analyze_word(self, word: str) -> dict[str, Any]:
        return self._run_text_tool("analyzer", word.strip())

    def analyze_words(self, words: list[str]) -> dict[str, Any]:
        """Analyze many words in ONE analyzer process. Results are keyed by the
        surface form (the analyzer echoes it as the first tab-column)."""
        spec = self.commands["analyzer"]
        availability = self._availability_for(spec)
        if not availability["available"]:
            return {"available": False, "setup": availability, "results": {}}

        cleaned = [w.strip() for w in words if w and w.strip()]
        if not cleaned:
            return {"available": True, "command": spec.command, "results": {}}

        args = shlex.split(spec.command)
        try:
            completed = subprocess.run(
                args,
                input="\n".join(cleaned) + "\n",
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
        except OSError as exc:
            return {"available": False, "setup": self._unavailable(spec, str(exc)), "results": {}}
        except subprocess.TimeoutExpired:
            return {"available": False, "error": "analyzer timed out after 60 seconds", "results": {}}

        grouped: dict[str, list[str]] = {}
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            surface = line.split("\t", 1)[0]
            grouped.setdefault(surface, []).append(line)

        results: dict[str, Any] = {}
        for word in cleaned:
            lines = grouped.get(word, [])
            # A word is unrecognized when its only analysis line ends in "+?".
            recognized = any(not line.rstrip().endswith("+?") for line in lines)
            results[word] = {
                "available": True,
                "recognized": recognized,
                "lines": lines,
                "output": "\n".join(lines),
            }
        return {
            "available": True,
            "command": spec.command,
            "exit_code": completed.returncode,
            "results": results,
            "stderr": completed.stderr.strip(),
        }

    def generate_forms(
        self,
        lemma: str,
        tags: str | None = None,
     ) -> dict[str, Any]:
        suffix = tags.strip() if tags else None
        text = lemma.strip() if suffix is None else f"{lemma.strip()}\t{suffix.strip()}"
        return self._run_text_tool("generator", text)

    def spellcheck_vro(self, text: str) -> dict[str, Any]:
        return self._run_text_tool("speller", text)

    def grammar_check_vro(self, text: str) -> dict[str, Any]:
        return self._run_text_tool("grammar", text)

    def availability(self) -> dict[str, Any]:
        return {
            key: self._availability_for(spec)
            for key, spec in self.commands.items()
        }

    def _run_text_tool(self, key: str, text: str) -> dict[str, Any]:
        spec = self.commands[key]
        availability = self._availability_for(spec)
        if not availability["available"]:
            return {"available": False, "setup": availability}
        if not text:
            return {"available": True, "output": "", "lines": []}

        args = shlex.split(spec.command)
        try:
            completed = subprocess.run(
                args,
                input=text + "\n",
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except OSError as exc:
            return {"available": False, "setup": self._unavailable(spec, str(exc))}
        except subprocess.TimeoutExpired:
            return {
                "available": False,
                "error": f"{spec.name} timed out after 30 seconds",
            }

        output = completed.stdout.strip()
        error = completed.stderr.strip()
        return {
            "available": True,
            "command": spec.command,
            "exit_code": completed.returncode,
            "output": output,
            "lines": [line for line in output.splitlines() if line],
            "stderr": error,
        }

    def _availability_for(self, spec: CommandSpec) -> dict[str, Any]:
        args = shlex.split(spec.command)
        if not args:
            return self._unavailable(spec, "empty command")

        executable = args[0]
        if os.sep in executable:
            path = Path(executable)
            if path.exists() and os.access(path, os.X_OK):
                check = self._run_check(args)
                if check is not None and check.returncode != 0:
                    reason = check.stderr.strip() or check.stdout.strip() or f"{spec.name} --check failed"
                    return self._unavailable(spec, reason)
                return {"available": True, "command": spec.command}
            return self._unavailable(spec, f"{path} is missing or not executable")

        if shutil.which(executable):
            return {"available": True, "command": spec.command}
        return self._unavailable(spec, f"{executable} was not found on PATH")

    @staticmethod
    def _run_check(args: list[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                [*args, "--check"],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    @staticmethod
    def _unavailable(spec: CommandSpec, reason: str) -> dict[str, Any]:
        return {
            "available": False,
            "name": spec.name,
            "command": spec.command,
            "env_var": spec.env_var,
            "reason": reason,
            "setup_hint": spec.setup_hint,
        }
